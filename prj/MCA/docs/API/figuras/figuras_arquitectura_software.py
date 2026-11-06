#!/usr/bin/env python3
"""Figuras de la arquitectura de software de la API: los niveles y los cinco ejes.

Genera cinco SVG a partir de leer `software/API/`, `software/app/` y
`software/pyproject.toml`:

  niveles_api.svg        de los registros de la PL a los notebooks: que nivel
                         apoya en cual, donde corre y cual se puede sustituir
  hilos_api.svg          los TRES sistemas de concurrencia independientes
                         (pipeline de adquisicion, servidor, GUI)
  filesystem_api.svg     lo que la API lee del filesystem para llegar al
                         hardware, y lo que escribe cuando mide
  tipos_y_ejecucion.svg  el esquema de evento que se arma en runtime, y las
                         dos maquinas de estados del usuario

Las cinco son ESQUEMAS de la estructura del codigo: los unicos numeros que
llevan son los ya medidos y publicados en los docs (ver epigrafes.txt, que
escribe este mismo script). Mismo criterio que
`docs/TOP/figuras/figuras_datapath_top.py`: un solo archivo, sin dependencias,
con paleta clara y oscura.

    python3 figuras_arquitectura_software.py
"""

from pathlib import Path

AQUI = Path(__file__).parent

# =============================================================================
# Infraestructura SVG comun. La clase `Lienzo` y la hoja `ESTILO` salen de
# docs/TOP/figuras/figuras_datapath_top.py; lo agregado aca son los dominios
# (PL/PS/PC), los carriles y las cajas con texto a la izquierda.
# =============================================================================

ESTILO = """
  .bg{fill:#ffffff}
  .blk{fill:#f0f0b8;stroke:#4a4a28;stroke-width:1.2}
  .blktxt{fill:#1b1f24}
  .blk-off{fill:#ececec;stroke:#9a9a9a;stroke-width:1.1;stroke-dasharray:5 3}
  .blktxt-off{fill:#6e7781}
  .blk-net{fill:#e8f0fa;stroke:#1b3a5c;stroke-width:1.2}
  .blk-sw{fill:#f6f8fa;stroke:#57606a;stroke-width:1.2}
  .blk-proc{fill:#ffffff;stroke:#1b1f24;stroke-width:1.2}
  .blk-warn{fill:#fdeeea;stroke:#8a3b2c;stroke-width:1.2}
  .blk-ok{fill:#e7f4ec;stroke:#0f6e4f;stroke-width:1.2}
  .nm{fill:#1b1f24}  .sb{fill:#57606a}  .wd{fill:#6e7781}
  .ttl{fill:#1b1f24} .sub{fill:#57606a} .note{fill:#57606a}
  .off{fill:#8a3b2c}
  .ok{fill:#0f6e4f}
  .region{fill:#ffffff;fill-opacity:0.55;stroke:#1b1f24;stroke-width:1.3;
          stroke-dasharray:6 4}
  .panel{fill:#f6f8fa;stroke:#8b949e;stroke-width:1}
  .wire{stroke:#1b1f24;stroke-width:2;fill:none}
  .wire-thin{stroke:#57606a;stroke-width:1.3;fill:none}
  .wire-dash{stroke:#57606a;stroke-width:1.3;fill:none;stroke-dasharray:5 4}
  .rail-a{stroke:#9a3b00;stroke-width:2.6;fill:none}
  .rail-b{stroke:#0f6e4f;stroke-width:2.6;fill:none}
  .rail-c{stroke:#5a2ea6;stroke-width:2.6;fill:none}
  .rail-d{stroke:#1b3a5c;stroke-width:2.6;fill:none}
  .fa{fill:#9a3b00} .fb{fill:#0f6e4f} .fc{fill:#5a2ea6} .fd{fill:#1b3a5c}
  .arrow{fill:#1b1f24} .arrow-thin{fill:#57606a}
  .loop{stroke:#8a3b2c;stroke-width:2.2;fill:none}
  .floop{fill:#8a3b2c}
  .badge{fill:#ffffff;stroke:#8b949e;stroke-width:1}
  .badge-off{fill:#fdeeea;stroke:#8a3b2c;stroke-width:1}
  .badge-ok{fill:#e7f4ec;stroke:#0f6e4f;stroke-width:1}
  .badgetxt{fill:#57606a} .badgetxt-off{fill:#8a3b2c} .badgetxt-ok{fill:#0f6e4f}
  .badge-pl{fill:#fdf0e3;stroke:#9a3b00;stroke-width:1.1}  .txt-pl{fill:#9a3b00}
  .badge-ps{fill:#e8f0fa;stroke:#1b3a5c;stroke-width:1.1}  .txt-ps{fill:#1b3a5c}
  .badge-pc{fill:#f1ebfb;stroke:#5a2ea6;stroke-width:1.1}  .txt-pc{fill:#5a2ea6}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}
    .blk{fill:#4a4a2e;stroke:#cfcf9a}
    .blktxt{fill:#f0f0dc}
    .blk-off{fill:#21262d;stroke:#6e7681}
    .blktxt-off{fill:#8b949e}
    .blk-net{fill:#15263a;stroke:#58a6ff}
    .blk-sw{fill:#161b22;stroke:#8b949e}
    .blk-proc{fill:#0d1117;stroke:#e6edf3}
    .blk-warn{fill:#2d1714;stroke:#f0a08c}
    .blk-ok{fill:#0f2a1c;stroke:#3fb950}
    .nm{fill:#e6edf3} .sb{fill:#8b949e} .wd{fill:#8b949e}
    .ttl{fill:#e6edf3} .sub{fill:#8b949e} .note{fill:#8b949e}
    .off{fill:#f0a08c}
    .ok{fill:#3fb950}
    .region{fill:#0d1117;fill-opacity:0.72;stroke:#e6edf3}
    .panel{fill:#161b22;stroke:#6e7681}
    .wire{stroke:#e6edf3} .wire-thin{stroke:#8b949e} .wire-dash{stroke:#8b949e}
    .rail-a{stroke:#e3a008} .rail-b{stroke:#3fb950} .rail-c{stroke:#a371f7}
    .rail-d{stroke:#58a6ff}
    .fa{fill:#e3a008} .fb{fill:#3fb950} .fc{fill:#a371f7} .fd{fill:#58a6ff}
    .arrow{fill:#e6edf3} .arrow-thin{fill:#8b949e}
    .loop{stroke:#f0a08c} .floop{fill:#f0a08c}
    .badge{fill:#0d1117;stroke:#6e7681}
    .badge-off{fill:#2d1714;stroke:#f0a08c}
    .badge-ok{fill:#0f2a1c;stroke:#3fb950}
    .badgetxt{fill:#8b949e} .badgetxt-off{fill:#f0a08c} .badgetxt-ok{fill:#3fb950}
    .badge-pl{fill:#2d1e0a;stroke:#e3a008}  .txt-pl{fill:#e3a008}
    .badge-ps{fill:#15263a;stroke:#58a6ff}  .txt-ps{fill:#58a6ff}
    .badge-pc{fill:#1d1430;stroke:#a371f7}  .txt-pc{fill:#a371f7}
  }
"""

