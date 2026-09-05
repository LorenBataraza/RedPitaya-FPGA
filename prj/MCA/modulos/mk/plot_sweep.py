#!/usr/bin/env python3
"""
Grafica el barrido en frecuencia a partir de sweep_results.csv
(lo genera extract_metrics.py).

Genera en <rpt-dir>/plots/:
    timing.png   WNS vs frecuencia (con la linea de cero)
    fmax.png     camino critico y periodo objetivo vs frecuencia
    logica.png   LUT / FF vs frecuencia
    dedicado.png DSP / BRAM vs frecuencia
    sweep.png    figura combinada 2x2

Uso:
    python3 plot_sweep.py [--rpt-dir rpt] [--csv ...] [--show]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import matplotlib


def load(csv_path: str):
    with open(csv_path) as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"[plot] CSV vacio: {csv_path}")

    def col(name):
        out = []
        for r in rows:
            try:
                out.append(float(r.get(name, "")))
            except (ValueError, TypeError):
                out.append(float("nan"))
        return out

    return col


# (archivo, titulo, ylabel, series=[(label, columna, color, marker)], zero_line)
def panels():
    return [
        ("timing", "Slack vs frecuencia", "WNS [ns]",
         [("WNS", "wns_ns", "tab:blue", "o")], True),
        ("fmax", "Camino critico vs frecuencia", "Tiempo [ns]",
         [("camino critico", "crit_path_ns", "tab:red", "o"),
          ("periodo objetivo", "period_ns", "tab:gray", "s")], False),
        ("logica", "Logica vs frecuencia", "celdas",
         [("LUT", "lut", "tab:green", "o"),
          ("FF", "ff", "tab:olive", "s")], False),
        ("dedicado", "Recursos dedicados vs frecuencia", "bloques",
         [("DSP", "dsp", "tab:orange", "o"),
          ("BRAM", "bram", "tab:purple", "s")], False),
    ]


def draw(ax, x, col, title, ylabel, series, zero_line):
    for label, key, color, marker in series:
        ax.plot(x, col(key), marker + "-", color=color, label=label)
    if zero_line:
        ax.axhline(0.0, color="0.6", ls=":", lw=1)
    ax.set_title(title)
    ax.set_xlabel("Frecuencia objetivo [MHz]")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.grid(True)
    ax.legend(fontsize=8)


def main() -> int:
    ap = argparse.ArgumentParser(description="Grafica el barrido en frecuencia.")
    ap.add_argument("--rpt-dir", default="rpt")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--show", action="store_true", help="mostrar interactivo")
    args = ap.parse_args()

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    csv_path = args.csv or os.path.join(args.rpt_dir, "sweep_results.csv")
    if not os.path.exists(csv_path):
        print(f"[plot] no existe {csv_path}. Corriste `make extract`?", file=sys.stderr)
        return 1

    col = load(csv_path)
    x = col("freq_mhz")

    plots_dir = os.path.join(args.rpt_dir, "plots")
    os.makedirs(plots_dir, exist_ok=True)
    pnls = panels()

    for fname, title, ylabel, series, zero in pnls:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        draw(ax, x, col, title, ylabel, series, zero)
        fig.tight_layout()
        out = os.path.join(plots_dir, f"{fname}.png")
        fig.savefig(out, dpi=130)
        print(f"[plot] -> {out}")
        plt.close(fig)

    fig, axs = plt.subplots(2, 2, figsize=(12, 8))
    for ax, (_, title, ylabel, series, zero) in zip(axs.flat, pnls):
        draw(ax, x, col, title, ylabel, series, zero)
    fig.suptitle("Barrido de sintesis out-of-context (Vivado, xc7z010)")
    fig.tight_layout()
    out = os.path.join(plots_dir, "sweep.png")
    fig.savefig(out, dpi=130)
    print(f"[plot] -> {out}")

    if args.show:
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
