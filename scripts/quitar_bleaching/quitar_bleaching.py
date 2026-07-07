from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

import numpy as np
import pandas as pd


IGNORED_COLUMNS = {"", "Slice", "frame", "tiempo_s"}
_DTD_CACHE: Dict[int, np.ndarray] = {}
_PENALTY_CACHE: Dict[Tuple[int, float, float, float, float], np.ndarray] = {}


def _is_ignored_column(column: str) -> bool:
	return column.strip() in IGNORED_COLUMNS


def split_metric_and_index(column: str) -> Tuple[str, int]:
	# Pattern 1: Mean123 / baseline_filt_123
	match_metric_first = re.match(r"^([a-zA-Z_]+?)(\d+)$", column)
	if match_metric_first:
		metric_name = match_metric_first.group(1)
		index = int(match_metric_first.group(2))
		return metric_name, index

	# Pattern 2: 123_mean / 123_baseline_filt
	match_index_first = re.match(r"^(\d+)_([a-zA-Z_]+)$", column)
	if match_index_first:
		index = int(match_index_first.group(1))
		metric_name = match_index_first.group(2)
		return metric_name, index

	raise ValueError(
		f"El nombre de columna '{column}' no coincide con los patrones soportados: "
		"'(NombreDeMetrica)(indice)' o '(indice)_(nombre_de_metrica)'"
	)


def _iter_signal_columns(columns: Iterable[str]) -> Tuple[List[str], List[str]]:
	signal_columns: List[str] = []
	skipped_columns: List[str] = []

	for col in columns:
		if _is_ignored_column(col):
			continue
		try:
			split_metric_and_index(col)
			signal_columns.append(col)
		except ValueError:
			skipped_columns.append(col)

	return signal_columns, skipped_columns


def get_metrics_and_indices(df: pd.DataFrame) -> Tuple[List[str], List[int]]:
	metrics: Set[str] = set()
	indices: Set[int] = set()

	signal_columns, _ = _iter_signal_columns(df.columns)
	for col in signal_columns:
		metric, idx = split_metric_and_index(col)
		metrics.add(metric)
		indices.add(idx)

	return sorted(metrics), sorted(indices)


def parse_metrics_param(metrics_param: str | None, available_metrics: Sequence[str]) -> List[str]:
	if not metrics_param:
		return list(available_metrics)

	requested = [m.strip() for m in metrics_param.split(",") if m.strip()]
	if not requested:
		return list(available_metrics)

	available_by_lower = {m.lower(): m for m in available_metrics}
	invalid = [m for m in requested if m.lower() not in available_by_lower]
	if invalid:
		raise ValueError(
			"Métrica(s) no encontrada(s) en el CSV: "
			+ ", ".join(invalid)
			+ ". Métricas disponibles: "
			+ ", ".join(available_metrics)
		)

	# Preserve user order while resolving to the canonical metric spelling in the CSV.
	return [available_by_lower[m.lower()] for m in requested]


def build_target_columns(df: pd.DataFrame, selected_metrics: Iterable[str]) -> List[str]:
	metric_set = set(selected_metrics)
	target_cols: List[str] = []

	signal_columns, _ = _iter_signal_columns(df.columns)
	for col in signal_columns:
		metric, _ = split_metric_and_index(col)
		if metric in metric_set:
			target_cols.append(col)

	if not target_cols:
		raise ValueError("No se encontraron columnas para las métricas seleccionadas.")

	return target_cols


def _build_dtd(length: int) -> np.ndarray:
	# Same dense formulation used in the notebook.
	d = np.diff(np.eye(length), 2, axis=0)
	return d.T @ d


def _build_lam_array(
	length: int,
	lam: float,
	lam_factor: float,
	rampup_fraction: float,
	rampdown_fraction: float,
) -> np.ndarray:
	rampup_len = max(1, int(rampup_fraction * length))
	rampdown_len = max(1, int(rampdown_fraction * length))
	middle_len = max(0, length - rampup_len - rampdown_len)

	lam_rampup = np.linspace(lam * lam_factor, lam, rampup_len)
	lam_middle = np.full(middle_len, lam)
	lam_rampdown = np.linspace(lam, lam * lam_factor, rampdown_len)
	lam_array = np.concatenate([lam_rampup, lam_middle, lam_rampdown])

	if lam_array.shape[0] != length:
		lam_array = lam_array[:length]
		if lam_array.shape[0] < length:
			lam_array = np.pad(lam_array, (0, length - lam_array.shape[0]), mode="edge")

	return lam_array


