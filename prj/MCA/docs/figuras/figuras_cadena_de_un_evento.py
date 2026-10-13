#!/usr/bin/env python3
"""La cadena de un evento, etapa por etapa, y quién inicia cada transferencia.

Genera `cadena_de_un_evento.svg`: el recorrido completo de un evento desde el
detector hasta la PC del banco, con una tarjeta por salto que dice el mecanismo,
**quién lo inicia y cuándo**, y en qué unidad se mueve el dato.

El color de cada flecha es el iniciador, no el dominio: es la pregunta que la
figura existe para responder.

Dibuja el camino que corre HOY (ruta B + archivo en microSD) y marca aparte las
tres bifurcaciones que lo cambian.

    python3 figuras_cadena_de_un_evento.py
"""

from pathlib import Path

SALIDA = Path(__file__).with_name("cadena_de_un_evento.svg")

W, H = 1240, 1250

SPINE_X, SPINE_W = 56, 290
ARROW_X = SPINE_X + SPINE_W / 2
CARD_X, CARD_W = 380, 560
BIF_X, BIF_W = 970, 250

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


# ---------------------------------------------------------------------------
# contenido
# ---------------------------------------------------------------------------
# (título, dominio, líneas de detalle)
ETAPAS = [
    ("Detector · IN1", "ANALÓGICO",
     ["pulso de ~2 µs sobre ±1 V (jumper LV)"]),
    ("ADC LTC2145-14", "ANALÓGICO",
     ["2 × 14 bit · 125 MS/s", "una muestra cada 8 ns"]),
    ("PL · datapath a adc_clk", "PL · FPGA",
     ["scope + multitrigger + mca_top,", "los tres en paralelo sobre la misma muestra"]),
    ("PL · BRAM del scope", "PL · FPGA",
     ["buffer circular: 8192 muestras/canal", "= 65 µs de historia hacia atrás"]),
    ("PL · ventana congelada", "PL · FPGA",
     ["la PL no captura otro evento", "hasta que el PS re-arme"]),
    ("PS · RAM del proceso", "PS · usuario",
     ["batch de NumPy en full_q", "reader.py produce, storage.py consume"]),
    ("PS · page cache del kernel", "PS · kernel",
     ["sigue siendo DDR: el dato todavía", "no está en la tarjeta"]),
    ("microSD · chunk_000123.npz", "PS · kernel",
     ["tmp + os.replace: nunca un .npz a medias"]),
    ("PC del banco", "AFUERA",
     ["y de ahí a su propio disco"]),
]

# (acento, mecanismo, quién/cuándo, unidad/costo)
SALTOS = [
    ("cont", "front-end analógico: atenuador + filtro ~50 MHz",
     "inicia: nadie — es continuo y analógico",
     "unidad: tensión · ±1 V a fondo de escala"),
    ("cont", "bus paralelo del ADC: 2 × 16 líneas LVCMOS18 + reloj diferencial",
     "inicia: el oscilador de 125 MHz, en cada ciclo · nunca se detiene",
     "unidad: 1 muestra (2 ch × 2 B) · 500 MB/s · valid sin ready: no se puede frenar"),
    ("cont", "escritura circular en la BRAM del scope",
     "inicia: el propio datapath, cada ciclo · no hay condición que esperar",
     "unidad: 1 muestra · no se llena: sobrescribe (es memoria como tiempo, no una cola)"),
    ("pl", "congelar la ventana: adc_we ← 0 y snapshot de wp_trig",
     "inicia: el trigger en RTL · cuando: cruce de umbral, filtrado por trigger_shield",
     "unidad: una ventana (pre+post) · no mueve el dato: lo detiene para que el PS lo lea"),
    ("ps", "lectura por M_AXI_GP0 y re-armado   ←  el cuello de hoy",
     "inicia: el PS, poleando wp_trig cada 2.3 µs · cuando: el snapshot cambió",
     "unidad: 32 muestras × 2 ch (~145 B) · τ = 252.7 µs/evento → techo 3.7 kev/s"),
    ("ps", "np.savez sobre un temporal, y os.replace atómico",
     "inicia: el hilo escritor, nunca el lector · cuando: batch.n == capacity",
     "unidad: un chunk de N eventos + metadata · 12.4 MB/s medidos"),
    ("os", "flush del page cache al dispositivo de bloque (SD0)",
     "inicia: el kernel, no la aplicación · el write() de la app ya había vuelto",
     "unidad: bloques de la SD · 4 bit @ 50 MHz → techo de bus ~25 MB/s"),
    ("man", "rsync / scp por Gigabit Ethernet",
     "inicia: una persona o un script · cuando: la corrida terminó",
     "unidad: archivos · 90–110 MB/s de techo de TCP — ver la bifurcación 3"),
]