#: etiqueta de dominio -> (clase de la chapa, clase del texto)
DOM = {
    "PL": ("badge-pl", "txt-pl"),
    "PS": ("badge-ps", "txt-ps"),
    "PC": ("badge-pc", "txt-pc"),
}


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
        # xml:space="preserve" o SVG colapsa los espacios repetidos, y con eso
        # se pierden las sangrias de los arboles de directorio y la alineacion
        # en columnas de las tablas monoespaciadas.
        w = f' font-weight="{weight}"' if weight else ""
        c = f"{cls} mono" if mono else cls
        self.p.append(
            f'<text class="{c}" xml:space="preserve" x="{x:.1f}" y="{y:.1f}" '
            f'font-size="{size}" text-anchor="{anchor}"{w}>{self.esc(s)}</text>'
        )

    def rect(self, x, y, w, h, cls="blk", rx=3):
        self.p.append(
            f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="{rx}"/>'
        )

    def caja(self, x, y, w, h, lineas, cls="blk", txtcls="blktxt", size=11.5,
             dy=14.5, rx=3, mono_desde=99, mono_idx=()):
        """Caja con las lineas de texto centradas.

        `mono_desde` marca a partir de que linea el texto va monoespaciado;
        `mono_idx` permite elegir lineas sueltas (tipico: solo el titulo, que
        es un nombre de fichero o de simbolo).
        """
        self.rect(x, y, w, h, cls, rx)
        cx = x + w / 2
        cy = y + h / 2 - (len(lineas) - 1) * dy / 2 + 4
        for i, ln in enumerate(lineas):
            self.txt(cx, cy + i * dy, ln, cls=txtcls, size=size,
                     anchor="middle", weight="600" if i == 0 else None,
                     mono=i >= mono_desde or i in mono_idx)

    def cajal(self, x, y, w, h, lineas, cls="blk-sw", txtcls="nm", size=10.5,
              dy=14.5, rx=3, pad=12, mono_idx=()):
        """Caja con el texto alineado a la IZQUIERDA.

        Para listas de rutas y de ficheros: centradas no se pueden barrer con
        la vista, que es justamente para lo que estan.
        """
        self.rect(x, y, w, h, cls, rx)
        cy = y + h / 2 - (len(lineas) - 1) * dy / 2 + 4
        for i, ln in enumerate(lineas):
            self.txt(x + pad, cy + i * dy, ln, cls=txtcls, size=size,
                     weight="600" if i == 0 else None, mono=i in mono_idx)

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
            self.punta(*punta, cls=pcls or "arrow")

    def flecha(self, x0, y0, x1, y1, cls="wire", pcls=None, k=1.0):
        self.cam(f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}", cls=cls)
        d = "r" if x1 > x0 else "l"
        if abs(y1 - y0) > abs(x1 - x0):
            d = "d" if y1 > y0 else "u"
        self.punta(x1, y1, d, cls=pcls or "arrow", k=k)

    def nodo(self, x, y, letra, cls="fd", r=8.5):
        """Numero de nivel: circulo con el digito adentro."""
        self.p.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')
        self.txt(x, y + 3.6, letra, cls="bg", size=10.5, anchor="middle",
                 weight="700")

    def chapa(self, x, y, s, cls="badge", txtcls="badgetxt", size=9.5,
              anchor="start", pad=6):
        """Etiqueta con fondo, para que no se pierda sobre una linea."""
        w = len(s) * size * 0.56 + 2 * pad
        x0 = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
        self.rect(x0, y - size * 0.86 - 3, w, size * 1.72 + 4, cls, rx=3)
        self.txt(x0 + pad, y + size * 0.34, s, cls=txtcls, size=size)

    def dominio(self, x, y, etiqueta, anchor="start"):
        """Chapa de dominio de ejecucion: PL, PS o PC."""
        cls, tcls = DOM.get(etiqueta.split()[0], ("badge", "badgetxt"))
        self.chapa(x, y, etiqueta, cls=cls, txtcls=tcls, size=9,
                   anchor=anchor, pad=5)

    def nivel(self, x, y, h, num, nombre, dom):
        """Rotulo de un nivel: numero, nombre y dominio donde corre."""
        cy = y + h / 2
        self.nodo(x + 22, cy, num, cls="fd")
        self.txt(x + 44, cy - 3, nombre, cls="nm", size=12.5, weight="600")
        self.dominio(x + 44, cy + 19, dom)

    def carril(self, x, y, w, h, titulo, sub):
        """Carril de un sistema de concurrencia: region + cabecera."""
        self.rect(x, y, w, h, "region", rx=6)
        self.rect(x + 12, y + 14, w - 24, 50, "panel", rx=3)
        self.txt(x + 26, y + 36, titulo, cls="nm", size=12.5, weight="700")
        self.txt(x + 26, y + 54, sub, cls="sb", size=10, mono=True)

    # --- salida -----------------------------------------------------------
    def guardar(self, nombre, titulo, subtitulo):
        self.txt(40, 42, titulo, cls="ttl", size=20, weight="700")
        for i, ln in enumerate(subtitulo):
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
# 1. niveles_api.svg
# =============================================================================

