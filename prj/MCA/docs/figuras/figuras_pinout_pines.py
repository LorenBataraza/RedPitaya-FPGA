#!/usr/bin/env python3
"""Pinout del XC7Z010 CLG400, sin la placa: qué es cada una de las 400 bolas.

Es la figura de referencia del encapsulado *pelado* — no dice qué usa la Red
Pitaya, sino qué ofrece el chip: banco, nombre del pin, pares diferenciales,
pines capaces de manejar reloj, entradas auxiliares del XADC, alimentación y
masa. La versión con los usos de la placa es `pinout_zynq.svg`
([`figuras_pinout_zynq.py`](figuras_pinout_zynq.py)).

Genera dos cosas:

    python3 figuras_pinout_pines.py           # → pinout_pines.svg
    python3 figuras_pinout_pines.py --tabla   # → las tablas en Markdown

Las tablas describen los pines que **sí** usa la placa, cruzando el pinout con
`sdc/red_pitaya.xdc`: un resumen por función y el detalle bola por bola. Se
pegan en [`../pinout_zynq.md`](../pinout_zynq.md); si no coinciden con lo que
imprime el script, manda el script.

Los datos del encapsulado salen de [`datos_pinout_z010.py`](datos_pinout_z010.py)
(volcado de la base de datos de Vivado, ver su cabecera).

Cómo leer el nombre de un pin de I/O, que es la convención de Xilinx:

    IO_L12P_T1_MRCC_34
       │   │  │  │    └─ banco
       │   │  │  └────── capaz de manejar reloj (MRCC = multi-región,
       │   │  │          SRCC = una región); otras marcas: VREF (bola de
       │   │  │          referencia del banco), DQS, ADxP/ADxN (entrada
       │   │  │          auxiliar del XADC), PUDC_B
       │   │  └───────── byte group dentro del banco (T0..T3)
       │   └──────────── lado P o N del par diferencial
       └──────────────── número de par dentro del banco
"""

import argparse
import re
from pathlib import Path

from datos_pinout_z010 import PINES, clase, corto

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "pinout_pines.svg"
# Los dos XDC que entran al build del MCA, en el orden en que los agrega
# red_pitaya_vivado_Z10_mca.tcl: el de la placa y el del proyecto (que agrega
# los IOSTANDARD del daisy y las líneas de E1 que sólo existen en el 7020).
XDCS = [AQUI.parents[3] / "sdc" / "red_pitaya.xdc",
        AQUI.parents[1] / "sdc" / "red_pitaya.xdc"]

FILAS = "ABCDEFGHJKLMNPRTUVWY"
NCOL = 20

# --------------------------------------------------------------------------- #
# Colores por clase (claros: adentro va texto negro)
# --------------------------------------------------------------------------- #
CLASES = [
    ("io34", "I/O del PL · banco 34",        "#d6e6f7"),
    ("io35", "I/O del PL · banco 35",        "#d7eedd"),
    ("nc",   "sin conexión (I/O en el 7020)", "#f4f5f6"),
    ("cfg",  "banco 0 · configuración, JTAG y XADC", "#e9e3f6"),
    ("mio",  "PS · MIO (bancos 500/501)",    "#f3e8d8"),
    ("ddr",  "PS · DDR3 (banco 502)",        "#e2e8f0"),
    ("ps",   "PS · reloj y reset",           "#cfdbe6"),
    ("vcc",  "alimentación",                 "#fae0d2"),
    ("gnd",  "masa",                         "#e6e9ec"),
]