def _get_penalty_matrix(
	length: int,
	lam: float,
	lam_factor: float,
	rampup_fraction: float,
	rampdown_fraction: float,
) -> np.ndarray:
	key = (
		length,
		round(lam, 12),
		round(lam_factor, 12),
		round(rampup_fraction, 12),
		round(rampdown_fraction, 12),
	)
	if key in _PENALTY_CACHE:
		return _PENALTY_CACHE[key]

	if length in _DTD_CACHE:
		dtd = _DTD_CACHE[length]
	else:
		dtd = _build_dtd(length)
		_DTD_CACHE[length] = dtd

	lam_array = _build_lam_array(length, lam, lam_factor, rampup_fraction, rampdown_fraction)
	penalty = lam_array[:, None] * dtd
	_PENALTY_CACHE[key] = penalty
	return penalty


def als_baseline_adaptive(
	y: np.ndarray,
	*,
	lam: float,
	p: float,
	niter: int,
	lam_factor: float,
	rampup_fraction: float,
	rampdown_fraction: float,
	penalty_matrix: np.ndarray | None = None,
) -> np.ndarray:
	length = y.shape[0]
	if length < 3:
		return y.copy()

	w = np.ones(length, dtype=float)
	if penalty_matrix is None:
		penalty_matrix = _get_penalty_matrix(
			length,
			lam,
			lam_factor,
			rampup_fraction,
			rampdown_fraction,
		)

	for _ in range(niter):
		z_matrix = penalty_matrix.copy()
		z_matrix.flat[:: length + 1] += w
		z = np.linalg.solve(z_matrix, w * y)
		w = p * (y > z) + (1 - p) * (y < z)

	return z