def figura_niveles():
    c = Lienzo(1540, 1000)

    XN, WN = 46, 186            # columna de rotulos de nivel
    XB, WB = 250, 800           # banda principal
    XR, WR = 1090, 410          # canal del camino remoto
    CXR = XR + WR / 2

    # (y, h, numero, nombre, dominio)
    NIVELES = [
        (130, 74, "7", "aplicación", "PS · PC"),
        (224, 86, "6", "fuentes y sesión", "PS"),
        (330, 66, "5", "funciones", "PS"),
        (416, 86, "4", "handles", "PS"),
        (522, 84, "3", "acceso de 32 b", "PS"),
        (626, 62, "2", "mapeo crudo", "PS"),
        (708, 90, "1", "registros", "PL"),
    ]
    for y, h, num, nombre, dom in NIVELES:
        c.rect(XN, y, WN, h, "panel", rx=4)
        c.nivel(XN, y, h, num, nombre, dom)

    # --- 7 · aplicacion ---------------------------------------------------
    c.caja(XB, 130, 390, 74,
           ["campanas/run_*.py", "barridos de caracterización",
            "run_acquire · run_campana · run_deriva"],
           cls="blk-sw", txtcls="nm", size=10.5, dy=15, mono_idx=(0, 2))
    c.caja(XB + 410, 130, 390, 74,
           ["_pitaya_run.ipynb", "el cuaderno vivo, adentro de la placa",
            "jupyters_viejos/ para lo ya cerrado"],
           cls="blk-sw", txtcls="nm", size=10.5, dy=15, mono_idx=(0, 2))

    # --- 6 · fuentes y sesion ---------------------------------------------
    for i, lineas in enumerate([
        ["EventSource", "arm · wait_event · snapshot",
         "read_into · rearm · close"],
        ["AcquisitionSession", "pool + 2 colas + 2 hilos",
         "wait() → duration|events|disk|error"],
        ["Annotator", "columnas externas, ya cacheadas",
         "sample_into() no hace I/O"],
    ]):
        c.caja(XB + i * 273, 224, 253, 64, lineas, cls="blk-sw", txtcls="nm",
               size=10.5, dy=15, mono_idx=(0, 1, 2))
    c.chapa(XB + 2, 300, "sustituible: FakeSource (todo el pipeline corre en la PC)",
            cls="badge-ok", txtcls="badgetxt-ok")

    # --- 5 · funciones ----------------------------------------------------
    c.caja(XB, 330, WB, 66,
           ["mca_*  ·  osciloscope_*  ·  multitrigger_*  ·  osciloscope_ring_*",
            "<módulo>_<capa>_<campo> — get/set por read-modify-write sobre "
            "_CAMPOS = {nombre: (offset, shift, mask)}"],
           cls="blk-sw", txtcls="nm", size=10.5, dy=16, mono_idx=(0, 1))

    # --- 4 · handles ------------------------------------------------------
    HX = XB + 2
    HANDLES = ["MCA", "Osciloscope", "MultiTrigger", "RingSource", "Integration"]
    for i, nombre in enumerate(HANDLES):
        c.caja(HX + i * 162, 424, 148, 46, [nombre], cls="blk-net",
               txtcls="nm", size=11, mono_desde=0)
    c.chapa(HX, 492,
            "sustituible: MCARemote(MCA) · FakeMCA · FakeOsc · FakeMultiTrigger",
            cls="badge-ok", txtcls="badgetxt-ok")

    # --- 3 · acceso de 32 b -----------------------------------------------
    c.caja(XB, 522, 390, 58,
           ["w32(off, v)", "asignación por SLICE, nunca struct.pack_into",
            "(memset previo → stores de 1 B → SIGBUS)"],
           cls="blk-proc", txtcls="nm", size=10, dy=16, mono_idx=(0,))
    c.caja(XB + 410, 522, 390, 58,
           ["r32(off)  ·  _read_words(off, n)",
            "palabra por palabra: ~6.7 µs/palabra, ~110 ms un espectro",
            "(ráfaga o LDRD → external abort → REINICIA la placa)"],
           cls="blk-proc", txtcls="nm", size=10, dy=16, mono_idx=(0,))
    c.chapa(XB + 2, 596, "sustituible: lazo caliente en C vía ctypes (13× medido en bench_reader_c.c)",
            cls="badge-ok", txtcls="badgetxt-ok")

    # --- 2 · mapeo crudo --------------------------------------------------
    c.caja(XB, 626, WB, 62,
           ["/dev/mem  +  mmap(MAP_SHARED, PROT_READ|PROT_WRITE, offset=base)"
            "  ·  O_RDWR | O_SYNC",
            "una región por slot  ·  sin driver de kernel  ·  "
            "un solo proceso a la vez"],
           cls="blk-proc", txtcls="nm", size=10.5, dy=16, mono_idx=(0,))

    # --- 1 · registros ----------------------------------------------------
    REGS = [
        ("MCA", "0x4070_0000", "slot 7"),
        ("osciloscopio", "0x4010_0000", "slot 1"),
        ("multitrigger", "0x4030_0000", "slot 3"),
        ("event_ring", "0x4020_0000", "slot 2"),
        ("TOP", "0x4060_0000", "slot 6"),
    ]
    for i, (nombre, base, slot) in enumerate(REGS):
        c.caja(HX + i * 162, 716, 148, 74, [nombre, base, slot], cls="blk",
               txtcls="blktxt", size=10.5, dy=15, mono_desde=1)

    c.caja(XB, 804, WB, 46,
           ["⚠ API/multitrigger.py todavía escribe 0x210–0x24C sobre el slot 1, "
            "donde ya no decodifica nadie.",
            "No lanza excepción: el esclavo hace ack de todo su slot, así que "
            "las escrituras se aceptan y no hacen nada."],
           cls="blk-warn", txtcls="off", size=10, dy=16)

    # --- transversales ----------------------------------------------------
    c.rect(XN, 876, 1004, 102, "panel", rx=4)
    c.txt(XN + 14, 898, "Transversales — ni tocan registros ni les importa en qué "
          "máquina corren", cls="nm", size=11.5, weight="600")
    for i, lineas in enumerate([
        ["API/analisis.py", "picos, FWHM, DNL, FOM, tau · numpy puro"],
        ["API/modelo_rtl/", "layout del slot y estimadores de referencia"],
        ["API/fpga.py", "bring-up por sysfs: cruza todos los niveles"],
    ]):
        c.caja(XN + 14 + i * 332, 908, 312, 58, lineas, cls="blk-sw",
               txtcls="nm", size=10, dy=15, mono_idx=(0,))

    # --- camino remoto ----------------------------------------------------
    c.rect(1072, 112, 446, 430, "region", rx=6)
    c.txt(1086, 132, "camino remoto — opcional", cls="nm", size=11.5,
          weight="600")
    c.dominio(1300, 129, "PC")

    c.caja(XR, 146, WR, 70,
           ["app/mcamon.py", "la GUI, en la PC · 34 pyqtSignal"],
           cls="blk-net", txtcls="nm", size=10.5, dy=15, mono_idx=(0,))
    c.caja(XR, 240, WR, 78,
           ["API/mca_remote.py", "MCARemote(MCA): subclase donde SÓLO",
            "r32/w32 salen por el socket"],
           cls="blk-net", txtcls="nm", size=10.5, dy=15, mono_idx=(0, 2))
    c.caja(XR, 342, WR, 66,
           ["API/mca_net.py", "una línea JSON de control + bloque binario"],
           cls="blk-net", txtcls="nm", size=10.5, dy=15, mono_idx=(0,))
    c.caja(XR, 444, WR, 86,
           ["app/mca_server.py", "en la placa: un cliente a la vez,",
            "un threading.Lock sobre el handle",
            "→ y vuelve a entrar por el nivel 4"],
           cls="blk-net", txtcls="nm", size=10.5, dy=15, mono_idx=(0, 2))

    c.flecha(CXR, 216, CXR, 240, cls="rail-d", pcls="fd")
    c.flecha(CXR, 318, CXR, 342, cls="rail-d", pcls="fd")
    c.flecha(CXR, 408, CXR, 444, cls="rail-d", pcls="fd")
    c.chapa(CXR + 14, 426, "red · TCP :1001", cls="badge-ps", txtcls="txt-ps")

    # el servidor vuelve a entrar por el nivel 4: de ahi para abajo, todo igual
    c.flecha(XR, 487, XB + WB + 4, 487, cls="rail-d", pcls="fd")

    c.guardar("niveles_api.svg",
              "Los niveles de la API",
              ["De los registros de la PL a los notebooks: qué nivel apoya en "
               "cuál, dónde corre cada uno y cuál se puede sustituir.",
               "Código: software/API/ · software/app/ — esquema de la "
               "estructura del código, sin datos medidos."])


