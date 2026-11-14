#!/usr/bin/env python3
"""El multitrigger en una franja: el índice de su pestaña y lo que está haciendo.

Los bloques siguen el panorama de `mt_top` (docs/mt/figuras/panorama_mt.tex), con
sus colores: todo el multitrigger es disparo (amarillo) y lo que entra, gris.

    entradas → fuentes → máscara OR → ≥1 → evento → captura, MCA, ring
                          ↑ re-arma   │
                          └─ shield ←─┘ → veto al MCA

- las fuentes: por canal, el Schmitt de nivel (su umbral es del OSC), la pendiente y
  el polo-cero; y el externo (DIO0), el ASG (`gen_pulsos`) y el software;
- la máscara OR de cada canal dice qué fuentes lo disparan; sin `indep_mode` todos
  los canales usan la del canal 0. Un canal que disparó queda bloqueado (protect)
  hasta que algo lo re-arme;
- el evento es el OR de los canales: el mismo disparo para la captura, el MCA y el
  ring. El snapshot (sticky) dice qué fuentes dispararon;
- el shield cuenta un holdoff desde sus fuentes; al expirar re-arma sus canales, y
  mientras corre puede vetar al MCA.

Bajo cada bloque, su estado y lo que está mal puesto (en rojo, si así no sale ningún
disparo). Las tasas son las del MCA: los disparos que le llegan (`cross`), el tiempo
con el veto y el tiempo con el disparo sin re-armar (`t_rearm`).

Las cuentas, sin Qt: `filas_mascara` (los bits del servidor, en filas por fuente),
`describir_escudo` (el shield en palabras), `diagnostico` (lo que está mal puesto) y
`flujo_mt` (las tasas).
"""

import re

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen

from app.franja import (AMARILLO, GRIS, GRIS_CORTE, GRIS_LEYENDA, ROJO_PERDIDA,
                        Franja, _cuenta, _pct, _tasa)

# (clave, título, qué hace, color), en el orden de la señal.
ETAPAS = (
    ('fuentes', 'Sources', 'level, slope, pole-zero\nDIO0, ASG, software', AMARILLO),
    ('mascara', 'OR mask', 'which sources trigger\neach channel', AMARILLO),
    ('evento', 'Event', 'OR of the channels\nsnapshot', AMARILLO),
    ('escudo', 'Shield', 'holdoff from triggers\nor DIO0', AMARILLO),
)
COLOR = {clave: color for clave, _t, _d, color in ETAPAS}

AYUDA = {
    'fuentes': 'What can trigger. Per channel: the level Schmitt (its threshold is '
               'in OSC settings → Trigger), the slope trigger and the pole-zero '
               'trigger (armed from Spectrum or by scripts). Plus the external '
               'input DIO0, the pulse generator (ASG source) and software.',
    'mascara': 'One OR mask per channel: the sources that trigger it. Without '
               'indep_mode every channel uses the mask of IN1. A channel that '
               'triggered stays blocked (protect) until something re-arms it; with '
               'we_keep the mask survives the trigger (continuous mode).',
    'evento': 'The OR of the channels: ONE trigger for the capture, the MCA and the '
              'ring. The snapshot keeps every source that triggered since it was '
              'last cleared (sticky).',
    'escudo': 'The trigger_shield: a holdoff counter started by its sources (a '
              'channel trigger or DIO0). When it expires it re-arms its channels; '
              'while it runs it can veto the MCA. There is one shield: as a veto it '
              'stops re-arming the channels it does not list.',
}

CICLO_NS = 8.0                      # adc_clk, 125 MHz


# =============================================================================
# Las cuentas, sin Qt
# =============================================================================

def canal_txt(ch):
    return f'IN{int(ch) + 1}'


_TIPOS = ('adc', 'slope', 'pz')
_RE_CANAL = re.compile(r'^(adc|slope|pz)_([pn])(\d)$')
_RE_EXTRA = re.compile(r'^(ext|asg)_([pn])$')
_RE_CADENA = re.compile(r'^trig_ch(\d)$')


