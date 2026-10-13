#!/usr/bin/env python3
"""Mapa de pines del ADC: las 16 líneas por canal del LTC2145-14 al Zynq.

Genera `adc_pinout.svg`: para cada canal, qué bit de `adc_dat_i` entra por qué
pin del encapsulado del Zynq y qué línea del ADC lo maneja, más el reloj
diferencial y las dos señales de control. Es la figura de
[`adc_ltc2145.md`](../adc_ltc2145.md) §1.

De dónde sale cada cosa:

  * bit de `adc_dat_i` → PACKAGE_PIN, IOSTANDARD, IOB y `set_input_delay`:
    de `sdc/red_pitaya.xdc` (líneas 18–74 y 199–201). Es el dato duro.
  * bit de `adc_dat_i` → línea de datos del ADC (D13..D0): DERIVADO de cómo el
    top interpreta el bus, `adc_dat_i[ch][15 -: ADW]` con `ADW = 14` y el bit 15
    como más significativo (`mca_red_pitaya_top.sv`, bloque *ADC IO*). O sea: es
    el mapeo que el RTL supone, no una lectura del esquemático. Los dos bits
    bajos no son datos del LTC2145-14: están ahí para el ADC de 16 bit de la
    SDRlab 122-16 y el RTL los descarta.

Sin dependencias: el SVG se emite a mano, igual que el de `datasheet.py`, para
que corra en la máquina del laboratorio.

    python3 figuras_adc_pinout.py
"""

from pathlib import Path

SALIDA = Path(__file__).with_name("adc_pinout.svg")

# --------------------------------------------------------------------------- #
# Datos (sdc/red_pitaya.xdc)
# --------------------------------------------------------------------------- #
PINES = {
    0: ["V17", "U17", "Y17", "W16", "Y16", "W15", "W14", "Y14",
        "W13", "V12", "V13", "T14", "T15", "V15", "T16", "V16"],
    1: ["T17", "R16", "R18", "P16", "P18", "N17", "R19", "T20",
        "T19", "U20", "V20", "W20", "W19", "Y19", "W18", "Y18"],
}
CANAL = {0: ("Canal A", "IN1", "DA"), 1: ("Canal B", "IN2", "DB")}

ADW = 14          # bits útiles: adc_dat_i[15:2]
NLIN = 16         # líneas cableadas por canal

CONTROL = [
    ("ADCLKP / ADCLKN", "U18 / U19", "DIFF_HSTL_I_18",
     "reloj de muestreo: el mismo del XO que maneja al ADC", True),
    ("adc_cdcs_o", "V18", "LVCMOS18",
     "clock duty cycle stabilizer — atado a 1 en el top", False),
    ("adc_clk_o[0] / [1]", "N20 / P20", "LVCMOS18",
     "salida de reloj opcional — sin uso en la 125-14", False),
]

# --------------------------------------------------------------------------- #
# Geometría
# --------------------------------------------------------------------------- #
W, H = 1180, 876
MG = 30
PANEL_W, GAP = 532, 44
HDR_H = 56
ROW_H = 21
ROW0 = 30                      # primer baseline dentro del panel, tras el header

# columnas, relativas al borde izquierdo del panel
C_ADC, C_AR1, C_PIN, C_AR2, C_BIT, C_USO = 16, 128, 160, 214, 246, 392

partes = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, cls="nm", size=11, anchor="start", weight=None, mono=False):
    w = f' font-weight="{weight}"' if weight else ""
    f = (' font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"'
         if mono else "")
    partes.append(
        f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
        f'text-anchor="{anchor}"{w}{f}>{esc(s)}</text>')


def rect(x, y, w, h, cls="box", rx=4):
    partes.append(f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" '
                  f'width="{w:.1f}" height="{h:.1f}" rx="{rx}"/>')


def linea(x0, y0, x1, y1, cls="pin"):
    partes.append(f'<line class="{cls}" x1="{x0:.1f}" y1="{y0:.1f}" '
                  f'x2="{x1:.1f}" y2="{y1:.1f}"/>')


def flecha(x, y, largo=18, cls="pin", clsf="arr"):
    """Flecha corta hacia la derecha, centrada verticalmente en y."""
    linea(x, y, x + largo - 5, y, cls)
    partes.append(f'<polygon class="{clsf}" points="'
                  f'{x + largo:.1f},{y:.1f} {x + largo - 6:.1f},{y - 3.2:.1f} '
                  f'{x + largo - 6:.1f},{y + 3.2:.1f}"/>')


