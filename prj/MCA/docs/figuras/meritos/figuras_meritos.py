#!/usr/bin/env python3
"""Las figuras de mérito del MCA y del OSC medidas con `gen_pulsos` (generación interna),
en el estilo común de las figuras TikZ.

  meritos_tasa          aceptados y en su línea por segundo contra la tasa de entrada
  meritos_tasa_fuentes  lo mismo con 3 ranuras, para cada fuente de disparo
  meritos_lambda        el error de la tasa estimada λ̂ contra la tasa de entrada
  meritos_perdidas      dónde termina cada pulso de entrada, contra la tasa
  meritos_inl           la no linealidad integral del trapecio
  meritos_corrimiento   cuánto se corre la línea con la tasa (base fija)
  meritos_corrimiento_canal
                        el corrimiento en la placa y en la réplica con el canal medido,
                        con y sin los polos lentos, y la forma que elige el banco
  meritos_par           resolución de pulsos dobles: disparos y los dos en su línea contra Δt
  meritos_walk          curva S, walk y disparos por pulso contra la amplitud
  meritos_ruido         resolución de cada estimador contra el ruido de entrada
  meritos_histeresis    el centroide a lo largo de la rampa de tasas, ida y vuelta
  canal_analogico       respuesta al escalón y |H(f)|: OUT1 → IN1 con 50 Ω y OUT2 → IN2 sin carga
  fidelidad_analogica   IN1 contra el modelo del canal, y el residuo con su umbral
  meritos_forma         FWHM, ε y FWHM/ε² de una sola forma contra la ocupación ρ
  meritos_apilamiento   fondo contra ε de cada corte del discriminador
  meritos_dnl           la DNL del trapecio con la tabla de pasos de 5 y 6 ADU, y la que deja la tabla
  meritos_psd           los espectros de PSD de dos caídas y la FOM contra la amplitud
  meritos_polo_cero     el error del segundo pulso de un par contra ΔM
  meritos_ventana_ciega disparos, apilado aceptado y los dos en su línea contra Δt, con y sin corte
  meritos_base_dinamica en su línea, corrimiento y Δb con la base fija, el seguidor y la dinámica
  meritos_deriva        las líneas, el offset y la ganancia en 2 h, y contra la temperatura
  throughput_caminos    eventos registrados por segundo en los dos caminos de datos: el MCA
                        (el espectro en la FPGA) y el osciloscopio (las formas por el ring,
                        a la DDR, al lector de C, a la PC por la red y a la SD)

Las mismas convenciones en todas: el lazo digital va con línea llena y marcas llenas, el
canal analógico (OUT1 → IN1 con 50 Ω) con línea a trazos y marcas huecas; el color es la
categoría de la figura (la fuente de disparo, el estimador o las ranuras), de una paleta
derivada de la del proyecto y validada para daltonismo (el par más cercano está en la
banda de 6 a 8 de ΔE, por eso cada serie lleva además su forma de marca y rótulo).

Los datos son los de la placa del 2026-11-14 (`software/datos/`, que no se versiona):
las campañas `run_meritos_pulsos.py` y `run_fidelidad_osc.py` y las mediciones del canal.
Las seis de forma a ventana ciega usan la campaña del 2026-11-16
(`meritos2_2026-11-16_digital` y `_analogico`; la DNL, sólo la primera corrida
digital), y la ventana ciega le suma los Δt de 64 a 512 (`ciega_2026-11-17_*`).
`meritos_base_dinamica` usa `meritos_2026-11-14_analogico_seguidor` y
`meritos_2026-11-16_analogico_dinamica`, y `meritos_deriva`, `deriva_2026-11-16_analogico`.
`meritos_polo_cero` suma la placa simulada con el canal medido (`datos/sim_polo_cero_canal`).
`meritos_corrimiento_canal` usa además la placa simulada de `sim_corrimiento_canal.py`
(en `datos/sim_corrimiento_canal`).
`throughput_caminos` suma las campañas del ring de `run_etapas_ring.py` (generador del
ring, no `gen_pulsos`): A y B de `placa_etapas_20261112/etapas_AB`, D de
`etapas_red_2026-11-17b` y `c` (los mismos techos que `docs/API/figuras/bench_sd_red`) y C
de `etapas_sd_largo_2026-11-17`.
Le suma el camino original del osciloscopio, la BRAM, con `gen_pulsos` y sus dos lectores,
el de C y el original de Python con librp (`run_techo_bram.py`, `techo_bram_2026-11-19`).
Los epígrafes van en `<figura>.txt`, al lado de cada `.tex`.

    python3 figuras_meritos.py [--datos ../../../software/datos]
"""
import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]                           # prj/MCA
sys.path.insert(0, str(RAIZ / 'software' / 'campanas'))
import canal_analogico as CA                     # noqa: E402

FS = 125e6
TS_NS = 8.0

PREAMBULO = r"""%% %(desc)s. GENERADO por figuras_meritos.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../estilo_tikz.tex}
\usetikzlibrary{plotmarks}
%% la paleta de las series: los tonos del proyecto, oscurecidos para líneas y validados
%% (scripts/validate_palette.js de la guía de visualización, sobre blanco, todos los pares)
\definecolor{cazul}{HTML}{2A6FB5}
\definecolor{cnaranja}{HTML}{D9702A}
\definecolor{cverde}{HTML}{2E9E5B}
\definecolor{cmagenta}{HTML}{C2417C}
\definecolor{cgris}{HTML}{5A5A5A}
%% rampa ordinal (las ranuras): un solo tono, de claro a oscuro
\definecolor{r1}{HTML}{6FA8DC}
\definecolor{r2}{HTML}{2A6FB5}
\definecolor{r3}{HTML}{123D63}
\tikzset{
  eje/.style    = {black!60, line width=0.5pt},
  guia/.style   = {black!10, line width=0.4pt},
  tick/.style   = {font=\scriptsize, inner sep=1.5pt, black!75},
  titeje/.style = {font=\scriptsize, inner sep=1pt},
  digital/.style   = {line width=0.8pt, line join=round},
  analogico/.style = {line width=0.8pt, line join=round, dash pattern=on 3pt off 1.6pt},
  limite/.style    = {line width=1.2pt, line cap=round, line join=round, dash pattern=on 0pt off 2.3pt},
  directo/.style = {font=\scriptsize, inner sep=1.5pt},
  letra/.style  = {font=\scriptsize\bfseries, anchor=south west, inner sep=0pt},
}
%% una muestra de leyenda de un área: #1 color
\newcommand{\muestraarea}[1]{\tikz[baseline=-0.6ex]{\fill[#1] (0,-0.9mm) rectangle (3.2mm,1.3mm);}}
%% una muestra de leyenda: #1 color, #2 estilo de línea, #3 marca, #4 relleno de la marca
\newcommand{\muestra}[4]{\tikz[baseline=-0.6ex]{\draw[#1, #2] (0,0) -- (6mm,0);
  \draw[#1, line width=0.6pt] plot[only marks, mark=#3, mark size=1.35pt,
    mark options={fill=#4, solid}] coordinates {(3mm,0)};}}
\begin{document}
\begin{tikzpicture}[fondo]
%(cuerpo)s
\end{tikzpicture}
\end{document}
"""


def f(v):
    return f"{v:.3f}"


# =============================================================================
# Un panel: ejes lineales o logarítmicos, en cm
# =============================================================================
class Panel:
    def __init__(self, x0, y0, w, h, xlim, ylim, xlog=False, ylog=False):
        self.x0, self.y0, self.w, self.h = x0, y0, w, h
        self.xlim, self.ylim, self.xlog, self.ylog = xlim, ylim, xlog, ylog
        self.l = []

    def _t(self, v, lim, log):
        a, b = lim
        if log:
            return (math.log10(v) - math.log10(a)) / (math.log10(b) - math.log10(a))
        return (v - a) / (b - a)

    def X(self, v):
        return self.x0 + self._t(v, self.xlim, self.xlog) * self.w

    def Y(self, v):
        return self.y0 + self._t(v, self.ylim, self.ylog) * self.h

    def dentro(self, x, y):
        if x is None or y is None or not np.isfinite(x) or not np.isfinite(y):
            return False
        if (self.xlog and x <= 0) or (self.ylog and y <= 0):
            return False
        tx, ty = self._t(x, self.xlim, self.xlog), self._t(y, self.ylim, self.ylog)
        return -1e-6 <= tx <= 1 + 1e-6 and -1e-6 <= ty <= 1 + 1e-6

    def ejes(self, xticks, yticks, xlabel, ylabel, xfmt=str, yfmt=str, ylabel_dx=0.75):
        l, x0, y0, w, h = self.l, self.x0, self.y0, self.w, self.h
        for v in yticks:
            y = self.Y(v)
            l.append(f"\\draw[guia] ({f(x0)},{f(y)}) -- ({f(x0 + w)},{f(y)});")
            l.append(f"\\draw[eje] ({f(x0)},{f(y)}) -- ++(-0.07,0) node[tick, left] {{{yfmt(v)}}};")
        for v in xticks:
            x = self.X(v)
            l.append(f"\\draw[guia] ({f(x)},{f(y0)}) -- ({f(x)},{f(y0 + h)});")
            l.append(f"\\draw[eje] ({f(x)},{f(y0)}) -- ++(0,-0.07) node[tick, below] {{{xfmt(v)}}};")
        l.append(f"\\draw[eje] ({f(x0)},{f(y0)}) rectangle ({f(x0 + w)},{f(y0 + h)});")
        if xlabel:
            l.append(f"\\node[titeje, anchor=north] at ({f(x0 + w / 2)},{f(y0 - 0.42)}) {{{xlabel}}};")
        if ylabel:
            l.append(f"\\node[titeje, rotate=90, anchor=south] at ({f(x0 - ylabel_dx)},{f(y0 + h / 2)}) "
                     f"{{{ylabel}}};")

    def letra(self, s):
        self.l.append(f"\\node[letra] at ({f(self.x0)},{f(self.y0 + self.h + 0.12)}) {{{s}}};")

    def linea(self, xs, ys, color, estilo='digital', ancho=None):
        """La polilínea, recortada al marco; los huecos (None, nan) la cortan."""
        tramos, cur = [], []
        for x, y in zip(xs, ys):
            ok = (x is not None and y is not None and np.isfinite(x) and np.isfinite(y)
                  and not (self.xlog and x <= 0) and not (self.ylog and y <= 0))
            if ok:
                cur.append((x, y))
            elif cur:
                tramos.append(cur)
                cur = []
        if cur:
            tramos.append(cur)
        extra = f", line width={ancho}pt" if ancho else ""
        self.l.append(f"\\begin{{scope}}\\clip ({f(self.x0)},{f(self.y0)}) rectangle "
                      f"({f(self.x0 + self.w)},{f(self.y0 + self.h)});")
        for t in tramos:
            if len(t) < 2:
                continue
            pts = " ".join(f"({f(self.X(x))},{f(self.Y(y))})" for x, y in t)
            self.l.append(f"\\draw[{color}, {estilo}{extra}] plot coordinates {{{pts}}};")
        self.l.append("\\end{scope}")

    def marcas(self, xs, ys, color, marca='*', lleno=True):
        pts = " ".join(f"({f(self.X(x))},{f(self.Y(y))})" for x, y in zip(xs, ys)
                       if self.dentro(x, y))
        if pts:
            relleno = color if lleno else 'white'
            self.l.append(f"\\draw[{color}, line width=0.6pt] plot[only marks, mark={marca}, "
                          f"mark size=1.35pt, mark options={{fill={relleno}, solid}}] "
                          f"coordinates {{{pts}}};")

    def serie(self, xs, ys, color, marca, analogico=False, con_linea=True):
        estilo = 'analogico' if analogico else 'digital'
        if con_linea:
            self.linea(xs, ys, color, estilo)
        self.marcas(xs, ys, color, marca, lleno=not analogico)

    def texto(self, x, y, s, anchor='west', dx=0.0, dy=0.0, color='black'):
        self.l.append(f"\\node[directo, anchor={anchor}, text={color}] at "
                      f"({f(self.X(x) + dx)},{f(self.Y(y) + dy)}) {{{s}}};")

    def vertical(self, x, color='black!45', estilo='densely dotted', ancho=0.6):
        self.l.append(f"\\draw[{color}, {estilo}, line width={ancho}pt] ({f(self.X(x))},{f(self.y0)}) "
                      f"-- ({f(self.X(x))},{f(self.y0 + self.h)});")

    def horizontal(self, y, color='black!45', estilo='densely dotted', ancho=0.6):
        self.l.append(f"\\draw[{color}, {estilo}, line width={ancho}pt] ({f(self.x0)},{f(self.Y(y))}) "
                      f"-- ({f(self.x0 + self.w)},{f(self.Y(y))});")