# --------------------------------------------------------------------------- #
# Los grupos funcionales de la placa, para las tablas
# --------------------------------------------------------------------------- #
GRUPOS = [
    ("adc_dat_i[0]", "ADC · datos del canal A (IN1)",
     "las 14 líneas útiles más los 2 bits bajos reservados para el ADC de "
     "16 bit de la 122-16"),
    ("adc_dat_i[1]", "ADC · datos del canal B (IN2)", "ídem canal B"),
    ("adc_clk_i",    "ADC · reloj de muestreo",
     "par diferencial desde el oscilador de 125 MHz; entra por un par MRCC "
     "porque de ahí cuelga la PLL de todo el datapath"),
    ("adc_clk_o",    "ADC · salida de reloj opcional",
     "cableada pero sin uso en la 125-14: el reloj va del XO directo al ADC"),
    ("adc_cdcs_o",   "ADC · clock duty cycle stabilizer",
     "atada a 1 en el top; es el único control del ADC que llega al FPGA"),
    ("dac_dat_o",    "DAC · bus de datos entrelazado",
     "un solo bus de 14 bit para los dos canales, con los datos cambiando en "
     "los dos flancos"),
    ("dac_wrt_o",    "DAC · estrobo de escritura", "a 250 MHz"),
    ("dac_sel_o",    "DAC · selección de canal", "alterna A y B"),
    ("dac_clk_o",    "DAC · reloj", "desfasado −45° para centrar el muestreo"),
    ("dac_rst_o",    "DAC · reset", ""),
    ("dac_pwm_o",    "AO0–AO3 · salidas analógicas lentas",
     "no son un DAC: son PWM/PDM de la PL filtradas con RC en la placa"),
    ("exp_p_io",     "E1 · lado P de las 8 líneas digitales",
     "DIO0_P es el trigger externo y el veto del MCA; 4 de las 8 caen en "
     "pines capaces de manejar reloj"),
    ("exp_n_io",     "E1 · lado N de las 8 líneas digitales",
     "DIO0_N puede sacar el trigger del scope hacia afuera"),
    ("daisy_p_o",    "S1/S2 · salida diferencial", "lado P"),
    ("daisy_n_o",    "S1/S2 · salida diferencial", "lado N"),
    ("daisy_p_i",    "S1/S2 · entrada diferencial",
     "la línea [1] entra por un par MRCC: es la que puede traer reloj de otra "
     "placa (create_clock de 4 ns en el XDC)"),
    ("daisy_n_i",    "S1/S2 · entrada diferencial", "lado N"),
    ("led_o",        "LEDs", "los maneja red_pitaya_hk"),
    ("vinp_i",       "XADC · entradas analógicas lentas, lado P",
     "AI0–AI3 por pines ADxP del PL, más el par dedicado VP/VN del banco 0"),
    ("vinn_i",       "XADC · entradas analógicas lentas, lado N", ""),
]

DIREC = {"_i": "entrada", "_o": "salida", "_io": "bidireccional"}


def base_puerto(p):
    """Puerto sin su último índice: adc_dat_i[0][15] → adc_dat_i[0]."""
    return re.sub(r"\[\d+\]$", "", p)


def equilibra(p):
    """Recorta los ] de más que deja el regex en `[get_ports adc_clk_i[0]]`."""
    while p.count("]") > p.count("["):
        p = p[:-1]
    return p


def direccion(p):
    b = base_puerto(p)
    for suf in ("_io", "_i", "_o"):
        if b.endswith(suf):
            return DIREC[suf]
    return ""


def indice(p):
    """Índice de bit para ordenar: adc_dat_i[0][7] → (0, 7)."""
    return tuple(int(x) for x in re.findall(r"\[(\d+)\]", p))


def clase_fig(bola):
    c = clase(bola)
    if c == "io":
        return "io" + PINES[bola][0]
    return c


# --------------------------------------------------------------------------- #
# Lectura del XDC
# --------------------------------------------------------------------------- #
def lee_xdc(rutas):
    """→ {puerto: (bola, iostandard)} de las asignaciones de los XDC."""
    pines, patrones = {}, []
    for ruta in rutas:
        txt = "\n".join(l for l in Path(ruta).read_text().splitlines()
                        if not l.lstrip().startswith("#"))
        for m in re.finditer(r"PACKAGE_PIN\s+([A-Z]+\d+)[^\n]*?get_ports\s*"
                             r"\{?\s*([A-Za-z0-9_\[\]]+)", txt):
            pines[equilibra(m.group(2))] = m.group(1)
        # IOSTANDARD: en el mismo -dict que el pin, o aparte con comodines
        for m in re.finditer(r"PACKAGE_PIN\s+[A-Z]+\d+\s+IOSTANDARD\s+(\w+)"
                             r"[^\n]*?get_ports\s*\{?\s*([A-Za-z0-9_\[\]\*]+)",
                             txt):
            patrones.append((equilibra(m.group(2)), m.group(1)))
        for m in re.finditer(r"set_property\s+IOSTANDARD\s+(\w+)\s+\[get_ports"
                             r"\s*\{?\s*([A-Za-z0-9_\[\]\*]+)", txt):
            patrones.append((equilibra(m.group(2)), m.group(1)))
    out = {}
    for p, bola in pines.items():
        std = ""
        for pat, s in patrones:
            if re.fullmatch(re.escape(pat).replace(r"\*", r"[^\]]*"), p):
                std = s
        out[p] = (bola, std)
    return out


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
W, H = 1200, 900
MG = 30
X0, Y0 = 78, 128
CW, CH = 53.5, 32
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


