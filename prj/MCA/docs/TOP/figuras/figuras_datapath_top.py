#!/usr/bin/env python3
"""Figuras del datapath del top en integracion: donde se conmuta y que ve cada
seccion del sistema.

Genera, a partir del RTL de `mca_red_pitaya_top.sv`:

  conformado_mca_interno.svg  dentro del MCA: un solo flujo de muestras y tres
                              procesamientos, con el lazo de linea de base

`datapath_top.svg` (la cadena DSP unica y los tres `dsp_tap_mux`, uno por
consumidor) ya NO sale de aca: paso a TikZ, en `datapath_top.tex`, con el
estilo comun de los panoramas (`docs/figuras/estilo_tikz.tex`). Su epigrafe
sigue en EPIGRAFES para que `epigrafes.txt` quede completo.

Es un ESQUEMA de la estructura del RTL: no lleva numeros medidos.

LAS FIGURAS VAN SIN PROSA ADENTRO. Lo que llevan son nombres de senal, codigos
de registro y MARCAS NUMERADAS; cada marca es una fila de la tabla del
documento que las embebe (`docs/TOP/register_map_top.md`). Es el criterio que
`figuras_movimiento_de_datos.py` ya declaraba para el overlay de la placa, y la
razon es la misma: con el texto adentro habia dos copias de lo mismo --el
dibujo y el epigrafe-- y se desincronizan.

Hubo una tercera figura, `conformado_por_tap.svg`, que era una matriz de cuatro
nodos por cinco capas sin una sola flecha. Eso es una tabla, y como tabla esta
ahora: en `register_map_top.md`.

Los epigrafes estan en `epigrafes.txt`, que escribe este mismo script.

    python3 figuras_datapath_top.py
"""

from pathlib import Path

AQUI = Path(__file__).parent

# =============================================================================
# Infraestructura SVG comun. Mismo criterio que figuras_movimiento_de_datos.py:
# un solo archivo por figura, sin dependencias, con paleta clara y oscura.
# =============================================================================

ESTILO = """
  .bg{fill:#ffffff}
  .blk{fill:#f0f0b8;stroke:#4a4a28;stroke-width:1.2}
  .blktxt{fill:#1b1f24}
  .blk-off{fill:#ececec;stroke:#9a9a9a;stroke-width:1.1;stroke-dasharray:5 3}
  .blktxt-off{fill:#6e7781}
  .blk-mca{fill:#dde9f7;stroke:#1b3a5c;stroke-width:1.2}
  .blk-proc{fill:#ffffff;stroke:#1b1f24;stroke-width:1.2}
  .nm{fill:#1b1f24}  .sb{fill:#57606a}  .wd{fill:#6e7781}
  .ttl{fill:#1b1f24} .sub{fill:#57606a} .note{fill:#57606a}
  .off{fill:#8a3b2c}
  .region{fill:#ffffff;fill-opacity:0.55;stroke:#1b1f24;stroke-width:1.3;
          stroke-dasharray:6 4}
  .panel{fill:#f6f8fa;stroke:#8b949e;stroke-width:1}
  .wire{stroke:#1b1f24;stroke-width:2;fill:none}
  .wire-thin{stroke:#57606a;stroke-width:1.3;fill:none}
  .wire-off{stroke:#9a9a9a;stroke-width:1.6;fill:none;stroke-dasharray:6 4}
  .rail-a{stroke:#9a3b00;stroke-width:2.6;fill:none}
  .rail-b{stroke:#0f6e4f;stroke-width:2.6;fill:none}
  .rail-c{stroke:#5a2ea6;stroke-width:2.6;fill:none}
  .rail-d{stroke:#1b3a5c;stroke-width:2.6;fill:none}
  .fa{fill:#9a3b00} .fb{fill:#0f6e4f} .fc{fill:#5a2ea6} .fd{fill:#1b3a5c}
  .arrow{fill:#1b1f24} .arrow-thin{fill:#57606a} .arrow-off{fill:#9a9a9a}
  .col{stroke:#1b1f24;stroke-width:1.6;fill:none}
  .mux{fill:#ffffff;stroke:#1b1f24;stroke-width:1.4}
  .dot-ring{fill:none;stroke:#1b1f24;stroke-width:1.8}
  .loop{stroke:#8a3b2c;stroke-width:2.2;fill:none}
  .floop{fill:#8a3b2c}
  .badge{fill:#ffffff;stroke:#8b949e;stroke-width:1}
  .badge-off{fill:#ffffff;stroke:#8a3b2c;stroke-width:1}
  .badgetxt{fill:#57606a} .badgetxt-off{fill:#8a3b2c}
  .marca{fill:#1b1f24;stroke:#ffffff;stroke-width:1.6}
  .marcatxt{fill:#ffffff}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .blk{fill:#4a4a2e;stroke:#cfcf9a}
    .blktxt{fill:#f0f0dc}
    .blk-off{fill:#21262d;stroke:#6e7681}
    .blktxt-off{fill:#8b949e}
    .blk-mca{fill:#15263a;stroke:#58a6ff}
    .blk-proc{fill:#0d1117;stroke:#e6edf3}
    .nm{fill:#e6edf3} .sb{fill:#8b949e} .wd{fill:#8b949e}
    .ttl{fill:#e6edf3} .sub{fill:#8b949e} .note{fill:#8b949e}
    .off{fill:#f0a08c}
    .region{fill:#0d1117;fill-opacity:0.72;stroke:#e6edf3}
    .panel{fill:#161b22;stroke:#6e7681}
    .wire{stroke:#e6edf3} .wire-thin{stroke:#8b949e} .wire-off{stroke:#6e7681}
    .rail-a{stroke:#e3a008} .rail-b{stroke:#3fb950} .rail-c{stroke:#a371f7}
    .rail-d{stroke:#58a6ff}
    .fa{fill:#e3a008} .fb{fill:#3fb950} .fc{fill:#a371f7} .fd{fill:#58a6ff}
    .arrow{fill:#e6edf3} .arrow-thin{fill:#8b949e} .arrow-off{fill:#6e7681}
    .col{stroke:#e6edf3} .mux{fill:#0d1117;stroke:#e6edf3}
    .dot-ring{stroke:#e6edf3}
    .loop{stroke:#f0a08c} .floop{fill:#f0a08c}
    .badge{fill:#0d1117;stroke:#6e7681}
    .badge-off{fill:#0d1117;stroke:#f0a08c}
    .badgetxt{fill:#8b949e} .badgetxt-off{fill:#f0a08c}
    .marca{fill:#e6edf3;stroke:#0d1117} .marcatxt{fill:#0d1117}
  }
"""


