#!/usr/bin/env python3
"""
Junta los metrics.txt de un barrido en frecuencia y arma un CSV + un resumen
Markdown.

Estructura esperada (la genera `make sweep`):

    <rpt-dir>/
        100MHz/   metrics.txt utilization.rpt timing.rpt power.rpt
        125MHz/   ...
        150MHz/   ...

A diferencia del extract_metrics.py del generador original (que regexeaba los
reportes de Synopsys), aca no se parsea ningun .rpt: syn_ooc.tcl ya emitio un
metrics.txt en CLAVE=VALOR leyendo las properties de Vivado. Los reportes
cambian de formato entre versiones; las properties no.

Salidas (en <rpt-dir>):
    sweep_results.csv   una fila por frecuencia
    resumen.md          tabla legible frecuencia x metrica

Uso:
    python3 extract_metrics.py [--rpt-dir rpt] [--out-csv ...] [--out-md ...]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

# Columnas del CSV, en orden. Son las claves que escribe syn_ooc.tcl mas las
# derivadas que se calculan aca.
COLUMNS = [
    "freq_mhz", "period_ns", "wns_ns", "crit_path_ns", "fmax_mhz",
    "logic_levels", "timing_met",
    "lut", "ff", "dsp", "bram", "carry", "muxf",
    "power_w",
    "startpoint", "endpoint",
]

NUMERIC = {
    "freq_mhz", "period_ns", "wns_ns", "crit_path_ns", "fmax_mhz",
    "logic_levels", "lut", "ff", "dsp", "bram", "carry", "muxf", "power_w",
}


def read_metrics(path: str) -> dict:
    """Lee un metrics.txt CLAVE=VALOR. Devuelve {} si no existe."""
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    except OSError:
        return {}
    return out


def read_power(path: str):
    """Potencia total on-chip [W] del report_power de Vivado.

    Es lo unico que se saca de un .rpt: report_power no expone la cifra por
    property de forma estable. Si el formato cambia, se pierde la columna de
    potencia y el resto del barrido sigue sirviendo.
    """
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return None
    m = re.search(r"Total On-Chip Power \(W\)\s*\|\s*([\d.]+)", text)
    return float(m.group(1)) if m else None


def collect_row(rpt_dir: str, freq: int) -> dict:
    d = os.path.join(rpt_dir, f"{freq}MHz")
    m = read_metrics(os.path.join(d, "metrics.txt"))

    row = {k: m.get(k, "") for k in COLUMNS if k in m}
    row["freq_mhz"] = freq
    row.setdefault("period_ns", round(1000.0 / freq, 4))

    p = read_power(os.path.join(d, "power.rpt"))
    if p is not None:
        row["power_w"] = p

    for k in NUMERIC:
        v = row.get(k, "")
        if v not in ("", None):
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                row[k] = ""

    wns = row.get("wns_ns", "")
    row["timing_met"] = "" if wns == "" else ("MET" if wns >= 0 else "VIOLATED")
    return row


def discover_freqs(rpt_dir: str) -> list:
    fs = []
    if os.path.isdir(rpt_dir):
        for name in os.listdir(rpt_dir):
            m = re.fullmatch(r"(\d+)MHz", name)
            if m:
                fs.append(int(m.group(1)))
    return sorted(fs)


def write_csv(rows: list, path: str) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})


# (clave, encabezado, formato) de la tabla legible
_MD = [
    ("freq_mhz",     "Frec [MHz]",        "{:.0f}"),
    ("period_ns",    "Periodo [ns]",      "{:.3f}"),
    ("wns_ns",       "WNS [ns]",          "{:+.3f}"),
    ("crit_path_ns", "Camino crit. [ns]", "{:.3f}"),
    ("fmax_mhz",     "Fmax [MHz]",        "{:.1f}"),
    ("logic_levels", "Niveles",           "{:.0f}"),
    ("lut",          "LUT",               "{:.0f}"),
    ("ff",           "FF",                "{:.0f}"),
    ("dsp",          "DSP",               "{:.0f}"),
    ("bram",         "BRAM",              "{:.0f}"),
    ("power_w",      "Pot. [W]",          "{:.3f}"),
    ("timing_met",   "Timing",            "{}"),
]


def _cell(row: dict, key: str, fmt: str) -> str:
    v = row.get(key, "")
    if v in ("", None):
        return "n/a"
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def write_md(rows: list, path: str, module: str) -> str:
    heads = [h for _, h, _ in _MD]
    table = [[_cell(r, k, f) for k, _, f in _MD] for r in rows]
    widths = [max([len(heads[i])] + [len(tr[i]) for tr in table])
              for i in range(len(heads))]

    def line(cells):
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    md = [f"# Barrido de sintesis en frecuencia — {module}",
          "",
          "Sintesis out-of-context en Vivado sobre xc7z010clg400-1.",
          "Las metricas salen de `metrics.txt` (properties de Vivado), no de",
          "parsear los reportes.",
          "",
          line(heads), sep]
    md += [line(tr) for tr in table]
    md += ["",
           "- **WNS** < 0 indica violacion de timing al periodo objetivo.",
           "- **Camino critico** = periodo - WNS.",
           "- **Fmax** = 1000 / camino critico [MHz].",
           "- **Pot.** = potencia total on-chip estimada post-sintesis (sin P&R,",
           "  asi que es una cota gruesa: sirve para comparar, no como cifra final).",
           ""]
    text = "\n".join(md)
    with open(path, "w") as fh:
        fh.write(text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Junta las metricas de un barrido OOC.")
    ap.add_argument("--rpt-dir", default="rpt",
                    help="carpeta con subdirectorios <n>MHz (default: rpt)")
    ap.add_argument("--out-csv", default=None)
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args()

    freqs = discover_freqs(args.rpt_dir)
    if not freqs:
        print(f"[extract] no encontre subdirectorios <n>MHz en '{args.rpt_dir}'."
              " Corriste `make sweep`?", file=sys.stderr)
        return 1

    rows = [collect_row(args.rpt_dir, f) for f in freqs]
    module = next((read_metrics(os.path.join(args.rpt_dir, f"{f}MHz", "metrics.txt"))
                   .get("module", "?") for f in freqs), "?")

    out_csv = args.out_csv or os.path.join(args.rpt_dir, "sweep_results.csv")
    out_md = args.out_md or os.path.join(args.rpt_dir, "resumen.md")
    write_csv(rows, out_csv)
    print(write_md(rows, out_md, module))
    print(f"[extract] -> {out_csv}")
    print(f"[extract] -> {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
