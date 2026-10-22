#!/usr/bin/env python3
"""Paralizable o no paralizable: lo decide el RE-ARMADO, no la compuerta.

La pregunta natural es si `cfg_gate_mode` (histéresis contra compuerta fija)
es lo que elige entre los dos modelos de tiempo muerto. La respuesta que dan
estas figuras es que NO: los dos modos del MCA son paralizables, y con el
mismo tiempo muerto efectivo.

Lo que decide es el re-armado del Schmitt
([`mca_pulse_feature.sv`](../../../modulos/mca/rtl/mca_pulse_feature.sv),
:567-577): `armed` es una condición de NIVEL —la señal tiene que bajar de
thr_lo— y no un contador. Mientras la cola del último pulso siga arriba el
módulo no puede abrir, y cualquier pulso que llegue en ese lapso levanta la
señal y ALARGA el bloqueo. Eso es, palabra por palabra, la definición de
tiempo muerto paralizable.

De ahí sale una regla simple que las figuras ponen a prueba:

    tau_efectivo = max(cierre de la ventana, cola sobre thr_lo)
    y el modelo es PARALIZABLE,  m = n·e^{-n·tau}

  modo 0 (histéresis)      cierra JUSTO cuando la señal baja de thr_lo, asi
                           que tau = la cola, 5.9 us, y feat_busy lo cuenta
                           entero: el contador es honesto.
  modo 1, gate_long = 384  cierra a 3.07 us, antes que la cola. tau sigue
                           siendo 5.9 us, pero feat_busy sólo cuenta 3.07:
                           el contador subestima.
  modo 1, gate_long = 1024 cierra a 8.19 us, DESPUÉS que la cola: tau = 8.2 us
                           y el contador vuelve a ser casi honesto... pero la
                           pérdida EMPEORA, porque tau creció.
  re-armado por contador   la única variante no paralizable. No está en el
                           RTL, y el comentario de :569-573 explica por qué:
                           abriría a mitad de un pulso en curso y mediría una
                           amplitud truncada. Es, en cambio, lo que hace el
                           lector de Python, que puede permitírselo porque su
                           tau = 250 us es mucho mayor que la cola.

Nada se dibuja a mano. Se sintetiza la señal a 125 MS/s sumando pulsos de
detector y se corre sobre ella la misma FSM del RTL: Schmitt con re-armado
por debajo de thr_lo, desarme si la señal cruza thr_hi con el módulo ocupado,
y los dos modos de cierre. Los puntos salen de ahí; las líneas son las
fórmulas, y que coincidan es el resultado.

Parámetros, todos del RTL o de la campaña: fs = 125 MHz, cfg_thr = 100,
cfg_hyst = 40 (thr_lo = 60), cfg_gate_long = 384 muestras = 3.07 us,
cfg_maxlen = 4096, S_DIV = 16 ciclos. La cola del pulso (tau = 1.14 us sobre
una amplitud de 8192 cuentas) está elegida para que un pulso aislado quede
sobre thr_lo unas 700 muestras, que es lo que el comentario de :206 del RTL
reporta medido en placa; la simulación da 737.

  05_politicas_trigger.png
      El mismo tren visto por los dos modos de cierre. La fila del modo 0 es
      la única SIN rayado: su ventana termina donde termina el bloqueo. En el
      modo 1 el rayado es tiempo muerto real que ningún contador registra, y
      los pulsos que caen ahí (marca gris) se pierden sin dejar rastro — y
      encima alargan el bloqueo.

  06_paralizable_vs_no.png
      (a) tasa registrada y (b) fracción perdida con Poisson: las tres
      configuraciones del RTL caen sobre su curva PARALIZABLE, con el tau que
      predice la regla de arriba; sólo el re-armado por contador sigue la no
      paralizable. (c) el mismo barrido PERIÓDICO, que es el ensayo que las
      separa sin ambigüedad: las paralizables se desploman a CERO en
      T = tau_efectivo y la no paralizable sigue registrando.

  07a_cronograma.png
      La señal y, debajo, el cronograma de los dos relojes sobre un caso
      concreto: lo que cuenta feat_busy contra lo que el sistema estuvo
      realmente bloqueado. Va sola porque se lee sobre un eje de tiempo.

  07b_deadtime_oculto.png
      Cuánto difieren esos dos relojes, contra la tasa. El
      contado NO es monótono: pasa por un máximo y después BAJA, porque a tasa
      alta ya casi no se abren ventanas. Un `deadtime_cnt` que baja al subir
      la tasa es la firma de este efecto, no de un sistema que se descongestiona.

    python3 figuras_trigger.py [--out DIR] [--rapido]
"""