def clasificar(nombre):
    """(fila, polaridad, canal de la fuente) de un bit de la máscara o del snapshot:
    ('slope0', 'p', 0) para 'slope_p0', ('ext', 'n', None) para 'ext_n'. Un nombre
    que no se conoce queda en una fila propia, con su nombre."""
    if nombre.startswith('sw'):
        return 'sw', 'p', None
    m = _RE_CANAL.match(nombre)
    if m:
        return f'{m.group(1)}{m.group(3)}', m.group(2), int(m.group(3))
    m = _RE_EXTRA.match(nombre)
    if m:
        return m.group(1), m.group(2), None
    m = _RE_CADENA.match(nombre)
    if m:
        return f'cadena{m.group(1)}', 'p', int(m.group(1))
    return nombre, 'p', None


def rotulo_fila(fila):
    if fila == 'sw':
        return 'software'
    m = re.match(r'^(adc|slope|pz)(\d)$', fila)
    if m:
        return {'adc': 'level', 'slope': 'slope', 'pz': 'pole-zero'}[m.group(1)] + \
            ' ' + canal_txt(m.group(2))
    if fila == 'ext':
        return 'external DIO0'
    if fila == 'asg':
        return 'generator (ASG)'
    m = re.match(r'^cadena(\d)$', fila)
    if m:
        return f'chain ch{m.group(1)}'
    return fila


def nombre_corto(nombre):
    """'slope IN1 ↑' para 'slope_p0': lo que se lista en la franja."""
    fila, pol, _ch = clasificar(nombre)
    r = rotulo_fila(fila)
    if fila == 'sw' or fila.startswith(('pz', 'cadena')) or fila == nombre:
        return r
    return f"{r} {'↑' if pol == 'p' else '↓'}"


def _orden(fila):
    if fila == 'sw':
        return (0, 0, 0)
    m = re.match(r'^(adc|slope|pz)(\d)$', fila)
    if m:
        return (1, int(m.group(2)), _TIPOS.index(m.group(1)))
    if fila == 'ext':
        return (2, 0, 0)
    if fila == 'asg':
        return (3, 0, 0)
    m = re.match(r'^cadena(\d)$', fila)
    if m:
        return (4, int(m.group(1)), 0)
    return (5, 0, 0)


def filas_mascara(bits, n_ch=2):
    """Los bits de la máscara (los del servidor: [nombre, valor, ayuda]) en filas por
    fuente, en el orden de la señal (el software; por canal, nivel, pendiente y
    polo-cero; el externo, el ASG y la cadena), con sus dos polaridades:
    ([(fila, rótulo, {'p': (nombre, valor, ayuda), 'n': ...})], ocultos).

    Quedan afuera las fuentes de canales que el bitstream no trae (canal ≥ n_ch) y,
    con dos canales, la cadena de otro scope, que en ese top está atada a 0;
    `ocultos` es la máscara de esos bits."""
    filas, ocultos = {}, 0
    for nombre, valor, ayuda in bits:
        fila, pol, ch = clasificar(nombre)
        cadena = fila.startswith('cadena')
        if ch is not None and ((not cadena and ch >= n_ch) or (cadena and n_ch <= 2)):
            ocultos |= int(valor)
            continue
        filas.setdefault(fila, {})[pol] = (nombre, int(valor), ayuda)
    orden = sorted(filas, key=_orden)
    return [(f, rotulo_fila(f), filas[f]) for f in orden], ocultos


def mascaras_efectivas(config, n_ch=2, indep=None):
    """La máscara que usa cada canal (IN1, IN2): sin `indep_mode` (su bit en 0), la
    del canal 0, porque `mt_cfg` hace el fan-out. Con `indep` None (no se sabe), la
    propia."""
    propias = [int(config.get(f'or_mask_ch{c}', 0) or 0) for c in range(min(n_ch, 2))]
    if indep is None:
        return propias
    return [m if c == 0 or (indep >> c) & 1 else propias[0]
            for c, m in enumerate(propias)]


def _nombres(valor, bits):
    return [n for n, v, _a in (bits or ()) if int(valor) & int(v)]


def _ciclos(dur):
    t_us = dur * CICLO_NS / 1000.0
    return f'{dur} cycles ({t_us:.3g} µs)'