def leyenda(x, y, entradas, ancho=15.5):
    """Una fila (o varias, con None de separador) de muestras: (color, estilo, marca,
    lleno, texto)."""
    filas, cur = [], []
    for e in entradas:
        if e is None:
            filas.append(cur)
            cur = []
        else:
            cur.append(e)
    if cur:
        filas.append(cur)
    def una(c, s, m, ll, t):
        if m is None:                            # una línea sola, sin marca
            return f"\\tikz[baseline=-0.6ex]{{\\draw[{c}, {s}] (0,0) -- (6mm,0);}}~{t}"
        if m == 'area':
            return f"\\muestraarea{{{c}}}~{t}"
        return f"\\muestra{{{c}}}{{{s}}}{{{m}}}{{{c if ll else 'white'}}}~{t}"
    txt = "\\\\[1.5pt]".join("\\hspace{4mm}".join(una(*e) for e in fila) for fila in filas)
    return (f"\\node[anchor=north west, font=\\scriptsize, align=left, inner sep=0pt, "
            f"text width={ancho}cm] at ({f(x)},{f(y)}) {{{txt}}};")


def log_ticks(a, b, mult=(1, 2, 5)):
    out = []
    e = math.floor(math.log10(a))
    while 10 ** e <= b * 1.0001:
        for m in mult:
            v = m * 10 ** e
            if a * 0.9999 <= v <= b * 1.0001:
                out.append(v)
        e += 1
    return out


def num(v):
    """Un tick de eje: entero si lo es, sin ceros de más; miles con espacio fino."""
    if abs(v - round(v)) < 1e-9:
        s = f"{int(round(v))}"
        return s if len(s) < 5 else f"{int(round(v)):,}".replace(',', '\\,')
    return f"{v:g}"


# =============================================================================
# Los datos
# =============================================================================
class Datos:
    def __init__(self, raiz):
        self.raiz = Path(raiz)
        self.D = self._json('meritos_2026-11-14_digital/meritos.json')
        self.A = self._json('meritos_2026-11-14_analogico/meritos.json')
        # las etapas del 2026-11-16 (forma, apilamiento, dnl, psd, polo_cero y
        # ventana_ciega); la analógica entra en las figuras cuando está
        self.D2 = self._json('meritos2_2026-11-16_digital/meritos.json')
        self.A2 = self._json_o('meritos2_2026-11-16_analogico/meritos.json')
        # la tasa en el canal analógico con las otras bases (seguidor del 14, dinámica del
        # 16) y la deriva de 2 h (2026-11-16)
        self.Aseg = self._json_o('meritos_2026-11-14_analogico_seguidor/meritos.json')
        self.Adin = self._json_o('meritos_2026-11-16_analogico_dinamica/meritos.json')
        self.Der = self._json_o('deriva_2026-11-16_analogico/meritos.json')
        # la ventana ciega con Δt de 32 a 512 (2026-11-17), más allá de la ventana
        self.C2 = {False: self._json_o('ciega_2026-11-17_digital/meritos.json'),
                   True: self._json_o('ciega_2026-11-17_analogico/meritos.json')}
        # el camino del osciloscopio (run_etapas_ring.py, generador del ring): A y B del
        # 2026-11-12, D por la red y C contra la SD con puntos largos del 2026-11-17
        self.RingAB = self._json_o('placa_etapas_20261112/etapas_AB/etapas_ring.json')
        self.RingD = [self._json_o(f'etapas_red_2026-11-17{s}/etapas_ring.json') for s in 'bc']
        self.RingC = [self._json_o(f'etapas_sd_largo_2026-11-17/{v}/etapas_ring.json')
                      for v in ('8_24', '16_240_11', '32_992_13')]
        # el camino original del osciloscopio, la BRAM, con gen_pulsos (run_techo_bram.py):
        # el lector de C de libmca y el lazo original de Python con librp (2026-11-19)
        self.Bram = self._json_o('techo_bram_2026-11-19/techo_bram.json')

    def _json(self, rel):
        with open(self.raiz / rel) as fh:
            return json.load(fh)

    def _json_o(self, rel):
        return self._json(rel) if (self.raiz / rel).is_file() else None

    def modos2(self, etapa):
        """(json, analógico) de las campañas del 2026-11-16 que tienen la etapa."""
        return [(m, an) for m, an in ((self.D2, False), (self.A2, True))
                if m is not None and any(r['etapa'] == etapa for r in m['filas'])]

    def npz(self, rel):
        return np.load(self.raiz / rel)

    @staticmethod
    def filas(m, etapa, **kw):
        out = [r for r in m['filas'] if r['etapa'] == etapa]
        for k, v in kw.items():
            out = [r for r in out if r.get(k) == v]
        return out


def corrida(r, espectro):
    return next(c for c in r['corridas'] if c['espectro'] == espectro)


# =============================================================================
# tasa
# =============================================================================
def fig_tasa(d):
    W, H, G = 6.3, 4.6, 1.75
    xl, yl = (8, 4000), (8, 4000)
    pa = Panel(0, 0, W, H, xl, yl, True, True)
    pb = Panel(W + G, 0, W, H, xl, yl, True, True)
    tx = [10, 100, 1000]
    ty = [10, 100, 1000]
    pa.ejes(tx, ty, 'tasa de entrada [k/s]', 'aceptados [k/s]', num, num)
    pb.ejes(tx, ty, 'tasa de entrada [k/s]', 'en su línea [k/s]', num, num)
    pa.letra('(a)')
    pb.letra('(b)')
    for p in (pa, pb):
        p.linea([8, 4000], [8, 4000], 'black!35', 'densely dotted')
    pa.l.append(f"\\node[directo, anchor=south east, text=black!55] at "
                f"({f(pa.x0 + pa.w)},{f(pa.y0 + pa.h + 0.02)}) {{$\\cdots$ salida = entrada}};")
    colores = {1: 'r1', 2: 'r2', 3: 'r3'}
    for n_acc, color in colores.items():
        for m, analog in ((d.D, False), (d.A, True)):
            filas = sorted(d.filas(m, 'tasa', fuente='asg', n_acc=n_acc), key=lambda r: r['tasa'])
            me = [corrida(r, 'trapecio')['meritos'] for r in filas]
            x = [q['n_in_hz'] / 1e3 for q in me]
            pa.serie(x, [q['aceptados_hz'] / 1e3 for q in me], color, '*', analog)
            pb.serie(x, [q['buenos_hz'] / 1e3 for q in me], color, '*', analog)
        q = corrida(sorted(d.filas(d.D, 'tasa', fuente='asg', n_acc=n_acc),
                           key=lambda r: r['tasa'])[-1], 'trapecio')['meritos']
        nombre = f"{n_acc} ranura" + ("s" if n_acc > 1 else "")
        pa.l.append(f"\\node[directo, anchor=west] at ({f(pa.x0 + pa.w + 0.05)},"
                    f"{f(pa.Y(q['aceptados_hz'] / 1e3))}) {{{nombre}}};")
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico (OUT1 $\\to$ IN1)'),
        ('r1', 'digital', '*', True, '1 ranura'),
        ('r2', 'digital', '*', True, '2 ranuras'),
        ('r3', 'digital', '*', True, '3 ranuras')]))
    return "\n".join(cuerpo)


# =============================================================================
# tasa con cada fuente de disparo, el error de λ̂ y las pérdidas
# =============================================================================
FUENTES_TASA = (('asg', 'cazul', '*', 'ASG'), ('pz', 'cnaranja', 'square*', 'polo-cero'),
                ('pendiente', 'cverde', 'triangle*', 'pendiente'))


def _tasa(m, fuente, n_acc):
    filas = sorted(Datos.filas(m, 'tasa', fuente=fuente, n_acc=n_acc), key=lambda r: r['tasa'])
    return [corrida(r, 'trapecio')['meritos'] for r in filas]


def fig_tasa_fuentes(d):
    W, H, G = 6.1, 4.6, 2.7
    xl, yl = (8, 4000), (8, 4000)
    pa = Panel(0, 0, W, H, xl, yl, True, True)
    pb = Panel(W + G, 0, W, H, xl, yl, True, True)
    pa.ejes([10, 100, 1000], [10, 100, 1000], 'tasa de entrada [k/s]', 'aceptados [k/s]', num, num)
    pb.ejes([10, 100, 1000], [10, 100, 1000], 'tasa de entrada [k/s]', 'en su línea [k/s]', num, num)
    pa.letra('(a) 3 ranuras')
    pb.letra('(b) 3 ranuras')
    for p in (pa, pb):
        p.linea([8, 4000], [8, 4000], 'black!35', 'densely dotted')
    pa.l.append(f"\\node[directo, anchor=south east, text=black!55] at "
                f"({f(pa.x0 + pa.w)},{f(pa.y0 + pa.h + 0.02)}) {{$\\cdots$ salida = entrada}};")
    rot = {pa: [], pb: []}
    for fuente, color, marca, nombre in FUENTES_TASA:
        for m, analog in ((d.D, False), (d.A, True)):
            me = _tasa(m, fuente, 3)
            x = [q['n_in_hz'] / 1e3 for q in me]
            for p, clave in ((pa, 'aceptados_hz'), (pb, 'buenos_hz')):
                y = [q[clave] / 1e3 for q in me]
                p.serie(x, y, color, marca, analog)
                if not analog:
                    rot[p].append((y[-1], nombre, color, marca, True))
    for p in (pa, pb):
        rotulos_derecha(p, rot[p])
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'ASG (no mira la señal)'),
        ('cnaranja', 'digital', 'square*', True, 'polo-cero'),
        ('cverde', 'digital', 'triangle*', True, 'pendiente'), None,
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico (OUT1 $\\to$ IN1)')]))
    return "\n".join(cuerpo)


def fig_lambda(d):
    W, H, G = 5.9, 4.4, 2.8
    xl, yl = (8, 4000), (-32, 8)
    pa = Panel(0, 0, W, H, xl, yl, True, False)
    pb = Panel(W + G, 0, W, H, xl, yl, True, False)
    for p, n_acc in ((pa, 1), (pb, 3)):
        p.ejes([10, 100, 1000], [-30, -20, -10, 0], 'tasa de entrada [k/s]',
               'error de $\\hat\\lambda$ [\\%]', num, num)
        p.letra(f"({'a' if n_acc == 1 else 'b'}) {n_acc} ranura" + ("s" if n_acc > 1 else ""))
        p.horizontal(0, 'black!45', 'solid', 0.5)
        rot = []
        for fuente, color, marca, nombre in FUENTES_TASA:
            for m, analog in ((d.D, False), (d.A, True)):
                me = _tasa(m, fuente, n_acc)
                y = [100 * q['err_lam'] for q in me]
                p.serie([q['n_in_hz'] / 1e3 for q in me], y, color, marca, analog)
                if not analog:
                    rot.append((y[-1], nombre, color, marca, True))
        rotulos_derecha(p, rot)
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'ASG'),
        ('cnaranja', 'digital', 'square*', True, 'polo-cero'),
        ('cverde', 'digital', 'triangle*', True, 'pendiente'), None,
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico (OUT1 $\\to$ IN1)')]))
    return "\n".join(cuerpo)


# Dónde termina cada pulso de entrada, de abajo hacia arriba. Suman 1: cada pérdida
# tiene su contador (cross = open + lost_active + dropped + lost_veto).
CAUSAS = (('cazul', 'aceptado en su línea ($\\pm$2 \\%)'),
          ('r1', 'aceptado fuera de su línea'),
          ('black!16', 'perdido en el publicador'),
          ('black!36', 'sin ranura libre'),
          ('black!60', 'sin disparo'))


def _fracciones(q):
    return [q['frac_buenos'], q['eficiencia'] - q['frac_buenos'], q['perd_publicador'],
            q['perd_ranura'], q['perd_disparo'] + q['perd_veto']]