import argparse
import os
import sys

import numpy as np
from scipy.signal import fftconvolve
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))

from figuras_resolucion import (TINTA, TINTA2, MUDO, GRILLA,   # noqa: E402
                               AZUL, NARAN, ROJO, _limpiar, _panel)

VERDE = '#3a9a5c'

# --- hardware ---------------------------------------------------------------
FS_HZ     = 125e6
DT_US     = 1e6 / FS_HZ          # 0.008 us por muestra
THR_HI    = 100.0                # cfg_thr   [cuentas]
THR_LO    = 60.0                 # cfg_thr - cfg_hyst
GATE_LONG = 384                  # cfg_gate_long [muestras] = 3.072 us
MAXLEN    = 4096                 # cfg_maxlen    [muestras] = 32.8 us
N_DIV     = 16                   # ciclos de S_DIV = DIV_W de mca_top
# Eran 6, que es el DEFAULT del parametro Q_W de mca_div_restore y no el valor
# con el que mca_top instancia los divisores: DIV_W = 16. La latencia es Q_W
# ciclos fija (mca_div_restore.sv:19-21), asi que S_DIV dura 16 y no 6. El
# efecto sobre tau es chico —0.08 us sobre 5.9— y no cambia ninguna conclusion,
# pero los numeros de las figuras y las tablas del README se corrieron.
AMP_CNT   = 8192.0               # pulso de 1 V en el rango de +-1 V
T_RISE_US = 0.08
TAU_US    = 1.14                 # da ~700 muestras sobre thr_lo (RTL :206)

GATE_LARGO = 1024                # 8.19 us: MAYOR que la cola sobre thr_lo

# Los dos modos del RTL con la configuración de la campaña, el mismo modo 1
# con la compuerta estirada más allá de la cola, y la variante hipotética que
# re-arma por contador. Lo que cambia entre ellas es UNA cosa: si al cerrar la
# ventana la señal ya bajó de thr_lo o no.
POLITICAS = ('compuerta', 'histeresis', 'gate_largo', 'rearme')
CFG = {
    'compuerta':  dict(politica='compuerta',  gate_long=GATE_LONG),
    'histeresis': dict(politica='histeresis'),
    'gate_largo': dict(politica='compuerta',  gate_long=GATE_LARGO),
    'rearme':     dict(politica='rearme',     gate_long=GATE_LONG),
}
ETIQUETA = {
    'compuerta':  'modo 1, gate_long = 384  (campaña)',
    'histeresis': 'modo 0, histéresis',
    'gate_largo': 'modo 1, gate_long = 1024',
    'rearme':     're-armado por contador (no está en el RTL)',
}
COLOR = {'compuerta': NARAN, 'histeresis': ROJO, 'gate_largo': VERDE,
         'rearme': AZUL}
# marcadores distintos: modo 0 y modo 1 caen uno encima del otro, y eso ES el
# resultado -- hay que poder ver que son dos series y no una.
MARCA = {'compuerta': 'o', 'histeresis': 's', 'gate_largo': '^',
         'rearme': 'D'}


# =============================================================================
# Señal
# =============================================================================

def kernel(dur_us=14.0):
    """Pulso de detector normalizado a AMP_CNT, muestreado a FS_HZ."""
    t = np.arange(0.0, dur_us, DT_US)
    y = (1.0 - np.exp(-t / T_RISE_US)) * np.exp(-t / TAU_US)
    return (AMP_CNT * y / y.max()).astype(np.float32)


def t_sobre_thr_lo():
    """Cuántas muestras queda un pulso AISLADO por encima de thr_lo."""
    k = kernel()
    return int(np.flatnonzero(k >= THR_LO)[-1] - np.flatnonzero(k >= THR_LO)[0] + 1)


def senal(t_arribo_us, t_fin_us, k=None):
    """Suma de pulsos en los instantes dados, muestreada a FS_HZ."""
    if k is None:
        k = kernel()
    n = int(round(t_fin_us / DT_US)) + k.size
    deltas = np.zeros(n, np.float32)
    idx = np.round(np.asarray(t_arribo_us) / DT_US).astype(np.int64)
    idx = idx[(idx >= 0) & (idx < n)]
    np.add.at(deltas, idx, 1.0)
    x = fftconvolve(deltas, k)[:n].astype(np.float32)
    return x, idx


# =============================================================================
# La máquina de estados del RTL, corrida sobre la señal
# =============================================================================

