# This Python file uses the following encoding: utf-8
"""seleccionar_activas — Selecciona células/trazas activas por umbral de actividad.

Lee un CSV de trazas de fluorescencia (columnas = células/métricas, filas = tiempo),
detecta qué trazas presentan al menos un evento de actividad — un tramo de
``min_duracion`` frames consecutivos por encima de ``media + umbral_std·desvío`` — y
escribe un CSV con las columnas de metadatos (frame, tiempo_s) más únicamente las
trazas consideradas activas. Preserva el formato para los scripts posteriores
(matriz_pearson, generar_graficos).

Contrato: ver README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

# Columnas de metadatos que no son señales de células (se conservan tal cual).
IGNORED_COLUMNS = {"", "Slice", "frame", "tiempo_s", "tiempo", "time"}


def _signal_columns(df: pd.DataFrame):
    """Devuelve las columnas de señal: numéricas y que no sean metadatos."""
    cols = []
    for col in df.columns:
        if str(col).strip() in IGNORED_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(col)
    return cols


def _max_run_above(values: np.ndarray, threshold: float) -> int:
    """Longitud del tramo más largo de valores consecutivos por encima del umbral.

    Los NaN cuentan como 'por debajo' (interrumpen el tramo).
    """
    with np.errstate(invalid="ignore"):
        above = (values > threshold) & ~np.isnan(values)
    best = run = 0
    for flag in above:
        run = run + 1 if flag else 0
        if run > best:
            best = run
    return best


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    umbral_std = float(params.get("umbral_std", 2.5))
    min_duracion = int(params.get("min_duracion", 3))

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"No se encontró el CSV de entrada: {input_csv}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Leyendo trazas: {os.path.basename(input_csv)}")
    df = pd.read_csv(input_csv)

    signal_cols = _signal_columns(df)
    meta_cols = [c for c in df.columns if c not in signal_cols]
    if not signal_cols:
        raise ValueError("El CSV no contiene columnas de señal numéricas.")

    print(f"  Columnas de señal: {len(signal_cols)} | metadatos: {len(meta_cols)}")
    print(f"  Criterio: > media + {umbral_std}·desvío durante >= {min_duracion} frames")

    active_cols = []
    total = len(signal_cols)
    for i, col in enumerate(signal_cols, start=1):
        x = df[col].to_numpy(dtype=float)
        # Robust baseline: median + k·σ_MAD. Using median/MAD instead of mean/std
        # keeps the threshold from being inflated by the events themselves (a few
        # large transients would otherwise raise std and mask real activity).
        median = np.nanmedian(x)
        mad = np.nanmedian(np.abs(x - median))
        robust_std = 1.4826 * mad
        if not robust_std or np.isnan(robust_std):
            robust_std = np.nanstd(x)  # fallback for degenerate/flat traces
        threshold = median + umbral_std * robust_std
        if _max_run_above(x, threshold) >= min_duracion:
            active_cols.append(col)

        if total and (i % max(1, total // 10) == 0 or i == total):
            print(f"PROGRESS:{i / total * 100:.0f}")

    print(f"Células activas: {len(active_cols)} / {total}")

    out_df = df[meta_cols + active_cols]
    base = os.path.splitext(os.path.basename(input_csv))[0]
    active_path = os.path.join(output_dir, f"{base}_activas.csv")
    out_df.to_csv(active_path, index=False)
    print(f"CSV de activas guardado: {active_path}")

    return {"active_csv": active_path}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Selecciona células/trazas activas.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--umbral_std", type=float, default=2.5)
    parser.add_argument("--min_duracion", type=int, default=3)
    args = parser.parse_args()
    print(run(vars(args)))
