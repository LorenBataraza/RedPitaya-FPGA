#!/usr/bin/env python3
"""La cadena de un evento, etapa por etapa, y quién inicia cada transferencia.

Genera `cadena_de_un_evento.svg`: el recorrido completo de un evento desde el
detector hasta la PC del banco, con una tarjeta por salto que dice el mecanismo,
**quién lo inicia y cuándo**, y en qué unidad se mueve el dato.

El color de cada flecha es el iniciador, no el dominio: es la pregunta que la
figura existe para responder. La paleta es la de las figuras TikZ
(`estilo_svg.py`); como son tonos pastel, las flechas van rellenas y con borde
negro en vez de ser una linea de color, que en amarillo no se veria.

Dibuja el camino que corre HOY (ruta B + archivo en microSD) y marca aparte las
tres bifurcaciones que lo cambian.

    python3 figuras_cadena_de_un_evento.py
"""

from pathlib import Path

from estilo_svg import (FONT_MONO, FONT_SERIF, MUDO, NOTA, TINTA, TINTA2,
                        ancho_serif, tinte)

SALIDA = Path(__file__).with_name("cadena_de_un_evento.svg")

W, H = 690, 886

SPINE_X, SPINE_W = 56, 330
ARROW_X = SPINE_X + SPINE_W / 2
MARCA_X = SPINE_X + SPINE_W + 46        # la columna de marcas numeradas
BIF_X = SPINE_X + SPINE_W + 108         # los indicadores de bifurcacion

partes = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, cls="nm", size=11, anchor="start", weight=None, mono=False):
    w = f' font-weight="{weight}"' if weight else ""
    f = f' font-family="{FONT_MONO}"' if mono else ""
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

# Color de relleno por iniciador (flechas y leyenda) y por bifurcacion. B1 vive
# en la BRAM del MCA y B2 en DDR, asi que toman el color que esos caminos tienen
# en los panoramas; B3 comparte el de B2 como antes.
COLOR = {"cont": "azul", "pl": "verde", "ps": "naranja", "os": "amarillo",
         "man": "grisr", "ra": "verde", "rc": "naranja"}

ESTILO = f"""
  .bg{{fill:#ffffff}}
  .stage{{fill:{tinte("grisr", 0.45)};stroke:{TINTA};stroke-width:1.3}}
  .ti{{fill:{TINTA}}} .nm{{fill:{TINTA}}} .sb{{fill:{TINTA2}}} .wd{{fill:{TINTA2}}}
  .ttl{{fill:{TINTA}}} .sub{{fill:{TINTA2}}} .note{{fill:{NOTA}}}
  .dom{{fill:{TINTA2};letter-spacing:0.06em}}
  .leader{{stroke:{MUDO};stroke-width:1;stroke-dasharray:3 3;fill:none}}
  .marca{{fill:{TINTA};stroke:#ffffff;stroke-width:1.6}}
  .marcatxt{{fill:#ffffff}}
  .bifm{{stroke:{TINTA};stroke-width:1.1}}
  .biftxt{{fill:{TINTA}}}
  .flecha{{stroke:{TINTA};stroke-width:1.1;stroke-linejoin:round}}
""" + "".join("  .f-%s{fill:%s}\n" % (k, tinte(c)) for k, c in COLOR.items())

# ---------------------------------------------------------------------------
# dibujo
# ---------------------------------------------------------------------------
partes.append(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
txt(56, 36, "La cadena de un evento, y quién inicia cada tramo", cls="ttl", size=18,
    weight="700")
Y0, SH, GAP = 112, 46, 34
PITCH = SH + GAP

# etapas: nombre y dominio, NADA MAS. Las lineas de detalle que cada caja
# llevaba son la columna "Qué es" de la tabla de movimiento_de_datos.md §2.
for i, (titulo, dom, _lineas) in enumerate(ETAPAS):
    y = Y0 + i * PITCH
    partes.append(
        f'<rect class="stage" x="{SPINE_X}" y="{y}" width="{SPINE_W}" '
        f'height="{SH}" rx="4"/>'
    )
    txt(SPINE_X + 14, y + SH / 2 + 4.5, titulo, cls="ti", size=11.5,
        weight="700")
    txt(SPINE_X + SPINE_W - 12, y + SH / 2 + 3.5, dom, cls="dom", size=7.8,
        anchor="end", weight="700")

# saltos: la flecha, coloreada por QUIEN INICIA, y su marca numerada.
# La tarjeta de tres lineas que cada salto llevaba es una fila de la tabla.
for i, (acc, _mec, _quien, _unidad) in enumerate(SALTOS):
    y_top = Y0 + i * PITCH + SH
    y_bot = Y0 + (i + 1) * PITCH
    # Flecha de bloque: cuerpo de 10 px y punta de 20 x 12, rellena y con borde.
    ys, yp = y_top + 1, y_bot - 12
    partes.append(
        f'<path class="flecha f-{acc}" d="M{ARROW_X - 5},{ys} V{yp} '
        f'H{ARROW_X - 10} L{ARROW_X},{y_bot - 1} L{ARROW_X + 10},{yp} '
        f'H{ARROW_X + 5} V{ys} Z"/>'
    )
    cy = (y_top + y_bot) / 2
    partes.append(f'<path class="leader" d="M{ARROW_X + 8},{cy} H{MARCA_X - 11}"/>')
    partes.append(
        f'<circle class="marca" cx="{MARCA_X}" cy="{cy}" r="10.5"/>')
    txt(MARCA_X, cy + 3.8, str(i + 1), cls="marcatxt", size=11,
        anchor="middle", weight="700")

# bifurcaciones: donde se abre cada una, y nada mas. Que hace cada una ya
# estaba en la tabla "Las tres bifurcaciones" del documento.
BIF_EN = [(2, "1", "ra"), (4, "2", "rc"), (6, "3", "rc")]
for idx, n, acc in BIF_EN:
    cy = Y0 + idx * PITCH + SH / 2
    partes.append(f'<path class="leader" d="M{SPINE_X + SPINE_W},{cy} H{BIF_X - 13}"/>')
    partes.append(f'<circle class="bifm f-{acc}" cx="{BIF_X}" cy="{cy}" r="12.5"/>')
    txt(BIF_X, cy + 4, f"B{n}", cls="biftxt", size=10, anchor="middle",
        weight="700")

# leyenda: el color de la flecha es QUIEN inicia la transferencia
txt(SPINE_X, 64, "El color de cada flecha es quién inicia la transferencia:",
    cls="sub", size=10.5)
_lx = SPINE_X
for acc, etq in INICIADORES:
    partes.append(f'<rect class="flecha f-{acc}" x="{_lx}" y="76" width="16" '
                  f'height="9" rx="2"/>')
    corto = etq.split(":")[0].split("—")[0].strip()
    txt(_lx + 22, 85, corto, cls="sb", size=9.5)
    _lx += 22 + ancho_serif(corto, 9.5) + 16

txt(SPINE_X, H - 20,
    "Qué pasa en cada tramo y en cada bifurcación: la tabla de "
    "movimiento_de_datos.md §2.",
    cls="note", size=10)

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}" font-family="{FONT_SERIF}">\n'
    f"<style>{ESTILO}</style>\n" + "\n".join(partes) + "\n</svg>\n"
)

SALIDA.write_text(svg, encoding="utf-8")
print(f"escrito {SALIDA} ({len(svg)} bytes)")