class Lienzo:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.p = []

    # --- primitivas -------------------------------------------------------
    @staticmethod
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def txt(self, x, y, s, cls="nm", size=11, anchor="start", weight=None,
            mono=False):
        w = f' font-weight="{weight}"' if weight else ""
        c = f"{cls} mono" if mono else cls
        self.p.append(
            f'<text class="{c}" x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
            f'text-anchor="{anchor}"{w}>{self.esc(s)}</text>'
        )

    def rect(self, x, y, w, h, cls="blk", rx=3):
        self.p.append(
            f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="{rx}"/>'
        )

    def caja(self, x, y, w, h, lineas, cls="blk", txtcls="blktxt", size=11.5,
             dy=14.5, rx=3, mono_desde=99):
        """Caja con las lineas de texto centradas. `mono_desde` marca a partir
        de que linea el texto va en monoespaciado (nombres de senales)."""
        self.rect(x, y, w, h, cls, rx)
        cx = x + w / 2
        cy = y + h / 2 - (len(lineas) - 1) * dy / 2 + 4
        for i, ln in enumerate(lineas):
            self.txt(cx, cy + i * dy, ln, cls=txtcls, size=size,
                     anchor="middle", weight="600" if i == 0 else None,
                     mono=i >= mono_desde)

    def punta(self, x, y, d, cls="arrow", k=1.0):
        """Punta de flecha en (x,y) apuntando a 'r', 'l', 'd' o 'u'."""
        a, b = 9 * k, 5.5 * k
        if d == "r":
            pts = f"{x-a},{y-b} {x},{y} {x-a},{y+b}"
        elif d == "l":
            pts = f"{x+a},{y-b} {x},{y} {x+a},{y+b}"
        elif d == "d":
            pts = f"{x-b},{y-a} {x},{y} {x+b},{y-a}"
        else:
            pts = f"{x-b},{y+a} {x},{y} {x+b},{y+a}"
        self.p.append(f'<polygon class="{cls}" points="{pts}"/>')

    def cam(self, d, cls="wire", punta=None, pcls=None):
        self.p.append(f'<path class="{cls}" d="{d}"/>')
        if punta:
            self.punta(*punta, cls=pcls or cls.replace("wire", "arrow")
                       .replace("rail-", "f"))

    def flecha(self, x0, y0, x1, y1, cls="wire", pcls=None):
        self.cam(f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}", cls=cls)
        d = "r" if x1 > x0 else "l"
        if abs(y1 - y0) > abs(x1 - x0):
            d = "d" if y1 > y0 else "u"
        self.punta(x1, y1, d, cls=pcls or "arrow")

    def nodo(self, x, y, letra, cls="fd", r=8.5):
        """Nodo utilizable de la cadena: circulo con la letra adentro."""
        self.p.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')
        self.txt(x, y + 3.6, letra, cls="bg", size=10.5, anchor="middle",
                 weight="700")

    def punto(self, x, y, cls="fd", r=5.5, anillo=False):
        """Cruce activo del crossbar. Con anillo = valor de reset (NATIVO)."""
        if anillo:
            self.p.append(
                f'<circle class="dot-ring" cx="{x:.1f}" cy="{y:.1f}" r="{r+4.5}"/>'
            )
        self.p.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')

    def trapecio(self, cx, y, w, h, cls="mux"):
        """Trapecio de mux: ancho arriba (entradas), angosto abajo (salida)."""
        a, b = w / 2, w / 2 - h * 0.45
        pts = (f"{cx-a:.1f},{y:.1f} {cx+a:.1f},{y:.1f} "
               f"{cx+b:.1f},{y+h:.1f} {cx-b:.1f},{y+h:.1f}")
        self.p.append(f'<polygon class="{cls}" points="{pts}"/>')

    def chapa(self, x, y, s, cls="badge", txtcls="badgetxt", size=9.5,
              anchor="start", pad=6):
        """Etiqueta con fondo, para que no se pierda sobre una linea."""
        w = len(s) * size * 0.56 + 2 * pad
        x0 = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
        self.rect(x0, y - size * 0.86 - 3, w, size * 1.72 + 4, cls, rx=3)
        self.txt(x0 + pad, y + size * 0.34, s, cls=txtcls, size=size)

    def marca(self, x, y, n, cls="marca", r=9.5):
        """Marca numerada: el numero indexa una FILA DE TABLA del documento.

        Es la pieza que permite sacar la prosa del dibujo. El criterio es el
        de `figuras_movimiento_de_datos.py`: la figura lleva la ID y nada
        mas, y el que quiera el detalle lo busca en la tabla, para que no
        puedan desincronizarse dos copias del mismo texto.
        """
        self.p.append(
            f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')
        self.txt(x, y + 3.6, str(n), cls="marcatxt", size=10.5,
                 anchor="middle", weight="700")

    # --- salida -----------------------------------------------------------
    def guardar(self, nombre, titulo, subtitulo=()):
        self.txt(40, 42, titulo, cls="ttl", size=20, weight="700")
        for i, ln in enumerate(subtitulo or ()):
            self.txt(40, 66 + i * 16, ln, cls="sub", size=11.5)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
            f'font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif">\n'
            f"<style>{ESTILO}</style>\n"
            f'<rect class="bg" x="0" y="0" width="{self.w}" height="{self.h}"/>\n'
            + "\n".join(self.p)
            + "\n</svg>\n"
        )
        (AQUI / nombre).write_text(svg, encoding="utf-8")
        print(f"  {nombre}")