class _Cruces:
    """Índices donde x cruza cada umbral, con búsqueda hacia adelante/atrás."""

    def __init__(self, x):
        self.lo = np.flatnonzero(x < THR_LO)        # habilita `armed`
        self.hi = np.flatnonzero(x >= THR_HI)       # dispara / desarma
        self.n = x.size

    def prox_lo(self, i):
        j = np.searchsorted(self.lo, i)
        return int(self.lo[j]) if j < self.lo.size else None

    def prox_hi(self, i):
        j = np.searchsorted(self.hi, i)
        return int(self.hi[j]) if j < self.hi.size else None

    def ult_lo(self, i0, i1):
        j = np.searchsorted(self.lo, i1)
        return int(self.lo[j - 1]) if j > 0 and self.lo[j - 1] >= i0 else -1

    def ult_hi(self, i0, i1):
        j = np.searchsorted(self.hi, i1)
        return int(self.hi[j - 1]) if j > 0 and self.hi[j - 1] >= i0 else -1


def correr_fsm(x, politica, gate_long=GATE_LONG, maxlen=MAXLEN):
    """Replica la FSM de mca_pulse_feature sobre la señal `x`.

    `politica` es 'compuerta' (cfg_gate_mode=1), 'histeresis' (=0), o
    'rearme', que es la compuerta fija pero re-armando por contador apenas
    cierra la ventana, sin esperar a que la señal baje de thr_lo. Esa última
    NO está en el RTL: es la variante que aísla cuál de las dos reglas decide
    si el sistema es paralizable.

    El re-armado del RTL (:567-577): `armed` se pone por debajo de thr_lo y se
    BORRA si la señal cruza thr_hi con el módulo ocupado. Mientras la cola del
    último pulso siga sobre thr_lo el sistema no puede abrir, y cualquier
    pulso que llegue en ese lapso levanta la señal y lo ALARGA.

    Devuelve los eventos (apertura, fin de ocupado, destino) y los totales de
    ocupado (lo que cuenta feat_busy) y bloqueado (ocupado + no armado).
    """
    c = _Cruces(x)
    eventos = []            # (i_abre, i_fin_busy, destino)
    bloqueos = []           # (i0, i1) bloqueado por re-armado, fuera de busy
    muestras_busy = 0
    muestras_bloq = 0
    i, armed = 0, False

    while True:
        if not armed:
            j = c.prox_lo(i)
            if j is None:
                break
            if j > i:
                bloqueos.append((i, j))
                muestras_bloq += j - i      # idle sin armar: también bloquea
            i, armed = j, True
        k = c.prox_hi(i)
        if k is None:
            break

        # --- cierre, según la política ------------------------------------
        if politica == 'histeresis':
            j = c.prox_lo(k + 1)
            if j is None:
                break
            if j - k >= maxlen:
                i_cierre, destino = k + maxlen, 'apilado'
            else:
                i_cierre, destino = j, 'aceptado'
        else:
            i_cierre = k + gate_long
            destino = 'aceptado'
            # gate_2nd: la señal bajó de thr_lo y volvió a cruzar thr_hi
            # DENTRO de la compuerta. Con la cola de un pulso real eso sólo
            # puede pasar si gate_long supera el tiempo sobre thr_lo.
            j = c.prox_lo(k + 1)
            if j is not None and j < i_cierre:
                m = c.prox_hi(j)
                if m is not None and m < i_cierre:
                    destino = 'apilado'

        i_busy = min(i_cierre + N_DIV, c.n)
        eventos.append((k, i_busy, destino))
        muestras_busy += i_busy - k
        muestras_bloq += i_busy - k

        # --- armed al salir de busy ---------------------------------------
        if politica == 'rearme':
            armed = True
        else:
            armed = c.ult_lo(k, i_busy) > c.ult_hi(k, i_busy)
        i = i_busy

    return dict(eventos=eventos, bloqueos=bloqueos,
                aceptados=sum(1 for e in eventos if e[2] == 'aceptado'),
                apilados=sum(1 for e in eventos if e[2] == 'apilado'),
                f_busy=muestras_busy / c.n,
                f_bloq=muestras_bloq / c.n)