def fig_perdidas(d):
    W, H, GX, GY = 4.3, 3.0, 0.45, 0.8
    xl, yl = (10, 3000), (0, 100)
    cuerpo = []
    letras = iter('abcdef')
    for i, n_acc in enumerate((1, 3)):
        for j, (fuente, _, _, nombre) in enumerate(FUENTES_TASA):
            p = Panel(j * (W + GX), (1 - i) * (H + GY), W, H, xl, yl, True, False)
            p.ejes([10, 100, 1000], [0, 25, 50, 75, 100],
                   'tasa de entrada [k/s]' if i == 1 else '',
                   'pulsos de entrada [\\%]' if j == 0 else '',
                   num if i == 1 else (lambda v: ''), num if j == 0 else (lambda v: ''))
            p.letra(f"({next(letras)}) {nombre}, {n_acc} ranura" + ("s" if n_acc > 1 else ""))
            me = _tasa(d.D, fuente, n_acc)
            x = [q['n_in_hz'] / 1e3 for q in me]
            acum = np.cumsum(np.array([_fracciones(q) for q in me]) * 100, axis=1)
            acum[:, -1] = np.minimum(acum[:, -1], 100.0)
            for c, (color, _) in enumerate(CAUSAS):
                arriba = acum[:, c]
                abajo = acum[:, c - 1] if c else np.zeros(len(x))
                pts = ([(p.X(a), p.Y(b)) for a, b in zip(x, arriba)]
                       + [(p.X(a), p.Y(b)) for a, b in zip(x[::-1], abajo[::-1])])
                poly = " -- ".join(f"({f(u)},{f(v)})" for u, v in pts)
                p.l.append(f"\\fill[{color}, draw=white, line width=0.4pt] {poly} -- cycle;")
            # el canal analógico: hasta dónde llegan los eventos en su línea
            ma = _tasa(d.A, fuente, n_acc)
            p.linea([q['n_in_hz'] / 1e3 for q in ma], [100 * q['frac_buenos'] for q in ma],
                    'black', 'analogico')
            p.l.append(f"\\draw[eje] ({f(p.x0)},{f(p.y0)}) rectangle ({f(p.x0 + W)},{f(p.y0 + H)});")
            cuerpo += p.l
    cuerpo.append(leyenda(0, -1.0, [(c, '', 'area', True, t) for c, t in CAUSAS[:3]]
                          + [None] + [(c, '', 'area', True, t) for c, t in CAUSAS[3:]]
                          + [('black', 'analogico', 'none', True,
                              'en su línea, canal analógico (OUT1 $\\to$ IN1)')], ancho=14.0))
    return "\n".join(cuerpo)


# =============================================================================
# INL del trapecio
# =============================================================================
INL_AJUSTE = (200, 3200)      # donde las tres fuentes miden en los dos modos


def _inl(m, fuente, ajuste=INL_AJUSTE):
    """El residuo del trapecio contra una recta por los puntos de `ajuste`, en % del
    fondo de escala (8191 ADU por la ganancia). Sólo los puntos donde dispara
    siempre y hay línea (el polo-cero en el analógico no la tiene desde 5000)."""
    filas = sorted(Datos.filas(m, 'walk', fuente=fuente), key=lambda r: r['amplitud'])
    a = np.array([r['amplitud'] for r in filas], float)
    y = np.array([r['medida']['trapecio'] if (r['medida']['efic_disparo'] >= 0.99 and
                                              r['medida']['trapecio']) else np.nan
                  for r in filas], float)
    sel = (a >= ajuste[0]) & (a <= ajuste[1]) & np.isfinite(y)
    g, b = np.polyfit(a[sel], y[sel], 1)
    ok = np.isfinite(y)
    return a[ok], 100 * (y[ok] - (g * a[ok] + b)) / (g * 8191)


def fig_inl(d):
    W, H, G = 6.0, 4.2, 2.0
    xl = (18, 9000)
    xt = [20, 100, 1000, 5000]
    pa = Panel(0, 0, W, H, xl, (-0.004, 0.004), True, False)
    pb = Panel(W + G, 0, W, H, xl, (-0.1, 0.1), True, False)
    pa.ejes(xt, [-0.004, -0.002, 0, 0.002, 0.004], 'amplitud del generador [ADU]',
            'residuo del trapecio [\\% FS]', num, lambda v: f"{v:g}", ylabel_dx=1.0)
    pb.ejes(xt, [-0.1, -0.05, 0, 0.05, 0.1], 'amplitud del generador [ADU]',
            'residuo del trapecio [\\% FS]', num, lambda v: f"{v:g}", ylabel_dx=0.95)
    pa.letra('(a) lazo digital')
    pb.letra('(b) canal analógico')
    # Desde dónde el sobrepico del canal pasa el fondo de escala del ADC
    c = d.A['meta']['canal']
    a_sat = (8191 - c['offset']) / (c['ganancia'] * (1 + c['sobrepico']))
    pb.l.append(f"\\fill[black!7] ({f(pb.X(a_sat))},{f(pb.y0)}) rectangle "
                f"({f(pb.x0 + W)},{f(pb.y0 + H)});")
    for p in (pa, pb):
        p.horizontal(0, 'black!45', 'solid', 0.5)
    for fuente, color, marca, _ in FUENTES_TASA:
        for p, m, analog in ((pa, d.D, False), (pb, d.A, True)):
            a, r = _inl(m, fuente)
            p.serie(a, r, color, marca, analog)
            for x, y in zip(a, r):           # fuera de escala: una flecha en el borde
                if y > p.ylim[1]:
                    xx = p.X(x)
                    p.l.append(f"\\draw[{color}, line width=0.6pt, -{{Stealth[length=1.6mm]}}] "
                               f"({f(xx)},{f(p.y0 + H - 0.42)}) -- ({f(xx)},{f(p.y0 + H - 0.05)});")
                    if fuente == 'asg':
                        p.texto(x, p.ylim[1], f"$+{y:.2f}$\\,\\%", anchor='east', dx=-0.42,
                                dy=-0.55)
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'ASG'),
        ('cnaranja', 'digital', 'square*', True, 'polo-cero'),
        ('cverde', 'digital', 'triangle*', True, 'pendiente'), None,
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico (OUT1 $\\to$ IN1)'),
        ('black!7', '', 'area', True, 'el sobrepico pasa el fondo de escala del ADC')]))
    return "\n".join(cuerpo)


# =============================================================================
# corrimiento de la línea con la tasa (base fija)
# =============================================================================
def _corrimientos(m):
    ref = m['referencias']['tasa/asg']['trapecio']['lineas']
    out = []
    for r in sorted(Datos.filas(m, 'tasa', fuente='asg', n_acc=3), key=lambda r: r['tasa']):
        c = corrida(r, 'trapecio')
        h = {int(k): v for k, v in c['hist'].items()}
        ch = np.array(sorted(h))
        n = np.array([h[k] for k in ch])
        fila = [c['meritos']['n_in_hz'] / 1e3]
        for L in ref:
            sel = np.abs(ch - L) < 0.15 * L
            fila.append(float((ch[sel] * n[sel]).sum() / n[sel].sum() - L))
        out.append(fila)
    return np.array(out), ref


def fig_corrimiento(d):
    W, H = 9.0, 4.6
    p = Panel(0, 0, W, H, (8, 4000), (-30, 6), True, False)
    p.ejes([10, 100, 1000], list(range(-30, 6, 5)), 'tasa de entrada [k/s]',
           'corrimiento de la línea [canales]', num, num)
    p.horizontal(0, 'black!45', 'solid', 0.5)
    rot = []
    for m, analog in ((d.D, False), (d.A, True)):
        c, ref = _corrimientos(m)
        for j, (color, marca) in enumerate((('cazul', '*'), ('cnaranja', 'square*'))):
            p.serie(c[:, 0], c[:, 1 + j], color, marca, analog)
            if analog:
                rot.append((c[-1, 0], c[-1, 1 + j], (500, 1300)[j]))
    for x, y, a in rot:
        p.texto(x, y, f"{a} ADU", dx=0.12)
    cuerpo = p.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'línea de 500 ADU'),
        ('cnaranja', 'digital', 'square*', True, 'línea de 1300 ADU'), None,
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico (OUT1 $\\to$ IN1)')], ancho=9.0))
    return "\n".join(cuerpo)


# =============================================================================
# corrimiento: la placa contra la réplica con el canal medido, con y sin polos lentos
# =============================================================================
SIM_CORR = 'sim_corrimiento_canal'      # lo de campanas/sim_corrimiento_canal.py
ORIGENES_CORR = (
    ('placa', 'cazul', '*', 'placa (OUT1 $\\to$ IN1 con 50 $\\Omega$)'),
    ('con_lentos', 'cmagenta', 'diamond*', 'réplica con el canal medido'),
    ('sin_lentos', 'cgris', 'triangle*', 'réplica sin los polos lentos'))
FORMAS_CORR = ('r3', 'r2', 'r1')       # k = 64, 32, 8: de la más larga a la más corta


def fig_corrimiento_canal(d):
    W, H, G, GC = 4.4, 4.0, 0.5, 1.35
    xl, xt = (8, 4000), [10, 100, 1000]
    pa = Panel(0, 0, W, H, xl, (-36, 4), True, False)
    pb = Panel(W + G, 0, W, H, xl, (-36, 4), True, False)
    pc = Panel(2 * W + G + GC, 0, W, H, xl, (0, 100), True, False)
    yt = [-30, -20, -10, 0]
    pa.ejes(xt, yt, 'tasa de entrada [k/s]', 'corrimiento de la línea [canales]', num, num)
    pb.ejes(xt, yt, 'tasa de entrada [k/s]', '', num, lambda v: '')
    pc.ejes(xt, [0, 25, 50, 75, 100], 'tasa de entrada [k/s]',
            'eventos de las dos líneas [\\%]', num, num, ylabel_dx=0.7)
    pa.letra('(a) línea de 500 ADU')
    pb.letra('(b) línea de 1300 ADU')
    pc.letra('(c) forma del banco, en la réplica')
    for p in (pa, pb):
        p.horizontal(0, 'black!45', 'solid', 0.5)
    for origen, color, marca, _ in ORIGENES_CORR:
        m = d.A if origen == 'placa' else d._json(f'{SIM_CORR}/{origen}/meritos.json')
        c, _ = _corrimientos(m)
        for j, p in enumerate((pa, pb)):
            p.serie(c[:, 0], c[:, 1 + j], color, marca, analogico=True)
    fz = d._json(f'{SIM_CORR}/formas.json')
    x = [q['n_in_hz'] / 1e3 for q in fz['puntos']]
    fr = np.array([[100 * f['fraccion'] for f in q['formas']] for q in fz['puntos']])
    acum = np.cumsum(fr, axis=1)
    acum[:, -1] = np.minimum(acum[:, -1], 100.0)
    for c, color in enumerate(FORMAS_CORR):
        arriba = acum[:, c]
        abajo = acum[:, c - 1] if c else np.zeros(len(x))
        pts = ([(pc.X(a), pc.Y(b)) for a, b in zip(x, arriba)]
               + [(pc.X(a), pc.Y(b)) for a, b in zip(x[::-1], abajo[::-1])])
        poly = " -- ".join(f"({f(u)},{f(v)})" for u, v in pts)
        pc.l.append(f"\\fill[{color}, draw=white, line width=0.4pt] {poly} -- cycle;")
    pc.l.append(f"\\draw[eje] ({f(pc.x0)},{f(pc.y0)}) rectangle ({f(pc.x0 + W)},{f(pc.y0 + H)});")
    formas = fz['puntos'][0]['formas']
    cuerpo = pa.l + pb.l + pc.l
    cuerpo.append(leyenda(0, -1.0, [(c, 'analogico', mk, False, t) for _, c, mk, t in ORIGENES_CORR]
                          + [None] + [(col, '', 'area', True,
                                       f"forma k = {q['k']}: (k + m)/$\\tau$ = {q['l_tau']:.2f}")
                                      for col, q in zip(FORMAS_CORR, formas)]))
    return "\n".join(cuerpo)


# =============================================================================
# par: resolución de pulsos dobles
# =============================================================================
FUENTES_PAR = (('pz', 'cnaranja', 'square*', 'polo-cero'), ('pendiente', 'cverde', 'triangle*', 'pendiente'))