def panel_canal(x, y, ch):
    """Un panel por canal: 16 filas, de bit 15 (MSB) a bit 0."""
    nombre, entrada, pref = CANAL[ch]
    alto = HDR_H + NLIN * ROW_H + 14
    rect(x, y, PANEL_W, alto)
    rect(x + 1, y + 1, PANEL_W - 2, HDR_H - 1, "hdr", 3)

    txt(x + C_ADC, y + 21, f"{nombre} — {entrada}", "ti", 12.5, weight="700")
    txt(x + C_ADC, y + 39, f"adc_dat_i[{ch}][15 -: 14]  →  signed 14 bit", "sb",
        10.5, mono=True)
    txt(x + PANEL_W - 14, y + 21, "LVCMOS18 · IOB TRUE", "sb", 9.5,
        anchor="end")
    txt(x + PANEL_W - 14, y + 39, "set_input_delay 3.400 ns", "sb", 9.5,
        anchor="end")

    # encabezados de columna
    yh = y + HDR_H + 14
    txt(x + C_ADC, yh, "línea del ADC", "wd", 9)
    txt(x + C_PIN, yh, "pin Zynq", "wd", 9)
    txt(x + C_BIT, yh, "bit del bus", "wd", 9)
    txt(x + C_USO, yh, "peso", "wd", 9)
    linea(x + C_ADC, yh + 5, x + PANEL_W - 14, yh + 5, "sep")

    for i, bit in enumerate(range(NLIN - 1, -1, -1)):
        yb = y + HDR_H + ROW0 + i * ROW_H
        usado = bit >= NLIN - ADW                      # bits 15..2
        cls_n, cls_w = ("nm", "wd") if usado else ("dim", "dim")

        if usado:
            if i % 2 == 0:
                rect(x + C_ADC - 6, yb - 14, PANEL_W - C_ADC - 2, ROW_H,
                     "zebra", 2)
            dnum = bit - (NLIN - ADW)                  # 15→13 ... 2→0
            adc = f"{pref}{dnum}"
            if dnum == ADW - 1:
                peso = "MSB · pasa a bit de signo"
            elif dnum == 0:
                peso = "LSB · 122 µV (rango LV)"
            else:
                peso = f"2^{dnum} · {122.07 * 2 ** dnum / 1000:,.2f} mV".replace(",", " ")
        else:
            adc = "—"
            peso = "reservado: 16 bit de la 122-16"

        txt(x + C_ADC, yb, adc, cls_n, 11, mono=True,
            weight="700" if usado and bit == NLIN - 1 else None)
        if usado:
            flecha(x + C_AR1, yb - 4)
        else:
            linea(x + C_AR1, yb - 4, x + C_AR1 + 18, yb - 4, "sepv")
        txt(x + C_PIN, yb, PINES[ch][bit], cls_n, 11, mono=True, weight="700")
        if usado:
            flecha(x + C_AR2, yb - 4)
        txt(x + C_BIT, yb, f"adc_dat_i[{ch}][{bit:>2}]", cls_n, 10.5, mono=True)
        txt(x + C_USO, yb, peso, cls_w, 9.5)

    # llave que marca los 14 bits que el RTL toma
    xb = x + C_BIT - 8
    y_top = y + HDR_H + ROW0 - 15
    y_bot = y_top + ADW * ROW_H
    partes.append(f'<path class="brace" d="M {xb + 5:.1f} {y_top:.1f} '
                  f'h -5 V {y_bot:.1f} h 5"/>')
    return alto


def panel_control(x, y, ancho):
    alto = HDR_H + len(CONTROL) * ROW_H + 16
    rect(x, y, ancho, alto)
    rect(x + 1, y + 1, ancho - 2, HDR_H - 1, "hdr", 3)
    txt(x + C_ADC, y + 21, "Reloj y control", "ti", 12.5, weight="700")
    txt(x + C_ADC, y + 39,
        "el reloj no sale de la PL: va del XO al ADC y de ahí al FPGA — "
        "y es el reloj del datapath", "sb", 10.5)

    yh = y + HDR_H + 14
    txt(x + C_ADC, yh, "señal", "wd", 9)
    txt(x + 190, yh, "pin Zynq", "wd", 9)
    txt(x + 290, yh, "IOSTANDARD", "wd", 9)
    txt(x + 430, yh, "qué hace", "wd", 9)
    linea(x + C_ADC, yh + 5, x + ancho - 14, yh + 5, "sep")

    for i, (sig, pin, std, nota, fuerte) in enumerate(CONTROL):
        yb = y + HDR_H + ROW0 + i * ROW_H
        if i % 2 == 0:
            rect(x + C_ADC - 6, yb - 14, ancho - C_ADC - 2, ROW_H, "zebra", 2)
        cls = "nm" if fuerte else "dim"
        txt(x + C_ADC, yb, sig, cls, 11, mono=True,
            weight="700" if fuerte else None)
        txt(x + 190, yb, pin, cls, 11, mono=True, weight="700")
        txt(x + 290, yb, std, cls, 10, mono=True)
        txt(x + 430, yb, nota, "wd" if fuerte else "dim", 9.5)
    return alto


