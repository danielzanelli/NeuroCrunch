# This Python file uses the following encoding: utf-8
"""matriz_pearson — Matriz de correlación de Pearson entre trazas.

Lee un CSV de trazas (columnas = células, filas = tiempo), calcula la matriz de
correlación de Pearson entre todas las células y guarda:
  * matrix_csv   — la matriz de correlación como CSV
  * heatmap_png  — un mapa de calor de la matriz

``umbral_correlacion`` se usa para informar cuántos pares de células superan ese
valor absoluto de correlación.

Contrato: ver README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

IGNORED_COLUMNS = {"", "Slice", "frame", "tiempo_s", "tiempo", "time"}


def _signal_columns(df: pd.DataFrame):
    return [
        c for c in df.columns
        if str(c).strip() not in IGNORED_COLUMNS and pd.api.types.is_numeric_dtype(df[c])
    ]


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    umbral = float(params.get("umbral_correlacion", 0.5))

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"No se encontró el CSV de entrada: {input_csv}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Leyendo trazas: {os.path.basename(input_csv)}")
    df = pd.read_csv(input_csv)
    signal_cols = _signal_columns(df)
    if len(signal_cols) < 2:
        raise ValueError("Se necesitan al menos 2 columnas de señal para correlacionar.")

    print(f"  Calculando correlación de Pearson entre {len(signal_cols)} células...")
    print("PROGRESS:30")
    corr = df[signal_cols].corr(method="pearson")

    base = os.path.splitext(os.path.basename(input_csv))[0]
    matrix_path = os.path.join(output_dir, f"{base}_pearson.csv")
    corr.to_csv(matrix_path)
    print(f"Matriz guardada: {matrix_path}")
    print("PROGRESS:60")

    # Contar pares (triángulo superior) que superan el umbral en valor absoluto.
    n = len(signal_cols)
    upper = np.triu(np.ones((n, n), dtype=bool), k=1)
    vals = corr.to_numpy()
    n_pairs = int(np.sum((np.abs(vals) >= umbral) & upper))
    total_pairs = n * (n - 1) // 2
    print(f"Pares con |correlación| >= {umbral}: {n_pairs} / {total_pairs}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(max(4, n * 0.3), max(4, n * 0.3)))
    im = ax.imshow(vals, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_title("Matriz de correlación de Pearson")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(signal_cols, rotation=90, fontsize=6)
    ax.set_yticklabels(signal_cols, fontsize=6)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="r de Pearson")
    heatmap_path = os.path.join(output_dir, f"{base}_pearson_heatmap.png")
    fig.savefig(heatmap_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Mapa de calor guardado: {heatmap_path}")
    print("PROGRESS:100")

    return {"matrix_csv": matrix_path, "heatmap_png": heatmap_path}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Matriz de correlación de Pearson.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--umbral_correlacion", type=float, default=0.5)
    args = parser.parse_args()
    print(run(vars(args)))