# =============================================================================
# FIGURA 1 — la cadena DSP única y el crossbar de taps
#
# La cadena va VERTICAL y los cuatro nodos utilizables salen en horizontal hacia
# la derecha: así cada rail cruza las tres columnas de mux sin que ningún cable
# se cruce con otro, y donde hay un punto hay una conexión posible de verdad.
# =============================================================================

# =============================================================================
# FIGURA 2 — ERA "que acondicionado acumulo la muestra en cada nodo".
#
# Se saco: era una matriz de 4 columnas x 5 capas con un "si/no la vio" en
# cada celda y ni una flecha --el SVG tenia 64 nodos de texto, 22 rectangulos
# y UN path--. Eso es una tabla dibujada, y como tabla se lee mejor, se puede
# copiar, la busca el grep y no hay que regenerar nada para corregirla. Vive
# en `docs/TOP/register_map_top.md`, seccion "Ruteo del datapath".
#
# El panel "Lo que NO hay" que la figura llevaba al costado era prosa pura y
# estaba duplicado palabra por palabra en el epigrafe; ahora esta una sola vez,
# en el documento.
# =============================================================================

# =============================================================================
# FIGURA 3 — dentro del MCA: un flujo, tres procesamientos
#
# Es la figura que responde la pregunta de fondo: la detección, la discriminación
# de apilamiento y la restauración de base NO tienen un conformado propio cada
# una. Comparten el flujo x = dat_q − baseline. El único bloque que MODIFICA ese
# flujo es el seguidor de base, y por eso es el único lazo del dibujo.
# =============================================================================

