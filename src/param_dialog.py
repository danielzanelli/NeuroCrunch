# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""NeuroCrunch - Parameter Dialog (Phase 3)

Auto-generates a configuration dialog for a script plugin based on its
manifest parameter definitions.  Supports all documented parameter types
and pre-fills linked parameters from the pipeline context.

Usage::

    dialog = ParamDialog(plugin_info, current_values, pipeline_context, parent)
    if dialog.exec() == QDialog.Accepted:
        saved = dialog.get_values()
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Type alias for the pipeline context passed from the main window.
# Shape: { script_id: { output_key: value } }
PipelineContext = Dict[str, Dict[str, Any]]


def _resolve_label(field: Dict[str, Any], key: str = 'label') -> str:
    """Return a human-readable string for *key* in *field*, handling locale maps.

    Manifest labels can be either a plain string or a dict mapping locale codes
    to strings (e.g. ``{"en": "…", "es": "…"}``).  This helper always returns a
    plain string, preferring English, then any available value, then falling back
    to the parameter ``name``.
    """
    value = field.get(key)
    if value is None:
        return field.get('name', '')
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('en') or value.get('es') or next(iter(value.values()), field.get('name', ''))
    return str(value)


def _resolve_link(link: str, pipeline_context: PipelineContext) -> Optional[Any]:
    """Try to look up *link* (``"script_id.output_key"``) in *pipeline_context*.

    Returns the resolved value, or ``None`` if the link is malformed or missing.
    """
    if not isinstance(link, str) or '.' not in link:
        return None
    parts = link.split('.', 1)
    script_id, output_key = parts[0].strip(), parts[1].strip()
    if not script_id or not output_key:
        return None
    script_outputs = pipeline_context.get(script_id)
    if not isinstance(script_outputs, dict):
        return None
    return script_outputs.get(output_key)  # may be None