def fig_par(d):
    W, H, G = 4.55, 4.0, 1.05
    xl = (2, 512)
    xt = [2, 8, 32, 128, 512]
    pa = Panel(0, 0, W, H, xl, (0.8, 4.2), True, False)
    pb = Panel(W + G, 0, W, H, xl, (-0.05, 1.05), True, False)
    pc = Panel(2 * (W + G), 0, W, H, xl, (-0.05, 1.05), True, False)
    pa.ejes(xt, [1, 2, 3, 4], '$\\Delta t$ [ciclos]', 'disparos por par', num, num)
    pb.ejes(xt, [0, 0.5, 1], '$\\Delta t$ [ciclos]', 'pares con los dos en su línea', num,
            lambda v: f"{v:g}", ylabel_dx=0.65)
    pc.ejes(xt, [0, 0.5, 1], '$\\Delta t$ [ciclos]', '', num, lambda v: f"{v:g}")
    pa.letra('(a) disparos, 3 ranuras')
    pb.letra('(b) los dos en su línea, 3 ranuras')
    pc.letra('(c) los dos en su línea, 1 ranura')
    for fuente, color, marca, _ in FUENTES_PAR:
        for m, analog in ((d.D, False), (d.A, True)):
            for p, n_acc, que in ((pa, 3, 'disparos'), (pb, 3, 'buenos'), (pc, 1, 'buenos')):
                filas = sorted(d.filas(m, 'par', fuente=fuente, n_acc=n_acc), key=lambda r: r['dt'])
                me = [corrida(r, 'trapecio')['meritos'] for r in filas]
                x = [r['dt'] for r in filas]
                if que == 'disparos':
                    y = [q['disparos_par'] for q in me]
                else:
                    y = [min(q['frac_a1'], q['frac_a2']) for q in me]
                p.serie(x, y, color, marca, analog)
    cuerpo = pa.l + pb.l + pc.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cnaranja', 'digital', 'square*', True, 'disparo por polo-cero'),
        ('cverde', 'digital', 'triangle*', True, 'disparo por pendiente'),
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico')]))
    return "\n".join(cuerpo)


# =============================================================================
# walk: curva S, walk y disparos por pulso contra la amplitud
# =============================================================================
FUENTES_WALK = (('asg', 'cazul', '*', 'ASG'),) + FUENTES_PAR


def fig_walk(d):
    W, H, G = 13.0, 2.55, 0.55
    xl = (18, 9000)
    xt = [20, 50, 100, 200, 500, 1000, 2000, 5000]
    pc = Panel(0, 0, W, H, xl, (-0.15, 3.3), True, False)
    pb = Panel(0, H + G, W, H, xl, (-4, 64), True, False)
    pa = Panel(0, 2 * (H + G), W, H, xl, (-0.05, 1.05), True, False)
    pa.ejes(xt, [0, 0.5, 1], '', 'eficiencia de disparo', lambda v: '', lambda v: f"{v:g}")
    pb.ejes(xt, [0, 20, 40, 60], '', 'retardo del disparo [ns]', lambda v: '', num)
    pc.ejes(xt, [0, 1, 2, 3], 'amplitud del pulso [ADU del generador]', 'disparos por pulso',
            num, num)
    pa.letra('(a)')
    pb.letra('(b)')
    pc.letra('(c)')
    for fuente, color, marca, _ in FUENTES_WALK:
        for m, analog in ((d.D, False), (d.A, True)):
            w = m['meta']['walk'][fuente]
            amps = w['amplitudes']
            if fuente != 'asg':
                pa.serie(amps, w['efic'], color, marca, analog)
                # el walk guardado es t_subida menos el del ASG, que en el canal analógico
                # arrastra el corrimiento de la ventana del ASG: lo que importa es cuánto
                # más tarde dispara un pulso chico que uno grande. Sin disparos (debajo de
                # la curva S) no hay walk: hueco en la línea.
                wk = w['walk']
                ref = wk[str(max(int(k) for k in wk))]
                pb.serie(amps, [(ref - wk[str(a)]) * TS_NS if str(a) in wk else None
                                for a in amps], color, marca, analog)
            filas = {r['amplitud']: r for r in d.filas(m, 'walk', fuente=fuente)}
            y = []
            for a in amps:
                c = corrida(filas[a], 'trapecio')
                y.append(c['cnt']['trig_edges'] / filas[a]['gen']['n'])
            pc.serie(amps, y, color, marca, analog)
    cuerpo = pa.l + pb.l + pc.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'ASG (no mira la señal)'),
        ('cnaranja', 'digital', 'square*', True, 'polo-cero'),
        ('cverde', 'digital', 'triangle*', True, 'pendiente'),
        ('black', 'digital', '*', True, 'lazo digital'),
        ('black', 'analogico', '*', False, 'canal analógico')], ancho=14.5))
    return "\n".join(cuerpo)


# =============================================================================
# ruido: la resolución de cada estimador
# =============================================================================
ESTIMADORES = (('forma0', 'cazul', '*', 'trapecio $k=64$'),
               ('forma1', 'cnaranja', 'square*', 'trapecio $k=32$'),
               ('forma2', 'cverde', 'triangle*', 'trapecio $k=8$'),
               ('pico', 'cmagenta', 'diamond*', 'pico'))


def fig_ruido(d):
    W, H, G = 6.0, 4.8, 2.3
    xl, yl = (0.4, 200), (0.04, 300)
    pa = Panel(0, 0, W, H, xl, yl, True, True)
    pb = Panel(W + G, 0, W, H, xl, yl, True, True)
    xt = [1, 10, 100]
    yt = [0.1, 1, 10, 100]
    lab_x = '$\\sigma$ del ruido de entrada [ADU]'
    lab_y = '$\\sigma$ de la línea [ADU]'
    pa.ejes(xt, yt, lab_x, lab_y, num, num)
    pb.ejes(xt, yt, lab_x, lab_y, num, num)
    pa.letra('(a) lazo digital')
    pb.letra('(b) canal analógico')
    xs = np.logspace(math.log10(xl[0]), math.log10(xl[1]), 80)
    for p, m, analog in ((pa, d.D, False), (pb, d.A, True)):
        estilo = 'analogico' if analog else 'digital'
        rot = []
        for est, color, marca, _ in ESTIMADORES:
            r = m['meta']['ruido'][est]
            pts = [q for q in r['puntos'] if q['sigma_in'] > 0]
            sx, sy = [q['sigma_in'] for q in pts], [q['sigma'] for q in pts]
            p.marcas(sx, sy, color, marca, lleno=not analog)
            g, s0 = r['ganancia_ruido'], r['sigma_0']
            if est == 'pico':
                # el pico no es lineal (el máximo de varias muestras con ruido): el
                # ajuste no lo describe, así que van los puntos unidos
                p.linea(sx, sy, color, estilo, ancho=0.6)
                rot.append((sy[-1], 'pico', color, marca, not analog))
            else:
                p.linea(xs, np.sqrt((g * xs) ** 2 + s0 ** 2), color, estilo, ancho=0.6)
                rot.append((g * xl[1], f"$g={g:.2f}$", color, marca, not analog))
        rotulos_derecha(p, rot)
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [(c, 'digital', mk, True, t) for _, c, mk, t in ESTIMADORES]
                          + [None, ('black', 'digital', '*', True, 'lazo digital'),
                             ('black', 'analogico', '*', False, 'canal analógico'),
                             ('black', 'digital', 'none', True,
                              'ajuste $\\sigma^2 = (g\\,\\sigma_\\mathrm{ruido})^2 + \\sigma_0^2$')]))
    return "\n".join(cuerpo)


def rotulos_derecha(p, items, sep=0.3):
    """Rótulos a la derecha del marco, a la altura de cada valor, separados al menos
    `sep` cm: los que caerían encima se reparten hacia arriba y hacia abajo."""
    ys = sorted(((p.Y(it[0]),) + tuple(it[1:]) for it in items), key=lambda e: e[0])
    pos = [e[0] for e in ys]
    for _ in range(50):                  # relajación: empujar los pares que se tocan
        cambio = False
        for i in range(1, len(pos)):
            falta = sep - (pos[i] - pos[i - 1])
            if falta > 1e-6:
                pos[i - 1] -= falta / 2
                pos[i] += falta / 2
                cambio = True
        if not cambio:
            break
    for y, (_, t, *mk) in zip(pos, ys):
        marca = ''
        if mk:                           # la marca de la serie, para saber de cuál es
            color, m, lleno = mk
            marca = (f"\\tikz[baseline=-0.6ex]\\draw[{color}, line width=0.6pt] plot[only marks, "
                     f"mark={m}, mark size=1.35pt, mark options={{fill={color if lleno else 'white'}}}] "
                     f"coordinates {{(0,0)}};~")
        p.l.append(f"\\node[directo, anchor=west] at ({f(p.x0 + p.w + 0.05)},{f(y)}) {{{marca}{t}}};")


# =============================================================================
# histéresis
# =============================================================================
HUECA = {'*': 'o', 'square*': 'square', 'triangle*': 'triangle', 'diamond*': 'diamond'}


def fig_histeresis(d):
    W, H, G = 6.3, 4.4, 1.75
    xl, yl = (70, 1.2e6), (-4, 4)
    pa = Panel(0, 0, W, H, xl, yl, True, False)
    pb = Panel(W + G, 0, W, H, xl, yl, True, False)
    xt = [100, 1000, 1e4, 1e5, 1e6]
    fx = {100: '100', 1000: '1 k', 1e4: '10 k', 1e5: '100 k', 1e6: '1 M'}
    for p, t in ((pa, '(a) lazo digital'), (pb, '(b) canal analógico')):
        p.ejes(xt, [-4, -2, 0, 2, 4], 'tasa [pulsos/s]', 'corrimiento del centroide [canales]',
               lambda v: fx[v], num)
        p.letra(t)
        p.horizontal(0, 'black!45', 'solid', 0.5)
    modos = (('fija', 'cazul', '*', 'base fija'), ('seguidor', 'cnaranja', 'square*', 'seguidor de base'))
    for p, m in ((pa, d.D), (pb, d.A)):
        for modo, color, marca, _ in modos:
            filas = d.filas(m, 'histeresis', modo=modo)
            if not filas:
                continue
            ida = sorted((r for r in filas if r['pasada'] == 'ida'), key=lambda r: r['tasa'])
            vta = sorted((r for r in filas if r['pasada'] == 'vuelta'), key=lambda r: r['tasa'])
            c0 = ida[0]['medida']['linea']['centroide']
            p.linea([r['tasa'] for r in ida], [r['medida']['linea']['centroide'] - c0 for r in ida],
                     color, 'digital', ancho=0.6)
            p.marcas([r['tasa'] for r in ida], [r['medida']['linea']['centroide'] - c0 for r in ida],
                     color, marca, True)
            p.marcas([r['tasa'] for r in vta], [r['medida']['linea']['centroide'] - c0 for r in vta],
                     color, HUECA[marca], True)
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'base fija'),
        ('cnaranja', 'digital', 'square*', True, 'seguidor de base'),
        ('black', 'digital', '*', True, 'ida (tasas en subida)'),
        ('black', 'draw=none', 'o', True, 'vuelta (en bajada)')]))
    return "\n".join(cuerpo)


# =============================================================================
# el canal analógico
# =============================================================================
CANALES = (('canal_par2_2026-11-14/par2.npz', 'lazo_ch1', 'excitacion_in2', 'piso_in2',
            'cmagenta', 'diamond*', 'OUT2 $\\to$ IN2 sin carga (cable de $\\sim$4 m)'),
           ('fidelidad_2026-11-14_analogico/canal.npz', 'x', 'y0', 'piso0',
            'cazul', '*', 'OUT1 $\\to$ IN1 con 50 $\\Omega$ (el de las campañas)'))


