# This Python file uses the following encoding: utf-8
"""generar_graficos — Genera gráficos de resumen a partir de trazas procesadas.

Lee un CSV de trazas (columnas = células, filas = tiempo) y produce, en la carpeta
de salida:
  * traces_overlay.<fmt>  — todas las trazas superpuestas
  * traces_raster.<fmt>   — mapa de calor (raster) de células × tiempo
  * mean_trace.<fmt>      — traza promedio ± desvío

El formato de imagen (png/svg/pdf) es configurable.

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


def _time_axis(df: pd.DataFrame, n: int):
    """Usa tiempo_s si está disponible, si no el índice de frame."""
    for name in ("tiempo_s", "tiempo", "time"):
        if name in df.columns:
            return df[name].to_numpy(dtype=float), "Tiempo (s)"
    return np.arange(n, dtype=float), "Frame"


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    fmt = params.get("formato", "png")
    titulo = params.get("titulo", "") or "Resumen de trazas"

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"No se encontró el CSV de entrada: {input_csv}")
    figures_dir = os.path.join(output_dir, "figuras")
    os.makedirs(figures_dir, exist_ok=True)

    print(f"Leyendo trazas: {os.path.basename(input_csv)}")
    df = pd.read_csv(input_csv)
    signal_cols = _signal_columns(df)
    if not signal_cols:
        raise ValueError("El CSV no contiene columnas de señal numéricas.")

    t, t_label = _time_axis(df, len(df))
    data = df[signal_cols].to_numpy(dtype=float)  # shape (frames, cells)
    print(f"  {len(signal_cols)} células × {len(df)} frames")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    saved = []

    # 1) Overlay de todas las trazas.
    fig, ax = plt.subplots(figsize=(10, 5))
    for j in range(data.shape[1]):
        ax.plot(t, data[:, j], linewidth=0.6, alpha=0.7)
    ax.set_title(f"{titulo} — trazas superpuestas")
    ax.set_xlabel(t_label)
    ax.set_ylabel("Fluorescencia")
    p = os.path.join(figures_dir, f"traces_overlay.{fmt}")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)
    print("PROGRESS:40")

    # 2) Raster / mapa de calor células × tiempo.
    fig, ax = plt.subplots(figsize=(10, max(3, data.shape[1] * 0.2)))
    im = ax.imshow(
        data.T, aspect="auto", cmap="viridis",
        extent=[float(t[0]), float(t[-1]), data.shape[1], 0],
    )
    ax.set_title(f"{titulo} — raster")
    ax.set_xlabel(t_label)
    ax.set_ylabel("Célula")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="Fluorescencia")
    p = os.path.join(figures_dir, f"traces_raster.{fmt}")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)
    print("PROGRESS:70")

    # 3) Traza promedio ± desvío.
    mean = np.nanmean(data, axis=1)
    std = np.nanstd(data, axis=1)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, mean, color="C0", label="media")
    ax.fill_between(t, mean - std, mean + std, color="C0", alpha=0.25, label="± desvío")
    ax.set_title(f"{titulo} — traza promedio")
    ax.set_xlabel(t_label)
    ax.set_ylabel("Fluorescencia")
    ax.legend(loc="upper right")
    p = os.path.join(figures_dir, f"mean_trace.{fmt}")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)
    print("PROGRESS:100")

    print(f"Gráficos guardados en: {figures_dir}")
    for s in saved:
        print(f"  {os.path.basename(s)}")

    return {"figures_dir": figures_dir}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Genera gráficos de resumen.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--formato", default="png", choices=["png", "svg", "pdf"])
    parser.add_argument("--titulo", default="")
    args = parser.parse_args()
    print(run(vars(args)))