# =============================================================================
# 2. hilos_api.svg
# =============================================================================

def figura_hilos():
    c = Lienzo(1572, 664)

    YC, HC = 112, 678

    # ------------------------------------------------------------------ A
    XA, WA = 46, 620
    c.carril(XA, YC, WA, HC, "Pipeline de adquisición",
             "API/osciloscope_store/ — en la placa")
    xa = XA + 20
    wa = WA - 40                        # 580

    c.caja(xa, 190, wa, 52,
           ["hilo principal — AcquisitionSession.wait()",
            "poléa cada 0.2 s: duration | events | disk | error | source"],
           cls="blk-sw", txtcls="nm", size=10.5, dy=15, mono_idx=(1,))

    c.caja(xa, 256, wa, 50,
           ["pool preasignado — batches_for_budget(budget_mb) acotado a [2, 8]",
            "la RAM es una constante conocida de antemano y descartar cuesta O(1)"],
           cls="blk", txtcls="blktxt", size=10.5, dy=16, mono_idx=(0,))
    c.flecha(xa + 126, 310, xa + 126, 326, cls="wire-thin", pcls="arrow-thin",
             k=0.85)
    c.flecha(xa + 454, 310, xa + 454, 326, cls="wire-thin", pcls="arrow-thin",
             k=0.85)

    c.caja(xa, 330, 252, 96,
           ["osc-reader", "el único hilo que toca el scope",
            "wait_event → read_into → rearm",
            "y recién después los annotators"],
           cls="blk-proc", txtcls="nm", size=10, dy=14.5, mono_idx=(0, 2))
    c.caja(xa + 328, 330, 252, 96,
           ["osc-writer", "payload → .tmp → os.replace",
            "float32 → int16 acá, fuera del",
            "camino crítico"],
           cls="blk-proc", txtcls="nm", size=10, dy=14.5, mono_idx=(0, 1))

    # las dos colas
    c.flecha(xa + 256, 360, xa + 324, 360, cls="wire", pcls="arrow")
    c.chapa(xa + 290, 350, "full_q", cls="badge", anchor="middle")
    c.flecha(xa + 324, 406, xa + 256, 406, cls="wire", pcls="arrow")
    c.chapa(xa + 290, 420, "free_q", cls="badge", anchor="middle")

    c.caja(xa, 450, 252, 78,
           ["annot-<prefijo>", "un hilo por annotator lento",
            "poll() acá; sample_into() sólo",
            "copia el valor ya cacheado"],
           cls="blk-sw", txtcls="nm", size=10, dy=13.5, mono_idx=(0, 2))
    c.caja(xa + 328, 450, 252, 78,
           ["chunk_000000.npz", "+ run_summary.json",
            "escritura atómica: todo archivo",
            "visible está completo"],
           cls="blk-sw", txtcls="nm", size=10, dy=13.5, mono_idx=(0, 1))
    c.flecha(xa + 126, 448, xa + 126, 430, cls="wire-thin", pcls="arrow-thin",
             k=0.85)
    c.flecha(xa + 454, 430, xa + 454, 446, cls="wire-thin", pcls="arrow-thin",
             k=0.85)

    c.caja(xa, 548, wa, 64,
           ["rama de descarte — sin batch libre: pending += 1, n_dropped += 1, "
            "rearm(), continue",
            "re-armar TAMBIÉN acá: omitirlo dio 14 996 eventos fantasma contra "
            "10 251 reales"],
           cls="blk-warn", txtcls="off", size=10, dy=16, mono_idx=(0,))


    # ------------------------------------------------------------------ B
    XB, WB = 696, 400
    c.carril(XB, YC, WB, HC, "Servidor", "app/mca_server.py — en la placa")
    xb = XB + 20
    wb = WB - 40                        # 360

    c.caja(xb, 190, wb, 86,
           ["mca-cliente", "un hilo por conexión aceptada,",
            "pero sólo uno vivo a la vez: el 2º",
            "se rechaza con un hint explícito"],
           cls="blk-proc", txtcls="nm", size=10, dy=14.5, mono_idx=(0,))
    c.chapa(xb, 292, "«un solo proceso puede tocar /dev/mem»",
            cls="badge-off", txtcls="badgetxt-off")

    c.caja(xb, 312, wb, 64,
           ["self._lock = threading.Lock()",
            "protege TODO acceso al handle"],
           cls="blk-sw", txtcls="nm", size=10.5, dy=15, mono_idx=(0,))

    c.caja(xb, 396, wb, 86,
           ["mca-exposicion", "el MCA es free-running: no hay",
            "registro de tiempo de exposición en",
            "el HW, así que poléa livetime_s"],
           cls="blk-proc", txtcls="nm", size=10, dy=14.5, mono_idx=(0,))

    c.caja(xb, 502, wb, 78,
           ["_lock_cliente + testigo", "el finally de un cliente que se va",
            "no puede borrar al recién llegado"],
           cls="blk-sw", txtcls="nm", size=10, dy=15, mono_idx=(0,))


    # ------------------------------------------------------------------ C
    XG, WG = 1126, 400
    c.carril(XG, YC, WG, HC, "GUI", "app/mcamon.py — en la PC")
    xg = XG + 20
    wg = WG - 40

    c.caja(xg, 190, wg, 86,
           ["Trabajador(QObject)", "dueño ÚNICO del MCARemote,",
            "vive en su propio QThread;",
            "nadie más toca el socket"],
           cls="blk-proc", txtcls="nm", size=10, dy=14.5, mono_idx=(0, 2))

    c.caja(xg, 296, wg, 78,
           ["34 pyqtSignal", "la comunicación va en los dos",
            "sentidos y es toda por señales:",
            "cero locks en la GUI"],
           cls="blk-sw", txtcls="nm", size=10, dy=14.5, mono_idx=(0,))

    c.caja(xg, 394, wg, 78,
           ["2 QTimer, adentro del worker", "estado (PERIODO_ESTADO_MS) y",
            "espectro (REFRESCO_ESPECTRO_S)"],
           cls="blk-sw", txtcls="nm", size=10, dy=15, mono_idx=(0, 1, 2))

    c.caja(xg, 492, wg, 78,
           ["hilo.finished → deleteLater", "el worker se destruye en SU hilo:",
            "Qt no deja parar sus timers desde otro"],
           cls="blk-sw", txtcls="nm", size=10, dy=15, mono_idx=(0,))


    c.guardar("hilos_api.svg",
              "Tres sistemas de concurrencia, no uno",
              ["Cada carril resuelve un problema distinto y elige una "
               "primitiva distinta. Los números son los medidos en la placa.",
               "Código: software/API/osciloscope_store/ · software/app/ — "
               "estructura del código y mediciones ya publicadas."])


# =============================================================================
# 3. filesystem_api.svg
# =============================================================================