def clasificar(idx, eventos, n):
    """Para cada arribo: 'abre' (disparó la ventana), 'ocupado' (cayó dentro
    de una ventana abierta) o 'mudo' (el módulo estaba idle pero sin armar —
    no queda en NINGÚN contador del RTL)."""
    if not eventos:
        return np.full(idx.size, 'mudo', dtype='<U8')
    i0 = np.array([e[0] for e in eventos])
    i1 = np.array([e[1] for e in eventos])
    fuera = np.full(idx.size, 'mudo', dtype='<U8')
    for j, ii in enumerate(idx):
        p = np.searchsorted(i0, ii)
        if p < i0.size and i0[p] - ii <= 5:        # el pulso que la abrió
            fuera[j] = 'abre'
        elif p > 0 and ii < i1[p - 1]:             # llegó con la ventana abierta
            fuera[j] = 'ocupado'
    return fuera


def medir(t_arribo_us, t_fin_us, politica, k=None, **kw):
    x, idx = senal(t_arribo_us, t_fin_us, k)
    r = correr_fsm(x, politica, **kw)
    r['n_arribos'] = idx.size
    return r


# =============================================================================
# Fórmulas
# =============================================================================

TAU_FIJA_US  = (GATE_LONG + N_DIV) * DT_US          # compuerta corta + divisor
TAU_LARGA_US = (GATE_LARGO + N_DIV) * DT_US         # compuerta larga + divisor


def f_no_paralizable(n_hz, tau_us):
    return n_hz / (1.0 + n_hz * tau_us * 1e-6)


def f_paralizable(n_hz, tau_us):
    return n_hz * np.exp(-n_hz * tau_us * 1e-6)


# =============================================================================
# Figura 5 — el mismo tren, los dos modos
# =============================================================================

def fig_politicas(out):
    """El mismo tren visto por los dos modos de cierre del RTL.

    El tren está elegido para separar los dos mecanismos: un par a 6.5 us
    (la señal alcanza a bajar de thr_lo en el medio) y un par a 1.4 us (no
    alcanza). El segundo es el que ninguna compuerta detecta.
    """
    arribos = np.array([1.0, 5.5, 9.5, 16.0, 24.0, 25.4, 32.0])
    t_fin = 41.0
    k = kernel()
    x, idx = senal(arribos, t_fin, k)
    t = np.arange(x.size) * DT_US
    filas = ('compuerta', 'histeresis')

    fig, axs = plt.subplots(2, 1, figsize=(9.0, 4.6), sharex=True,
                            layout='constrained')

    for ax, pol in zip(axs, filas):
        r = correr_fsm(x, **CFG[pol])
        fin = t.size - 1
        for (i0, i1, destino) in r['eventos']:
            ax.axvspan(t[i0], t[min(i1, fin)],
                       color=GRILLA if destino == 'aceptado' else '#f6d8d8',
                       lw=0, zorder=0)
        for (i0, i1) in r['bloqueos']:
            ax.axvspan(t[min(i0, fin)], t[min(i1, fin)], facecolor='none',
                       edgecolor=ROJO, hatch='////', lw=0.0, zorder=1)
        ax.plot(t, x, color=TINTA2, lw=1.0, zorder=3)
        ax.axhline(THR_HI, color=MUDO, lw=0.7, ls='--')
        ax.axhline(THR_LO, color=MUDO, lw=0.7, ls=':')

        destinos = {e[0]: e[2] for e in r['eventos']}
        for ii, cls in zip(idx, clasificar(idx, r['eventos'], x.size)):
            if cls == 'abre':
                p = min(destinos, key=lambda a: abs(a - ii))
                col = AZUL if destinos[p] == 'aceptado' else ROJO
                marca = 'v' if destinos[p] == 'aceptado' else 'x'
            else:
                col, marca = (MUDO, '|') if cls == 'mudo' else (ROJO, '1')
            ax.plot(t[ii], 2.2 * THR_HI, marca, ms=8, color=col, zorder=5,
                    mew=1.8)

        ax.set_ylabel(ETIQUETA[pol].replace(', ', ',\n'), fontsize=8.5,
                      color=TINTA2)
        ax.set_yscale('symlog', linthresh=100)
        ax.set_ylim(0, 2.2 * AMP_CNT)
        ax.set_yticks([THR_LO, THR_HI, 1000, 8000])
        ax.set_yticklabels(['thr_lo', 'thr_hi', '1k', '8k'], fontsize=8)
        ax.grid(False)
        _limpiar(ax)

    axs[0].plot([], [], 'v', color=AZUL, ms=6.5, label='abre y se acepta')
    axs[0].plot([], [], '1', color=ROJO, ms=6.5, mew=1.4,
                label='perdido, ventana abierta')
    axs[0].plot([], [], '|', color=MUDO, ms=6.5, mew=1.4,
                label='perdido SIN armar (ningún contador)')
    axs[0].fill_between([], [], [], color=GRILLA, label='ocupado (feat_busy)')
    axs[0].fill_between([], [], [], facecolor='none', edgecolor=ROJO,
                        hatch='////', lw=0.0, label='bloqueado, no contado')
    axs[0].legend(loc='lower left', ncol=3, fontsize=8.2,
                  bbox_to_anchor=(0.0, 1.02))
    for ax, letra in zip(axs, 'ab'):
        _panel(ax, letra)
    axs[-1].set_xlabel(r'tiempo  [$\mu$s]')
    axs[-1].set_xlim(0, t_fin)

    fig.savefig(os.path.join(out, '05_politicas_trigger.png'))
    plt.close(fig)
    print('  05_politicas_trigger.png')