class ParamDialog(QDialog):
    """Auto-generated parameter configuration dialog for a script plugin.

    Parameters
    ----------
    plugin_info:
        ``PluginInfo`` object from ``plugin_manager.py``.  Its ``parameters``
        list drives widget generation.
    current_values:
        Dict of previously saved values for this script
        (``self.config[script_id]['parametros']``).  May be empty.
    pipeline_context:
        Mapping ``{script_id: {output_key: value}}`` used to pre-fill linked
        parameters.  Pass ``{}`` when no context is available yet.
    parent:
        Parent widget (the main window).
    """

    # Column index in the "Configured" table column — not used here but
    # kept as a named constant for documentation clarity.
    COL_CONFIGURED = 4

    def __init__(
        self,
        plugin_info,
        current_values: Dict[str, Any],
        pipeline_context: PipelineContext,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_info = plugin_info
        self._current_values = dict(current_values) if current_values else {}
        self._pipeline_context = pipeline_context if isinstance(pipeline_context, dict) else {}

        # Maps parameter name → widget (or tuple of widgets for compound types)
        self._widgets: Dict[str, Any] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        from PySide6.QtCore import QCoreApplication
        self.setWindowTitle(QCoreApplication.translate('ParamDialog', f'Configure: {self._plugin_info.name}'))
        self.setMinimumWidth(480)

        outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(8)

        # Scrollable area for the parameter form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form_layout.setSpacing(8)
        form_layout.setContentsMargins(8, 8, 8, 8)

        parameters: List[Dict[str, Any]] = self._plugin_info.parameters or []

        if not parameters:
            no_params = QLabel(QCoreApplication.translate('ParamDialog', 'This script has no configurable parameters.'))
            no_params.setAlignment(Qt.AlignCenter)
            form_layout.addRow(no_params)
        else:
            for param in parameters:
                self._add_param_row(form_layout, param)

        scroll.setWidget(form_container)
        outer_layout.addWidget(scroll)

        # OK / Cancel buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText(QCoreApplication.translate('ParamDialog', 'Accept'))
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(QCoreApplication.translate('ParamDialog', 'Cancel'))
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        outer_layout.addWidget(button_box)

    def _add_param_row(self, form_layout: QFormLayout, param: Dict[str, Any]) -> None:
        """Add a label + widget row for *param* to *form_layout*."""
        name: str = param.get('name', '')
        ptype: str = param.get('type', 'string')
        label_text: str = _resolve_label(param, 'label') or name
        description: str = _resolve_label(param, 'description')
        required: bool = bool(param.get('required', False))
        default = param.get('default')
        link: str = param.get('link', '')

        # Determine the initial value to populate the widget with.
        # Priority: saved value → linked value from context → manifest default
        current_val = self._current_values.get(name)
        linked_val: Optional[Any] = None
        link_source: str = ''
        if link:
            linked_val = _resolve_link(link, self._pipeline_context)
            if linked_val is not None:
                link_source = link.split('.')[0]  # script_id portion

        if current_val is None and linked_val is not None:
            initial_val = linked_val
        elif current_val is not None:
            initial_val = current_val
        else:
            initial_val = default

        # Build the label widget (mark required fields with *)
        if required:
            label_text = label_text + ' *'
        label_widget = QLabel(label_text)
        if description:
            label_widget.setToolTip(description)

        # Build the input widget
        widget = self._build_widget(ptype, param, initial_val)
        self._widgets[name] = widget

        # For compound types (file/directory), widget is a QWidget container;
        # for simple types it's the widget itself.
        if isinstance(widget, QWidget):
            input_widget = widget
        else:
            input_widget = widget  # same object

        # Wrap with link hint if applicable
        if link_source:
            hint_label = QLabel(f'<i>{QCoreApplication.translate("ParamDialog", "Source: ")}{link_source}</i>')
            hint_label.setStyleSheet('color: #888888; font-size: 10px;')
            hint_label.setToolTip(QCoreApplication.translate('ParamDialog', f'Value pre-filled from the output of "{link_source}"'))
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(2)
            vbox.addWidget(input_widget)
            vbox.addWidget(hint_label)
            input_widget = container

        form_layout.addRow(label_widget, input_widget)

        # Tooltip on the label for description
        if description:
            # Already set on label; also set on the actual input widget
            actual_widget = self._get_leaf_widget(name)
            if actual_widget is not None:
                actual_widget.setToolTip(description)

    def _build_widget(self, ptype: str, param: Dict[str, Any], initial_val: Any) -> QWidget:
        """Create and return the appropriate Qt widget for *ptype*."""
        if ptype == 'string':
            return self._make_line_edit(initial_val)

        elif ptype == 'int':
            return self._make_spin_box(param, initial_val)

        elif ptype == 'float':
            return self._make_double_spin_box(param, initial_val)

        elif ptype == 'bool':
            return self._make_checkbox(param, initial_val)

        elif ptype == 'file':
            return self._make_file_picker(param, initial_val, directory=False)

        elif ptype == 'directory':
            return self._make_file_picker(param, initial_val, directory=True)

        elif ptype == 'choice':
            return self._make_combo_box(param, initial_val)

        elif ptype == 'text':
            return self._make_text_edit(initial_val)

        else:
            # Unknown type — fall back to a plain line edit
            return self._make_line_edit(initial_val)

    # ------------------------------------------------------------------
    # Widget factory helpers
    # ------------------------------------------------------------------

    def _make_line_edit(self, initial_val: Any) -> QLineEdit:
        w = QLineEdit()
        if initial_val is not None:
            w.setText(str(initial_val))
        return w

    def _make_spin_box(self, param: Dict[str, Any], initial_val: Any) -> QSpinBox:
        w = QSpinBox()
        w.setMinimum(int(param.get('min', -2147483648)))
        w.setMaximum(int(param.get('max', 2147483647)))
        if initial_val is not None:
            try:
                w.setValue(int(initial_val))
            except (ValueError, TypeError):
                pass
        return w

    def _make_double_spin_box(self, param: Dict[str, Any], initial_val: Any) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setMinimum(float(param.get('min', -1e12)))
        w.setMaximum(float(param.get('max', 1e12)))
        decimals = int(param.get('decimals', 4))
        w.setDecimals(decimals)
        if initial_val is not None:
            try:
                w.setValue(float(initial_val))
            except (ValueError, TypeError):
                pass
        return w

    def _make_checkbox(self, param: Dict[str, Any], initial_val: Any) -> QCheckBox:
        w = QCheckBox()
        if initial_val is not None:
            if isinstance(initial_val, bool):
                w.setChecked(initial_val)
            elif isinstance(initial_val, str):
                w.setChecked(initial_val.lower() in ('true', '1', 'yes'))
            else:
                w.setChecked(bool(initial_val))
        return w

    def _make_file_picker(
        self, param: Dict[str, Any], initial_val: Any, *, directory: bool
    ) -> QWidget:
        """Build a QLineEdit + Browse button for file or directory selection."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        line_edit = QLineEdit()
        if initial_val is not None:
            line_edit.setText(str(initial_val))
        layout.addWidget(line_edit)

        btn = QPushButton('Browse…')
        btn.setFixedWidth(90)
        btn.setFocusPolicy(Qt.NoFocus)

        extensions: List[str] = param.get('extensions', [])

        if directory:
            def browse():
                path = QFileDialog.getExistingDirectory(
                    self, 'Select folder', line_edit.text() or ''
                )
                if path:
                    line_edit.setText(path)
        else:
            def browse():
                ext_filter = ''
                if extensions:
                    patterns = ' '.join(f'*{e}' for e in extensions)
                    ext_filter = f'Files ({patterns});;All files (*)'
                path, _ = QFileDialog.getOpenFileName(
                    self, 'Select file', line_edit.text() or '', ext_filter
                )
                if path:
                    line_edit.setText(path)

        btn.clicked.connect(browse)
        layout.addWidget(btn)

        # Store the inner QLineEdit so we can retrieve its text later.
        # We use a custom attribute on the container widget.
        container._line_edit = line_edit  # type: ignore[attr-defined]
        return container

    def _make_combo_box(self, param: Dict[str, Any], initial_val: Any) -> QComboBox:
        w = QComboBox()
        options: List[str] = [str(o) for o in param.get('options', [])]
        w.addItems(options)
        if initial_val is not None:
            idx = w.findText(str(initial_val))
            if idx >= 0:
                w.setCurrentIndex(idx)
        return w

    def _make_text_edit(self, initial_val: Any) -> QTextEdit:
        w = QTextEdit()
        w.setMaximumHeight(120)
        if initial_val is not None:
            w.setPlainText(str(initial_val))
        return w

    # ------------------------------------------------------------------
    # Value extraction helpers
    # ------------------------------------------------------------------

    def _get_leaf_widget(self, name: str) -> Optional[QWidget]:
        """Return the primary interactive widget for parameter *name*."""
        w = self._widgets.get(name)
        if w is None:
            return None
        # Compound file/directory pickers store the QLineEdit as _line_edit
        if hasattr(w, '_line_edit'):
            return w._line_edit  # type: ignore[attr-defined]
        return w

    def _extract_value(self, name: str, param: Dict[str, Any]) -> Any:
        """Extract the current value for *name* from its widget."""
        ptype = param.get('type', 'string')
        w = self._widgets.get(name)
        if w is None:
            return None

        if ptype == 'string':
            return w.text().strip()
        elif ptype == 'int':
            return w.value()
        elif ptype == 'float':
            return w.value()
        elif ptype == 'bool':
            return w.isChecked()
        elif ptype in ('file', 'directory'):
            line_edit = getattr(w, '_line_edit', None)
            return line_edit.text().strip() if line_edit is not None else ''
        elif ptype == 'choice':
            return w.currentText()
        elif ptype == 'text':
            return w.toPlainText().strip()
        else:
            # Unknown — try text() as fallback
            if hasattr(w, 'text'):
                return w.text().strip()
            return None

    # ------------------------------------------------------------------
    # Validation & accept
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        """Validate required fields; accept only when all are non-empty."""
        parameters: List[Dict[str, Any]] = self._plugin_info.parameters or []
        missing_labels: List[str] = []

        for param in parameters:
            if not param.get('required', False):
                continue
            name = param.get('name', '')
            value = self._extract_value(name, param)
            ptype = param.get('type', 'string')

            # Numeric types are never truly "empty"; bools are always valid.
            if ptype in ('int', 'float', 'bool'):
                continue

            if value is None or (isinstance(value, str) and not value):
                label = _resolve_label(param, 'label') or name
                missing_labels.append(label)

        if missing_labels:
            QMessageBox.warning(
                self,
                'Required parameters',
                'The following parameters are required and have not been filled in:\n\n'
                + '\n'.join(f'• {lbl}' for lbl in missing_labels),
            )
            return

        self.accept()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_values(self) -> Dict[str, Any]:
        """Return a dict mapping parameter name → current widget value.

        Call this after ``exec()`` returns ``QDialog.Accepted``.
        """
        parameters: List[Dict[str, Any]] = self._plugin_info.parameters or []
        return {
            param.get('name', ''): self._extract_value(param.get('name', ''), param)
            for param in parameters
            if param.get('name')
        }


# ---------------------------------------------------------------------------
# Helpers for the main window (used by NeuroCrunch.py)
# ---------------------------------------------------------------------------

def is_script_configured(plugin_info, saved_values: Dict[str, Any]) -> bool:
    """Return True when all ``required`` parameters in *plugin_info* have
    non-empty values in *saved_values*.

    A script with no required parameters is always considered configured.
    Numeric and boolean parameters with a saved value are always considered
    configured (they cannot be "empty").
    """
    parameters: List[Dict[str, Any]] = plugin_info.parameters or []
    for param in parameters:
        if not param.get('required', False):
            continue
        name = param.get('name', '')
        ptype = param.get('type', 'string')
        val = saved_values.get(name)

        # Numeric/bool: presence of any value (including 0 or False) is valid.
        if ptype in ('int', 'float', 'bool'):
            if val is None:
                return False
            continue

        # String-like types must be non-empty.
        if val is None or (isinstance(val, str) and not val.strip()):
            return False

    return True