def fig_canal(d):
    from scipy import signal
    W, H, G = 6.3, 4.6, 1.75
    pa = Panel(0, 0, W, H, (-40, 400), (-0.2, 2.6), False, False)
    pb = Panel(W + G, 0, W, H, (0, 62.5), (0.05, 40), False, True)
    pa.ejes([0, 100, 200, 300, 400], [0, 0.5, 1, 1.5, 2, 2.5], 'tiempo desde el escalón [ns]',
            'salida / escalón', num, lambda v: f"{v:g}")
    pb.ejes([0, 10, 20, 30, 40, 50, 60], [0.1, 1, 10], 'frecuencia [MHz]', '$|H(f)|$', num, num)
    pa.letra('(a) respuesta al escalón')
    pb.letra('(b) transferencia')
    pa.horizontal(1, 'black!45', 'solid', 0.5)
    pb.horizontal(1, 'black!45', 'solid', 0.5)
    i0 = None
    for rel, kx, ky, kp, color, marca, _ in CANALES:
        z = d.npz(rel)
        x, y = z[kx].astype(float), z[ky].astype(float) - z[kp].mean()
        if i0 is None:
            i0 = int(np.flatnonzero((np.abs(x[1:]) > 300) & (np.abs(x[:-1]) < 30))[0]) + 1
            esc = x[i0]
            t = (np.arange(i0 - 5, i0 + 50) - i0) * TS_NS
            pa.linea(t, x[i0 - 5:i0 + 50] / esc, 'cgris', 'digital', ancho=0.7)
            pa.texto(-35, 1.0, 'generador', anchor='south west', dy=0.05, color='black!65')
        t = (np.arange(i0 - 5, i0 + 50) - i0) * TS_NS
        pa.linea(t, y[i0 - 5:i0 + 50] / esc, color, 'analogico', ancho=0.7)
        # 1024 puntos (122 kHz por bin): la posición del pico da el largo del cable
        fr, pxy = signal.csd(x, y, FS, nperseg=1024)
        _, pxx = signal.welch(x, FS, nperseg=1024)
        h = np.abs(pxy / pxx)
        pb.linea(fr / 1e6, h, color, 'analogico', ancho=0.7)
        # las resonancias del cable abierto: el cuarto de onda y su tercer armónico
        picos, _ = signal.find_peaks(h, prominence=0.5)
        for k in (k for k in picos if h[k] > 5):
            # el de frecuencia más baja se rotula a la izquierda, el otro a la derecha
            izq = fr[k] < 20e6
            pb.marcas([fr[k] / 1e6], [h[k]], color, marca, False)
            pb.l.append(f"\\node[directo, align=center, anchor={'south east' if izq else 'south west'}] "
                        f"at ({f(pb.X(fr[k] / 1e6) + (-0.08 if izq else 0.08))},{f(pb.Y(h[k]) + 0.08)}) "
                        f"{{$\\times${h[k]:.0f}\\\\ {fr[k] / 1e6:.1f} MHz}};")
    cuerpo = pa.l + pb.l
    ent = [(c, 'analogico', 'none', True, t) for *_, c, mk, t in CANALES]
    cuerpo.append(leyenda(0, -1.0, [('cgris', 'digital', 'none', True,
                                     'el generador (lazo digital)'), None, ent[0], ent[1]]))
    return "\n".join(cuerpo)


# =============================================================================
# la fidelidad analógica: IN1 contra el modelo
# =============================================================================
def fig_fidelidad(d):
    z = d.npz('fidelidad_2026-11-14_analogico/canal.npz')
    canal = CA.caracterizar(z['x'], z['y0'], z['y1'], z['piso0'], z['piso1'])
    b = d.npz('fidelidad_2026-11-14_analogico/bram_2.npz')          # el caso Poisson
    x, y = b['buf'].astype(float), b['y0'].astype(float)
    pred = CA.predecir_canal(x, canal)
    q = CA.residuo(y, pred, canal['ruido'])
    r = y - pred
    # una ventana con varios pulsos: la de más energía entre las de 3 µs
    n = 375
    e = np.convolve(np.abs(np.diff(x, prepend=0)), np.ones(n), 'valid')
    i0 = int(np.argmax(e[4000:7000])) + 4000
    sl = slice(i0, i0 + n)
    t = np.arange(n) * TS_NS / 1e3
    W, H1, H2, G = 13.0, 3.6, 2.2, 0.6
    ymin, ymax = np.floor(min(y[sl].min(), pred[sl].min()) / 1000) * 1000, \
        np.ceil(max(y[sl].max(), pred[sl].max()) / 1000) * 1000
    pa = Panel(0, H2 + G, W, H1, (0, t[-1]), (ymin, ymax))
    lim = 1.15 * (q['umbral'] + CA.TOL_ALINEAL * np.abs(pred[sl]).max())
    rr = float(np.ceil(lim / 50) * 50)
    pb = Panel(0, 0, W, H2, (0, t[-1]), (-rr, rr))
    pa.ejes(np.arange(0, t[-1] + 1e-9, 0.5), np.arange(ymin, ymax + 1, 1000), '',
            'IN1 [ADU]', lambda v: '', lambda v: num(v))
    pb.ejes(np.arange(0, t[-1] + 1e-9, 0.5), [-rr, 0, rr], 'tiempo [$\\mu$s]',
            'residuo [ADU]', lambda v: f"{v:g}", num)
    pa.letra('(a)')
    pb.letra('(b)')
    # el umbral de un error de captura: alrededor de la mediana, crece con la señal
    lim_t = q['umbral'] + CA.TOL_ALINEAL * np.abs(pred[sl])
    med = float(np.median(r))
    arriba = " ".join(f"({f(pb.X(a))},{f(pb.Y(min(med + c, rr)))})" for a, c in zip(t, lim_t))
    abajo = " ".join(f"({f(pb.X(a))},{f(pb.Y(max(med - c, -rr)))})" for a, c in zip(t[::-1], lim_t[::-1]))
    pb.l.insert(0, f"\\fill[grisr!80] {arriba.replace(') (', ') -- (')} -- "
                   f"{abajo.replace(') (', ') -- (')} -- cycle;")
    pa.linea(t, pred[sl], 'black!70', 'digital', ancho=0.6)
    pa.marcas(t[::3], y[sl][::3], 'cazul', '*', True)
    pb.linea(t, r[sl], 'cazul', 'digital', ancho=0.6)
    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'draw=none', '*', True, 'IN1 medido (una muestra de cada tres)'),
        ('black!70', 'digital', 'none', True, 'modelo del canal aplicado al generador'),
        ('cazul', 'digital', 'none', True, 'residuo'),
        ('grisr', 'line width=4pt', 'none', True, 'umbral de un error de captura')], ancho=13.0))
    return "\n".join(cuerpo), q


# =============================================================================
# las etapas del 2026-11-16: forma, apilamiento, dnl, psd, polo_cero, ventana_ciega
# =============================================================================
def _rm():
    """run_meritos_pulsos, para los análisis (se importa sólo para estas figuras)."""
    import run_meritos_pulsos as RM
    return RM


def _tasa_txt(t):
    return f"{t / 1e6:g} M/s" if t >= 1e6 else f"{t / 1e3:g} k/s"


TASAS_FORMA = ((30000.0, 'cazul', '*'), (100000.0, 'cnaranja', 'square*'),
               (300000.0, 'cverde', 'triangle*'), (1e6, 'cmagenta', 'diamond*'))


def fig_forma(d):
    W, H, G = 4.55, 4.0, 1.15
    # el canal analógico llega a FWHM de 7 % y a FWHM/ε² de 100: arriba se recorta
    pa = Panel(0, 0, W, H, (6, 700), (0.1, 10), True, True)
    pb = Panel(W + G, 0, W, H, (0.004, 5), (0, 1.05), True, False)
    pc = Panel(2 * (W + G), 0, W, H, (0.004, 5), (0.001, 10), True, True)
    gx = lambda v: f"{v:g}"
    pa.ejes([8, 32, 128, 512], [0.1, 0.2, 0.5, 1, 2, 5, 10], 'subida $k$ de la forma [muestras]',
            'FWHM [\\% de la línea]', num, gx)
    pb.ejes([0.01, 0.1, 1], [0, 0.5, 1], 'ocupación $\\rho$', 'eficiencia $\\varepsilon$', gx, gx,
            ylabel_dx=0.65)
    pc.ejes([0.01, 0.1, 1], [0.001, 0.01, 0.1, 1, 10], 'ocupación $\\rho$',
            'FWHM$/\\varepsilon^2$', gx, gx, ylabel_dx=0.85)
    pa.letra('(a)')
    pb.letra('(b)')
    pc.letra('(c)')
    rr = np.logspace(math.log10(0.004), math.log10(5), 80)
    pb.linea(rr, np.exp(-rr), 'black!45', 'densely dotted')
    pb.texto(0.02, math.exp(-0.02), '$e^{-\\rho}$', anchor='north east', dy=-0.12, color='black!60')
    pc.vertical(0.25)
    pc.texto(0.25, 10, '$\\rho = 1/4$', anchor='north west', dx=0.04, dy=-0.04, color='black!60')
    for m, analog in d.modos2('forma'):
        ref = m['referencias']
        ks = sorted(int(k.split('/')[1]) for k in ref if k.startswith('forma/'))
        pa.serie(ks, [100 * ref[f'forma/{k}']['fwhm_rel'] for k in ks], 'black', 'star', analog)
        for tasa, color, marca in TASAS_FORMA:
            q = m['meta']['forma'].get(str(tasa))
            if not q:
                continue
            pa.serie(q['ks'], [100 * v for v in q['fwhm_rel']], color, marca, analog)
            pb.serie(q['rho'], q['eps'], color, marca, analog)
            pc.serie(q['rho'], q['T'], color, marca, analog)
    cuerpo = pa.l + pb.l + pc.l
    ent = [('black', 'digital', 'star', True, 'pulsos aislados')]
    ent += [(c, 'digital', mk, True, _tasa_txt(t)) for t, c, mk in TASAS_FORMA]
    ent += [None, ('black', 'digital', '*', True, 'lazo digital')]
    if d.A2 is not None:
        ent.append(('black', 'analogico', '*', False, 'canal analógico'))
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)


CORTES_APIL = (('sin', 'black', 'pentagon*', 'sin corte'),
               ('solape', 'cmagenta', 'diamond*', 'solape = 0'),
               ('dt_anterior', 'cazul', '*', '$\\Delta t$ al anterior $\\geq$ 50 a 800 ciclos'),
               ('t_subida', 'cnaranja', 'square*', '$t_{\\mathrm{subida}}$ en el intervalo de los aislados'),
               ('ancho_inv', 'cverde', 'triangle*', 'ancho inverso en el intervalo de los aislados'))
PISO_FONDO = 0.007        # [%]: un fondo de 0 se dibuja en el borde de abajo


def fig_apilamiento(d):
    W, H, GX, GY = 4.3, 3.2, 0.55, 0.95
    tasas = (1e5, 3e5, 1e6)
    fuentes = (('pz', 'polo-cero'), ('pendiente', 'pendiente'))
    gx = lambda v: f"{v:g}"
    nada = lambda v: ''
    cuerpo = []
    for i, (fuente, nombre) in enumerate(fuentes):
        y0 = (1 - i) * (H + GY)
        for j, tasa in enumerate(tasas):
            p = Panel(j * (W + GX), y0, W, H, (0, 100), (0.005, 30), False, True)
            p.ejes([0, 25, 50, 75, 100], [0.01, 0.1, 1, 10],
                   '$\\varepsilon$ [\\%]' if i == 1 else '', 'fondo [\\%]' if j == 0 else '',
                   num if i == 1 else nada, gx if j == 0 else nada)
            p.letra(f"({'abcdef'[3 * i + j]}) {nombre}, {_tasa_txt(tasa)}")
            for m, analog in d.modos2('apilamiento'):
                filas = [r for r in m['filas'] if r['etapa'] == 'apilamiento'
                         and r['fuente'] == fuente and r['tasa'] == tasa]
                for corte, color, marca, _ in CORTES_APIL:
                    fs = sorted((r for r in filas if r['corte'] == corte),
                                key=lambda r: r['umbral'] or 0)
                    x = [100 * r['meritos']['eps'] for r in fs]
                    y = [max(100 * r['meritos']['fondo'], PISO_FONDO) for r in fs]
                    p.serie(x, y, color, marca, analog, con_linea=len(fs) > 1)
            cuerpo += p.l
    ent = [(c, 'digital', mk, True, t) for _, c, mk, t in CORTES_APIL]
    ent.insert(3, None)
    ent += [None, ('black', 'digital', '*', True, 'lazo digital')]
    if d.A2 is not None:
        ent.append(('black', 'analogico', '*', False, 'canal analógico'))
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)


RANGO_DNL = (500, 6000)   # la tabla de la etapa dnl (--rango-dnl por defecto)


def _dnl(h, c0, c1):
    """La DNL como en analizar_dnl: h/ĥ − 1 con ĥ un polinomio de grado 3."""
    c = np.arange(c0, c1 + 1)
    x = (c - c.mean()) / np.ptp(c)
    ajuste = np.polyval(np.polyfit(x, h[c], 3), x)
    return c, h[c] / ajuste - 1.0, ajuste