def figura_mca_interno():
    """Dentro del MCA, SIN los cuerpos de texto de cada bloque.

    Lo que el dibujo tiene que mostrar es la TOPOLOGIA, que es lo que no se
    puede decir en una tabla: que hay un solo flujo x del que cuelgan tres
    procesamientos, que la restauracion de base es el unico que realimenta, y
    que el veto entra por un lado a la apertura de pulsos y por otro a los
    relojes. Que hace cada bloque va en la tabla de marcas del documento.
    """
    c = Lienzo(1280, 740)

    c.rect(36, 96, 1208, 616, "region", rx=6)
    c.txt(52, 118, "mca_top — slot 7 (0x4070_0000), dominio adc_clk",
          cls="nm", size=12, weight="600")

    Y = 286                                # linea del flujo de muestras

    # --- entrada: del crossbar al flujo relativo a la base ----------------
    c.caja(64, Y - 28, 100, 56, ["mca_dat[2]", "mca_val[2]"], cls="blk-mca",
           txtcls="nm", size=10.5, dy=15)
    c.marca(164, Y - 20, 1)

    c.flecha(164, Y, 192, Y)
    c.trapecio(210, Y - 24, 52, 48)
    c.txt(210, Y + 4, "ch", cls="nm", size=10, anchor="middle", weight="600")
    c.marca(210, Y + 40, 2)

    c.flecha(232, Y, 262, Y)
    c.caja(262, Y - 24, 96, 48, ["diezmado"], cls="blk", txtcls="blktxt",
           size=10.5, dy=15)
    c.marca(358, Y + 20, 3)

    c.flecha(358, Y, 386, Y)
    c.caja(386, Y - 24, 74, 48, ["dat_q"], cls="blk", txtcls="blktxt",
           size=10.5, dy=15)

    c.flecha(460, Y, 494, Y)
    c.p.append(f'<circle class="mux" cx="510" cy="{Y}" r="15"/>')
    c.txt(510, Y + 4.5, "−", cls="nm", size=17, anchor="middle", weight="700")
    c.flecha(525, Y, 580, Y)
    c.marca(510, Y - 32, 4)

    # --- las tres ramas que salen del MISMO flujo -------------------------
    X_R, W_R = 580, 250
    c.cam(f"M{X_R:.1f},{Y:.1f} L{X_R:.1f},186 M{X_R:.1f},{Y:.1f} "
          f"L{X_R:.1f},412", cls="wire")
    # A la derecha del bus de ramas no entra: por ahi sube el ramal del veto.
    c.chapa(416, 344, "x = dat_q − baseline", cls="panel", txtcls="nm",
            size=10.5)

    ramas = [(166, 44, "1 · DETECCIÓN", 5),
             (264, 44, "2 · CARACTERIZACIÓN", 6),
             (390, 44, "3 · RESTAURACIÓN DE BASE", 7)]
    for y, h, titulo, mk in ramas:
        c.flecha(X_R, y + h / 2, X_R + 34, y + h / 2)
        c.rect(X_R + 34, y, W_R, h, "blk-proc", rx=4)
        c.txt(X_R + 34 + W_R / 2, y + h / 2 + 4, titulo, cls="nm", size=11,
              anchor="middle", weight="700")
        c.marca(X_R + 34 + W_R, y + h / 2, mk)

    # el lazo de la base: es realimentacion, no una rama mas
    c.cam(f"M{X_R+34:.1f},412 L544,412 L544,{Y+15:.1f}", cls="loop")
    c.punta(544, Y + 15, "u", cls="floop")

    # --- apilamiento: sale de la FSM, no de un conformado propio ----------
    XRC, WRC = 918, 290
    CXRC = XRC + WRC / 2
    c.flecha(X_R + 34 + W_R, 188, XRC, 188, cls="wire-thin",
             pcls="arrow-thin")
    c.caja(XRC, 166, WRC, 44, ["APILAMIENTO"], cls="blk-proc", txtcls="nm",
           size=11, dy=15)
    c.marca(XRC + WRC, 188, 8)

    # --- del evento a los histogramas -------------------------------------
    c.flecha(X_R + 34 + W_R, 286, XRC, 286)
    c.caja(XRC, 264, WRC, 44, ["ev_feat[16]"], cls="blk-mca", txtcls="nm",
           size=11, dy=15)
    c.marca(XRC + WRC, 286, 9)

    c.flecha(CXRC, 308, CXRC, 336)
    c.caja(XRC, 336, WRC, 44, ["mca_discriminator"], cls="blk-proc",
           txtcls="nm", size=11, dy=15)
    c.marca(XRC + WRC, 358, 10)

    c.flecha(CXRC, 380, CXRC, 408)
    c.caja(XRC, 408, WRC, 44, ["mux de eje ×3 + mca_zoom ×3"], cls="blk",
           txtcls="blktxt", size=10.5, dy=15)
    c.marca(XRC + WRC, 430, 11)

    c.cam(f"M{CXRC:.1f},452 L{CXRC:.1f},470", cls="wire")
    for cx in (XRC + 68, XRC + 222):
        c.cam(f"M{CXRC:.1f},470 L{cx:.1f},470 L{cx:.1f},480", cls="wire")
        c.punta(cx, 484, "d")
    c.caja(XRC, 484, 136, 46, ["mca_hist 1D"], cls="blk-mca", txtcls="nm",
           size=10.5, dy=15)
    c.caja(XRC + 154, 484, 136, 46, ["mca_hist 2D"], cls="blk-mca",
           txtcls="nm", size=10.5, dy=15)
    c.marca(XRC + WRC, 507, 12)

    # --- veto: entra a la apertura y a los relojes ------------------------
    c.cam("M64,590 L110,590", cls="loop")
    c.caja(110, 568, 166, 44, ["veto_i (nivel)"], cls="blk-proc", txtcls="nm",
           size=10.5, dy=14)
    c.marca(276, 590, 13)
    c.cam("M276,590 L614,590 L614,214", cls="loop")
    c.punta(614, 210, "u", cls="floop")
    c.cam("M400,590 L400,632", cls="loop")
    c.punta(400, 636, "d", cls="floop")
    c.caja(286, 636, 300, 44, ["relojes de 64 b"], cls="panel", txtcls="nm",
           size=10.5, dy=15)
    c.marca(586, 658, 14)

    c.guardar("conformado_mca_interno.svg",
              "Dentro del MCA: un solo flujo, tres procesamientos")


