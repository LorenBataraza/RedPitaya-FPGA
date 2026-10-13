#!/usr/bin/env python3
"""Pinout del Zynq-7000 de la placa: las 400 bolas del XC7Z010 CLG400.

Genera `pinout_zynq.svg`: la grilla completa de 20 × 20 bolas del encapsulado,
cada una pintada según qué es (I/O del PL, DDR3 del PS, MIO del PS,
alimentación, masa, configuración, sin conexión) y, para las que este diseño
usa, según a qué función va. Las bolas del bus del ADC llevan adentro el número
de bit, así que se ve dónde cae físicamente cada línea de la figura
`adc_pinout.svg`.

Dos fuentes, las dos verificables:

  * **Qué es cada bola**: [`datos_pinout_z010.py`](datos_pinout_z010.py), que es
    el volcado de la base de datos de Vivado para este encapsulado (banco,
    función, capacidad de reloj). Con `--bsdl <archivo>` se contrasta contra el
    BSDL del mismo encapsulado, que es una fuente independiente.
  * **Para qué la usa la placa**: `sdc/red_pitaya.xdc`, leído en vivo del repo.

Lo que las dos juntas dicen, y está anotado en la figura:

  * el 7010 tiene **100 bolas de I/O del PL** y la Red Pitaya usa **99**: la
    única libre es R17;
  * las **25 bolas sin conexión** del 7010 son I/O en el 7020 (que tiene 125):
    ahí están las 6 líneas extra de E1 que el RTL habilita con `DWE = 11`;
  * el PS se lleva 133 bolas y la alimentación 128.

    python3 figuras_pinout_zynq.py
    python3 figuras_pinout_zynq.py --bsdl /tools/Xilinx/Vivado/2021.2/data/\\
        parts/xilinx/zynq/public/bsdl/xc7z010_clg400.bsd
"""

import argparse
import re
from pathlib import Path

from datos_pinout_z010 import PINES, clase

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "pinout_zynq.svg"
XDC = AQUI.parents[3] / "sdc" / "red_pitaya.xdc"

FILAS = "ABCDEFGHJKLMNPRTUVWY"          # JEDEC: sin I, O, Q, S, X, Z
NCOL = 20

# --------------------------------------------------------------------------- #
# Grupos funcionales (orden = orden de la leyenda)
# --------------------------------------------------------------------------- #
GRUPOS = [
    ("adca",  "ADC · datos canal A (IN1)",      "#0b6bcb", "#ffffff"),
    ("adcb",  "ADC · datos canal B (IN2)",      "#4c9ae8", "#0d1117"),
    ("adcc",  "ADC · reloj y control",          "#7b3fb5", "#ffffff"),
    ("dac",   "DAC y salidas PWM lentas",       "#b5651d", "#ffffff"),
    ("e1",    "E1 · 16 líneas digitales",       "#2f9e44", "#ffffff"),
    ("daisy", "S1/S2 · daisy chain",            "#c2185b", "#ffffff"),
    ("led",   "LEDs",                           "#b58900", "#ffffff"),
    ("xadc",  "XADC · 4 entradas lentas (AI0–AI3)", "#0b7285", "#ffffff"),
    ("free",  "I/O del PL sin usar",            None,      None),
    ("nc",    "sin conexión (I/O en el 7020)",  None,      None),
    ("ddr",   "PS · DDR3",                      "#9fb0c2", "#1b1f24"),
    ("mio",   "PS · MIO",                       "#c2b49f", "#1b1f24"),
    ("ps",    "PS · reloj y reset",             "#7f93a8", "#ffffff"),
    ("cfg",   "configuración, JTAG, XADC ded.", "#a8a3b8", "#1b1f24"),
    ("vcc",   "alimentación",                   "#d89a7f", "#1b1f24"),
    ("gnd",   "masa",                           "#8c959f", "#ffffff"),
]
ORDEN = [g[0] for g in GRUPOS]