def _y(cosas):
    cosas = list(cosas)
    if len(cosas) <= 1:
        return ''.join(cosas)
    return ', '.join(cosas[:-1]) + ' or ' + cosas[-1]


def _quien_dispara(n_src):
    chs = [canal_txt(m.group(1)) for n in n_src for m in [re.match(r'^ch(\d)$', n)]
           if m]
    out = [f"trigger of {' or '.join(chs)}"] if chs else []
    for n in n_src:
        if re.match(r'^ch(\d)$', n):
            continue
        if n == 'ext_p':
            out.append('rising edge of DIO0')
        elif n == 'ext_n':
            out.append('falling edge of DIO0')
        elif n != 'ext_lvl':
            out.append(n)
    return out


def canales_rearmados(src, dst, bits_dst):
    """Los canales que el shield re-arma (los de `dst`, si algo lo dispara)."""
    if not src:
        return []
    return [int(m.group(1)) for n in _nombres(dst, bits_dst)
            for m in [re.match(r'^ch(\d)$', n)] if m]


def describir_escudo(src, dst, dur, bits_src, bits_dst):
    """El shield en palabras: qué lo dispara, qué hace y cuándo. `bits_*` son los del
    servidor ([nombre, valor, ayuda]), así que no depende del orden de los bits.

    Sigue a `trigger_shield.sv`: cada disparo de una fuente recarga el contador con
    `dur`; con `dur` = 0 el re-armado es en el ciclo siguiente, y si no al expirar.
    El nivel de DIO0 «dispara» en cada ciclo alto. El veto es `src_fire | active`. Un
    canal en `dst` ya no recibe el re-armado por software (0x94): lo maneja el shield."""
    n_src, n_dst = _nombres(src, bits_src), _nombres(dst, bits_dst)
    if not n_src:
        return ('Off. A channel that triggered stays blocked until software '
                're-arms it (TRIG_DIS_CLR).')
    if not n_dst:
        return 'It counts, but acts on nothing: it re-arms no channel and vetoes nothing.'
    nivel = 'ext_lvl' in n_src
    quien = _quien_dispara(n_src)
    rearma = [canal_txt(c) for c in canales_rearmados(src, dst, bits_dst)]
    frases = []
    if rearma:
        chs = ' and '.join(rearma)
        if quien:
            if dur == 0:
                frases.append(f'Each {_y(quien)} re-arms {chs} at once: '
                              f'hardware re-arm.')
            else:
                frases.append(f'Each {_y(quien)} re-arms {chs} {_ciclos(dur)} later '
                              f'(holdoff).')
        if nivel:
            frases.append(f'While DIO0 is high it re-arms {chs} every cycle.' if not dur
                          else f'It re-arms {chs} {_ciclos(dur)} after DIO0 goes low.')
        frases.append('Software re-arm no longer reaches '
                      + ('it.' if len(rearma) == 1 else 'them.'))
    else:
        frases.append('It re-arms no channel: one that triggered waits for software.')
    if 'mca' in n_dst:
        cuando = []
        if nivel:
            cuando.append('while DIO0 is high' + (f' and {_ciclos(dur)} after'
                                                   if dur else ''))
        if quien:
            cuando.append(f'from each {_y(quien)} '
                          + (f'for {_ciclos(dur)}' if dur else 'for one cycle'))
        frases.append('Vetoes the MCA ' + ', and '.join(cuando) + ': no new windows, '
                      'and its live-time clock stops.')
    return ' '.join(frases)


def resumen_escudo(src, dst, dur, bits_dst):
    """Una línea para la franja."""
    if not src:
        return 'off: software re-arm'
    rearma = [canal_txt(c) for c in canales_rearmados(src, dst, bits_dst)]
    veto = 'mca' in _nombres(dst, bits_dst)
    if rearma:
        s = f"re-arms {', '.join(rearma)} " + ('at once' if dur == 0 else
                                                 f'after {dur} cyc')
        return s + (' · veto' if veto else '')
    if veto:
        return 'veto to the MCA only' + (f', {dur} cyc' if dur else '')
    return 'acts on nothing'