def svg():
    txt(MG, 36, "Pinout del XC7Z010 CLG400: qué es cada bola", "ttl", 19,
        weight="700")
    txt(MG, 58,
        "El encapsulado solo, sin la placa: banco, nombre del pin y "
        "capacidades. Lo que la Red Pitaya conecta a cada uno está en "
        "pinout_zynq.svg.", "st", 11.5)
    txt(MG, 82,
        "IO_L12P_T1_MRCC_34  →  par 12, lado P, byte group T1, capaz de manejar "
        "reloj, banco 34.   Marcas: MRCC/SRCC reloj · VREF referencia del banco "
        "· ADxP/ADxN entrada del XADC · DQS · PUDC_B.", "note", 10)
    txt(MG, 100,
        "Datos de la base de Vivado para esta parte (ver datos_pinout_z010.py), "
        "contrastados contra el BSDL del encapsulado.", "note", 10)

    for c in range(1, NCOL + 1):
        x = X0 + (c - 1) * CW + CW / 2
        txt(x, Y0 - 8, str(c), "ax", 9.5, anchor="middle")
        txt(x, Y0 + NCOL * CH + 15, str(c), "ax", 9.5, anchor="middle")
    for i, f in enumerate(FILAS):
        y = Y0 + i * CH + CH / 2 + 3.5
        txt(X0 - 12, y, f, "ax", 9.5, anchor="middle")
        txt(X0 + NCOL * CW + 12, y, f, "ax", 9.5, anchor="middle")

    for i, f in enumerate(FILAS):
        for c in range(1, NCOL + 1):
            bola = f"{f}{c}"
            cl = clase_fig(bola)
            x, y = X0 + (c - 1) * CW, Y0 + i * CH
            partes.append(f'<rect class="c-{cl}" x="{x + 1:.1f}" '
                          f'y="{y + 1:.1f}" width="{CW - 2:.1f}" '
                          f'height="{CH - 2:.1f}" rx="3"/>')
            n, sub = corto(bola)
            marcas = PINES[bola][3]
            partes.append(
                f'<text class="pn" x="{x + CW / 2:.1f}" y="{y + 14:.1f}" '
                f'font-size="8.2" text-anchor="middle" font-weight="600" '
                f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'
                f'monospace">{esc(n)}</text>')
            if sub:
                cls = "pc" if "c" in marcas else "ps2"
                partes.append(
                    f'<text class="{cls}" x="{x + CW / 2:.1f}" '
                    f'y="{y + 24:.1f}" font-size="7" text-anchor="middle" '
                    f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'
                    f'monospace">{esc(sub)}</text>')

    # leyenda horizontal
    yl = Y0 + NCOL * CH + 44
    x = MG
    for cl, etiqueta, _ in CLASES:
        partes.append(f'<rect class="c-{cl}" x="{x:.1f}" y="{yl - 9:.1f}" '
                      f'width="16" height="12" rx="2"/>')
        txt(x + 22, yl, etiqueta, "nm", 9.8)
        x += 26 + 5.1 * len(etiqueta)
        if x > W - 240:
            x, yl = MG, yl + 19

    txt(MG, yl + 26,
        "Los 100 pines de I/O del PL del 7010 son exactamente 50 del banco 34 "
        "y 50 del 35. El banco 13 existe en el encapsulado —tiene sus cuatro "
        "bolas de VCCO— pero no tiene una sola I/O bondeada:", "note", 10.5)
    txt(MG, yl + 42,
        "sus 25 pines son las bolas sin conexión de esta figura, y son I/O en "
        "el 7020. Por eso la misma PCB acepta los dos chips, y por eso el 7020 "
        "tiene 125 I/O en vez de 100.", "note", 10.5)