def panel_cadena(x, y, ancho):
    """Lo que el RTL hace con el bus, de pin a muestra con signo."""
    alto = 128
    rect(x, y, ancho, alto)
    rect(x + 1, y + 1, ancho - 2, HDR_H - 1, "hdr", 3)
    txt(x + C_ADC, y + 21, "De las 16 líneas a la muestra con signo", "ti",
        12.5, weight="700")
    txt(x + C_ADC, y + 39,
        "mca_red_pitaya_top.sv, bloque ADC IO — un solo paso de offset binary "
        "de pendiente negativa a complemento a 2", "sb", 10.5)

    cajas = [
        ("16 líneas", "adc_dat_i[ch][15:0]", 150),
        ("rebanada", "[15 -: 14]  (tira [1:0])", 190),
        ("inversión", "{b[13], ~b[12:0]}", 170),
        ("muestra", "signed 14 bit @ adc_clk", 200),
    ]
    xc, yc = x + C_ADC, y + HDR_H + 18
    for i, (titulo, det, w) in enumerate(cajas):
        rect(xc, yc, w, 40, "sub", 3)
        txt(xc + w / 2, yc + 17, titulo, "nm", 10.5, anchor="middle",
            weight="700")
        txt(xc + w / 2, yc + 31, det, "wd", 9.5, anchor="middle", mono=True)
        xc += w
        if i < len(cajas) - 1:
            flecha(xc + 4, yc + 20, 22)
            xc += 30
    return alto


# --------------------------------------------------------------------------- #
# Armado
# --------------------------------------------------------------------------- #
partes.append(
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans,Helvetica,Arial,'
    f'sans-serif">')
partes.append("""<style>
  .bg{fill:#ffffff}
  .box{fill:#ffffff;stroke:#1b1f24;stroke-width:1.5}
  .sub{fill:#ffffff;stroke:#1b1f24;stroke-width:1.1}
  .hdr{fill:#f2f4f7;stroke:none}
  .zebra{fill:#f6f8fa;stroke:none}
  .sep{stroke:#c3cad1;stroke-width:0.9;stroke-dasharray:4 4}
  .sepv{stroke:#c3cad1;stroke-width:0.9;stroke-dasharray:2 3}
  .pin{stroke:#1b1f24;stroke-width:1.2;fill:none}
  .arr{fill:#1b1f24;stroke:none}
  .brace{fill:none;stroke:#0b6bcb;stroke-width:1.6}
  .nm{fill:#1b1f24}  .wd{fill:#57606a}  .dim{fill:#9aa4ae}
  .ti{fill:#1b1f24}  .sb{fill:#57606a}
  .ttl{fill:#1b1f24} .st{fill:#57606a} .note{fill:#57606a}
  .key{fill:#0b6bcb}
  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .box{fill:#0d1117;stroke:#c9d1d9}
    .sub{fill:#0d1117;stroke:#c9d1d9}
    .hdr{fill:#161b22}
    .zebra{fill:#161b22}
    .sep{stroke:#30363d} .sepv{stroke:#30363d}
    .pin{stroke:#c9d1d9} .arr{fill:#c9d1d9}
    .brace{stroke:#58a6ff}
    .nm{fill:#e6edf3} .wd{fill:#8b949e} .dim{fill:#6e7781}
    .ti{fill:#e6edf3} .sb{fill:#8b949e}
    .ttl{fill:#e6edf3} .st{fill:#8b949e} .note{fill:#8b949e}
    .key{fill:#58a6ff}
  }
</style>""")
partes.append(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')

txt(MG, 34, "ADC → Zynq: las 16 líneas por canal", "ttl", 19, weight="700")
txt(MG, 56,
    "LTC2145-14 (QFN-64, 9 × 9 mm) · salida CMOS paralela de 1.8 V · "
    "16 líneas cableadas por canal, 14 útiles · pines de sdc/red_pitaya.xdc",
    "st", 11.5)

y0 = 76
alto_p = panel_canal(MG, y0, 0)
panel_canal(MG + PANEL_W + GAP, y0, 1)

y1 = y0 + alto_p + 22
ancho_total = 2 * PANEL_W + GAP
alto_c = panel_control(MG, y1, ancho_total)

y2 = y1 + alto_c + 22
alto_cad = panel_cadena(MG, y2, ancho_total)

y3 = y2 + alto_cad + 26
txt(MG, y3,
    "La llave azul marca lo que el RTL toma: los 14 bits altos. Los dos bajos "
    "están cableados pero no son datos del LTC2145-14 — son los LSB del ADC de "
    "16 bit de la SDRlab 122-16.", "note", 10.5)
txt(MG, y3 + 17,
    "El mapeo línea del ADC → bit del bus es el que el RTL supone (bit 15 = "
    "más significativo); los pines, el IOSTANDARD y los 3.4 ns de "
    "set_input_delay salen del XDC.", "note", 10.5)

partes.append("</svg>")

SALIDA.write_text("\n".join(partes) + "\n", encoding="utf-8")
print(f"escrito {SALIDA} ({SALIDA.stat().st_size} B)")
