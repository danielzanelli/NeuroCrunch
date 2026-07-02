# This Python file uses the following encoding: utf-8
"""NeuroCrunch - Script Runner (Phase 4)

Executes a configured pipeline of script plugins as subprocesses, streaming
their stdout to the UI log and threading each script's declared outputs into
a shared ``PipelineContext`` so downstream scripts can resolve linked
parameters (see ``param_dialog.py`` and README.md > "Plugin / Script
Standard").

Execution contract (see README.md > "main.py — execution contract")::

    python main.py --nc_params /tmp/.../<id>_params.json \\
                   --nc_output /tmp/.../<id>_output.json

``<id>_params.json`` contains every configured parameter value plus a
``_context`` key with ``session_dir`` and the pipeline outputs collected so
far. The script writes its declared output keys to ``<id>_output.json`` when
it finishes. Anything printed to stdout/stderr is streamed line-by-line to
the UI log. A non-zero exit code halts the pipeline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from param_dialog import _resolve_link

# Type alias matching param_dialog.PipelineContext's shape:
# { script_id: { output_key: value } }
PipelineContextData = Dict[str, Dict[str, Any]]

PIPELINE_CONTEXT_FILENAME = 'pipeline_context.json'


class PipelineContext:
    """Stores ``{script_id: {output_key: value}}`` for the current session.

    Optionally persisted to ``session_dir/pipeline_context.json`` so it
    survives across runs (e.g. reopening the app and continuing a pipeline).
    """

    def __init__(self, session_dir: Optional[str] = None) -> None:
        self.session_dir = session_dir
        self.data: PipelineContextData = {}
        if session_dir:
            self.load()

    @property
    def path(self) -> Optional[str]:
        if not self.session_dir:
            return None
        return os.path.join(self.session_dir, PIPELINE_CONTEXT_FILENAME)

    def get_outputs(self, script_id: str) -> Dict[str, Any]:
        """Return the outputs recorded for *script_id* (empty dict if none)."""
        return self.data.get(script_id, {})

    def set_outputs(self, script_id: str, outputs: Dict[str, Any]) -> None:
        """Merge *outputs* into the entry for *script_id* and persist to disk."""
        if not outputs:
            return
        self.data.setdefault(script_id, {}).update(outputs)
        self.save()

    def as_dict(self) -> PipelineContextData:
        """Return the underlying ``{script_id: {output_key: value}}`` mapping."""
        return self.data

    def load(self) -> None:
        """Load previously persisted context from ``session_dir``, if present."""
        path = self.path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        """Persist the current context to ``session_dir``, if configured."""
        path = self.path
        if not path:
            return
        try:
            os.makedirs(self.session_dir, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


class ScriptRunner(QThread):
    """Runs an ordered pipeline of scripts as subprocesses, one at a time.

    Parameters
    ----------
    pipeline:
        Ordered list of ``(script_id, plugin_info, params)`` tuples to run in
        sequence. ``params`` is the dict of saved parameter values for that
        script (before linked-parameter resolution, which happens right
        before each script runs).
    pipeline_context:
        Shared ``PipelineContext`` instance, updated after each script
        finishes with its declared outputs.
    """

    log_message = Signal(str)
    script_started = Signal(str)
    script_finished = Signal(str, bool)
    pipeline_done = Signal(bool)

    def __init__(
        self,
        pipeline: List[Tuple[str, Any, Dict[str, Any]]],
        pipeline_context: PipelineContext,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._context = pipeline_context
        self._stop_requested = False
        self._current_process: Optional[subprocess.Popen] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Request cancellation of the pipeline.

        Terminates the currently running script (if any); remaining scripts
        in the pipeline are skipped.
        """
        self._stop_requested = True
        process = self._current_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        overall_success = True

        for script_id, plugin_info, params in self._pipeline:
            if self._stop_requested:
                self.log_message.emit(
                    f'Pipeline detenido antes de ejecutar "{plugin_info.name}".'
                )
                overall_success = False
                break

            resolved_params = self._resolve_linked_params(plugin_info, params)

            self.script_started.emit(script_id)
            self.log_message.emit(f'--- Ejecutando "{plugin_info.name}" ---')

            success, outputs = self._run_script(script_id, plugin_info, resolved_params)

            if outputs:
                self._context.set_outputs(script_id, outputs)

            self.script_finished.emit(script_id, success)

            if not success:
                overall_success = False
                if not self._stop_requested:
                    self.log_message.emit(
                        f'"{plugin_info.name}" finalizó con error. Pipeline detenido.'
                    )
                break

        self.pipeline_done.emit(overall_success and not self._stop_requested)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_linked_params(self, plugin_info, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of *params* with any ``link``-ed values refreshed
        from the current pipeline context (in case the linked script has run
        earlier in this same pipeline execution)."""
        resolved = dict(params)
        for param in plugin_info.parameters or []:
            link = param.get('link')
            name = param.get('name')
            if not link or not name:
                continue
            linked_val = _resolve_link(link, self._context.as_dict())
            if linked_val is not None:
                resolved[name] = linked_val
        return resolved

    def _run_script(
        self, script_id: str, plugin_info, params: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Run a single script as a subprocess, streaming its stdout to the
        log and reading back its declared outputs.

        Returns ``(success, outputs)``.
        """
        entry_point = plugin_info.entry_point
        script_dir = os.path.dirname(entry_point)

        session_dir = self._context.session_dir or script_dir
        params_payload = dict(params)
        params_payload['_context'] = {
            'session_dir': session_dir,
            'pipeline_outputs': self._context.as_dict(),
        }

        with tempfile.TemporaryDirectory(prefix=f'neurocrunch_{script_id}_') as tmp_dir:
            params_path = os.path.join(tmp_dir, f'{script_id}_params.json')
            output_path = os.path.join(tmp_dir, f'{script_id}_output.json')

            try:
                with open(params_path, 'w', encoding='utf-8') as f:
                    json.dump(params_payload, f, ensure_ascii=False, indent=2)
            except OSError as e:
                self.log_message.emit(
                    f'No se pudo escribir params.json para "{plugin_info.name}": {e}'
                )
                return False, {}

            cmd = [
                sys.executable,
                '-u',  # Disable buffering
                entry_point,
                '--nc_params', params_path,
                '--nc_output', output_path,
            ]

            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=script_dir,
                    stdin=subprocess.DEVNULL,  # Close stdin to prevent blocking
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as e:
                self.log_message.emit(f'No se pudo iniciar "{plugin_info.name}": {e}')
                return False, {}

            self._current_process = process

            if process.stdout is not None:
                for line in process.stdout:
                    line = line.rstrip('\n')
                    if line:
                        self.log_message.emit(line)
                process.stdout.close()

            return_code = process.wait()
            self._current_process = None

            if self._stop_requested:
                self.log_message.emit(f'"{plugin_info.name}" cancelado por el usuario.')
                return False, self._read_outputs(output_path)

            success = (return_code == 0)
            if not success:
                self.log_message.emit(
                    f'"{plugin_info.name}" terminó con código de salida {return_code}.'
                )

            outputs = self._read_outputs(output_path)
            return success, outputs

    def _read_outputs(self, output_path: str) -> Dict[str, Any]:
        """Read the ``output.json`` file written by the script, if present."""
        if not os.path.isfile(output_path):
            return {}
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError) as e:
            self.log_message.emit(f'No se pudo leer la salida "{output_path}": {e}')
            return {}