def _dnl_tabla(h, c, lo, hi):
    """La DNL que deja la tabla de la etapa: 1024 alturas de lo a hi redondeadas a
    enteros (pasos de 5 y 6 ADU), cada una ensanchada por un dither gaussiano. Ajusta la
    ganancia, el offset y el σ del dither a la DNL medida; devuelve (dnl, (g, o, σ))."""
    from scipy.optimize import minimize
    from scipy.special import erf
    tabla = np.round(np.linspace(float(lo), float(hi), 1024))
    bordes = np.arange(c[0], c[-1] + 2) - 0.5
    x = (c - c.mean()) / np.ptp(c)
    medida = _dnl(h, c[0], c[-1])[1]

    def modelo(p):
        g, o, s = p
        cdf = 0.5 * (1 + erf((bordes[None, :] - (tabla * g + o)[:, None])
                             / (math.sqrt(2) * abs(s) * g)))
        y = np.diff(cdf, axis=1).sum(0)
        return y / np.polyval(np.polyfit(x, y, 3), x) - 1.0

    nivel = np.median(h[h > 0.2 * h.max()])
    sobre = np.flatnonzero(h >= 0.5 * nivel)
    g0 = (sobre[-1] - sobre[0]) / float(hi - lo)
    o0 = sobre[0] - lo * g0
    costo = lambda p: float(np.sum((medida - modelo(p)) ** 2))
    p0 = min(((g0 * (1 + dg), o0 + do, s) for s in (3, 4, 5, 6)
              for dg in np.linspace(-0.002, 0.002, 9) for do in (-1, 0, 1)), key=costo)
    r = minimize(costo, p0, method='Nelder-Mead', options=dict(xatol=1e-6, fatol=1e-9,
                                                               maxiter=800))
    return modelo(r.x), tuple(float(v) for v in r.x)


def fig_dnl(d):
    """Sólo el carácter periódico: 160 canales del trapecio de la primera corrida (lazo
    digital, tabla de 500 a 6000 ADU en pasos de 5 y 6) y la DNL que deja la tabla. Los
    valores de todas las corridas van en una tabla en el documento (§2.14)."""
    W, H = 13.0, 3.2
    q = d.D2['meta']['dnl']['trapecio']
    h = np.zeros(1 << d.D2['meta']['h_aw'])
    for k, v in q['hist'].items():
        h[int(k)] = v
    c, dnl, aj = _dnl(h, *q['canales'])
    mod, par = _dnl_tabla(h, c, *RANGO_DNL)
    info = dict(sigma=par[2], rms_modelo=float(mod.std()), resto=float((dnl - mod).std()),
                poisson=float(math.sqrt(np.mean(1 / aj))), rms=float(dnl.std()))
    a0 = int(c[c.size // 2])
    sel = (c >= a0) & (c < a0 + 160)
    p = Panel(0, 0, W, H, (a0, a0 + 160), (-9, 9))
    p.ejes(list(range(a0 - a0 % 20 + 20, a0 + 161, 20)), [-8, -4, 0, 4, 8], 'canal',
           'DNL [\\%]', num, num)
    p.horizontal(0, 'black!45', 'solid', 0.5)
    p.linea(c[sel], 100 * mod[sel], 'black!70', 'digital', ancho=0.6)
    p.serie(c[sel], 100 * dnl[sel], 'cazul', '*')
    cuerpo = p.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cazul', 'digital', '*', True, 'la DNL medida'),
        ('black!70', 'digital', 'none', True,
         'la DNL de la tabla redondeada, con dither de $\\sigma$ = '
         f"{info['sigma']:.1f} ADU")], ancho=13.0))
    return "\n".join(cuerpo), info


def fig_psd(d):
    W, H, G = 4.55, 4.0, 1.05
    RM = _rm()
    gx = lambda v: f"{v:g}"
    # el canal analógico corre las dos PSD a 0.91-0.94
    pa = Panel(0, 0, W, H, (0.845, 0.945), (0, 1.08))
    pb = Panel(W + G, 0, W, H, (0.845, 0.945), (0, 1.08))
    pc = Panel(2 * (W + G), 0, W, H, (35, 5000), (0.3, 100), True, True)
    xt = [0.86, 0.88, 0.90, 0.92, 0.94]
    pa.ejes(xt, [0, 0.5, 1], 'PSD = $Q_{\\mathrm{cola}}/Q$', 'cuentas (relativas)',
            lambda v: f"{v:.2f}", gx, ylabel_dx=0.65)
    pb.ejes(xt, [0, 0.5, 1], 'PSD = $Q_{\\mathrm{cola}}/Q$', '', lambda v: f"{v:.2f}", gx)
    pc.ejes([50, 100, 200, 500, 1000, 2000, 5000], [0.5, 1, 2, 5, 10, 20, 50],
            'amplitud [ADU]', 'FOM', num, gx, ylabel_dx=0.65)
    pc.horizontal(1.27)
    pc.texto(4500, 1.27, 'FOM = 1.27', anchor='south east', dy=0.02, color='black!60')
    taus = ((200.0, 'cazul', '*', '$\\tau$ = 200'), (250.0, 'cnaranja', 'square*', '$\\tau$ = 250'))
    for p, amp in ((pa, 100), (pb, 1000)):
        p.letra(f'(a) {amp} ADU' if p is pa else f'(b) {amp} ADU')
        for m, analog in d.modos2('psd'):
            h_aw = m['meta']['h_aw']
            for tau, color, marca, _ in taus:
                r = next((r for r in m['filas'] if r['etapa'] == 'psd'
                          and r['tau'] == tau and r['amplitud'] == amp), None)
                if r is None:
                    continue
                c = corrida(r, 'psd')
                # de a 4 canales, para que se vea la forma con 4000 pulsos
                k = np.array(sorted(int(k) for k in c['hist']))
                k0 = k.min() - k.min() % 4
                n = np.bincount((k - k0) // 4, [c['hist'][str(v)] for v in k]).astype(float)
                x = RM.valor_de_canal(k0 + 4 * np.arange(n.size) + 1.5, h_aw, *c['zoom']) / 65536.0
                p.linea(x, n / n.max(), color, 'analogico' if analog else 'digital', ancho=0.7)
    pc.letra('(c)')
    for m, analog in d.modos2('psd'):
        q = m['meta']['psd']
        amps = sorted(int(a) for a in q)
        pc.serie(amps, [q[str(a)]['fom'] for a in amps], 'black', '*', analog)
    cuerpo = pa.l + pb.l + pc.l
    ent = [(c, 'digital', 'none', True, t) for _, c, _, t in taus]
    ent += [None, ('black', 'digital', '*', True, 'lazo digital')]
    if d.A2 is not None:
        ent.append(('black', 'analogico', '*', False, 'canal analógico'))
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)


DTS_PZ = ((100, 'r1', '*'), (200, 'r2', 'square*'), (400, 'r3', 'triangle*'))


def fig_polo_cero(d):
    W, H, G = 6.3, 4.4, 1.75
    RM = _rm()
    pa = Panel(0, 0, W, H, (-10.8, 10.8), (-6.5, 6.5))
    pb = Panel(W + G, 0, W, H, (80, 420), (0.1, 0.8), False, True)
    pa.ejes([-10, -5, 0, 5, 10], [-6, -3, 0, 3, 6], '$\\Delta M$ [\\%]',
            'error de la amplitud [\\%]', num, num)
    pb.ejes([100, 200, 300, 400], [0.1, 0.2, 0.5], '$\\Delta t$ [ciclos]',
            '$|$pendiente$|$ cerca de $\\Delta M = 0$', num, lambda v: f"{v:g}")
    pa.letra('(a)')
    pb.letra('(b)')
    pa.horizontal(0, 'black!45', 'solid', 0.5)
    pa.vertical(0, 'black!45', 'solid', 0.5)
    info = {}
    for m, analog in d.modos2('polo_cero'):
        an = RM.analizar_polo_cero([r for r in m['filas'] if r['etapa'] == 'polo_cero'])
        info[analog] = an
        for dt, color, marca in DTS_PZ:
            q = an.get(str(dt))
            if not q:
                continue
            pa.serie([100 * v for v in q['dm']], [100 * v for v in q['err_a2']], color, marca, analog)
        q = an[str(DTS_PZ[0][0])]
        pa.serie([100 * v for v in q['dm']], [100 * v for v in q['err_a1']], 'black', 'star', analog)
        dts = [dt for dt, *_ in DTS_PZ if str(dt) in an]
        ps = [abs(an[str(dt)]['pendiente']) for dt in dts]
        pb.serie(dts, ps, 'black', '*', analog)
        tau = m['meta']['args'].get('tau', 250.0) if isinstance(m['meta'].get('args'), dict) else 250.0
        xx = np.linspace(80, 420, 50)
        pb.linea(xx, ps[0] * np.exp(-(xx - dts[0]) / tau), 'black!45', 'densely dotted')
    pb.texto(260, 0.45, '$\\propto e^{-\\Delta t/\\tau}$', anchor='south west', color='black!60')
    cuerpo = pa.l + pb.l
    ent = [(c, 'digital', mk, True, f'A2 con $\\Delta t$ = {dt}') for dt, c, mk in DTS_PZ]
    ent += [('black', 'digital', 'star', True, 'A1'), None,
            ('black', 'digital', '*', True, 'lazo digital')]
    if d.A2 is not None:
        ent.append(('black', 'analogico', '*', False, 'canal analógico'))
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo), info


def fig_polo_cero_canal(d):
    """Cuánto hay que correr M en el canal analógico, en la placa y en la réplica con el
    canal medido, con y sin los polos lentos (datos/sim_polo_cero_canal)."""
    W, H, G = 6.3, 4.4, 1.75
    RM = _rm()
    pc = Panel(0, 0, W, H, (60, 900), (-17, 2), True, False)
    pd = Panel(W + G, 0, W, H, (40, 2000), (-1.6, 0.2), True, False)
    pc.ejes([100, 200, 400, 800], [-15, -10, -5, 0], '$\\Delta t$ [ciclos]',
            '$\\Delta M$ que anula el error de A2 [\\%]', num, num, ylabel_dx=0.65)
    pd.ejes([50, 100, 200, 400, 800, 1600], [-1.5, -1, -0.5, 0], '$\\Delta t$ [ciclos]',
            'error de A2 con $\\Delta M = 0$ [\\%]', num, lambda v: f"{v:g}", ylabel_dx=0.75)
    pc.letra('(a)')
    pd.letra('(b)')
    for p_ in (pc, pd):
        p_.horizontal(0, 'black!45', 'solid', 0.5)
    curvas = [(m, an, 'black', '*') for m, an in d.modos2('polo_cero')]
    for sub, color, marca in (('con_lentos', 'cmagenta', 'diamond*'),
                              ('sin_lentos', 'cgris', 'triangle*')):
        filas = []
        for x in ([sub, sub + '_ext'] if sub == 'con_lentos' else [sub]):
            mm = d._json_o(f'sim_polo_cero_canal/{x}/meritos.json')
            if mm is not None:
                filas += [r for r in mm['filas'] if r['etapa'] == 'polo_cero']
        if filas:
            curvas.append(({'filas': filas}, True, color, marca))
    for m, analog, color, marca in curvas:
        an = RM.analizar_polo_cero([r for r in m['filas'] if r['etapa'] == 'polo_cero'])
        dts = sorted(int(k) for k in an)
        e0 = [100 * dict(zip(an[str(t)]['dm'], an[str(t)]['err_a2']))[0.0] for t in dts]
        # el cero sólo donde el error cruza en el rango de ΔM (no en Δt = 50 ni 1600)
        cz = [(t, 100 * an[str(t)]['dm_cero']) for t in dts
              if min(an[str(t)]['err_a2']) < 0 < max(an[str(t)]['err_a2'])]
        pc.serie([t for t, _ in cz], [v for _, v in cz], color, marca, analog and color == 'black')
        pd.serie(dts, e0, color, marca, analog and color == 'black')
    cuerpo = pc.l + pd.l
    ent = [('black', 'digital', '*', True, 'lazo digital')]
    if d.A2 is not None:
        ent.append(('black', 'analogico', '*', False, 'canal analógico'))
    ent += [None, ('cmagenta', 'digital', 'diamond*', True, 'réplica con el canal medido'),
            ('cgris', 'digital', 'triangle*', True, 'réplica sin los polos lentos')]
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)


SERIES_CIEGA = (('disparos', 'cgris', 'diamond*', 'disparos por par'),
                ('sin', 'cazul', '*', 'apilados aceptados, sin corte'),
                ('t_subida', 'cnaranja', 'square*', 'con el corte por $t_{\\mathrm{subida}}$'),
                ('ancho_inv', 'cverde', 'triangle*', 'con el corte por ancho inverso'))