def bleach_correct_and_smooth(
	y: np.ndarray,
	*,
	baseline_lam: float,
	baseline_p: float,
	baseline_niter: int,
	baseline_lam_factor: float,
	baseline_rampup: float,
	baseline_rampdown: float,
	smooth_lam: float,
	smooth_p: float,
	smooth_niter: int,
	baseline_penalty: np.ndarray | None = None,
	smooth_penalty: np.ndarray | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
	baseline = als_baseline_adaptive(
		y,
		lam=baseline_lam,
		p=baseline_p,
		niter=baseline_niter,
		lam_factor=baseline_lam_factor,
		rampup_fraction=baseline_rampup,
		rampdown_fraction=baseline_rampdown,
		penalty_matrix=baseline_penalty,
	)

	eps = np.finfo(float).eps
	corrected = (y - baseline) / np.maximum(np.abs(baseline), eps)

	# Follow notebook logic: second ALS pass over corrected trace,
	# taking its baseline as the final smoothed signal.
	smoothed = als_baseline_adaptive(
		corrected,
		lam=smooth_lam,
		p=smooth_p,
		niter=smooth_niter,
		lam_factor=1.0,
		rampup_fraction=0.0,
		rampdown_fraction=0.0,
		penalty_matrix=smooth_penalty,
	)

	return baseline, corrected, smoothed


def main(params: Dict[str, Any]) -> Dict[str, Any]:
	input_csv = os.path.abspath(os.path.normpath(params["input_csv"]))
	output_dir = os.path.abspath(os.path.normpath(params["output_dir"]))
	progress_every = max(1, int(params.get("progress_every", 25)))

	baseline_lam = float(params.get("baseline_lam", 1e5))
	baseline_p = float(params.get("baseline_p", 0.01))
	baseline_niter = int(params.get("baseline_niter", 10))
	baseline_lam_factor = float(params.get("baseline_lam_factor", 1e-3))
	baseline_rampup = float(params.get("baseline_rampup_fraction", 0.2))
	baseline_rampdown = float(params.get("baseline_rampdown_fraction", 0.2))

	smooth_lam = float(params.get("smooth_lam", 1e1))
	smooth_p = float(params.get("smooth_p", 0.5))
	smooth_niter = int(params.get("smooth_niter", 10))

	if not os.path.isfile(input_csv):
		raise FileNotFoundError(f"No se encontró input_csv: {input_csv}")
	os.makedirs(output_dir, exist_ok=True)

	print(f"Cargando CSV: {input_csv}")
	df = pd.read_csv(input_csv)
	print(f"CSV cargado: {df.shape[0]} filas x {df.shape[1]} columnas")
	signal_columns, skipped_columns = _iter_signal_columns(df.columns)
	if skipped_columns:
		print(
			"Omitiendo columnas no compatibles (sin patrón de señal): "
			+ ", ".join(skipped_columns)
		)
	if not signal_columns:
		raise ValueError("No se encontraron columnas de señal en el CSV de entrada.")

	available_metrics, _ = get_metrics_and_indices(df)
	selected_metrics = parse_metrics_param(params.get("metrics"), available_metrics)
	target_columns = build_target_columns(df, selected_metrics)

	print(f"Métricas disponibles: {', '.join(available_metrics)}")
	print(f"Métricas seleccionadas: {', '.join(selected_metrics)}")
	print(f"Columnas a procesar: {len(target_columns)}")
	print("Iniciando corrección de bleaching...")

	baseline_df = pd.DataFrame(index=df.index)
	process_start = time.time()
	series_len = len(df.index)
	target_count = len(target_columns)

	baseline_matrix = np.empty((series_len, target_count), dtype=float)
	baseline_matrix.fill(np.nan)
	corrected_matrix = np.empty((series_len, target_count), dtype=float)
	corrected_matrix.fill(np.nan)
	smoothed_matrix = np.empty((series_len, target_count), dtype=float)
	smoothed_matrix.fill(np.nan)

	baseline_penalty = _get_penalty_matrix(
		series_len,
		baseline_lam,
		baseline_lam_factor,
		baseline_rampup,
		baseline_rampdown,
	)
	smooth_penalty = _get_penalty_matrix(
		series_len,
		smooth_lam,
		1.0,
		0.0,
		0.0,
	)
	nan_all_count = 0
	nan_partial_count = 0

	for idx, (col_idx, column) in enumerate(enumerate(target_columns), start=1):
		if idx == 1 or idx % progress_every == 0 or idx == len(target_columns):
			elapsed = time.time() - process_start
			avg_per_col = elapsed / idx
			remaining = max(0, len(target_columns) - idx)
			remaining_minutes = (avg_per_col * remaining) / 60.0
			elapsed_minutes = elapsed / 60.0
			percent = 100.0 * idx / len(target_columns)
			print(
				f"\rProgreso: {percent:.2f}% | "
				f"Transcurrido: {elapsed_minutes:.1f} min | "
				f"Restante: {remaining_minutes:.1f} min",
				end="",
				flush=True,
			)

		y = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
		nan_mask = np.isnan(y)
		if nan_mask.all():
			nan_all_count += 1
			baseline_matrix[:, col_idx] = np.nan
			corrected_matrix[:, col_idx] = np.nan
			smoothed_matrix[:, col_idx] = np.nan
			continue

		if nan_mask.any():
			nan_partial_count += 1
			valid_idx = np.flatnonzero(~nan_mask)
			y[nan_mask] = np.interp(np.flatnonzero(nan_mask), valid_idx, y[valid_idx])

		baseline, corrected, smoothed = bleach_correct_and_smooth(
			y,
			baseline_lam=baseline_lam,
			baseline_p=baseline_p,
			baseline_niter=baseline_niter,
			baseline_lam_factor=baseline_lam_factor,
			baseline_rampup=baseline_rampup,
			baseline_rampdown=baseline_rampdown,
			smooth_lam=smooth_lam,
			smooth_p=smooth_p,
			smooth_niter=smooth_niter,
			baseline_penalty=baseline_penalty,
			smooth_penalty=smooth_penalty,
		)

		baseline_matrix[:, col_idx] = baseline
		corrected_matrix[:, col_idx] = corrected
		smoothed_matrix[:, col_idx] = smoothed

	# Close the in-place progress line.
	print()

	baseline_df = pd.DataFrame(baseline_matrix, index=df.index, columns=target_columns)
	corrected_df = df.copy()
	smoothed_df = df.copy()
	corrected_df.loc[:, target_columns] = corrected_matrix
	smoothed_df.loc[:, target_columns] = smoothed_matrix

	stem = os.path.splitext(os.path.basename(input_csv))[0]
	baseline_csv = os.path.join(output_dir, f"{stem}_baseline_als.csv")
	corrected_csv = os.path.join(output_dir, f"{stem}_corrected_als.csv")
	smoothed_csv = os.path.join(output_dir, f"{stem}_smoothed_als.csv")
	print("Guardando resultados en CSV...")

	baseline_df.to_csv(baseline_csv, index=False)
	corrected_df.to_csv(corrected_csv, index=False)
	smoothed_df.to_csv(smoothed_csv, index=False)
	total_elapsed = time.time() - process_start

	print(f"CSV de baseline guardado en: {baseline_csv}")
	print(f"CSV corregido guardado en: {corrected_csv}")
	print(f"CSV suavizado guardado en: {smoothed_csv}")
	if nan_all_count or nan_partial_count:
		print(
			f"Resumen NaN: {nan_all_count} columnas con solo NaN, "
			f"{nan_partial_count} columnas con NaN interpolados."
		)
	print(f"Tiempo total de procesamiento: {total_elapsed:.1f}s")

	print(f"OUTPUT:baseline_csv={baseline_csv}")
	print(f"OUTPUT:corrected_csv={corrected_csv}")
	print(f"OUTPUT:smoothed_csv={smoothed_csv}")

	return {
		"baseline_csv": baseline_csv,
		"corrected_csv": corrected_csv,
		"smoothed_csv": smoothed_csv,
	}


# run() is the canonical entry point called by the app's script runner.
# main() is kept as an alias for backward compatibility and CLI use.
run = main


if __name__ == "__main__":
	parser = argparse.ArgumentParser(
		description="Quita bleaching con ALS y aplica suavizado ALS final."
	)
	parser.add_argument("--nc_params", type=str)
	parser.add_argument("--nc_output", type=str)
	parser.add_argument("--params_json", type=str)

	parser.add_argument("--input_csv", type=str)
	parser.add_argument("--output_dir", type=str)
	parser.add_argument("--metrics", type=str, default="")

	parser.add_argument("--baseline_lam", type=float, default=1e5)
	parser.add_argument("--baseline_p", type=float, default=0.01)
	parser.add_argument("--baseline_niter", type=int, default=10)
	parser.add_argument("--baseline_lam_factor", type=float, default=1e-3)
	parser.add_argument("--baseline_rampup_fraction", type=float, default=0.2)
	parser.add_argument("--baseline_rampdown_fraction", type=float, default=0.2)

	parser.add_argument("--smooth_lam", type=float, default=1e1)
	parser.add_argument("--smooth_p", type=float, default=0.5)
	parser.add_argument("--smooth_niter", type=int, default=10)
	parser.add_argument("--progress_every", type=int, default=25)

	args = parser.parse_args()

	if args.nc_params:
		try:
			with open(args.nc_params, "r", encoding="utf-8") as f:
				params = json.load(f)
		except (OSError, json.JSONDecodeError) as exc:
			print(f"ERROR: no se pudo leer --nc_params: {exc}", file=sys.stderr)
			sys.exit(1)
		params.pop("_context", None)
	elif args.params_json:
		try:
			params = json.loads(args.params_json)
		except json.JSONDecodeError as exc:
			print(f"ERROR: JSON invalido en --params_json: {exc}", file=sys.stderr)
			sys.exit(1)
	else:
		if not args.input_csv or not args.output_dir:
			parser.error("Se requieren --input_csv y --output_dir")

		params = {
			"input_csv": args.input_csv,
			"output_dir": args.output_dir,
			"metrics": args.metrics,
			"baseline_lam": args.baseline_lam,
			"baseline_p": args.baseline_p,
			"baseline_niter": args.baseline_niter,
			"baseline_lam_factor": args.baseline_lam_factor,
			"baseline_rampup_fraction": args.baseline_rampup_fraction,
			"baseline_rampdown_fraction": args.baseline_rampdown_fraction,
			"smooth_lam": args.smooth_lam,
			"smooth_p": args.smooth_p,
			"smooth_niter": args.smooth_niter,
			"progress_every": args.progress_every,
		}

	try:
		outputs = main(params)
	except Exception as exc:  # noqa: BLE001
		print(f"ERROR: {exc}", file=sys.stderr)
		sys.exit(1)

	if args.nc_output:
		try:
			with open(args.nc_output, "w", encoding="utf-8") as f:
				json.dump(outputs or {}, f, ensure_ascii=False, indent=2)
		except OSError as exc:
			print(f"ERROR: no se pudo escribir --nc_output: {exc}", file=sys.stderr)
			sys.exit(1)