# =============================================================================
# Epígrafes. Los escribe el script para que no puedan desincronizarse de las
# figuras (mismo criterio que docs/mca/figuras/epigrafes.txt).
# =============================================================================

EPIGRAFES = """\
Epígrafes de las figuras del datapath del top en integración.
Los genera figuras_datapath_top.py; no editar a mano.

Son los epígrafes de la FIGURA: dicen qué se está mirando y cómo se lee. Lo que
significa cada marca numerada NO está acá, está en la tabla del documento que
embebe cada figura — una fila por marca. Tenerlo en los dos lados era el
problema que este rediseño vino a sacar.

-------------------------------------------------------------------------------
datapath_top.svg
-------------------------------------------------------------------------------
Datapath del top en integración. Hay UNA sola cadena de acondicionado por
canal --calibración, ecualizador, diezmado, retardo-- con cuatro nodos (A a D).
Cada consumidor (osciloscopio, multitrigger y MCA) tiene su propio dsp_tap_mux
4:1: no es una matriz de conmutación, son tres selectores independientes. Cada
entrada de un mux lleva su código de tap (0 a 3) y la letra del nodo que entra;
las entradas 1 a 3 son los mismos nodos para los tres, y la 0 es el nodo nativo
de cada uno, el valor de reset. Cada consumidor elige en runtime escribiendo su
ROUTE_* en la región de TOP (slot 6). A la izquierda, el lazo digital: con
digital_loop[0] la cadena toma los pulsos de gen_pulsos en lugar del ADC. Abajo,
lo que el multitrigger da a los otros consumidores, y el event_ring (sólo en su
top), que toma las mismas muestras que el MCA. Las marcas numeradas son las
filas de la tabla de register_map_top.md, sección Ruteo del datapath.

Embebida en: docs/TOP/register_map_top.md

-------------------------------------------------------------------------------
conformado_mca_interno.svg
-------------------------------------------------------------------------------
Dentro del MCA. La muestra que llega del mux pasa por el selector de canal, el
diezmado propio del MCA y un registro de entrada, y se le resta la línea de
base: de ahí sale un único flujo x que alimenta las TRES funciones. Eso es lo
que la figura está para mostrar, y es lo único que no se puede decir en una
tabla: la forma. Ninguna de las tres tiene conformado propio --el conformado es
común y lo que cambia es el procesamiento--, el seguidor de base es el único
bloque que modifica el flujo que ven los otros dos y por eso es el único lazo
del dibujo, y el veto entra por dos lados distintos: a la apertura de pulsos y a
los relojes. Qué hace cada bloque está en la tabla del datasheet.

Embebida en: docs/mca/datasheet_mca_top.md, sección 1.1
"""


if __name__ == "__main__":
    print("Generando figuras en", AQUI)
    figura_mca_interno()
    (AQUI / "epigrafes.txt").write_text(EPIGRAFES, encoding="utf-8")
    print("  epigrafes.txt")