def _ciega(d, m, analog, subida, fuente, corte):
    """Las filas de la ventana ciega de un corte (umbral 0.9), por Δt: las del
    2026-11-16 hasta 48 y las del 2026-11-17 más allá."""
    def de(mm):
        if mm is None:
            return {}
        return {f['dt']: f for f in mm['filas'] if f['etapa'] == 'ventana_ciega'
                and f['subida'] == subida and f['fuente'] == fuente and f['corte'] == corte
                and f['umbral'] in (None, 0.9)}
    filas = de(d.C2[analog])
    filas.update(de(m))
    return [filas[k] for k in sorted(filas)]


def fig_ventana_ciega(d):
    W, H, HL, GX, GY, GL = 6.6, 2.6, 1.9, 0.4, 0.95, 0.35
    gx = lambda v: f"{v:g}"
    nada = lambda v: ''
    cuerpo = []
    alto = H + GL + HL + GY
    xl, xt = (2, 600), [2, 4, 8, 16, 32, 64, 128, 256, 512]
    for i, subida in enumerate((0, 2)):
        y0 = (1 - i) * alto + HL + GL
        fuentes = (('pz', 'polo-cero'), ('pendiente', 'pendiente'))
        por = {fu: [(m, an, {c: _ciega(d, m, an, subida, fu, c)
                             for c in ('sin', 't_subida', 'ancho_inv')})
                    for m, an in d.modos2('ventana_ciega')] for fu, _ in fuentes}
        # la misma escala en los dos paneles de la fila (el de la derecha no la rotula)
        ymax = max([2.0] + [f['meritos']['disparos_par'] for v in por.values()
                            for _, _, q in v for f in q['sin']])
        ytop = 2.15 if ymax <= 2.1 else math.ceil(ymax) + 0.15
        for j, (fuente, nombre) in enumerate(fuentes):
            datos = por[fuente]
            p = Panel(j * (W + GX), y0, W, H, xl, (-0.08, ytop), True, False)
            p.ejes(xt, list(range(0, int(ytop) + 1)), '', 'por par' if j == 0 else '',
                   nada, gx if j == 0 else nada)
            p.letra(f"({'abcd'[2 * i + j]}) {nombre}, subida {subida}")
            pl = Panel(j * (W + GX), y0 - GL - HL, W, HL, xl, (-0.05, 1.08), True, False)
            pl.ejes(xt, [0, 0.5, 1], '$\\Delta t$ [ciclos]' if i == 1 else '',
                    'en su línea' if j == 0 else '', num if i == 1 else nada,
                    gx if j == 0 else nada)
            for m, analog, q in datos:
                for que, color, marca, _ in SERIES_CIEGA:
                    fs = q['sin' if que == 'disparos' else que]
                    if not fs:
                        continue
                    x = [f['dt'] for f in fs]
                    if que == 'disparos':
                        p.serie(x, [f['meritos']['disparos_par'] for f in fs], color, marca, analog)
                        continue
                    p.serie(x, [f['meritos']['apilado_aceptado'] for f in fs], color, marca, analog)
                    pl.serie(x, [(f['meritos']['a1'] + f['meritos']['a2']) / 2 for f in fs],
                             color, marca, analog)
            cuerpo += p.l + pl.l
    ent = [(c, 'digital', mk, True, t) for _, c, mk, t in SERIES_CIEGA]
    ent.insert(2, None)
    ent += [None, ('black', 'digital', '*', True, 'lazo digital')]
    if d.A2 is not None:
        ent.append(('black', 'analogico', '*', False, 'canal analógico'))
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)



# =============================================================================
# base dinámica y deriva
# =============================================================================
BASES = (('fija', 'cgris', 'diamond*', 'base fija'),
         ('seguidor', 'cnaranja', 'triangle*', 'seguidor de base'),
         ('dinamica', 'cazul', '*', 'base dinámica'))


def _en_linea(m, n_acc):
    filas = sorted(Datos.filas(m, 'tasa', fuente='asg', n_acc=n_acc), key=lambda r: r['tasa'])
    me = [corrida(r, 'trapecio')['meritos'] for r in filas]
    return [q['n_in_hz'] / 1e3 for q in me], [q['buenos_hz'] / 1e3 for q in me]


def _delta_b(m):
    """Δb de la ley, el último paso de cada corrida (asg, n_acc = 3)."""
    out = []
    for r in sorted(Datos.filas(m, 'tasa', fuente='asg', n_acc=3), key=lambda r: r['tasa']):
        c = corrida(r, 'trapecio')
        out.append((c['meritos']['n_in_hz'] / 1e3, c['base_dinamica']['final']['delta_b']))
    return np.array(out)


def fig_base_dinamica(d):
    W, H, G = 4.4, 4.0, 1.25
    xl, xt = (8, 4000), [10, 100, 1000]
    pa = Panel(0, 0, W, H, xl, (8, 2000), True, True)
    pb = Panel(W + G, 0, W, H, xl, (-36, 16), True, False)
    pc = Panel(2 * (W + G), 0, W, H, xl, (-450, 10), True, False)
    pa.ejes(xt, [10, 100, 1000], 'tasa de entrada [k/s]', 'en su línea [k/s]', num, num)
    pb.ejes(xt, [-30, -20, -10, 0, 10], 'tasa de entrada [k/s]',
            'corrimiento de la línea [canales]', num, num)
    pc.ejes(xt, [-400, -300, -200, -100, 0], 'tasa de entrada [k/s]',
            '$\\Delta b$ de la ley [ADU]', num, num, ylabel_dx=0.85)
    pa.letra('(a)')
    pb.letra('(b) línea de 1300 ADU')
    pc.letra('(c)')
    pa.linea([8, 4000], [8, 4000], 'black!35', 'densely dotted')
    pb.horizontal(0, 'black!45', 'solid', 0.5)
    pc.horizontal(0, 'black!45', 'solid', 0.5)
    for n_acc, marca in ((1, '*'), (3, 'square*')):
        x, y = _en_linea(d.D, n_acc)
        pa.serie(x, y, 'black', marca)
    modos = (('fija', d.A), ('seguidor', d.Aseg), ('dinamica', d.Adin))
    for que, m in modos:
        if m is None:
            continue
        color, marca = next((c, mk) for q, c, mk, _ in BASES if q == que)
        for n_acc, mk in ((1, '*'), (3, 'square*')):
            x, y = _en_linea(m, n_acc)
            pa.serie(x, y, color, mk, True)
        c, _ = _corrimientos(m)
        pb.serie(c[:, 0], c[:, 2], color, marca, True)
    if d.Adin is not None:
        db = _delta_b(d.Adin)
        pc.serie(db[:, 0], db[:, 1], 'cazul', '*', True)
    cuerpo = pa.l + pb.l + pc.l
    ent = [(c, 'analogico', mk, False, t) for _, c, mk, t in BASES]
    ent += [None, ('black', 'digital', '*', True, 'lazo digital'),
            ('black', 'digital', '*', True, '$n_{\\mathrm{acc}} = 1$ (en a)'),
            ('black', 'digital', 'square*', True, '$n_{\\mathrm{acc}} = 3$')]
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)


def fig_deriva(d):
    q = d.Der['meta']['deriva']
    W, H, GX, GY = 6.4, 3.0, 1.3, 1.05
    t = np.array(q['t_h'])
    T = np.array([np.nan if v is None else v for v in q['temp_serie']], float)
    gx = lambda v: f"{v:g}"
    # todo respecto de la media de las 2 h
    pa = Panel(0, H + GY, W, H, (0, 2), (-0.8, 0.8), False, False)
    pb = Panel(W + GX, H + GY, W, H, (0, 2), (-140, 140), False, False)
    pc = Panel(0, 0, W, H, (0, 2), (41.6, 43.4), False, False)
    pd = Panel(W + GX, 0, W, H, (41.6, 43.4), (-140, 140), False, False)
    pa.ejes([0, 0.5, 1, 1.5, 2], [-0.5, 0, 0.5], '', 'desplazamiento [ADU]', lambda v: '', gx)
    pb.ejes([0, 0.5, 1, 1.5, 2], [-100, -50, 0, 50, 100], '', 'ganancia [ppm]',
            lambda v: '', num, ylabel_dx=0.85)
    pc.ejes([0, 0.5, 1, 1.5, 2], [42, 43], 'tiempo [h]', 'temperatura [°C]', gx, gx)
    pd.ejes([42, 42.5, 43], [-100, -50, 0, 50, 100], 'temperatura [°C]', 'ganancia [ppm]',
            gx, num, ylabel_dx=0.85)
    pa.letra('(a)')
    pb.letra('(b)')
    pc.letra('(c) temperatura del FPGA')
    pd.letra('(d)')
    a1, a2 = q['amplitudes']
    for k, color, marca, rot in (('linea1', 'cazul', '*', f'línea de {a1} ADU'),
                                 ('linea2', 'cnaranja', 'square*', f'línea de {a2} ADU'),
                                 ('offset', 'cgris', 'diamond*', 'offset')):
        y = np.array(q[k]['serie'])
        pa.serie(t, y - y.mean(), color, marca, True)
    g = np.array(q['ganancia_ppm']['serie'])
    g = g - g.mean()
    pb.serie(t, g, 'cazul', '*', True)
    pc.serie(t, T, 'black', '*', True)
    pd.marcas(T, g, 'cazul', '*', lleno=False)
    if 'por_grado' in q['ganancia_ppm']:
        k = q['ganancia_ppm']['por_grado']
        ok = np.isfinite(T)
        b = float(np.mean(g[ok]) - k * np.mean(T[ok]))
        tt = np.array([41.7, 43.3])
        pd.linea(tt, k * tt + b, 'black!60', 'densely dashed', ancho=0.6)
        pd.texto(43.35, 140, f"{k:.0f} ppm/°C (r = {q['ganancia_ppm']['corr_temp']:.2f})",
                 anchor='north east', dy=-0.05, color='black!60')
    cuerpo = pa.l + pb.l + pc.l + pd.l
    ent = [('cazul', 'analogico', '*', False, f'línea de {a1} ADU (en a) y la ganancia'),
           ('cnaranja', 'analogico', 'square*', False, f'línea de {a2} ADU'),
           ('cgris', 'analogico', 'diamond*', False, 'offset')]
    cuerpo.append(leyenda(0, -1.0, ent))
    return "\n".join(cuerpo)


# =============================================================================
# throughput de los dos caminos: el MCA (el espectro en la FPGA) y el osciloscopio
# (las formas por el event_ring)
# =============================================================================
# el destino de cada etapa del ring, en el orden de la leyenda
ETAPAS_RING = (('A', 'black', '*', 'OSC $\\to$ DDR'),
               ('B', 'cmagenta', 'diamond*', 'OSC $\\to$ lector de C del ring'),
               ('D', 'cazul', 'square*', 'OSC $\\to$ PC por la red'),
               ('C', 'cnaranja', 'triangle*', 'OSC $\\to$ SD de la placa'))
TCP_MB_S = 50.38        # make bench-tcp-placa, 2026-11-17 (1 GiB en 21.3 s)
# 16 + 998 no va en (b): cae a 10 muestras de 32 + 992 pero su slot es de 4 KB y no de
# 8 KB, así que el writer pasa más (59 contra 49 k/s) y la curva haría un escalón
SIN_B = (1014,)
# la BRAM, con sus dos lectores (run_techo_bram.py): el lazo de C y el original de Python
BRAM = (('c', 'cgris', 'square*', 'lector de C', 'BRAM, C'),
        ('python', 'black!45', 'diamond*', 'librp desde Python, el camino original',
         'BRAM, Python'))


def _bram(d, etapa, lector):
    """(x, eventos leídos por segundo en k/s) de la BRAM: contra la tasa de entrada en
    k/s (tasa) o contra las muestras de la ventana (techo)."""
    pts = [q for q in d.Bram['puntos'] if q['etapa'] == etapa and q['lector'] == lector]
    pts.sort(key=lambda q: q['tasa_in'] if etapa == 'tasa' else q['muestras'])
    return ([q['tasa_in'] / 1e3 if etapa == 'tasa' else q['muestras'] for q in pts],
            [q['tasa_out'] / 1e3 for q in pts])


def _bytes_ev(muestras):
    """Bytes por evento del slot sin el relleno: 32 de cabecera y 2 por muestra y canal."""
    return 32 + 4 * muestras