def grupo_por_puerto(p):
    """Puerto del XDC → grupo de la leyenda, y número de bit si lo tiene."""
    if p.startswith("adc_dat_i[0]"):
        return "adca", p.split("][")[1].rstrip("]")
    if p.startswith("adc_dat_i[1]"):
        return "adcb", p.split("][")[1].rstrip("]")
    if p.startswith(("adc_clk", "adc_cdcs")):
        return "adcc", None
    if p.startswith("dac_"):
        return "dac", None
    if p.startswith("exp_"):
        return "e1", None
    if p.startswith("daisy_"):
        return "daisy", None
    if p.startswith("led_"):
        return "led", None
    if p.startswith(("vinp_i", "vinn_i")):
        return "xadc", None
    return "otro", None


# --------------------------------------------------------------------------- #
# Carga de datos
# --------------------------------------------------------------------------- #
def clases_del_modulo():
    """Bola → grupo de la leyenda, antes de aplicar el XDC."""
    return {b: ("free" if clase(b) == "io" else clase(b)) for b in PINES}


def clases_del_bsdl(ruta):
    """Re-deriva las clases del PIN_MAP_STRING del BSDL."""
    src = Path(ruta).read_text(errors="ignore")
    m = re.search(r"constant CLG400: PIN_MAP_STRING:=(.*?);", src, re.S)
    cuerpo = re.sub(r"--[^\n]*", "", m.group(1))
    cuerpo = cuerpo.replace('"', "").replace("&", "").replace("\n", " ")
    d = {}
    for nombre, val in re.findall(
            r"([A-Za-z0-9_]+)\s*:\s*(\([^)]*\)|[A-Z]+\d+)", cuerpo):
        if nombre.startswith("IO_"):
            k = "io"
        elif nombre == "NOCONNECT":
            k = "nc"
        elif nombre.startswith("PS_DDR"):
            k = "ddr"
        elif nombre.startswith("PS_MIO"):
            k = "mio"
        elif nombre.startswith("PS_"):
            k = "ps"
        elif nombre.startswith(("VCC", "RSVDVCC")):
            k = "vcc"
        elif nombre.startswith("GND") or nombre.startswith("RSVDGND"):
            k = "gnd"
        else:
            k = "cfg"
        for b in [x.strip() for x in val.strip("()").split(",") if x.strip()]:
            d[b] = k
    return d


def funciones_del_xdc(ruta):
    """ball → (grupo, bit) según las asignaciones PACKAGE_PIN del XDC."""
    txt = Path(ruta).read_text()
    out = {}
    for m in re.finditer(
            r"PACKAGE_PIN\s+([A-Z]+\d+)[^\n]*?get_ports\s*\{?\s*"
            r"([A-Za-z0-9_\[\]]+)", txt):
        g, bit = grupo_por_puerto(m.group(2))
        if g != "otro":
            out[m.group(1)] = (g, bit)
    return out


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
W, H = 1150, 830
MG = 30
X0, Y0, CELL, R = 74, 108, 29, 11.2
LEG_X = X0 + NCOL * CELL + 46

partes = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, cls="nm", size=11, anchor="start", weight=None, mono=False):
    w = f' font-weight="{weight}"' if weight else ""
    f = (' font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"'
         if mono else "")
    partes.append(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" '
                  f'font-size="{size}" text-anchor="{anchor}"{w}{f}>'
                  f'{esc(s)}</text>')


def centro(fila, col):
    return (X0 + (col - 1) * CELL + CELL / 2,
            Y0 + FILAS.index(fila) * CELL + CELL / 2)


