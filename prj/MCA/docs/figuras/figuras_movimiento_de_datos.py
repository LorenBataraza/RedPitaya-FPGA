#!/usr/bin/env python3
"""Overlay del movimiento de datos sobre el diagrama de bloques de la placa.

Genera `movimiento_de_datos.svg`: el diagrama de bloques oficial de la Red
Pitaya (redibujado) con un overlay que (a) abre el bloque del Zynq en PL y PS
con los módulos de este proyecto, y (b) numera cada conexión del camino de
datos. Los números son las IDs de la tabla de `movimiento_de_datos.md`, que es
donde viven el throughput, el costo de CPU y el trabajo de puesta a punto.

La figura deliberadamente NO repite la tabla: lleva sólo la ID y el caudal, para
que no puedan desincronizarse dos copias de los mismos números.

    python3 figuras_movimiento_de_datos.py
"""

from pathlib import Path

SALIDA = Path(__file__).with_name("movimiento_de_datos.svg")

W, H = 1400, 940
OUT_X, OUT_Y, OUT_W, OUT_H = 40, 92, 1320, 780

partes = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, cls="nm", size=11, anchor="start", weight=None, mono=False):
    w = f' font-weight="{weight}"' if weight else ""
    f = ' font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"' if mono else ""
    partes.append(
        f'<text class="{cls}" x="{x}" y="{y}" font-size="{size}" '
        f'text-anchor="{anchor}"{w}{f}>{esc(s)}</text>'
    )


def bloque(x, y, w, h, lineas, cls="blk", size=11.5, dy=15):
    """Caja amarilla del diagrama original, con el texto centrado."""
    partes.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>')
    cx, cy = x + w / 2, y + h / 2 - (len(lineas) - 1) * dy / 2 + 4
    for i, ln in enumerate(lineas):
        txt(cx, cy + i * dy, ln, cls="blktxt", size=size, anchor="middle")


def flecha_gorda(x0, y0, x1, y1, doble=False, cls="fat"):
    """Las flechas huecas del diagrama original."""
    sh, hh, hl = 6, 12, 14
    if y0 == y1:
        s = 1 if x1 > x0 else -1
        a, b, y = x0, x1, y0
        if doble:
            pts = [
                (a + s * hl, y - sh), (a + s * hl, y - hh), (a, y), (a + s * hl, y + hh),
                (a + s * hl, y + sh), (b - s * hl, y + sh), (b - s * hl, y + hh),
                (b, y), (b - s * hl, y - hh), (b - s * hl, y - sh),
            ]
        else:
            pts = [
                (a, y - sh), (b - s * hl, y - sh), (b - s * hl, y - hh),
                (b, y), (b - s * hl, y + hh), (b - s * hl, y + sh), (a, y + sh),
            ]
    else:
        s = 1 if y1 > y0 else -1
        a, b, x = y0, y1, x0
        if doble:
            pts = [
                (x - sh, a + s * hl), (x - hh, a + s * hl), (x, a), (x + hh, a + s * hl),
                (x + sh, a + s * hl), (x + sh, b - s * hl), (x + hh, b - s * hl),
                (x, b), (x - hh, b - s * hl), (x - sh, b - s * hl),
            ]
        else:
            pts = [
                (x - sh, a), (x - sh, b - s * hl), (x - hh, b - s * hl),
                (x, b), (x + hh, b - s * hl), (x + sh, b - s * hl), (x + sh, a),
            ]
    d = " ".join(f"{px},{py}" for px, py in pts)
    partes.append(f'<polygon class="{cls}" points="{d}"/>')