# =============================================================================
# Figura 6 — las curvas que resultan
# =============================================================================

T_MIN_US = 400.0        # piso de duración: si no, a tasa alta se mide ruido


def _arribos(n_hz, t_fin, periodico, seed):
    if periodico:
        return np.arange(0.0, t_fin, 1e6 / n_hz)
    rng = np.random.default_rng(seed)
    n = int(1.3 * n_hz * t_fin * 1e-6) + 50
    arr = np.cumsum(rng.exponential(1e6 / n_hz, size=n))
    return arr[arr < t_fin]


def _barrido(rates_hz, nombre, n_pulsos, periodico=False, seed=0):
    """Corre la FSM a cada tasa y devuelve (m_hz, perdida, n_arribos)."""
    k = kernel()
    m, perd, n_ev = [], [], []
    for i, n_hz in enumerate(rates_hz):
        t_fin = max(1e6 * n_pulsos / n_hz, T_MIN_US)        # us
        arr = _arribos(n_hz, t_fin, periodico, seed + i)
        r = medir(arr, t_fin, k=k, **CFG[nombre])
        m.append(r['aceptados'] / (t_fin * 1e-6))
        perd.append(1.0 - r['aceptados'] / max(r['n_arribos'], 1))
        n_ev.append(r['n_arribos'])
    return np.array(m), np.array(perd), np.array(n_ev)