def _flags(est):
    w = int((est or {}).get('flags', 0) or 0)
    return ([bool((w >> c) & 1) for c in range(4)],
            [bool((w >> (4 + c)) & 1) for c in range(4)])


def diagnostico(info):
    """Lo que está mal puesto o hay que saber, por etapa: {etapa: [(texto, grave)]}.
    Grave: así no sale ningún disparo de esa fuente o de ese canal."""
    cfg = info.get('config') or {}
    est = info.get('status') or {}
    n_ch = int(info.get('n_ch') or 2)
    indep = info.get('indep')
    bits = info.get('bits') or ()
    canales = info.get('canales') or []
    efect = mascaras_efectivas(cfg, n_ch, indep)
    out = {clave: [] for clave, *_r in ETAPAS}

    def decir(etapa, texto, grave):
        if (texto, grave) not in out[etapa]:
            out[etapa].append((texto, grave))

    if not any(efect):
        decir('mascara', 'no source in any mask: nothing triggers', True)
    for nombre, valor, _a in bits:
        if not any(m & int(valor) for m in efect):
            continue
        fila, _pol, ch = clasificar(nombre)
        tipo = re.sub(r'\d+$', '', fila)
        clave = {'slope': 'pendiente', 'pz': 'polo_cero'}.get(tipo)
        if clave is None or ch is None or ch >= len(canales):
            continue
        c = canales[ch].get(clave)
        if c is None:
            decir('fuentes', f'{rotulo_fila(fila)}: not in this bitstream', True)
        elif not c.get('en'):
            decir('fuentes', f'{rotulo_fila(fila)} is in a mask but off', True)
        elif int(c.get('hyst', 0)) >= int(c.get('thr', 0)):
            decir('fuentes', f'{rotulo_fila(fila)}: hysteresis ≥ threshold, '
                             f'it never re-arms', True)

    _filas, ocultos = filas_mascara(bits, n_ch)
    for c in range(min(n_ch, 2)):
        propia = int(cfg.get(f'or_mask_ch{c}', 0) or 0)
        if c and indep is not None and not (indep >> c) & 1 and propia != efect[0]:
            decir('mascara', f'{canal_txt(c)} uses the mask of IN1', False)
        if propia & ocultos:
            decir('mascara', f'{canal_txt(c)}: sources not in this bitstream', False)

    dis_act, we_keep = _flags(est)
    src = int(cfg.get('shield_src', 0) or 0)
    dst = int(cfg.get('shield_dst', 0) or 0)
    rearmados = canales_rearmados(src, dst, info.get('bits_shield_dst'))
    for c in range(len(efect)):
        # Sin indep_mode IN2 repite a IN1: se avisa una vez.
        if not efect[c] or c in rearmados or efect[c] in efect[:c]:
            continue
        # Si sus fuentes también disparan otro canal que sí se re-arma (IN2 con la
        # máscara de IN1, sin indep_mode), el evento no pierde nada: es el OR.
        if any(c2 in rearmados and not efect[c] & ~efect[c2]
               for c2 in range(len(efect)) if efect[c2]):
            continue
        if we_keep[c] and src:
            decir('escudo', f'{canal_txt(c)} stops after its first trigger', True)
        elif we_keep[c]:
            decir('escudo', f'shield off: {canal_txt(c)} waits for software', False)
        elif dis_act[c]:
            decir('evento', f'{canal_txt(c)} blocked: waits for a software re-arm',
                  False)
    if any(efect) and not any(we_keep[c] for c in range(len(efect)) if efect[c]):
        decir('mascara', 'single shot: no we_keep, the mask turns off', False)
    return out


def flujo_mt(cnt):
    """Lo que el MCA ve del multitrigger, desde sus contadores (`mca_read_counters`):
    los disparos que le llegan (`cross`, con veto o sin él), los que cayeron en el
    veto, y la fracción del tiempo real con el veto y con el disparo sin re-armar."""
    def s(clave):
        return float((cnt or {}).get(clave, 0.0) or 0.0)

    T = s('realtime_s')
    cross = int(s('cross'))
    return dict(T=T, disparos=cross, tasa=(cross / T if T > 0 else 0.0),
                vetados=int(s('lost_veto')),
                frac_veto=(s('vetotime_s') / T if T > 0 else 0.0),
                frac_rearmado=(s('t_rearm_s') / T if T > 0 else 0.0))