def ruta(d, acento, punta=None):
    """Trazo del overlay: camino de datos resaltado sobre el diagrama."""
    partes.append(f'<path class="ov-{acento}" d="{d}"/>')
    if punta:
        x, y, dirn = punta
        if dirn == "r":
            p = f"M{x-9},{y-5.5} L{x},{y} L{x-9},{y+5.5} Z"
        elif dirn == "l":
            p = f"M{x+9},{y-5.5} L{x},{y} L{x+9},{y+5.5} Z"
        elif dirn == "d":
            p = f"M{x-5.5},{y-9} L{x},{y} L{x+5.5},{y-9} Z"
        else:
            p = f"M{x-5.5},{y+9} L{x},{y} L{x+5.5},{y+9} Z"
        partes.append(f'<path class="ovf-{acento}" d="{p}"/>')


def pastilla(x, y, s, cls, size=10.5, anchor="middle"):
    """Texto con fondo: sin esto las anotaciones no se leen sobre el salmón."""
    w = len(s) * size * 0.62 + 12
    px = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
    partes.append(
        f'<rect class="pill" x="{px:.1f}" y="{y - size * 0.86:.1f}" '
        f'width="{w:.1f}" height="{size * 1.42:.1f}" rx="3"/>'
    )
    txt(x, y, s, cls=cls, size=size, anchor=anchor, weight="700", mono=True)


def chapa(x, y, n, acento, caudal=None, cau_x=None, cau_y=None, cau_anchor="middle"):
    """Círculo numerado: la ID de la conexión en la tabla."""
    partes.append(f'<circle class="ovf-{acento}" cx="{x}" cy="{y}" r="13"/>')
    partes.append(f'<circle class="chapa-ring" cx="{x}" cy="{y}" r="13"/>')
    txt(x, y + 4.5, str(n), cls="chapa-n", size=13, anchor="middle", weight="700", mono=True)
    if caudal:
        pastilla(cau_x if cau_x is not None else x,
                 cau_y if cau_y is not None else y + 30,
                 caudal, f"cau-{acento}", anchor=cau_anchor)


# ---------------------------------------------------------------------------
ESTILO = """
  .bg{fill:#ffffff}
  .board{fill:#e8786c;stroke:#b4564c;stroke-width:1.5}
  .blk{fill:#f0f0b8;stroke:#4a4a28;stroke-width:1.2}
  .blktxt{fill:#1b1f24}
  .fat{fill:#ffffff;stroke:#4a4a28;stroke-width:1.2}
  .fat-off{fill:#e0cfc6;stroke:#9a7c72;stroke-width:1.1}
  .nm{fill:#1b1f24}  .sb{fill:#57606a}  .wd{fill:#6e7781}
  .ttl{fill:#1b1f24} .sub{fill:#57606a} .note{fill:#57606a}
  .off{fill:#8a3b2c}
  .pill{fill:#ffffff;fill-opacity:0.92}
  .region{fill:#ffffff;fill-opacity:0.55;stroke:#1b1f24;stroke-width:1.3;
          stroke-dasharray:6 4}
  .sub-blk{fill:#ffffff;stroke:#1b1f24;stroke-width:1.2}
  .reglbl{fill:#1b1f24}
  .chapa-ring{fill:none;stroke:#ffffff;stroke-width:1.6}
  .chapa-n{fill:#ffffff}

  .ov-ra{stroke:#0f6e4f;stroke-width:3.2;fill:none;stroke-linejoin:round}
  .ov-rb{stroke:#9a3b00;stroke-width:3.2;fill:none;stroke-linejoin:round}
  .ov-rc{stroke:#5a2ea6;stroke-width:3.2;fill:none;stroke-linejoin:round}
  .ov-rn{stroke:#1b3a5c;stroke-width:3.2;fill:none;stroke-linejoin:round}
  .ov-rg{stroke:#5b6670;stroke-width:2.4;fill:none;stroke-dasharray:5 4}
  .ovf-ra{fill:#0f6e4f} .ovf-rb{fill:#9a3b00} .ovf-rc{fill:#5a2ea6}
  .ovf-rn{fill:#1b3a5c} .ovf-rg{fill:#5b6670}
  .cau-ra{fill:#0f6e4f} .cau-rb{fill:#9a3b00} .cau-rc{fill:#5a2ea6}
  .cau-rn{fill:#1b3a5c} .cau-rg{fill:#5b6670}

  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .board{fill:#8f4a42;stroke:#c98a80}
    .blk{fill:#4a4a2e;stroke:#cfcf9a}
    .blktxt{fill:#f0f0dc}
    .fat{fill:#2a2a1c;stroke:#cfcf9a}
    .fat-off{fill:#3a2b26;stroke:#8a6a60}
    .nm{fill:#e6edf3} .sb{fill:#8b949e} .wd{fill:#8b949e}
    .ttl{fill:#e6edf3} .sub{fill:#8b949e} .note{fill:#8b949e}
    .off{fill:#f0a08c}
    .pill{fill:#0d1117;fill-opacity:0.9}
    .region{fill:#0d1117;fill-opacity:0.72;stroke:#e6edf3}
    .sub-blk{fill:#0d1117;stroke:#e6edf3}
    .reglbl{fill:#e6edf3}
    .chapa-ring{stroke:#0d1117}
    .chapa-n{fill:#ffffff}

    .ov-ra{stroke:#3fb950} .ov-rb{stroke:#e3a008} .ov-rc{stroke:#a371f7}
    .ov-rn{stroke:#58a6ff} .ov-rg{stroke:#8b949e}
    .ovf-ra{fill:#3fb950} .ovf-rb{fill:#e3a008} .ovf-rc{fill:#a371f7}
    .ovf-rn{fill:#58a6ff} .ovf-rg{fill:#8b949e}
    .cau-ra{fill:#3fb950} .cau-rb{fill:#e3a008} .cau-rc{fill:#a371f7}
    .cau-rn{fill:#58a6ff} .cau-rg{fill:#8b949e}
  }
"""