def construir(clases, usos):
    # --- encabezado ---------------------------------------------------------
    txt(MG, 36, "Pinout del Zynq: las 400 bolas del XC7Z010 CLG400", "ttl", 19,
        weight="700")
    txt(MG, 58,
        "BGA de 400 bolas en grilla de 20 × 20 · filas JEDEC (sin I, O, Q, S, "
        "X, Z) · clases del BSDL de Vivado, funciones de sdc/red_pitaya.xdc",
        "st", 11.5)
    txt(MG, 80,
        "Las bolas del bus del ADC llevan adentro su número de bit: es la misma "
        "información de adc_pinout.svg, puesta sobre el encapsulado.", "note",
        10.5)

    # --- rótulos de la grilla ----------------------------------------------
    for c in range(1, NCOL + 1):
        x = X0 + (c - 1) * CELL + CELL / 2
        txt(x, Y0 - 9, str(c), "ax", 9.5, anchor="middle")
        txt(x, Y0 + NCOL * CELL + 16, str(c), "ax", 9.5, anchor="middle")
    for i, f in enumerate(FILAS):
        y = Y0 + i * CELL + CELL / 2 + 3.5
        txt(X0 - 11, y, f, "ax", 9.5, anchor="middle")
        txt(X0 + NCOL * CELL + 11, y, f, "ax", 9.5, anchor="middle")

    # --- bolas --------------------------------------------------------------
    cuenta = {g: 0 for g in ORDEN}
    for i, f in enumerate(FILAS):
        for c in range(1, NCOL + 1):
            bola = f"{f}{c}"
            g = clases[bola]
            bit = None
            if g == "free" and bola in usos:
                g, bit = usos[bola]
            cuenta[g] += 1
            x, y = centro(f, c)
            partes.append(f'<circle class="b-{g}" cx="{x:.1f}" cy="{y:.1f}" '
                          f'r="{R}"/>')
            if bit is not None:
                partes.append(
                    f'<text class="t-{g}" x="{x:.1f}" y="{y + 3.3:.1f}" '
                    f'font-size="9" text-anchor="middle" '
                    f'font-family="ui-monospace,SFMono-Regular,Menlo,'
                    f'Consolas,monospace">{bit}</text>')

    # --- la única I/O libre: anillo (sin línea guía, que taparía bolas) -----
    libre = [b for b, g in clases.items() if g == "free" and b not in usos]
    for b in libre:
        fx, cx_ = re.match(r"([A-Z]+)(\d+)", b).groups()
        x, y = centro(fx, int(cx_))
        partes.append(f'<circle class="ring" cx="{x:.1f}" cy="{y:.1f}" '
                      f'r="{R + 4.5:.1f}"/>')

    # --- leyenda ------------------------------------------------------------
    yl = Y0 + 6
    txt(LEG_X, yl, "Qué es cada bola", "ti", 12.5, weight="700")
    yl += 10
    for g, etiqueta, _, _ in GRUPOS:
        yl += 21
        if yl > Y0 + NCOL * CELL - 40:        # la columna de la llamada
            continue
        partes.append(f'<circle class="b-{g}" cx="{LEG_X + 9:.1f}" '
                      f'cy="{yl - 4:.1f}" r="8"/>')
        txt(LEG_X + 26, yl, etiqueta, "nm", 10.5)
        txt(W - MG, yl, str(cuenta[g]), "wd", 10.5, anchor="end", mono=True)
    partes.append(f'<line class="sep" x1="{LEG_X}" y1="{yl + 10:.1f}" '
                  f'x2="{W - MG}" y2="{yl + 10:.1f}"/>')
    txt(LEG_X + 26, yl + 27, "total", "nm", 10.5, weight="700")
    txt(W - MG, yl + 27, str(sum(cuenta.values())), "nm", 10.5, anchor="end",
        mono=True, weight="700")

    # --- notas --------------------------------------------------------------
    yn = Y0 + NCOL * CELL + 44
    io_pl = sum(1 for g in clases.values() if g == "free")
    io_usadas = io_pl - cuenta["free"]
    for i, nota in enumerate([
        f"El 7010 tiene {io_pl} bolas de I/O del PL y esta placa usa "
        f"{io_usadas}: la única libre es {', '.join(sorted(libre))}, marcada "
        f"con el anillo azul. Lo que entra y sale del FPGA está, "
        f"prácticamente, al límite del encapsulado.",
        f"Las {cuenta['nc']} bolas sin conexión son I/O en el 7020, que tiene "
        f"125: ahí viven las 6 líneas extra de E1 que el RTL habilita con "
        f"DWE = 11 en vez de 8 (22 GPIO en vez de 16).",
        f"El PS se lleva {cuenta['ddr'] + cuenta['mio'] + cuenta['ps']} bolas "
        f"({cuenta['ddr']} de DDR3, {cuenta['mio']} de MIO, {cuenta['ps']} de "
        f"reloj y reset) y la alimentación {cuenta['vcc'] + cuenta['gnd']} "
        f"({cuenta['vcc']} VCC + {cuenta['gnd']} GND): de 400 bolas, sólo una "
        f"cuarta parte es I/O del PL.",
        "Las dos entradas analógicas dedicadas del XADC (VP/VN, K9 y L10) no "
        "son I/O: son los pines analógicos del conversor interno, y la placa "
        "los usa como el par AI de más.",
    ]):
        txt(MG, yn + i * 17, nota, "note", 10.5)