BIFURCACIONES = [
    (406, 92, "ra", "Bifurcación 1 · el espectro", [
        "mca_top acumula en su propia BRAM y el",
        "espectro sale por el socket TCP, ~1 por s.",
        "32 kB con H_AW=13 (build Z10_2CH);",
        "64 kB con H_AW=14 (top del event_ring).",
        "No toca ni la DDR ni el disco."]),
    (583, 106, "rc", "Bifurcación 2 · event_ring", [
        "La PL escribe la ventana en DDR por HP0",
        "(DMA) y el PS lee por lotes de 64 kB,",
        "poleando el footer en vez de un registro.",
        "Reemplaza congelar/leer/re-armar y saca al",
        "PS del camino crítico: ~3.9 Mev/s."]),
    (962, 92, "rc", "Bifurcación 3 · NFS", [
        "El write() del escritor va directo a la PC:",
        "desaparecen las dos etapas de microSD.",
        "El archivo local queda sólo de respaldo si",
        "la red se cae (el ring da ~2.3 s de colchón)."]),
]

INICIADORES = [
    ("cont", "el reloj: continuo, no se puede frenar"),
    ("pl", "la PL: un trigger en RTL"),
    ("ps", "el PS: software, por poll o por umbral"),
    ("os", "el kernel: cuando a él le conviene"),
    ("man", "una persona o un script, offline"),
]

ESTILO = """
  .bg{fill:#ffffff}
  .stage{fill:#ffffff;stroke:#1b1f24;stroke-width:1.5}
  .card{fill:#f6f8fa;stroke:#8c959f;stroke-width:1}
  .bif{fill:#ffffff;stroke:#8c959f;stroke-width:1.2;stroke-dasharray:5 3}
  .ti{fill:#1b1f24} .nm{fill:#1b1f24} .sb{fill:#57606a} .wd{fill:#6e7781}
  .ttl{fill:#1b1f24} .sub{fill:#57606a} .note{fill:#57606a}
  .dom{fill:#6e7781;letter-spacing:0.06em}
  .leader{stroke:#b1b8c0;stroke-width:1;stroke-dasharray:3 3;fill:none}

  .a-cont{stroke:#1b4f8c;stroke-width:4;fill:none}
  .a-pl{stroke:#5a2ea6;stroke-width:4;fill:none}
  .a-ps{stroke:#9a3b00;stroke-width:4;fill:none}
  .a-os{stroke:#0f6e4f;stroke-width:4;fill:none}
  .a-man{stroke:#5b6670;stroke-width:4;fill:none}
  .f-cont{fill:#1b4f8c} .f-pl{fill:#5a2ea6} .f-ps{fill:#9a3b00}
  .f-os{fill:#0f6e4f} .f-man{fill:#5b6670}
  .f-ra{fill:#0f6e4f}  .f-rc{fill:#5a2ea6}

  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .stage{fill:#0d1117;stroke:#c9d1d9}
    .card{fill:#161b22;stroke:#6e7681}
    .bif{fill:#0d1117;stroke:#6e7681}
    .ti{fill:#e6edf3} .nm{fill:#e6edf3} .sb{fill:#8b949e} .wd{fill:#8b949e}
    .ttl{fill:#e6edf3} .sub{fill:#8b949e} .note{fill:#8b949e}
    .dom{fill:#8b949e}
    .leader{stroke:#484f58}

    .a-cont{stroke:#58a6ff} .a-pl{stroke:#a371f7} .a-ps{stroke:#e3a008}
    .a-os{stroke:#3fb950}   .a-man{stroke:#8b949e}
    .f-cont{fill:#58a6ff} .f-pl{fill:#a371f7} .f-ps{fill:#e3a008}
    .f-os{fill:#3fb950}   .f-man{fill:#8b949e}
    .f-ra{fill:#3fb950}   .f-rc{fill:#a371f7}
  }
"""