# ---------------------------------------------------------------------------
# encabezado
# ---------------------------------------------------------------------------
partes.append(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
txt(40, 36, "Movimiento de datos a nivel de plataforma", cls="ttl", size=19, weight="700")
txt(40, 57,
    "Overlay sobre el diagrama de bloques de la STEMlab 125-14. "
    "Cada círculo es una conexión; los números son las IDs de la tabla.",
    cls="sub", size=10.5)

# leyenda de rutas
LEYENDA = [
    ("rn", "camino común"),
    ("ra", "ruta A · reducir en la PL"),
    ("rb", "ruta B · GP0 muestra a muestra"),
    ("rc", "ruta C · DMA a DDR"),
    ("rg", "control (no mueve datos)"),
]
lx = 40
for acc, lbl in LEYENDA:
    partes.append(f'<rect class="ovf-{acc}" x="{lx}" y="{72}" width="22" height="5" rx="2.5"/>')
    txt(lx + 29, 78, lbl, cls="wd", size=9.5)
    lx += 33 + len(lbl) * 5.5 + 26

# ---------------------------------------------------------------------------
# la placa
# ---------------------------------------------------------------------------
partes.append(
    f'<rect class="board" x="{OUT_X}" y="{OUT_Y}" width="{OUT_W}" height="{OUT_H}" rx="12"/>'
)

# fila superior
bloque(64, 116, 620, 150, [
    "6x PS_MIOx (SPI, UART) + I2C",
    "4x slow analog input,",
    "4x slow analog output",
    "+5V, -3.3V",
    "'E2'"])
bloque(704, 116, 160, 150, ["DDR3 SDRAM", "256M x 16bit"])
bloque(884, 116, 150, 150, ["2 x serial link", "Up to 500Mbps", "'S1', 'S2'"])
bloque(1054, 116, 100, 150, ["Power", "supply"])
bloque(1174, 116, 162, 150, ["Micro USB", "Power connector", "5V/2A", "'PWR'"])

# cadena de entrada
bloque(64, 334, 56, 26, ["IN1"], size=10)
bloque(64, 382, 56, 26, ["IN2"], size=10)
bloque(140, 320, 150, 120, ["Range setting", "+ low pass filter", "~50MHz"])
bloque(330, 330, 150, 100, ["2x ADC", "14bit@125MHz"])

# cadena de salida (sin uso en el build del MCA)
bloque(64, 520, 56, 26, ["OUT1"], size=10)
bloque(64, 562, 56, 26, ["OUT2"], size=10)
bloque(140, 506, 150, 110, ["Low pass filter", "~50MHz"])
bloque(330, 516, 150, 90, ["2x DAC", "14bit@125MHz"])

# columna derecha
bloque(1030, 300, 290, 100, ["Micro USB", "Console connector", "'CON'"])
bloque(1030, 424, 290, 100, ["MicroSD slot", "'CN9'"])
bloque(1030, 548, 290, 100, ["USB-A OTG", "Connector", "'CN12'"])
bloque(1030, 672, 290, 120, ["100/1000 Base-T", "Ethernet interface", "'ETH'"])

# fila inferior
bloque(64, 700, 540, 148, ["16 single ended or 8 differential IO lines,", "+3.3V", "'E1'"],
       size=11)
bloque(624, 700, 130, 148, ["9x User LED", "2x System LED"], size=10.5)
bloque(774, 700, 140, 148, ["JTAG", "interface", "'JTAG'"])

# el Zynq
bloque(520, 320, 460, 340, [])
txt(750, 344, "Xilinx ZYNQ  ·  XC7Z010", cls="blktxt", size=13.5, anchor="middle",
    weight="700")

# flechas originales
flecha_gorda(600, 266, 600, 320, doble=True)          # E2
flecha_gorda(800, 266, 800, 320, doble=True)          # DDR3
flecha_gorda(905, 266, 905, 320, doble=True)          # S1/S2
flecha_gorda(290, 380, 330, 380)                      # range -> adc
flecha_gorda(480, 380, 520, 380)                      # adc -> zynq
flecha_gorda(520, 561, 480, 561, cls="fat-off")       # zynq -> dac
flecha_gorda(330, 561, 290, 561, cls="fat-off")       # dac -> filtro
flecha_gorda(140, 561, 120, 561, cls="fat-off")       # filtro -> OUT
flecha_gorda(980, 350, 1030, 350, doble=True)         # CON
flecha_gorda(980, 474, 1030, 474, doble=True)         # microSD
flecha_gorda(980, 598, 1030, 598, doble=True)         # USB-A
flecha_gorda(560, 700, 560, 660, doble=True)          # E1
flecha_gorda(689, 700, 689, 660)                      # LEDs
flecha_gorda(844, 700, 844, 660, doble=True)          # JTAG
# la diagonal del original hacia ETH, acá resuelta en codo
partes.append('<polygon class="fat" points="974,650 986,650 986,730 974,730"/>')
flecha_gorda(980, 724, 1030, 724, doble=True)

# ---------------------------------------------------------------------------
# overlay: abrir el Zynq
# ---------------------------------------------------------------------------
partes.append('<rect class="region" x="532" y="362" width="210" height="286" rx="5"/>')
partes.append('<rect class="region" x="792" y="362" width="176" height="286" rx="5"/>')
txt(537, 379, "PL · lógica programable", cls="reglbl", size=9.5, weight="700")
txt(797, 379, "PS · 2× Cortex-A9 + Linux", cls="reglbl", size=9.5, weight="700")

SUB = [
    (556, 392, 176, 56, "mca_top", "histograma 8192 × 32 b"),
    (556, 462, 176, 56, "scope BRAM", "8192 muestras/canal · K=1"),
    (556, 532, 176, 56, "event_ring", "captura + writer AXI"),
    (800, 392, 160, 56, "Python + API", "/dev/mem + mmap"),
    (800, 462, 160, 86, "lector · escritor", "polea el footer, no GP0"),
]
for x, y, w, h, t, s in SUB:
    partes.append(f'<rect class="sub-blk" x="{x}" y="{y}" width="{w}" height="{h}" rx="4"/>')
    txt(x + 10, y + 21, t, cls="nm", size=11, weight="700", mono=True)
    txt(x + 10, y + 36, s, cls="wd", size=8.5, mono=True)

# tronco del datapath dentro de la PL
ruta("M520,380 H538 V560", "rn")
for yv in (420, 490, 560):
    ruta(f"M538,{yv} H556", "rn", punta=(556, yv, "r"))
pastilla(543, 606, "adc_dat · 500 MB/s", "cau-rn", size=9, anchor="start")

# ---------------------------------------------------------------------------
# overlay: las conexiones numeradas
# ---------------------------------------------------------------------------
# 1 · analógico
ruta("M120,347 H140 M120,395 H140 M290,380 H322", "rn", punta=(330, 380, "r"))
chapa(310, 380, 1, "rn", "±1 V · DC–60 MHz", cau_y=420)

# 2 · ADC -> PL
ruta("M480,380 H512", "rn", punta=(520, 380, "r"))
chapa(500, 380, 2, "rn", "500 MB/s", cau_y=420)

# 3 · reducción dentro de la PL
chapa(556, 392, 3, "ra")

# 6 · PL -> DDR3 (va primero: queda por debajo de las horizontales)
ruta("M732,560 H770 V274", "rc", punta=(770, 266, "u"))
chapa(770, 292, 6, "rc", "1 GB/s", cau_x=744, cau_y=252, cau_anchor="end")

# 7 · DDR3 -> PS
ruta("M830,266 V354", "rc", punta=(830, 362, "d"))
chapa(830, 292, 7, "rc", "221 MB/s", cau_x=856, cau_y=252, cau_anchor="start")

# 4 · GP0 espectro
ruta("M732,420 H784", "ra", punta=(792, 420, "r"))
chapa(762, 420, 4, "ra", "17 MB/s", cau_y=448)

# 5 · GP0 ventana K=1
ruta("M732,490 H784", "rb", punta=(792, 490, "r"))
chapa(762, 490, 5, "rb", "0.5 MB/s", cau_y=518)

# 8 · PS -> microSD
ruta("M968,474 H1022", "rb", punta=(1030, 474, "r"))
chapa(1005, 474, 8, "rb", "12.4 MB/s", cau_y=450)

# 9 · PS -> Ethernet
ruta("M968,620 H1000 V724 H1022", "rc", punta=(1030, 724, "r"))
chapa(1000, 690, 9, "rc", "60–110 MB/s", cau_x=1000, cau_y=666)

# 10 · E1: veto / trigger externo (control)
ruta("M560,700 V672", "rg", punta=(560, 664, "u"))
chapa(560, 684, 10, "rg")
pastilla(584, 688, "DIO0_P · veto", "cau-rg", size=9.5, anchor="start")

# 11 · USB-A: control del generador (control)
ruta("M968,598 H1022", "rg", punta=(1030, 598, "r"))
chapa(1005, 598, 11, "rg")
pastilla(1005, 572, "Rigol DG4162", "cau-rg", size=9.5)

# camino del DAC: construido pero apagado
pastilla(310, 648, "sin uso: el ASG está fuera del build (OUT1/OUT2 en 0 V)",
         "off", size=9.5)

# ---------------------------------------------------------------------------
# notas al pie
# ---------------------------------------------------------------------------
txt(40, 900,
    "El bloque del Zynq es el único que el overlay abre: todo lo que decide el techo "
    "de tasa pasa por el borde entre la PL y el PS.",
    cls="note", size=10)
txt(40, 918,
    "DDR3 de 16 bit: ~1.4 GB/s útiles — a 500 kev/s las conexiones 6 y 7 usan ~5 % cada una. "
    "El throughput, la CPU y el ajuste de cada ID están en la tabla del documento.",
    cls="note", size=10)

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans,Helvetica,Arial,sans-serif">\n'
    f"<style>{ESTILO}</style>\n" + "\n".join(partes) + "\n</svg>\n"
)

SALIDA.write_text(svg, encoding="utf-8")
print(f"escrito {SALIDA} ({len(svg)} bytes)")