def _techos_ring(d):
    """{etapa: {muestras: (mediana, mín, máx)}} de lo que pasa por cada etapa con el ring
    saturado, en ev/s. A y B: lo que lee la etapa en los puntos saturados (el máximo,
    como el resumen de run_etapas_ring); D: la mediana de los puntos con DROP_FULL, en
    los dos modos, con su rango (como bench_sd_red); C: el punto largo, con el sync."""
    from run_etapas_ring import saturado
    out = {'A': {}, 'B': {}, 'D': {}, 'C': {}}
    for e in ('A', 'B'):
        for m in sorted({p['muestras'] for p in d.RingAB['puntos']}):
            v = [p['tasa_consumo'] for p in d.RingAB['puntos']
                 if p['etapa'] == e and p['muestras'] == m and saturado(p)]
            out[e][m] = (max(v),) * 3
    pts = [p for j in d.RingD if j for p in j['puntos'] if p['etapa'] == 'D']
    for m in sorted({p['muestras'] for p in pts}):
        v = [p['tasa_consumo'] for p in pts if p['muestras'] == m and p['drop_full'] > 0]
        out['D'][m] = (float(np.median(v)), min(v), max(v))
    for j in d.RingC:
        if j:
            p = j['puntos'][0]
            out['C'][p['muestras']] = (p['tasa_con_sync'],) * 3
    return out


def _captura_ring(d, muestras, modo='aleatorio'):
    """(tasa de entrada, eventos que la etapa A pone en la DDR por segundo de
    estímulo), en k/s."""
    pts = sorted((p for p in d.RingAB['puntos'] if p['etapa'] == 'A'
                  and p['muestras'] == muestras and p['modo'] == modo),
                 key=lambda p: p['tasa'])
    return ([p['tasa'] / 1e3 for p in pts],
            [p['ev_cnt'] * p['tasa'] / p['gen_cnt'] / 1e3 for p in pts])


def _consumo_ring(d, etapa, muestras, modo='aleatorio'):
    """(tasa de entrada, eventos que consume la etapa por segundo), en k/s."""
    pts = sorted((p for p in d.RingAB['puntos'] if p['etapa'] == etapa
                  and p['muestras'] == muestras and p['modo'] == modo),
                 key=lambda p: p['tasa'])
    return [p['tasa'] / 1e3 for p in pts], [p['tasa_consumo'] / 1e3 for p in pts]


def _hasta_techo(xs, ys, techo):
    """La curva min(y, techo), con el cruce interpolado en log-log."""
    ox, oy = [], []
    for i, (x, y) in enumerate(zip(xs, ys)):
        if i and (ys[i - 1] - techo) * (y - techo) < 0:
            lx0, lx1 = math.log10(xs[i - 1]), math.log10(x)
            ly0, ly1 = math.log10(ys[i - 1]), math.log10(y)
            t = (math.log10(techo) - ly0) / (ly1 - ly0)
            ox.append(10 ** (lx0 + t * (lx1 - lx0)))
            oy.append(techo)
        ox.append(x)
        oy.append(min(y, techo))
    return ox, oy


def fig_throughput_caminos(d):
    W, H, G = 6.1, 4.6, 3.1
    T = _techos_ring(d)
    V = 32                                       # (a): la ventana de 8 + 24 muestras
    pa = Panel(0, 0, W, H, (0.3, 4000), (0.3, 4000), True, True)
    pb = Panel(W + G, 0, W, H, (24, 1400), (0.6, 4000), True, True)
    t = [1, 10, 100, 1000]
    pa.ejes(t, t, 'tasa de entrada [k/s]', 'eventos registrados [k/s]', num, num)
    pb.ejes([32, 64, 128, 256, 512, 1024], [1, 10, 100, 1000],
            'muestras por canal y evento', 'techo de la etapa [k/s]', num, num)
    pa.letra('(a) contra la tasa, con 8 + 24 muestras')
    pb.letra('(b) contra el largo de la ventana')

    # (a) la entrada pasa entera por la diagonal
    pa.linea([0.3, 4000], [0.3, 4000], 'black!30', 'solid', ancho=0.5)
    # el MCA: aceptados al espectro, 3 ranuras, disparo del ASG, lazo digital
    me = _tasa(d.D, 'asg', 3)
    xm = [q['n_in_hz'] / 1e3 for q in me]
    ym = [q['aceptados_hz'] / 1e3 for q in me]
    pa.serie(xm, ym, 'cverde', 'pentagon*')
    # el osciloscopio: lo que la captura pone en la DDR (medido), y lo que llega a cada
    # destino sostenido, min(A, techo de la etapa)
    xa, ya = _captura_ring(d, V)
    pa.serie(xa, ya, 'black', '*')
    # el lector de C del ring (B), medido contra la tasa: lo que consume por segundo
    _, cb, mb, _ = ETAPAS_RING[1]
    xb, yb = _consumo_ring(d, 'B', V)
    pa.serie(xb, yb, cb, mb)
    rot = [(ym[-1], 'MCA', 'cverde'), (ya[-1], 'DDR', 'black'), (yb[-1], 'lector del ring', cb)]
    # los techos de la red (D) y de la SD (C), medidos con el ring lleno: cada destino
    # sostiene lo que pasa la captura hasta su línea (de la red, la mediana)
    for e, color, marca, _ in ETAPAS_RING[2:]:
        med = T[e][V][0] / 1e3
        pa.linea([0.3, 4000], [med, med], color, 'limite')
        rot.append((med, {'D': 'red', 'C': 'SD'}[e], color))
    for y, s, color in rot:
        pa.l.append(f"\\node[directo, anchor=west, text={color}] at "
                    f"({f(pa.x0 + pa.w + 0.05)},{f(pa.Y(y))}) {{{s}}};")
    # la BRAM, con gen_pulsos y el disparo del ASG: lo que lee cada lector
    for k, color, marca, _, rotulo in BRAM:
        xs, ys = _bram(d, 'tasa', k)
        pa.linea(xs, ys, color, 'digital')
        pa.marcas(xs, ys, color, marca)
        pa.texto(xs[-1], ys[-1], rotulo, 'west', dx=0.1, color=color)

    # (b) lo que pasa con la etapa saturada, contra el largo de la ventana
    mm = np.geomspace(24, 1400, 60)
    # la captura no paralizable de 2·S + 3 ciclos y el ancho de banda de TCP solo
    pb.linea(mm, [FS / (2 * m + 3) / 1e3 for m in mm], 'black!45', 'limite', ancho=0.9)
    pb.linea(mm, [TCP_MB_S * 1e6 / _bytes_ev(m) / 1e3 for m in mm], 'cazul!55',
             'limite', ancho=0.9)
    # el MCA no guarda muestras: su referencia es lo que acepta con 3 M/s de entrada
    pb.horizontal(ym[-1], 'cverde', 'densely dashdotted', 0.8)
    for e, color, marca, _ in ETAPAS_RING:
        ms = [m for m in sorted(T[e]) if m not in SIN_B]
        med = [T[e][m][0] / 1e3 for m in ms]
        pb.linea(ms, med, color, 'digital')
        pb.marcas(ms, med, color, marca)
        for m in ms:
            _, lo, hi = T[e][m]
            if hi > lo:
                x = pb.X(m)
                pb.l.append(f"\\draw[{color}, line width=0.5pt] ({f(x)},{f(pb.Y(lo / 1e3))}) "
                            f"-- ({f(x)},{f(pb.Y(hi / 1e3))});")

    for k, color, marca, _, rotulo in BRAM:
        xs, ys = _bram(d, 'techo', k)
        pb.linea(xs, ys, color, 'digital')
        pb.marcas(xs, ys, color, marca)
        # adentro del panel, del lado donde la curva no pasa: las dos bajan a la derecha
        i = xs.index(128)
        if k == 'c':
            pb.texto(xs[i], ys[i], rotulo, 'north east', dx=-0.05, dy=-0.04, color=color)
        else:
            pb.texto(xs[i], ys[i], rotulo, 'north', dy=-0.2, color=color)

    cuerpo = pa.l + pb.l
    cuerpo.append(leyenda(0, -1.0, [
        ('cverde', 'digital', 'pentagon*', True, 'MCA $\\to$ espectro (3 ranuras)')]
        + [(c, 'digital', mk, True, s) for _, c, mk, s in ETAPAS_RING[:2]] + [None]
        + [(c, 'digital', mk, True, s) for _, c, mk, s in ETAPAS_RING[2:]] + [None]
        + [(c, 'digital', mk, True, f'OSC por la BRAM + {s}')
           for _, c, mk, s, _ in BRAM] + [None]
        + [('black!30', 'solid', None, True, 'salida = entrada (a)'),
           ('black!45', 'limite, line width=0.9pt', None, True, 'captura sola, $2S+3$ ciclos (b)'),
           ('cazul!55', 'limite, line width=0.9pt', None, True, 'TCP solo, 50 MB/s (b)'),
           ('cverde', 'densely dashdotted', None, True, 'MCA a 3 M/s (b)')]))
    return "\n".join(cuerpo)


# =============================================================================
def escribir(nombre, desc, cuerpo):
    tex = AQUI / f"{nombre}.tex"
    tex.write_text(PREAMBULO % {"desc": desc, "cuerpo": cuerpo}, encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                            f"-output-directory={tmp}", tex.name],
                           cwd=AQUI, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"pdflatex falló con {tex.name}:\n{r.stdout[-2500:]}")
        pdf = AQUI / f"{nombre}.pdf"
        shutil.copy(Path(tmp) / f"{nombre}.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print(f"  {nombre}.tex, .pdf y .svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--datos', default=str(RAIZ / 'software' / 'datos'))
    ap.add_argument('--solo', default='', help='nombres separados por coma')
    a = ap.parse_args()
    d = Datos(a.datos)
    figs = {
        'meritos_tasa': ('Tasa: aceptados y en su línea', lambda: fig_tasa(d)),
        'meritos_tasa_fuentes': ('Tasa con cada fuente de disparo', lambda: fig_tasa_fuentes(d)),
        'meritos_lambda': ('Error de la tasa estimada', lambda: fig_lambda(d)),
        'meritos_perdidas': ('Pérdidas por causa', lambda: fig_perdidas(d)),
        'meritos_inl': ('INL del trapecio', lambda: fig_inl(d)),
        'meritos_corrimiento': ('Corrimiento de la línea con la tasa', lambda: fig_corrimiento(d)),
        'meritos_corrimiento_canal': ('Corrimiento: placa y réplica con el canal medido',
                                      lambda: fig_corrimiento_canal(d)),
        'meritos_par': ('Resolución de pulsos dobles', lambda: fig_par(d)),
        'meritos_walk': ('Curva S, walk y disparos por pulso', lambda: fig_walk(d)),
        'meritos_ruido': ('Resolución contra el ruido', lambda: fig_ruido(d)),
        'meritos_histeresis': ('Histéresis con la tasa', lambda: fig_histeresis(d)),
        'canal_analogico': ('El canal OUT1 $\\to$ IN1', lambda: fig_canal(d)),
        'fidelidad_analogica': ('Fidelidad analógica', lambda: fig_fidelidad(d)[0]),
        'meritos_forma': ('Forma del trapecio contra la ocupación', lambda: fig_forma(d)),
        'meritos_apilamiento': ('Cortes contra el apilamiento', lambda: fig_apilamiento(d)),
        'meritos_dnl': ('No linealidad diferencial', lambda: fig_dnl(d)[0]),
        'meritos_psd': ('Separación de formas por PSD', lambda: fig_psd(d)),
        'meritos_polo_cero': ('Ajuste del polo-cero', lambda: fig_polo_cero(d)[0]),
        'meritos_polo_cero_canal': ('Polo-cero en el canal analógico',
                                    lambda: fig_polo_cero_canal(d)),
        'meritos_ventana_ciega': ('Ventana ciega de los cortes', lambda: fig_ventana_ciega(d)),
        'meritos_base_dinamica': ('Tasa con la base dinámica', lambda: fig_base_dinamica(d)),
        'meritos_deriva': ('Deriva en 2 h', lambda: fig_deriva(d)),
        'throughput_caminos': ('Throughput del MCA y del osciloscopio',
                               lambda: fig_throughput_caminos(d)),
    }
    solo = [s for s in a.solo.split(',') if s]
    for nombre, (desc, hacer) in figs.items():
        if solo and nombre not in solo:
            continue
        escribir(nombre, desc, hacer())


if __name__ == '__main__':
    main()