def figura_filesystem():
    c = Lienzo(1540, 742)

    YC, HC = 112, 740

    # ---------------------------------------------------------------- lee
    XL, WL = 46, 714
    c.carril(XL, YC, WL, HC, "Lo que la API LEE del filesystem",
             "para llegar al hardware — API/fpga.py, API/mca.py")
    xl, wl = XL + 20, WL - 40           # 66, 674

    c.cajal(xl, 190, wl, 66, [
        "/sys/class/fpga_manager/fpga0/state",
        "¿está programada la PL? tiene que decir `operating`",
    ], mono_idx=(0,))
    c.cajal(xl, 266, wl, 66, [
        "/sys/class/fpga_bridge/*/enable",
        "bajar los puentes AXI PS–PL antes de reconfigurar",
    ], mono_idx=(0,))
    c.cajal(xl, 342, wl, 66, [
        "/opt/redpitaya/bin/fpgautil -b  (o /usr/local/bin/)",
        "programa la PL; un shell no interactivo no lo tiene en el PATH",
    ], mono_idx=(0,))
    c.cajal(xl, 418, wl, 66, [
        "/root/red_pitaya_top.bit.bin  ·  /root/mca_red_pitaya.bit.bin",
        "BITSTREAM_DEFAULT de API/fpga.py, y el que carga el servidor",
    ], mono_idx=(0,))
    c.cajal(xl, 494, wl, 66, [
        "/sys/bus/i2c/devices/0-0050/eeprom  vía  monitor -f",
        "modelo de placa → qué Zynq → la guarda que impide un bitstream ajeno",
    ], mono_idx=(0,))
    c.cajal(xl, 570, wl, 66, [
        "/dev/mem",
        "O_RDWR | O_SYNC, un mmap por slot — el único camino a los registros",
    ], cls="blk", txtcls="blktxt", mono_idx=(0,))
    c.cajal(xl, 646, wl, 66, [
        "/opt/redpitaya/lib/python",
        "sys.path para el binding `rp` (rp_AcqGetDataPosV, rp.fBuffer)",
    ], mono_idx=(0,))

    c.caja(xl, 736, wl, 46,
           ["⚠ ORDEN: cerrar los mmap ANTES de reprogramar la PL",
            "si no, el puerto GP0 queda trabado hasta reiniciar la placa"],
           cls="blk-warn", txtcls="off", size=10, dy=16)
    c.caja(xl, 794, wl, 46,
           ["pl_probe() hace su lectura de prueba en un proceso HIJO",
            "así el SIGBUS mata al hijo y no al kernel de Jupyter"],
           cls="blk-warn", txtcls="off", size=10, dy=16, mono_idx=(0,))

    # -------------------------------------------------------------- escribe
    XE, WE = 790, 704
    c.carril(XE, YC, WE, HC, "Lo que la API ESCRIBE",
             "cuando mide — osciloscope_store/, API/mca.py")
    xe, we = XE + 20, WE - 40           # 810, 664

    c.cajal(xe, 190, we, 110, [
        "<run_dir>/",
        "    chunk_000000.npz   wave int16 (ev, canal, muestra)",
        "                       + una columna por campo escalar",
        "                       + meta como array 0-d de objeto",
        "    chunk_000001.npz   …",
        "    run_summary.json   los totales de la corrida",
    ], cls="blk-sw", size=10, dy=16, mono_idx=(0, 1, 2, 3, 4, 5))

    c.caja(xe, 314, we, 66,
           [".tmp  +  os.replace",
            "todo archivo visible en el directorio está completo: es la "
            "condición",
            "para que un file pusher consuma el directorio sin carreras"],
           cls="blk-ok", txtcls="nm", size=10, dy=15, mono_idx=(0,))

    c.caja(xe, 394, we, 50,
           ["a np.savez se le pasa un HANDLE, no un path",
            "si no, le agrega la extensión y queda chunk.npz.tmp.npz"],
           cls="blk-sw", txtcls="nm", size=10, dy=16, mono_idx=(0,))

    c.caja(xe, 458, we, 66,
           ["free_space_mb() cada 8 chunks  ·  MIN_FREE_MB = 200",
            "por debajo de eso: disk_full.set() → la sesión corta limpio",
            "y el escritor sigue drenando full_q para no trabar al lector"],
           cls="blk-sw", txtcls="nm", size=10, dy=15, mono_idx=(0,))

    c.caja(xe, 538, we, 50,
           ["el espectro del MCA: .csv (por defecto)  ·  .npz  ·  .json",
            "el .csv lleva la metadata en líneas de cabecera con #"],
           cls="blk-sw", txtcls="nm", size=10, dy=16, mono_idx=(0,))

    # el camino fisico
    c.txt(xe, 618, "Y después de write(), el camino físico:", cls="nm",
          size=11, weight="600")
    c.caja(xe, 630, 200, 56, ["page cache del kernel",
                              "write() vuelve antes", "de tocar la SD"],
           cls="blk-proc", txtcls="nm", size=10, dy=14, mono_idx=(1,))
    c.caja(xe + 232, 630, 200, 56, ["microSD", "12.4 MB/s medidos",
                                    "no hay SSD en esta placa"],
           cls="blk", txtcls="blktxt", size=10, dy=14)
    c.caja(xe + 464, 630, 200, 56, ["NFS", "la bifurcación: saca el",
                                    "disco de la placa del lazo"],
           cls="blk-sw", txtcls="nm", size=10, dy=14)
    c.flecha(xe + 200, 658, xe + 228, 658, cls="wire-thin", pcls="arrow-thin")
    c.flecha(xe + 432, 658, xe + 460, 658, cls="wire-thin", pcls="arrow-thin")


    c.guardar("filesystem_api.svg",
              "La API vista desde el filesystem",
              ["Qué rutas del sistema necesita para llegar al hardware, y qué "
               "deja escrito cuando mide."])


# =============================================================================
# 4. tipos_y_ejecucion.svg
# =============================================================================