# ---------------------------------------------------------------------------
# dibujo
# ---------------------------------------------------------------------------
partes.append(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
txt(56, 36, "La cadena de un evento, y quién inicia cada tramo", cls="ttl", size=19,
    weight="700")
txt(56, 57,
    "El color de cada flecha es el iniciador de la transferencia, no el dominio. "
    "A la derecha, las tres bifurcaciones que cambian el camino.",
    cls="sub", size=10.5)

lx = 56
for acc, lbl in INICIADORES:
    partes.append(f'<rect class="f-{acc}" x="{lx}" y="74" width="22" height="5" rx="2.5"/>')
    txt(lx + 29, 80, lbl, cls="wd", size=9.5)
    lx += 33 + len(lbl) * 5.35 + 22

Y0, SH, GAP = 110, 60, 64
PITCH = SH + GAP

# etapas
for i, (titulo, dom, lineas) in enumerate(ETAPAS):
    y = Y0 + i * PITCH
    partes.append(
        f'<rect class="stage" x="{SPINE_X}" y="{y}" width="{SPINE_W}" height="{SH}" rx="4"/>'
    )
    txt(SPINE_X + 14, y + 21, titulo, cls="ti", size=11.5, weight="700")
    txt(SPINE_X + SPINE_W - 12, y + 14, dom, cls="dom", size=7.8, anchor="end", weight="700")
    for j, ln in enumerate(lineas):
        txt(SPINE_X + 14, y + 37 + j * 12, ln, cls="sb", size=8.5)

# saltos: flecha, guía y tarjeta
for i, (acc, mec, quien, unidad) in enumerate(SALTOS):
    y_top = Y0 + i * PITCH + SH
    y_bot = Y0 + (i + 1) * PITCH
    partes.append(f'<path class="a-{acc}" d="M{ARROW_X},{y_top} V{y_bot - 10}"/>')
    partes.append(
        f'<path class="f-{acc}" d="M{ARROW_X - 6.5},{y_bot - 11} '
        f'L{ARROW_X},{y_bot} L{ARROW_X + 6.5},{y_bot - 11} Z"/>'
    )
    cy = (y_top + y_bot) / 2
    ch = 52
    partes.append(f'<path class="leader" d="M{ARROW_X + 8},{cy} H{CARD_X}"/>')
    partes.append(
        f'<rect class="card" x="{CARD_X}" y="{cy - ch / 2}" width="{CARD_W}" '
        f'height="{ch}" rx="4"/>'
    )
    partes.append(
        f'<rect class="f-{acc}" x="{CARD_X}" y="{cy - ch / 2}" width="4.5" '
        f'height="{ch}" rx="2"/>'
    )
    txt(CARD_X + 15, cy - ch / 2 + 16, mec, cls=f"f-{acc}", size=10.5, weight="700",
        mono=True)
    txt(CARD_X + 15, cy - ch / 2 + 31, quien, cls="nm", size=9.5, mono=True)
    txt(CARD_X + 15, cy - ch / 2 + 45, unidad, cls="sb", size=9.5, mono=True)

# bifurcaciones
for y, h, acc, titulo, lineas in BIFURCACIONES:
    partes.append(f'<path class="leader" d="M{CARD_X + CARD_W},{y + h / 2} H{BIF_X}"/>')
    partes.append(f'<rect class="bif" x="{BIF_X}" y="{y}" width="{BIF_W}" height="{h}" rx="4"/>')
    partes.append(f'<rect class="f-{acc}" x="{BIF_X}" y="{y}" width="4.5" height="{h}" rx="2"/>')
    txt(BIF_X + 14, y + 20, titulo, cls=f"f-{acc}", size=10.5, weight="700")
    for j, ln in enumerate(lineas):
        txt(BIF_X + 14, y + 36 + j * 12.5, ln, cls="sb", size=8.5)

# notas al pie
txt(56, H - 36,
    "Las dos etapas de RAM que es fácil pasar por alto: el batch del proceso y el page "
    "cache del kernel. El write() de la aplicación vuelve antes de que el dato esté en la "
    "tarjeta.",
    cls="note", size=10)
txt(56, H - 18,
    "No hay SSD en la placa: el único almacenamiento local es la microSD por SD0. "
    "El throughput y el ajuste de cada tramo están en movimiento_de_datos.md §1.",
    cls="note", size=10)

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans,Helvetica,Arial,sans-serif">\n'
    f"<style>{ESTILO}</style>\n" + "\n".join(partes) + "\n</svg>\n"
)

SALIDA.write_text(svg, encoding="utf-8")
print(f"escrito {SALIDA} ({len(svg)} bytes)")