def render():
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans,Helvetica,Arial,'
           f'sans-serif">']
    est = ["""<style>
  .bg{fill:#ffffff}
  .nm{fill:#1b1f24} .ax{fill:#8b949e} .ttl{fill:#1b1f24} .st{fill:#57606a}
  .note{fill:#57606a}
  .pn{fill:#1b1f24} .ps2{fill:#6e7781} .pc{fill:#0b6bcb;font-weight:700}
"""]
    for cl, _, fill in CLASES:
        borde = ";stroke:#c3cad1;stroke-width:0.8;stroke-dasharray:2 2" \
            if cl == "nc" else ""
        est.append(f"  .c-{cl}{{fill:{fill}{borde}}}\n")
    est.append("""  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .nm{fill:#e6edf3} .ax{fill:#6e7781} .ttl{fill:#e6edf3} .st{fill:#8b949e}
    .note{fill:#8b949e}
    .pn{fill:#0d1117} .ps2{fill:#30363d} .pc{fill:#0b4d8f}
  }
</style>""")
    out.append("".join(est))
    out.append(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
    out.extend(partes)
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Tablas
# --------------------------------------------------------------------------- #
def tablas(rutas):
    puertos = lee_xdc(rutas)
    sin_bondear = {p: b for p, (b, _) in puertos.items()
                   if clase(b) == "nc"}
    por_grupo = {}
    for p, (bola, std) in puertos.items():
        if p in sin_bondear:
            continue
        por_grupo.setdefault(base_puerto(p), []).append((p, bola, std))
    for v in por_grupo.values():
        v.sort(key=lambda t: indice(t[0]), reverse=True)

    print("### Resumen por función\n")
    print("| Puerto | Dirección | Bolas | Banco | IOSTANDARD | Qué es |")
    print("|---|---|---|---|---|---|")
    bolas_io = 0
    for base, titulo, _ in GRUPOS:
        filas = por_grupo.get(base, [])
        if not filas:
            continue
        bolas_io += sum(1 for _, b, _ in filas if clase(b) == "io")
        bancos = sorted({PINES[b][0] or "0" for _, b, _ in filas})
        stds = sorted({s for _, _, s in filas if s})
        print(f"| `{base}` | {direccion(base)} | {len(filas)} | "
              f"{' y '.join(bancos)} | "
              f"{' · '.join(f'`{s}`' for s in stds)} | {titulo} |")
    print(f"\n**{bolas_io} bolas de I/O del PL** de las 100 que tiene el 7010, "
          f"más el par dedicado VP/VN del XADC, que no es I/O.\n")
    if sin_bondear:
        lista = ", ".join(f"`{p}` → `{b}`"
                          for p, b in sorted(sin_bondear.items()))
        print(f"> Quedan afuera {len(sin_bondear)} asignaciones del XDC del "
              f"proyecto que caen en bolas **sin bondear en el 7010** "
              f"({lista}): son las líneas extra de E1 del 7020, y en el build "
              f"Z10 el puerto ni siquiera existe, así que la restricción no "
              f"aplica a nada.\n")

    print("### Detalle bola por bola\n")
    print("| Bola | Puerto | Banco | Función del pin | IOSTANDARD | Notas |")
    print("|---|---|---|---|---|---|")
    for base, titulo, nota in GRUPOS:
        for p, bola, std in por_grupo.get(base, []):
            banco, func, par, marcas = PINES[bola]
            notas = []
            if "c" in marcas:
                notas.append("**capaz de manejar reloj**")
            if "v" in marcas:
                notas.append("bola VREF del banco")
            if par:
                notas.append(f"par con `{par}`")
            print(f"| `{bola}` | `{p}` | {banco or '0'} | `{func}` | "
                  f"{f'`{std}`' if std else '—'} | {', '.join(notas)} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tabla", action="store_true",
                    help="imprime las tablas en Markdown en vez de la figura")
    args = ap.parse_args()
    if args.tabla:
        tablas(XDCS)
        return
    svg()
    SALIDA.write_text(render(), encoding="utf-8")
    print(f"escrito {SALIDA} ({SALIDA.stat().st_size} B)")


if __name__ == "__main__":
    main()