def render():
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans,Helvetica,Arial,'
           f'sans-serif">']
    estilos = ["""<style>
  .bg{fill:#ffffff}
  .nm{fill:#1b1f24} .wd{fill:#57606a} .ax{fill:#8b949e}
  .ti{fill:#1b1f24} .st{fill:#57606a} .ttl{fill:#1b1f24} .note{fill:#57606a}
  .key{fill:#0b6bcb}
  .sep{stroke:#c3cad1;stroke-width:0.9}
  .ring{fill:none;stroke:#0b6bcb;stroke-width:1.8}
  .lead{stroke:#0b6bcb;stroke-width:1.1;stroke-dasharray:3 3}
  .b-free{fill:#ffffff;stroke:#1b1f24;stroke-width:1.1}
  .b-nc{fill:none;stroke:#b6bec6;stroke-width:1;stroke-dasharray:2 2}
"""]
    for g, _, fill, tint in GRUPOS:
        if fill:
            estilos.append(f"  .b-{g}{{fill:{fill};stroke:none}}\n"
                           f"  .t-{g}{{fill:{tint}}}\n")
    estilos.append("""  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .nm{fill:#e6edf3} .wd{fill:#8b949e} .ax{fill:#6e7781}
    .ti{fill:#e6edf3} .st{fill:#8b949e} .ttl{fill:#e6edf3} .note{fill:#8b949e}
    .key{fill:#58a6ff}
    .sep{stroke:#30363d}
    .ring{stroke:#58a6ff} .lead{stroke:#58a6ff}
    .b-free{fill:#0d1117;stroke:#c9d1d9}
    .b-nc{stroke:#484f58}
  }
</style>""")
    out.append("".join(estilos))
    out.append(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
    out.extend(partes)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bsdl", help="re-derivar las clases del BSDL y verificar "
                                   "contra la copia embebida")
    args = ap.parse_args()

    clases = clases_del_modulo()
    if args.bsdl:
        ref = clases_del_bsdl(args.bsdl)
        equiv = {"free": "io"}
        dif = {b for b in clases
               if equiv.get(clases[b], clases[b]) != ref.get(b)}
        if dif:
            raise SystemExit(f"los datos del encapsulado no coinciden con el "
                             f"BSDL en {len(dif)} bolas: {sorted(dif)[:10]}")
        print(f"verificado contra {args.bsdl}: las 400 bolas coinciden")

    usos = funciones_del_xdc(XDC)
    construir(clases, usos)
    SALIDA.write_text(render(), encoding="utf-8")
    print(f"escrito {SALIDA} ({SALIDA.stat().st_size} B) · "
          f"{len(usos)} pines asignados en {XDC.name}")


if __name__ == "__main__":
    main()