def figura_tipos():
    c = Lienzo(1540, 700)

    YC, HC = 112, 700

    # ------------------------------------------------------------- tipos
    XT, WT = 46, 674
    c.carril(XT, YC, WT, HC, "Tipos de datos",
             "el esquema no está hardcodeado: se arma en runtime")
    xt, wt = XT + 20, WT - 40           # 66, 634

    c.caja(xt, 190, wt, 46,
           ["No hay dataclass, Enum, NamedTuple ni TypedDict en todo el árbol "
            "— a propósito:",
            "constantes de módulo, diccionarios y arrays de numpy"],
           cls="blk-warn", txtcls="off", size=10, dy=16, mono_idx=(0,))

    c.cajal(xt, 252, 300, 104, [
        "BASE_FIELDS",
        "t_ns   int64    perf_counter_ns",
        "wp     int32    wp_trig @0x1C",
        "snap   uint32   trig_snapshot",
        "gap    uint8    descartes previos",
    ], cls="blk-sw", size=10, dy=16, mono_idx=(0, 1, 2, 3, 4))
    c.cajal(xt + 334, 252, 300, 104, [
        "+ source.scalar_fields",
        "+ annotator.scalar_fields",
        "",
        "un GPS aporta sus columnas y su",
        "<prefijo>_age_ns; el DeadTime, dead_ns",
    ], cls="blk-sw", size=10, dy=16, mono_idx=(0, 1, 4))

    c.flecha(xt + 150, 356, xt + 300, 390, cls="wire-thin", pcls="arrow-thin")
    c.flecha(xt + 484, 356, xt + 334, 390, cls="wire-thin", pcls="arrow-thin")

    c.caja(xt, 396, wt, 50,
           ["merge_fields(source, annotators)",
            "falla fuerte ante nombres repetidos: una colisión silenciosa "
            "haría que dos productores se pisen la misma columna"],
           cls="blk-ok", txtcls="nm", size=10, dy=16, mono_idx=(0,))
    c.flecha(xt + wt / 2, 446, xt + wt / 2, 468, cls="wire", pcls="arrow")

    c.cajal(xt, 474, wt, 90, [
        "EventBatch  —  arrays C-contiguos preasignados para `capacity` eventos",
        "wave    (capacity, n_ch, samples)   float32 en RAM → int16 en disco",
        "        el canal es un EJE, no un nombre: el mismo código sirve",
        "        para 2 o 4 canales, porque la RTL es paramétrica en N_CH",
        "scalars {nombre: array}, y cada uno además como atributo",
    ], cls="blk", txtcls="blktxt", size=10, dy=16, mono_idx=(0, 1, 4))

    c.caja(xt, 578, wt, 46,
           ["gap satura en GAP_MAX = 255: responde «¿hay un hueco acá?», no "
            "«cuántos»",
            "el total exacto va aparte, en batch.dropped → meta['chunk_dropped']"],
           cls="blk-sw", txtcls="nm", size=10, dy=16, mono_idx=(0, 1))


    # --------------------------------------------------------- ejecucion
    XE, WE = 750, 744
    c.carril(XE, YC, WE, HC, "Ejecución",
             "las dos máquinas de estados que ve el usuario")
    xe, we = XE + 20, WE - 40           # 770, 704

    # -- EventSource: el lazo del lector
    c.txt(xe, 200, "EventSource — el lazo de la adquisición continua",
          cls="nm", size=11.5, weight="600")
    PASOS_SRC = [
        ("arm()", "deja el HW listo; orden crítico adentro"),
        ("wait_event(deadline_ns)", "devuelve wp_trig, o None si hubo timeout"),
        ("snapshot()", "qué fuente disparó (una lectura más, ~2.3 µs)"),
        ("read_into(batch, i, wp)", "escribe EN el destino provisto: sin basura de GC"),
        ("rearm()", "apenas la ventana está copiada; acá termina el tiempo muerto"),
    ]
    for i, (paso, nota) in enumerate(PASOS_SRC):
        y = 212 + i * 62
        c.caja(xe, y, 300, 46, [paso, nota], cls="blk-proc", txtcls="nm",
               size=9.5, dy=14, mono_idx=(0,))
        if i < len(PASOS_SRC) - 1:
            c.flecha(xe + 150, y + 46, xe + 150, y + 60, cls="wire",
                     pcls="arrow", k=0.85)
    # El lazo vuelve a wait_event(), no a arm(): arm() se llama una sola vez,
    # al abrir la corrida (reader.py, _loop).
    Y_REARM = 212 + 4 * 62 + 23
    Y_WAIT = 212 + 62 + 23
    c.cam(f"M{xe + 300:.1f},{Y_REARM:.1f} H{xe + 340:.1f} "
          f"V{Y_WAIT:.1f} H{xe + 304:.1f}", cls="loop",
          punta=(xe + 304, Y_WAIT, "l"), pcls="floop")
    c.caja(xe, 212 + 5 * 62, 300, 34, ["close()"], cls="blk-sw", txtcls="nm",
           size=10, mono_desde=0)
    c.flecha(xe + 150, 508, xe + 150, 518, cls="wire-dash", pcls="arrow-thin",
             k=0.8)

    # -- MCA: el flujo del espectro
    c.txt(xe + 390, 200, "MCA — el flujo del espectro", cls="nm", size=11.5,
          weight="600")
    PASOS_MCA = [
        ("mca_open()", "mapea y valida el magic «MCA1»"),
        ("mca_configure / mca_set_*", "umbral, histéresis, base, ventana, ejes"),
        ("mca_clear()", "poléa clear_busy con timeout"),
        ("mca_start()", "y el hardware acumula solo"),
        ("mca_read_histogram()", "mca_read_map2d · mca_read_counters"),
        ("mca_stop()", ""),
        ("mca_write_file_histogram()", "con meta=mca_get_metadata(h)"),
    ]
    for i, (paso, nota) in enumerate(PASOS_MCA):
        y = 212 + i * 50
        lineas = [paso] if not nota else [paso, nota]
        c.caja(xe + 390, y, 314, 38, lineas, cls="blk-proc", txtcls="nm",
               size=9.5, dy=13, mono_idx=(0,))
        if i < len(PASOS_MCA) - 1:
            c.flecha(xe + 547, y + 38, xe + 547, y + 48, cls="wire",
                     pcls="arrow", k=0.8)

    # -- las dos trampas de orden
    c.caja(xe, 596, we, 46,
           ["⚠ armar (0x00) y RECIÉN DESPUÉS habilitar la máscara (0x240/0x244)",
            "al revés, un flanco en el hueco gasta la máscara con la FSM "
            "todavía sin armar"],
           cls="blk-warn", txtcls="off", size=10, dy=16, mono_idx=(0,))
    c.caja(xe, 652, we, 46,
           ["⚠ en los relojes de 64 b, leer LO antes que HI",
            "la palabra baja congela la alta en un registro sombra: al revés "
            "la lectura se parte"],
           cls="blk-warn", txtcls="off", size=10, dy=16)

    c.guardar("tipos_y_ejecucion.svg",
              "Tipos de datos y ejecución",
              ["Sin clases de datos y sin enums: el esquema se arma en "
               "runtime, y el orden de las operaciones es parte del contrato."])


# =============================================================================
# ERA la figura 5, cobertura_tests.svg -> AHORA ES UNA TABLA
#
# Era una matriz de 7 niveles x 4 clases de verificacion con el nombre de los
# ficheros en cada celda. El SVG tenia 78 nodos de texto, 44 rectangulos y
# CERO paths --ni una flecha--: una tabla dibujada. Como tabla se lee mejor,
# se puede copiar, la encuentra el grep y se corrige sin regenerar nada.
#
# Vive en `docs/API/arquitectura_software.md`, seccion 5, "La matriz: que
# suite toca que nivel". Las tres notas al pie que llevaba --el norecursedirs,
# que hace `make verificar` y donde esta el codigo-- son ahora una cita en el
# mismo documento.
# =============================================================================

# =============================================================================
# Epigrafes
# =============================================================================