def fig_curvas(out, rapido=False):
    tau_h = t_sobre_thr_lo() * DT_US + N_DIV * DT_US       # paralizable
    n_pulsos = 1500 if rapido else 5000
    n_sim = 9 if rapido else 13

    n_lin = np.logspace(np.log10(3e3), np.log10(1.2e6), 400)
    n_pts = np.logspace(np.log10(2e4), np.log10(8e5), n_sim)

    fig, axs = plt.subplots(1, 3, figsize=(11.0, 4.6))
    fig.subplots_adjust(bottom=0.38, top=0.93, left=0.065, right=0.985,
                        wspace=0.30)
    ax_m, ax_p, ax_t = axs

    # El tiempo muerto EFECTIVO de cada configuración es el mayor entre el
    # cierre de la ventana y la cola sobre thr_lo: mientras la señal no baje,
    # el Schmitt no re-arma. Esa es la predicción que la simulación pone a
    # prueba, y el modelo es PARALIZABLE salvo si el re-armado es por contador.
    modelo = {
        'compuerta':  max(TAU_FIJA_US, tau_h),
        'histeresis': tau_h,
        'gate_largo': max(TAU_LARGA_US, tau_h),
        'rearme':     None,       # no sigue ningún modelo: cuenta de más
    }
    ln, = ax_m.plot(n_lin / 1e3, n_lin / 1e3, color=MUDO, lw=0.9, ls=':')
    ax_p.axhline(0.0, color=MUDO, lw=0.9, ls=':')
    manijas0, rotulos0 = [ln], ['ideal, $m = n$']
    # referencia: el MISMO tau, pero no paralizable. Es la comparación justa.
    ln, = ax_m.plot(n_lin / 1e3, f_no_paralizable(n_lin, tau_h) / 1e3,
                    color=TINTA2, lw=1.1, ls='-.')
    ax_p.plot(n_lin / 1e3, 1 - f_no_paralizable(n_lin, tau_h) / n_lin,
              color=TINTA2, lw=1.1, ls='-.')
    manijas0.append(ln)
    rotulos0.append(rf'referencia NO paralizable $n/(1+n\tau)$ con el MISMO '
                    rf'$\tau$ = {tau_h:.1f} $\mu$s')

    # --- simulación: Poisson ----------------------------------------------
    print(f'    simulando Poisson ({n_sim} tasas x {len(POLITICAS)} '
          f'políticas, {n_pulsos} pulsos)...')
    manijas, rotulos = [], []
    for pol in POLITICAS:
        tau = modelo[pol]
        if tau is not None:
            ax_m.plot(n_lin / 1e3, f_paralizable(n_lin, tau) / 1e3,
                      color=COLOR[pol], lw=1.1, ls='--')
            ax_p.plot(n_lin / 1e3, 1 - f_paralizable(n_lin, tau) / n_lin,
                      color=COLOR[pol], lw=1.1, ls='--')
            et = (rf'{ETIQUETA[pol]}  ·  PARALIZABLE $n\,e^{{-n\tau}}$, '
                  rf'$\tau$ = {tau:.1f} $\mu$s')
        else:
            et = rf'{ETIQUETA[pol]}  ·  no pierde: CUENTA DE MÁS'

        m, perd, nev = _barrido(n_pts, pol, n_pulsos)
        err = np.sqrt(np.maximum(np.abs(perd) * (1 - np.abs(perd)), 1e-6)
                      / nev)
        pt, = ax_m.plot(n_pts / 1e3, m / 1e3, MARCA[pol], color=COLOR[pol],
                        ms=4.5, mfc='none', mew=1.2)
        ax_p.errorbar(n_pts / 1e3, perd, yerr=err, fmt=MARCA[pol],
                      color=COLOR[pol], ms=4.5, mfc='none', mew=1.2,
                      elinewidth=0.9, capsize=2)
        manijas.append(pt)
        rotulos.append(et)

    manijas = manijas0 + manijas
    rotulos = rotulos0 + rotulos
    ax_m.set_xscale('log')
    ax_m.set_yscale('log')
    ax_m.set_xlim(3, 1200)
    ax_m.set_ylim(2, 400)
    ax_m.set_xlabel('tasa incidente  [kcps]  —  Poisson')
    ax_m.set_ylabel('tasa registrada  [kcps]')
    _limpiar(ax_m)
    _panel(ax_m, 'a')

    ax_p.set_xscale('log')
    ax_p.set_xlim(3, 1200)
    ax_p.set_ylim(-1.05, 1.05)
    ax_p.set_xlabel('tasa incidente  [kcps]  —  Poisson')
    ax_p.set_ylabel(r'$1 - m/n$   (negativo: cuenta de más)')
    _limpiar(ax_p)
    _panel(ax_p, 'b')

    # --- simulación: PERIÓDICO, el ensayo que las separa -------------------
    print('    simulando periódico...')
    n_per = np.logspace(np.log10(2e4), np.log10(6e5), n_sim)
    for pol in POLITICAS:
        m, _, _ = _barrido(n_per, pol, max(n_pulsos // 4, 400), periodico=True)
        ax_t.plot(n_per / 1e3, np.maximum(m, 1e-3) / 1e3, MARCA[pol] + '-',
                  color=COLOR[pol], ms=4.0, lw=1.2, mfc='none', mew=1.1)
    ax_t.plot(n_lin / 1e3, n_lin / 1e3, color=MUDO, lw=0.9, ls=':')
    ax_t.axvline(1e-3 / (tau_h * 1e-6), color=MUDO, lw=0.8, ls='--')
    ax_t.set_xscale('log')
    ax_t.set_yscale('log')
    ax_t.set_xlim(15, 800)
    ax_t.set_ylim(1, 400)
    ax_t.set_xlabel('tasa incidente  [kcps]  —  PERIÓDICO')
    ax_t.set_ylabel('tasa registrada  [kcps]')
    _limpiar(ax_t)
    _panel(ax_t, 'c')

    fig.legend(manijas, rotulos, loc='lower center', ncol=2, fontsize=7.2,
               labelspacing=0.4, columnspacing=1.6,
               bbox_to_anchor=(0.5, 0.005), bbox_transform=fig.transFigure)
    fig.savefig(os.path.join(out, '06_paralizable_vs_no.png'))
    plt.close(fig)
    print('  06_paralizable_vs_no.png')
    return tau_h


# =============================================================================
# Figura 7 — el tiempo muerto que feat_busy no cuenta
# =============================================================================

def fig_oculto(out, rapido=False):
    k = kernel()

    # --- (a) el caso, en el tiempo ----------------------------------------
    # dos pulsos: el 2do llega con el módulo ocupado -> se pierde Y desarma.
    # El sistema no puede abrir hasta que la cola del PERDIDO baje de thr_lo.
    arribos = np.array([1.0, 4.4, 13.0])
    t_fin = 21.0
    x, idx = senal(arribos, t_fin, k)
    t = np.arange(x.size) * DT_US
    r = correr_fsm(x, **CFG['compuerta'])
    fin = t.size - 1

    # El cronograma va en su PROPIA figura: se lee sobre un eje de tiempo,
    # mientras que (b) se lee sobre un eje de tasas. Mezclarlos obligaba a
    # cambiar de unidades a mitad de la imagen.
    fig_c, (ax_a, ax_w) = plt.subplots(2, 1, figsize=(8.0, 3.6), sharex=True,
                                       layout='constrained',
                                       gridspec_kw={'height_ratios': (2.0, 1.0)})
    fig = plt.figure(figsize=(5.6, 3.9), layout='constrained')
    ax_b = fig.add_subplot(1, 1, 1)

    # --- la señal ---------------------------------------------------------
    ax_a.plot(t, x, color=TINTA2, lw=1.1, zorder=3)
    ax_a.axhline(THR_HI, color=MUDO, lw=0.7, ls='--')
    ax_a.axhline(THR_LO, color=MUDO, lw=0.7, ls=':')
    for ii, cls in zip(idx, clasificar(idx, r['eventos'], x.size)):
        col, marca = {'abre': (AZUL, 'v'), 'ocupado': (ROJO, '1'),
                      'mudo': (MUDO, '|')}[cls]
        ax_a.plot(t[ii], 2.4 * THR_HI, marca, ms=8, mew=1.8, color=col,
                  zorder=5)
    ax_a.set_yscale('symlog', linthresh=100)
    ax_a.set_ylim(0, 2.6 * AMP_CNT)
    ax_a.set_yticks([THR_LO, THR_HI, 1000, 8000])
    ax_a.set_yticklabels(['thr_lo', 'thr_hi', '1k', '8k'], fontsize=8)
    ax_a.tick_params(labelbottom=False)
    ax_a.grid(False)
    _limpiar(ax_a)
    _panel(ax_a, 'a')
    ax_a.plot([], [], 'v', color=AZUL, ms=8, label='abre y se acepta')
    ax_a.plot([], [], '|', color=MUDO, ms=8, mew=1.8,
              label='perdido SIN armar (ningún contador)')
    ax_a.legend(loc='lower left', ncol=2, fontsize=8,
                bbox_to_anchor=(0.0, 1.02))

    # --- el cronograma de los dos "relojes" -------------------------------
    busy = [(t[i0], t[min(i1, fin)] - t[i0]) for (i0, i1, _) in r['eventos']]
    bloq = busy + [(t[min(i0, fin)], t[min(i1, fin)] - t[min(i0, fin)])
                   for (i0, i1) in r['bloqueos']]
    ax_w.broken_barh(busy, (1.08, 0.72), facecolor=GRILLA, edgecolor=TINTA2,
                     lw=0.6)
    ax_w.broken_barh(bloq, (0.20, 0.72), facecolor='#fadbd8',
                     edgecolor=ROJO, lw=0.6)
    ax_w.set_yticks([1.44, 0.56])
    ax_w.set_yticklabels(['feat_busy\n(lo que cuenta el FPGA)',
                          'bloqueo real\n(no puede abrir)'], fontsize=7.5)
    ax_w.set_ylim(0, 2.0)
    ax_w.set_xlim(0, t_fin)
    ax_w.set_xlabel(r'tiempo  [$\mu$s]')
    ax_w.grid(False)
    for lado in ('top', 'right', 'left'):
        ax_w.spines[lado].set_visible(False)
    ax_w.tick_params(axis='y', length=0)
    _panel(ax_w, 'b')
    fig_c.savefig(os.path.join(out, '07a_cronograma.png'))
    plt.close(fig_c)
    print('  07a_cronograma.png')

    # --- (b) cuánto, contra la tasa ---------------------------------------
    n_pulsos = 1500 if rapido else 5000
    n_pts = np.logspace(np.log10(2e4), np.log10(8e5), 9 if rapido else 13)
    print('    simulando tiempo muerto contado vs real...')
    tabla = {}
    for pol in ('compuerta', 'gate_largo'):
        f_busy, f_bloq = [], []
        for i, n_hz in enumerate(n_pts):
            t_sim = max(1e6 * n_pulsos / n_hz, T_MIN_US)
            arr = _arribos(n_hz, t_sim, False, 900 + i)
            rr = medir(arr, t_sim, k=k, **CFG[pol])
            f_busy.append(rr['f_busy'])
            f_bloq.append(rr['f_bloq'])
        tabla[pol] = (np.array(f_busy), np.array(f_bloq))

    for pol, mk in (('compuerta', 'o'), ('gate_largo', 's')):
        f_busy, f_bloq = tabla[pol]
        col = COLOR[pol]
        ax_b.plot(n_pts / 1e3, 100 * f_busy, mk + '--', color=col, ms=4,
                  lw=1.0, mfc='none',
                  label=f'{ETIQUETA[pol]}: `deadtime_cnt`')
        ax_b.plot(n_pts / 1e3, 100 * f_bloq, mk + '-', color=col, ms=4,
                  lw=1.6, label=f'{ETIQUETA[pol]}: bloqueo real')
        ax_b.fill_between(n_pts / 1e3, 100 * f_busy, 100 * f_bloq,
                          color=col, alpha=0.12, lw=0)
    ax_b.set_xscale('log')
    ax_b.set_xlim(15, 1000)
    ax_b.set_ylim(0, 105)
    ax_b.set_xlabel('tasa incidente  [kcps]')
    ax_b.set_ylabel('fracción del tiempo  [%]')
    ax_b.legend(loc='upper left', fontsize=6.8)
    _limpiar(ax_b)

    fig.savefig(os.path.join(out, '07b_deadtime_oculto.png'))
    plt.close(fig)
    print('  07b_deadtime_oculto.png')
    return n_pts, tabla


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='dónde dejar los PNG')
    ap.add_argument('--rapido', action='store_true',
                    help='menos pulsos por punto: para iterar el dibujo')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    n_lo = t_sobre_thr_lo()
    print(f'pulso: {n_lo} muestras sobre thr_lo = {n_lo*DT_US:.2f} us '
          f'(el RTL :206 reporta ~700)')
    print(f'tau ventana fija  = {TAU_FIJA_US:.3f} us  -> 1/tau = '
          f'{1e-3/(TAU_FIJA_US*1e-6):.0f} kcps')
    print(f'tau histéresis    = {(n_lo+N_DIV)*DT_US:.3f} us  -> 1/tau = '
          f'{1e-3/((n_lo+N_DIV)*DT_US*1e-6):.0f} kcps')
    print(f'tau compuerta 384 = {TAU_FIJA_US:.3f} us  -> 1/tau = '
          f'{1e-3/(TAU_FIJA_US*1e-6):.0f} kcps')
    print(f'tau compuerta 1024= {TAU_LARGA_US:.3f} us  -> 1/tau = '
          f'{1e-3/(TAU_LARGA_US*1e-6):.0f} kcps')
    print(f'figuras en {os.path.relpath(a.out)}:')
    fig_politicas(a.out)
    tau_h = fig_curvas(a.out, a.rapido)
    n_pts, tabla = fig_oculto(a.out, a.rapido)

    # --- los números que cita el README -----------------------------------
    taus = {'compuerta': max(TAU_FIJA_US, tau_h), 'histeresis': tau_h,
            'gate_largo': max(TAU_LARGA_US, tau_h), 'rearme': TAU_FIJA_US}
    print('\nperdida [%]: simulada (sim) contra el modelo que le toca (mod)')
    print('         modo1-384      modo0-hist     modo1-1024     re-armado')
    print('         PAR 5.9us      PAR 5.9us      PAR 8.2us      NO-PAR 3.1us')
    print('  kcps   sim   mod      sim   mod      sim   mod      sim   mod')
    n_tab = np.array([2e4, 5e4, 1e5, 2e5, 4e5])
    sims = {p: _barrido(n_tab, p, 1500 if a.rapido else 4000)[1]
            for p in POLITICAS}
    for j, n_hz in enumerate(n_tab):
        fila = ''
        for p in POLITICAS:
            f = f_no_paralizable if p == 'rearme' else f_paralizable
            mod = 1 - f(n_hz, taus[p]) / n_hz
            fila += f'{100*sims[p][j]:7.1f}{100*mod:6.1f}  '
        print(f'  {n_hz/1e3:<6.0f}' + fila)

    print('\ntiempo muerto: contado por el FPGA contra el real [%]')
    print('  kcps   modo1-384 cnt / real    modo1-1024 cnt / real')
    for j, n_hz in enumerate(n_pts):
        if j % (2 if a.rapido else 3):
            continue
        b1, r1 = tabla['compuerta'][0][j], tabla['compuerta'][1][j]
        b2, r2 = tabla['gate_largo'][0][j], tabla['gate_largo'][1][j]
        print(f'  {n_hz/1e3:<6.0f}{100*b1:10.1f} /{100*r1:6.1f}'
              f'{100*b2:16.1f} /{100*r2:6.1f}')


if __name__ == '__main__':
    main()