def _pct_f(f):
    return _pct(f, 1.0) if f > 0 else '0 %'


# =============================================================================
# El widget
# =============================================================================

class DiagramaMt(Franja):
    """Arriba las entradas, las fuentes, la máscara, el OR y el evento, hacia la
    captura y el MCA; abajo el shield, que re-arma la máscara y veta al MCA."""

    AYUDA = AYUDA

    LEYENDA = (
        (('red', ROJO_PERDIDA),
         (': set wrong, no trigger gets through.   ', GRIS_LEYENDA),
         ('dashed', GRIS_LEYENDA),
         (': not used by the current setup.   Changes apply at once; the MCA keeps '
          'measuring.', GRIS_LEYENDA)),
    )

    def __init__(self, parent=None):
        self._info = {}
        self._flujo = None
        self._hay_ring = False
        super().__init__(parent)

    # ---------- lo que la pestaña le dice ----------

    def actualizar_mtrg(self, info):
        self._info = dict(info or {})
        self.update()

    def actualizar_mca(self, cnt):
        self._flujo = flujo_mt(cnt) if cnt else None
        self.update()

    def configurar(self, hay_ring=False):
        self._hay_ring = bool(hay_ring)
        self.update()

    def limpiar(self):
        self._info, self._flujo = {}, None
        self.update()

    @property
    def flujo(self):
        return self._flujo

    def diagnostico(self):
        return diagnostico(self._info) if self._info else {}

    # ---------- medidas ----------

    def _medidas(self):
        f_tit, f_chico = self._fuentes()
        fmt, fmc = QFontMetrics(f_tit), QFontMetrics(f_chico)
        lc = fmc.height()
        h = fmt.height() + 2 * lc + 10.0
        return f_tit, f_chico, fmc, lc, h

    def _alto(self):
        _ft, _fc, _fm, lc, h = self._medidas()
        # fila de arriba, su estado, el shield (con su estado al lado) y la leyenda
        return int(6 + h + 4 + 2 * lc + 10 + h + 6 + lc + 6)

    def _geometria(self):
        f_tit, f_chico, fmc, lc, h = self._medidas()
        adv = fmc.horizontalAdvance
        x0, y0 = 6.0, 6.0
        ancho_in = max(adv(t) for t in ('IN1 · IN2', 'DIO0 · ASG · SW')) + 14.0
        ancho_s = max(adv(t) for t in ('BRAM capture', 'MCA trigger, ring',
                                       'MCA veto')) + 14.0
        hueco = max(adv(t) for t in ('sources', '999 k/s', 'triggers')) + 18.0
        d = lc + 6.0                                   # el círculo del OR
        hueco_or = d + 28.0
        x_s = self.width() - 6.0 - ancho_s
        libre = x_s - hueco - (x0 + ancho_in + hueco) - hueco - hueco_or
        ancho = max(60.0, libre / 3)
        xf = x0 + ancho_in + hueco
        xm = xf + ancho + hueco
        xe = xm + ancho + hueco_or
        self._cajas = {'fuentes': QRectF(xf, y0, ancho, h),
                       'mascara': QRectF(xm, y0, ancho, h),
                       'evento': QRectF(xe, y0, ancho, h)}
        cx = xm + ancho + hueco_or / 2
        # El shield, debajo de la máscara: le bajan los disparos de los canales (a la
        # derecha) y su re-armado sube a la máscara (a la izquierda).
        y_e = y0 + h + 4 + 2 * lc + 10
        self._cajas['escudo'] = QRectF(xm, y_e, ancho + 22, h)
        entradas = QRectF(x0, y0 + 4, ancho_in, h - 8)
        salida = QRectF(x_s, y0 + 4, ancho_s, h - 8)
        veto = QRectF(x_s, y_e + 8, ancho_s, h - 16)
        orc = QPointF(cx, y0 + h / 2)
        return f_tit, f_chico, fmc, lc, h, entradas, salida, veto, orc, d

    def _x_lazo(self):
        """Dónde bajan los disparos al shield y dónde sube su re-armado."""
        m = self._cajas['mascara']
        return m.right() + 8, m.left() + 14

    # ---------- el dibujo ----------

    def _caja_gris(self, p, r, lineas, fmc, lc, roja=False, punteada=False):
        pen = QPen(ROJO_PERDIDA if roja else QColor(90, 90, 90), 2.0 if roja else 1.0)
        if punteada:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(QColor(250, 219, 216) if roja else GRIS)
        p.drawRoundedRect(r, 3, 3)
        p.setBrush(Qt.NoBrush)
        f_chico = self._fuentes()[1]
        y = r.center().y() - (len(lineas) * lc) / 2 + fmc.ascent()
        for k, s in enumerate(lineas):
            self._rotulo(p, f_chico, r.center().x(), y + k * lc, s, Qt.black,
                         ancho_max=r.width() - 4)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        texto = self._texto()
        (f_tit, f_chico, fmc, lc, h, entradas, salida, veto, orc,
         d) = self._geometria()
        c = self._cajas
        ym = orc.y()
        info = self._info
        cfg = info.get('config') or {}
        est = info.get('status') or {}
        bits = info.get('bits') or ()
        n_ch = int(info.get('n_ch') or 2)
        efect = mascaras_efectivas(cfg, n_ch, info.get('indep'))
        diag = diagnostico(info) if info else {}
        fl = self._flujo
        src = int(cfg.get('shield_src', 0) or 0)
        dst = int(cfg.get('shield_dst', 0) or 0)
        dur = int(cfg.get('shield_dur', 0) or 0)
        bits_dst = info.get('bits_shield_dst')
        rearmados = canales_rearmados(src, dst, bits_dst)
        hay_veto = 'mca' in _nombres(dst, bits_dst) and bool(src)

        def rotulo(x, y_base, s, color=texto, centro=True, ancho_max=None):
            self._rotulo(p, f_chico, x, y_base, s, color, centro, ancho_max)

        # --- las entradas, y la fila del disparo ---
        self._caja_gris(p, entradas, ['IN1 · IN2', 'DIO0 · ASG · SW'], fmc, lc)
        self._flecha(p, entradas.right(), ym, c['fuentes'].left(), ym, texto)
        self._flecha(p, c['fuentes'].right(), ym, c['mascara'].left(), ym, texto)
        xc = (c['fuentes'].right() + c['mascara'].left()) / 2
        rotulo(xc, ym - 5, 'sources')
        usadas = [n for n, v, _a in bits if any(m & int(v) for m in efect)]
        if info:
            rotulo(xc, ym + fmc.ascent() + 4, f'{len(usadas)} in use',
                   ROJO_PERDIDA if not usadas else GRIS_CORTE)
        self._flecha(p, c['mascara'].right(), ym, orc.x() - d / 2, ym, texto)
        p.setPen(QPen(QColor(90, 90, 90), 1.0))
        p.setBrush(AMARILLO)
        p.drawEllipse(orc, d / 2, d / 2)
        p.setBrush(Qt.NoBrush)
        rotulo(orc.x(), ym + fmc.ascent() / 2 - 1, '≥1', Qt.black)
        self._flecha(p, orc.x() + d / 2, ym, c['evento'].left(), ym, texto)
        self._flecha(p, c['evento'].right(), ym, salida.left(), ym, texto)
        xc = (c['evento'].right() + salida.left()) / 2
        rotulo(xc, ym - 5, 'triggers')
        if fl is not None and fl['T'] > 0:
            rotulo(xc, ym + fmc.ascent() + 4, _tasa(fl['tasa']))
        self._caja_gris(p, salida, ['BRAM capture',
                                    'MCA trigger' + (', ring' if self._hay_ring
                                                     else '')], fmc, lc)

        # --- el lazo del shield: los disparos bajan, el re-armado sube ---
        e = c['escudo']
        x_baja, x_sube = self._x_lazo()
        self._flecha(p, x_baja, ym, x_baja, e.top(), texto, punteada=not src)
        self._flecha(p, x_sube, e.top(), x_sube, c['mascara'].bottom(), texto,
                     punteada=not rearmados)
        # el veto, hacia el MCA
        self._flecha(p, e.right(), veto.center().y(), veto.left(), veto.center().y(),
                     ROJO_PERDIDA if hay_veto else GRIS_CORTE, punteada=not hay_veto)
        self._caja_gris(p, veto, ['MCA veto' + (' · now' if est.get('mca_veto')
                                                else '')], fmc, lc,
                        roja=hay_veto, punteada=not hay_veto)

        for clave, titulo, desc, color in ETAPAS:
            self._bloque(p, clave, titulo, desc, color, c[clave], f_tit, f_chico)

        # --- el estado, bajo cada bloque ---
        debajo = {}
        if info:
            nombres = [nombre_corto(n) for n in usadas]
            debajo['fuentes'] = [(', '.join(nombres) if nombres
                                  else 'none in the masks',
                                  GRIS_CORTE if nombres else ROJO_PERDIDA)]
            partes = []
            for ch, m in enumerate(efect):
                propia = int(cfg.get(f'or_mask_ch{ch}', 0) or 0)
                if ch and m == efect[0] and m != propia:
                    partes.append(f'{canal_txt(ch)} = IN1')
                else:
                    k = sum(1 for _n, v, _a in bits if m & int(v))
                    partes.append(f'{canal_txt(ch)}: {k}')
            debajo['mascara'] = [(' · '.join(partes), GRIS_CORTE)]
            vistas = sorted({nombre_corto(n) for n in (est.get('fuentes') or [])})
            debajo['evento'] = [('seen: ' + (', '.join(vistas) if vistas else '—'),
                                 GRIS_CORTE)]
            debajo['escudo'] = [(resumen_escudo(src, dst, dur, bits_dst), GRIS_CORTE)]
        if fl is not None and fl['T'] > 0:
            debajo.setdefault('fuentes', []).append(
                (f"not armed {_pct_f(fl['frac_rearmado'])} of the time", GRIS_CORTE))
            if hay_veto or fl['vetados']:
                debajo.setdefault('escudo', []).append(
                    (f"MCA vetoed {_pct_f(fl['frac_veto'])} · "
                     f"{_cuenta(fl['vetados'])} triggers", GRIS_CORTE))
        # lo mal puesto va primero en la segunda línea (y rojo si es grave)
        for clave, avisos in diag.items():
            if avisos:
                graves = [a for a in avisos if a[1]] or avisos
                texto_a, grave = graves[0]
                lineas = debajo.setdefault(clave, [])
                lineas[1:2] = [(texto_a, ROJO_PERDIDA if grave else texto)]

        # La máscara escribe entre las dos flechas del lazo.
        desde = {'fuentes': c['fuentes'].left() + 2, 'mascara': x_sube + 6,
                 'evento': c['evento'].left() + 2}
        hasta = {'fuentes': c['mascara'].left() - 6, 'mascara': x_baja - 6,
                 'evento': salida.left() - 6}
        for clave in ('fuentes', 'mascara', 'evento'):
            yb = c[clave].bottom() + 4 + fmc.ascent()
            for k, (s, color) in enumerate(debajo.get(clave, [])[:2]):
                rotulo(desde[clave], yb + k * lc, s, color, centro=False,
                       ancho_max=hasta[clave] - desde[clave])
        # El shield escribe a su derecha: arriba y abajo de la flecha del veto.
        y_v = veto.center().y()
        for k, (s, color) in enumerate(debajo.get('escudo', [])[:2]):
            rotulo(e.right() + 8, y_v - 5 if k == 0 else y_v + fmc.ascent() + 4, s,
                   color, centro=False, ancho_max=veto.left() - e.right() - 18)

        # --- la leyenda, abajo de todo ---
        self._leyenda(p, f_chico, 6, e.bottom() + 6 + fmc.ascent(), self.width() - 12,
                      self.LEYENDA)