EPIGRAFES = """\
Epigrafes de las figuras de la arquitectura de software de la API.
Los genera figuras_arquitectura_software.py; no editar a mano.

Las cuatro figuras son ESQUEMAS de la estructura del codigo: salen de leer
software/API/, software/app/ y software/pyproject.toml. Los unicos numeros que
aparecen son mediciones ya publicadas en los documentos del repositorio, y cada
una esta citada en el epigrafe correspondiente.

-------------------------------------------------------------------------------
niveles_api.svg
-------------------------------------------------------------------------------
Los siete niveles de la API, de los registros de la logica programable (banda 1,
abajo) a los notebooks y las campanas (banda 7, arriba). Cada banda lleva su
dominio de ejecucion: PL para la logica programable, PS para el procesador de la
Red Pitaya y PC para la maquina del usuario.

La figura esta para dejar tres cosas claras.

PRIMERO, que no hay driver de kernel. Entre los registros y el Python no hay
nada mas que /dev/mem y un mmap por slot, y de ahi sale la restriccion que
atraviesa todo lo demas: un solo proceso puede tocar la PL a la vez. Las lineas
punteadas atan cada handle de la banda 4 con su bloque de registros de la banda
1, que es la unica relacion uno a uno de todo el diagrama.

SEGUNDO, que el nivel 3 es una frontera fisica, no una capa de conveniencia. La
escritura va por asignacion de slice y no por struct.pack_into, porque pack_into
hace un memset previo que sobre memoria de dispositivo sale como stores de a
byte y el esclavo AXI no los reconoce. La lectura en bloque va palabra por
palabra, a ~6.7 us por palabra y ~110 ms por un espectro de 16384 canales,
porque cualquier rafaga o acceso ancho se propaga como external abort y en esta
placa eso REINICIA el sistema. Las dos reglas estan verificadas en
API/tests/placa/test_rw_dev_mem.py y en API/tests/placa/diag_mca_hw.py.

TERCERO, donde se puede sustituir un nivel sin tocar los de arriba. Son cuatro
puntos, marcados en verde: el lazo caliente del nivel 3 puede bajar a C por
ctypes (13x medido en API/bench/bench_reader_c.c, aunque no es codigo de
produccion); los handles del nivel 4 admiten MCARemote y las variantes Fake*; y
la fuente del nivel 6 admite FakeSource, con lo que el pipeline entero corre en
la PC.

El camino remoto, a la derecha, es el que mas se malinterpreta. MCARemote es una
SUBCLASE de MCA en la que solo r32 y w32 salen por el socket: todo lo que esta
arriba del nivel 4 no se entera de que hay red abajo, y por eso el servidor
vuelve a entrar en la pila local exactamente por el nivel 4. La interfaz la fija
el consumidor, no el transporte.

El aviso en rojo al pie de la banda 1 es un estado real del arbol, no una nota
historica: el hardware del multitrigger se mudo al slot 3 (0x4030_0000) y
API/multitrigger.py todavia escribe los offsets 0x210-0x24C sobre el slot 1. No
lanza excepcion, porque el esclavo hace ack de todo su slot: las escrituras se
aceptan y no hacen nada.

OJO con la palabra "niveles". En API/README.md, "las tres capas" NO son niveles
de abstraccion: son los tres segmentos del NOMBRE de la funcion,
<modulo>_<capa>_<campo>. Son dos cosas distintas y conviven en el mismo
directorio de documentacion.

-------------------------------------------------------------------------------
hilos_api.svg
-------------------------------------------------------------------------------
Los tres sistemas de concurrencia del software, uno por carril. No hay un modelo
de hilos: hay tres, independientes entre si, y cada uno elige una primitiva
distinta porque resuelve un problema distinto. El pipeline usa colas, el
servidor usa locks y la GUI usa senales de Qt. No hay multiprocessing ni asyncio
en ninguno.

(a) EL PIPELINE DE ADQUISICION, en API/osciloscope_store/. Productor y consumidor
con dos colas y un pool de batches preasignados: osc-reader llena un batch y lo
pasa por full_q, osc-writer lo escribe como chunk_%06d.npz y lo devuelve por
free_q. El pool es lo que hace que la RAM sea una constante conocida de antemano
y que descartar cueste O(1). Un solo hilo toca el scope; el escritor solo ve
arrays de numpy.

La politica ante contrapresion es la decision de diseno central: descartar y
contar, NUNCA bloquear. Si el lector bloqueara esperando lugar en la cola, el
tiempo muerto pasaria a depender del disco y dejaria de ser una constante del
hardware, que es justo lo que rompe la estadistica de conteo. La rama de
descarte, en rojo, igual llama a rearm(): cuando eso no estaba, el buffer
quedaba congelado, wait_event volvia a disparar con el mismo evento y el
contador se llenaba de fantasmas. Medido: 14996 "eventos" vistos contra 10251
realmente generados.

Los tres numeros del panel inferior son mediciones de la placa. El stall maximo
del lector con el escritor de fondo era 5288 us, que es exactamente el
sys.getswitchinterval() por default: la firma de libro de la contencion de GIL,
y la razon por la que la sesion lo baja a 1 ms al arrancar. savez tarda 86 ms
para un chunk de 1.07 MB contra 628 ms de savez_compressed para 0.95 MB, o sea
7.3 veces el tiempo por 12 % de espacio, y ademas comprimir es CPU con el GIL
disputado mientras escribir es I/O con el GIL suelto. La conversion de float32 a
int16 vive en el hilo escritor, que tiene tiempo de sobra, y no en el lector.

Los annotators son un concepto aparte y no un EventSource: un GPS no define
cuando ocurre un evento, lo anota, y va tres o cuatro ordenes de magnitud mas
lento. Cada annotator lento corre su propio hilo, annot-<prefijo>, y
sample_into() dentro del lazo caliente solo copia un valor ya cacheado. Por eso
declara ademas un campo <prefijo>_age_ns: sin eso, un GPS que perdio el fix hace
diez minutos escribe coordenadas plausibles y silenciosamente falsas en cada
evento.

(b) EL SERVIDOR, en app/mca_server.py. Un threading.Lock protege todo acceso al
handle, y se acepta un cliente a la vez: el segundo se rechaza con el hint
explicito de que un solo proceso puede tocar /dev/mem. El hilo mca-exposicion
existe por una ausencia del hardware: el MCA es free-running y no hay registro
de tiempo de exposicion, asi que la exposicion la implementa un vigilante que
polea livetime_s y para al llegar al objetivo. La adquisicion NO se detiene
cuando el cliente se va, que es lo que permite que una medida de media hora
sobreviva a cerrar la GUI.

(c) LA GUI, en app/mcamon.py. Trabajador(QObject) es el dueno unico del
MCARemote y vive en su propio QThread; la comunicacion con la ventana va
enteramente por las 34 pyqtSignal, en los dos sentidos, y no hay un solo lock.
Es el patron opuesto al del servidor y es correcto por la misma razon por la que
el del servidor lo es: hay un unico dueno por recurso. El worker se destruye en
su propio hilo, via hilo.finished -> deleteLater, porque Qt no permite parar sus
QTimer desde otro hilo.

El pipeline y el servidor no corren a la vez sobre la misma placa, por la misma
regla de un solo proceso sobre /dev/mem.

-------------------------------------------------------------------------------
filesystem_api.svg
-------------------------------------------------------------------------------
La API vista desde el filesystem, en dos mitades que no se parecen. La izquierda
es configuracion del sistema que se lee una vez, al arrancar, para poder llegar
al hardware. La derecha es el producto de la medicion.

Del lado de la lectura, lo que importa no son las rutas sino las dos reglas en
rojo. La primera es de orden: hay que cerrar los mmap ANTES de reprogramar la
PL, porque reconfigurar con mapeos abiertos produce el external abort de dmesg y
puede dejar el puerto GP0 trabado hasta reiniciar la placa. La segunda es de
aislamiento: pl_probe() hace su lectura de prueba en un proceso HIJO, con un
subprocess, para que si el bus no esta listo el SIGBUS mate al hijo y nos
enteremos por el returncode, en vez de perder el kernel de Jupyter. Es la unica
forma segura de preguntar si ya se puede tocar el scope despues de reconfigurar.

La lectura de la EEPROM por i2c, via monitor -f, sostiene una garantia que no es
obvia: de ahi sale el modelo de placa, del modelo sale que Zynq lleva, y con eso
la guarda que impide cargar un bitstream compilado para otra parte. Son los 19
tests de test_guarda_bitstream.py, todos sin placa.

Del lado de la escritura, la propiedad central es la atomicidad. Los dos
escritores -- el de chunks y el del resumen -- escriben a un .tmp y hacen
os.replace, asi que todo archivo visible en el directorio esta completo. Es la
condicion para que un file pusher pueda consumir el directorio sin carreras, y
es lo que verifica el test de pipeline comprobando que no queden .tmp. A
np.savez se le pasa un HANDLE y no un path, porque savez agrega la extension por
su cuenta y terminariamos con chunk.npz.tmp.npz.

run_summary.json no es decorativo: la columna gap cuenta los descartes que
ocurrieron ENTRE dos eventos guardados, asi que los del FINAL de la corrida no
tienen ningun evento posterior donde anotarse. El invariante completo es

    sum(gap sobre todos los chunks) + trailing_dropped == n_dropped

y trailing_dropped sale de ese archivo. Sin el, una corrida que termina en medio
de una rafaga de descartes no cierra las cuentas.

La guarda de disco se chequea cada 8 chunks con os.statvfs y corta limpio por
debajo de 200 MB libres. Lo que no se ve a primera vista es que el escritor,
despues de cortar, sigue drenando full_q: si no lo hiciera, el lector se trabaria
esperando lugar.

El camino fisico al pie explica por que el formato esta elegido asi. write()
vuelve antes de tocar la tarjeta, porque escribe al page cache del kernel; el
sustrato real es una microSD a 12.4 MB/s medidos, y no hay SSD en esta placa. NFS
es la bifurcacion que saca el disco de la placa del lazo.

No se usa /dev/uio*, ni devmem, ni HDF5, ni ningun formato binario crudo propio.

-------------------------------------------------------------------------------
tipos_y_ejecucion.svg
-------------------------------------------------------------------------------
Los tipos de datos a la izquierda y las dos maquinas de estados del usuario a la
derecha.

El dato que ordena la mitad izquierda es una ausencia: no hay un solo dataclass,
Enum, NamedTuple ni TypedDict en todo el arbol, y es deliberado. Lo que hay son
constantes de modulo, diccionarios y arrays de numpy.

El esquema del evento NO esta hardcodeado: se arma en runtime. BASE_FIELDS trae
las cuatro columnas que existen siempre -- t_ns del reloj de software, wp del
hardware, snap de la fuente que disparo y gap de los descartes previos -- y
merge_fields() les suma lo que declaren la fuente y cada annotator. Falla fuerte
ante nombres repetidos, porque una colision silenciosa haria que dos productores
se pisen la misma columna. La consecuencia practica es la que justifica todo el
diseno: agregar columnas, sean features del MCA calculadas en hardware o la
posicion de un GPS, no toca al lector, ni al escritor, ni al formato de archivo.

Se guardan los dos relojes crudos a proposito. El de software es monotono pero
tiene jitter de microsegundos; el de hardware da 8 ns de resolucion pero envuelve
cada 16384 muestras. Los Delta-t salen de un np.diff offline, no se calculan en
el lazo.

En EventBatch, wave tiene forma (capacity, n_ch, samples): el canal es un EJE y
no un nombre de variable, asi que el mismo codigo sirve para 2 o 4 canales,
porque la RTL ya es parametrica en N_CH. Que canal es cada indice va en
meta['channels']. El dtype es una decision de almacenamiento y no de velocidad:
float32 en RAM porque es lo unico que entrega la API del rp en esta placa, int16
en disco porque el ADC es de 14 bits, y la conversion ocurre en el hilo escritor.

gap satura en 255 porque lo unico que importa por evento es SI hay un hueco: un
gap mayor que cero significa que el Delta-t contra el evento anterior no es real
y hay que excluirlo del analisis. El total exacto vive aparte, en batch.dropped,
que no satura.

Del lado de los registros se repite el mismo criterio sin clases: un R_* por
offset con el bit-layout en el comentario, y tablas _CAMPOS que mapean nombre a
(offset, shift, mask), sobre las que se generan los get y set por
read-modify-write. El bus de FEATURES merece una nota: _feat_idx() valida el
indice contra el diccionario porque apuntar a una ranura reservada daria el
espectro entero acumulado en el canal 0, sin lanzar ningun error.

A la derecha, las dos maquinas de estados. El lazo de EventSource -- arm,
wait_event, snapshot, read_into, rearm -- es la interfaz que existe para que el
dia que se migre a DDR solo cambie esa capa. read_into escribe EN el destino
provisto en vez de devolver arrays: evita la basura de GC de hacer un np.zeros
por llamada y por canal, y hace que la version DDR sea un memcpy sin capa
intermedia. rearm() es parte de la INTERFAZ y no un detalle de read_into,
precisamente para que el lector pueda re-armar tambien cuando descarta.

El flujo del MCA es mas corto porque el hardware acumula solo: se configura, se
limpia, se arranca, y la lectura es de un espectro ya formado. Eso es lo que saca
la tasa de eventos del cuello de botella del bus.

Las dos trampas de orden, en rojo, cuestan una sesion de laboratorio cada una.
Hay que armar la FSM (0x00) y RECIEN DESPUES habilitar la mascara (0x240/0x244):
al reves, un flanco que llegue en el hueco gasta la mascara con la FSM todavia
sin armar, y queda esperando un trigger imposible. Y en los relojes de 64 bits
hay que leer la palabra baja antes que la alta, porque leer LO congela HI en un
registro sombra del RTL; al reves, la lectura se parte.

"""


if __name__ == "__main__":
    print(f"Generando figuras en {AQUI}")
    figura_niveles()
    figura_hilos()
    figura_filesystem()
    figura_tipos()
    (AQUI / "epigrafes.txt").write_text(EPIGRAFES, encoding="utf-8")
    print("  epigrafes.txt")
