#!/usr/bin/env python3
"""Varianza de cada estimador de amplitud, familia de forma por familia.

Contesta con números la pregunta que `docs/mca/fuentes_de_jitter.md` dejaba
planteada en prosa: **cuánto vale la varianza de cada estimador sobre cada forma
de pulso**, y de qué término viene.

QUÉ SE CALCULA
--------------
1. **El modelo de ruido, medido.** No se postula σ: se lee de las 7054 ventanas
   crudas de `datos/e2e_20260528_013404/principal/` (las mismas del análisis de
   `API/modelo_rtl/`). De las 9 muestras de pre-disparo de cada ventana salen
   dos números distintos:
     - `sigma_n`: el ruido BLANCO por muestra (desvío dentro de la ventana,
       después de quitarle a cada ventana su propia media);
     - `sigma_bl`: el error de LÍNEA DE BASE por evento, común a todas las
       muestras de esa ventana. Sale del exceso de la dispersión de las medias
       de ventana sobre lo que predeciría el ruido blanco solo.
   La distinción es todo el asunto: el blanco promedia como 1/sqrt(N) y el de
   base NO promedia — se multiplica por N en una integral.

2. **La geometría de cada familia**: área/pico (`Sf`), energía (`Sf2`), cuántas
   muestras hay dentro de un ruido del ápice (`M_ef`) y el radio de curvatura
   del pico. Son los tres números que deciden, respectivamente, la integral, la
   cota de Cramér-Rao y el estimador de pico.

3. **Monte Carlo de los cuatro estimadores** sobre cada familia, con la misma
   réplica del RTL que usa el estudio de apilamiento (`replica_mca2.py`, con una
   ranura, la compuerta y el disparo por pendiente):
     - `pico`        muestra de pico             (`cfg_amp_src = 0`)
     - `pico_par`    pico interpolado a 3 puntos (NO está en el RTL)
     - `q_fija`      integral de la compuerta    (`cfg_amp_src = 1`)
     - `trapecio`    la meseta de `F_TRAP`, con k = FWHM/4, m = FWHM y el polo-cero
                     de la cola de la forma (si la tiene)
   `--mapa MCA1` corre el estudio viejo, con `q_hist` (la integral de la ventana
   por histéresis, que el MCA2 ya no tiene) en vez del trapecio.
   La fase de muestreo se barre ESTRATIFICADA (una grilla uniforme de sub-
   muestra), así que la descomposición de la varianza es exacta por ANOVA:

       sigma_tot^2 = E_fase[Var(est | fase)]  +  Var_fase(E[est | fase])
                     \_____ ruido ______/        \_____ fase ______/

   y el término de ruido se parte a su vez corriendo el mismo lote con
   `sigma_bl = 0`.

4. **La cota de Cramér-Rao**: con la forma y la fase conocidas, ningún
   estimador lineal de amplitud puede bajar de `sigma_n / sqrt(Sf2)`. Es la vara
   contra la que se mide cuánto deja cada estimador sobre la mesa.

CÓMO SE VALIDA
--------------
La familia `referencia` no es de Knoll: es la forma real del estímulo de la
campaña (`pileup.forma_referencia`, ajustada al FWHM y a la cola medidos). Sus
números predichos se comparan contra los medidos sobre esos mismos pulsos
(0.272 % pico, 0.149 % compuerta fija) y contra los del hardware. Si eso cierra,
las predicciones por familia valen; si no, lo que falla es el modelo de ruido.

    python3 varianza_estimadores.py                 # tablas + figura
    python3 varianza_estimadores.py --n 32000       # más estadística
    python3 varianza_estimadores.py --amp 800       # otra amplitud
    python3 varianza_estimadores.py --sin-figura
    python3 varianza_estimadores.py --mapa MCA1     # el estudio con el mapa viejo
"""

import argparse
import glob
import os
import sys
from functools import lru_cache

import numpy as np
from scipy import signal as sig
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                   # noqa: E402

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

import pileup as pu                                               # noqa: E402
import replica_mca2 as r2                                    # noqa: E402
import ruido as ru                                                # noqa: E402

_RAIZ = os.path.dirname(_AQUI)                                    # software/
sys.path.insert(0, _RAIZ)
import API.rigol_dg4162 as rg                                     # noqa: E402

TRAZAS = os.path.join(_RAIZ, 'datos', 'e2e_20260528_013404', 'principal')
FIGURAS = os.path.join(_RAIZ, '..', 'docs', 'mca', 'figuras')

FAMILIAS = ('cr', 'cr_rc', 'cr_rc4', 'triangular', 'trapezoidal', 'bipolar')
ETIQUETA = {'cr': 'CR', 'cr_rc': 'CR-RC', 'cr_rc4': 'CR-RC⁴',
            'triangular': 'triangular', 'trapezoidal': 'trapezoidal',
            'bipolar': 'bipolar', 'referencia': 'referencia (ARB real)'}

ESTIMADORES = ('pico', 'pico_par', 'q_fija', 'trapecio')    # MCA1: ver main()
ESTIMADORES_MCA1 = ('pico', 'pico_par', 'q_hist', 'q_fija')
NOMBRE_EST = {'pico': 'pico', 'pico_par': 'pico interp.',
              'q_hist': 'Q histéresis', 'q_fija': 'Q fija 384',
              'trapecio': 'trapecio'}

# Resolución (FWHM/centroide) medida, en %. Es contra esto que se valida la
# fila `referencia`. Dos columnas, y la distinción importa:
#   - OFFLINE: calculada sobre las MISMAS 7054 trazas crudas que le dan el
#     modelo de ruido a este script. Es la comparación limpia.
#   - PLACA: el mismo estimador medido con el espectro del hardware. Incluye lo
#     que el modelo no simula (deriva durante la adquisición, bineado, ajuste
#     del pico, dispersión de amplitud del propio generador), así que es
#     normal —y esperable— que dé algo peor.
# Fuentes: API/modelo_rtl/README.md y docs/resultados_validacion_hw.md §13.6,
# §14.2 (la histéresis en placa re-medida en las mismas condiciones da 0.325 %;
# el 0.528 % de la 2ª campaña está retirado como referencia).
MEDIDO_OFFLINE = {'pico': 0.272, 'q_fija': 0.149}
MEDIDO_PLACA = {'pico': 0.344, 'q_hist': 0.325, 'q_fija': 0.161}

# Paleta del proyecto (docs/mca/figuras/figuras_resolucion.py)
SUP, TINTA, TINTA2, MUDO, GRILLA = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9'
AZUL, NARAN, ROJO, VERDE = '#2a78d6', '#eb6834', '#d03b3b', '#2e8b57'
plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})


# =============================================================================
# 1. El modelo de ruido, medido sobre las trazas crudas
# =============================================================================

def modelo_ruido(dirtraz=TRAZAS):
    """El ruido medido, separado en blanco y correlacionado.

    No se mide acá: se reusa `ruido.ruido_medido`, que es el estimador cuidado
    de [`../../docs/ruido_del_sistema.md`](../../docs/ruido_del_sistema.md) §3 —
    autocovarianza sobre el canal que estaba EN VACÍO, quitando el perfil medio
    sobre eventos y no la media de cada ventana (quitar la media por ventana
    induce una correlación negativa espuria de −1/(n−1) y borra justo el término
    que se busca).

    Devuelve los dos términos que después se inyectan por separado:

      sigma_w : blanco, descorrelacionado a 8 ns. Promedia como 1/sqrt(N).
      sigma_c : correlacionado, con tau ~ 12 µs. En una ventana de 3 µs es
                prácticamente un offset constante, así que NO promedia; en una
                de 8 µs ya promedia un poco. Por eso se simula como proceso
                (Ornstein-Uhlenbeck) y no como una constante por evento: el
                largo de la ventana cambia de familia en familia, y con una
                constante el término quedaría sobreestimado en las más largas.

    Lo que este modelo NO incluye es el seguidor de línea de base del RTL, que
    resta una estimación de la base en vivo y baja el término correlacionado de
    0.87 a ~0.76 cuentas (`ruido_del_sistema.md` §5). El término de base de acá
    es entonces el de ANTES del seguidor: pesimista en un 15 %, y por un factor
    conocido.
    """
    wave, t_ns = ru.cargar_campana(dirtraz)
    r = ru.ruido_medido(wave, t_ns)
    return dict(sigma_n=r['sigma_w'], sigma_bl=r['sigma_c'],
                tau_c=r['tau_c_muestras'], tau_c_us=r['tau_c_us'],
                sigma_tot=r['sigma_tot'], f_codo_khz=r['f_codo_khz'],
                sigma_pre_senal=r['sigma_pre_senal'],
                sigma_pre_vacio=r['sigma_pre_vacio'],
                n_ventanas=r['n_ventanas'], n_muestras=r['n_muestras'])


def ou_lote(forma, sigma, tau_muestras, rng):
    """Ruido correlacionado (AR(1)) para una matriz de eventos, vectorizado.

    Una fila por evento: el proceso arranca estacionario en cada una y corre a
    lo largo de la ventana. Arrancar de nuevo en cada evento es lo correcto acá
    —los eventos reales están a 1 ms y tau es 12 µs, así que no se acuerdan uno
    del otro—, y es lo que permite usar `lfilter` sobre el eje del tiempo en vez
    del lazo en Python de `ruido._ou`, que con estos lotes no termina nunca.

    La condición inicial sale de `lfiltic` con una muestra estacionaria: sin
    eso, las primeras ~tau muestras de cada fila tendrían menos varianza que el
    resto y el término quedaría subestimado.
    """
    n_ev, n = forma
    a = float(np.exp(-1.0 / float(tau_muestras)))
    e = rng.normal(0.0, sigma * np.sqrt(1.0 - a * a), size=(n_ev, n))
    x0 = rng.normal(0.0, sigma, size=(n_ev, 1))
    zi = (a * x0)                                   # estado inicial del AR(1)
    y, _ = sig.lfilter([1.0], [1.0, -a], e, axis=1, zi=zi)
    return y


# =============================================================================
# 2. Geometría de cada familia, con fase de sub-muestra
# =============================================================================

@lru_cache(maxsize=64)
def _continua(familia, fwhm_s, fs_hz=pu.FS_HZ, piso=1e-5):
    """(f, escala, u_max, pico_continuo) de una familia del catálogo.

    `escala` sale de `rigol_dg4162._escala_para_fwhm`, el MISMO despeje que usó
    la campaña para cargarle la onda al generador: la forma de acá y la que vio
    la placa son la misma función.
    """
    f = rg.FORMAS_KNOLL[familia]
    escala = rg._escala_para_fwhm(f, float(fwhm_s) * float(fs_hz))
    u = np.arange(0.0, 400.0, 1.0 / 4096.0)
    y = np.asarray(f(u), dtype=float)
    pico = float(y.max())
    i_pk = int(np.argmax(y))
    cola = np.flatnonzero(np.abs(y[i_pk:]) < piso * pico)
    u_max = float(u[i_pk + int(cola[0])]) if cola.size else float(u[-1])
    return f, escala, u_max, pico


def plantilla(familia, fwhm_s, fase, fs_hz=pu.FS_HZ):
    """La forma muestreada con la grilla corrida `fase` muestras (0 ≤ fase < 1).

    Normalizada por el pico de la función CONTINUA, no por el máximo muestreado:
    así la amplitud verdadera del pulso es la misma para toda fase y el déficit
    de la muestra de pico es un error de estimación, no de definición. (Es la
    única diferencia con `pileup.forma_knoll`, que normaliza al máximo
    muestreado porque ahí lo que importa es la forma, no el sesgo.)
    """
    f, escala, u_max, pico = _continua(familia, fwhm_s, fs_hz)
    n = int(np.ceil(u_max * escala)) + 1
    u = (np.arange(n, dtype=float) + float(fase)) / escala
    return np.asarray(f(u), dtype=float) / pico


@lru_cache(maxsize=64)
def _continua_ref(fwhm_s, fs_hz=pu.FS_HZ):
    """(t_rise, tau, n) de la forma real del estímulo a ese ancho.

    La cola se ESCALA con el ancho (`tau = 186 muestras × fwhm/2 µs`) en vez de
    quedar fija. Si no, pedirle a `forma_referencia` un FWHM por debajo de
    `tau·ln2` ≈ 1 µs no da la misma forma más angosta: da un escalón con la
    misma cola de 1.5 µs, que es otra familia. Barrer el ancho con la cola fija
    mediría eso y no el estimador.
    """
    tau = pu.TAU_COLA * float(fwhm_s) / pu.FWHM_S
    _, info = pu.forma_referencia(fwhm_s=fwhm_s, tau_muestras=tau, fs_hz=fs_hz)
    return info['t_rise'], info['tau'], info['n']


def plantilla_ref(fwhm_s, fase, fs_hz=pu.FS_HZ):
    """Lo mismo para la forma real del estímulo (`pileup.forma_referencia`).

    `detector_pulse` es analítica, así que la fase se mete corriendo el eje y se
    normaliza por el pico continuo, que para (1-e^{-t/tr})·e^{-t/tau} tiene
    expresión cerrada.
    """
    tr, tau, n = _continua_ref(fwhm_s, fs_hz)
    t = np.arange(n, dtype=float) + float(fase)
    y = (1.0 - np.exp(-t / tr)) * np.exp(-t / tau)
    t_pico = tr * np.log1p(tau / tr)                     # dy/dt = 0
    pico = (1.0 - np.exp(-t_pico / tr)) * np.exp(-t_pico / tau)
    return np.clip(y, 0.0, None) / pico


def geometria(familia, fwhm_s, sigma_rel, n_fase=16):
    """Los números de forma que deciden cada estimador, promediados en fase.

    - `Sf`  = Σ f_i      : área/pico en muestras. Es el factor de forma × FWHM,
                           y es lo que multiplica a la amplitud en la integral.
    - `Sf2` = Σ f_i²     : la "energía" de la forma. Es lo único que entra en la
                           cota de Cramér-Rao del ajuste de amplitud.
    - `M_ef`             : cuántas muestras caen a menos de un ruido del ápice.
                           Es el M del máximo de M gaussianas: decide a la vez el
                           sesgo y la varianza del estimador de pico.
    - `caida`            : cuánto cae el pulso, en unidades del ruido, entre el
                           pico verdadero y la muestra vecina en el peor caso de
                           fase. Mide lo "en punta" que es el ápice.
    """
    Sf, Sf2, Mef, caida = [], [], [], []
    for fase in np.arange(n_fase) / n_fase:
        y = (plantilla_ref(fwhm_s, fase) if familia == 'referencia'
             else plantilla(familia, fwhm_s, fase))
        yp = np.clip(y, 0.0, None)
        Sf.append(yp.sum())
        Sf2.append((yp ** 2).sum())
        Mef.append(int(np.count_nonzero(y > 1.0 - sigma_rel)))
        k = int(np.argmax(y))
        caida.append(1.0 - y[k])
    return dict(Sf=float(np.mean(Sf)), Sf2=float(np.mean(Sf2)),
                M_ef=float(np.mean(Mef)), caida_max=float(np.max(caida)),
                n=int(y.size))


# =============================================================================
# 3. Monte Carlo
# =============================================================================

def _parabolico(x, k):
    """Pico interpolado con las tres muestras alrededor de `k`, vectorizado.

    Vértice de la parábola por los tres puntos. Tres guardas, y las tres hacen
    falta: el ápice tiene que ser cóncavo (si no, es ruido sobre un techo
    plano), el desplazamiento no puede pasar de media muestra, y los dos
    vecinos tienen que estar **arriba de la mitad del pico** — si uno de los dos
    está en la línea de base, las tres muestras no pertenecen a un mismo ápice y
    la parábola no describe nada (es el caso del flanco abrupto, donde la
    corrección se va al 12 % de la amplitud). Cuando alguna falla se devuelve la
    muestra de pico cruda, que es lo que haría cualquier implementación real.
    """
    y0, y1, y2 = x[k - 1].astype(float), x[k].astype(float), x[k + 1].astype(float)
    den = y0 - 2.0 * y1 + y2
    with np.errstate(divide='ignore', invalid='ignore'):
        d = 0.5 * (y0 - y2) / den
        est = y1 - 0.25 * (y0 - y2) * d
    ok = ((den < 0) & np.isfinite(d) & (np.abs(d) <= 0.5)
          & (np.minimum(y0, y2) > 0.5 * y1))
    return np.where(ok, est, y1)


def _lote(tpl, amp, n_ev, sigma_n, sigma_bl, tau_c, rng, guarda=512, lead=64):
    """`n_ev` pulsos idénticos y aislados, con ruido blanco y offset por evento.

    Cada evento vive en su propia fila de `paso` muestras, con el pulso corrido
    `lead` del arranque y `guarda` muestras de aire al final; después se aplana.
    Así los eventos no se tocan (la cola ya cayó por debajo de 1e-5 del pico) y
    la segmentación los ve como el RTL ve pulsos espaciados.

    El ruido entra en dos partes, que es lo que las separa: el blanco, muestra
    a muestra, y el correlacionado, como proceso con tau = 12 µs. El segundo es
    el que no promedia dentro de la ventana y el que por eso manda en la
    integral.
    """
    L = tpl.size
    paso = lead + L + guarda
    x = np.zeros((n_ev, paso), dtype=float)
    x[:, lead:lead + L] = amp * tpl
    x += rng.normal(0.0, sigma_n, size=x.shape)
    if sigma_bl > 0:
        x += ou_lote((n_ev, paso), sigma_bl, tau_c, rng)
    return np.rint(x.ravel()).astype(np.int64), paso, lead


AMP_PRE = 1920.0       # la línea del estudio de apilamiento


def _sufijo():
    """Las figuras del MCA1 siguen en docs/mca/fuentes_de_jitter.md §5: no se pisan."""
    return '_mca2' if 'trapecio' in ESTIMADORES else ''


def _mq_cola(tpl):
    """M*16 para la cola de la forma, si tiene una cola exponencial. Si no (el
    triangular, el trapezoidal, el bipolar) es 0: el trapecio de un impulso."""
    i = int(np.argmax(tpl))
    y = np.asarray(tpl, dtype=float)[i:]
    m = (y < 0.3) & (y > 0.03)
    if m.sum() < 8:
        return 0
    x = np.flatnonzero(m).astype(float)
    a, b = np.polyfit(x, np.log(y[m]), 1)
    if a >= 0 or np.std(np.log(y[m]) - (a * x + b)) > 0.02:
        return 0
    return int(round(16.0 / np.expm1(-a)))


def _cfg_mca2(tpl, fwhm_s, cfg1, sigma_n):
    """La réplica de una ranura para esta forma: el disparo, la compuerta y el
    trapecio. `pre_dly` se ajusta a la línea del estudio (`AMP_PRE`), para que la
    ventana abra en el pie, como se configuraría; al barrer la amplitud no se toca,
    así que la INL incluye el corrimiento del disparo. Sin lugar para la meseta en
    la compuerta (pulsos muy cortos con k y m que no escalan bien), sin trapecio."""
    fwhm = float(fwhm_s) * pu.FS_HZ
    c = r2.cfg(n_acc=1, gate_short=cfg1['corta'], gate_long=cfg1['larga'],
               trap_k=max(int(round(fwhm / 4)), 1), trap_m=max(int(round(fwhm)), 1),
               trap_mq=_mq_cola(tpl), **r2.disparo_para(tpl, a_pre=AMP_PRE, sigma=sigma_n))
    t = r2.trap_para(tpl, c)
    return {**c, **t} if t else {**c, 'trap': False}


def _corrida_mca2(familia, fwhm_s, amp, ruido, rng, n_fase, por_fase, cfg1, con_base):
    """`corrida` sobre la réplica del MCA2: todos los estimadores salen de la misma
    ventana, así que un evento es una fila con su primer disparo."""
    sal = {e: [] for e in ESTIMADORES}
    fases, largos = [], []
    perdidos = 0
    tpl0 = (plantilla_ref(fwhm_s, 0.0) if familia == 'referencia'
            else plantilla(familia, fwhm_s, 0.0))
    c = _cfg_mca2(tpl0, fwhm_s, cfg1, ruido['sigma_n'])
    for i_f, fase in enumerate(np.arange(n_fase) / n_fase):
        tpl = (plantilla_ref(fwhm_s, fase) if familia == 'referencia'
               else plantilla(familia, fwhm_s, fase))
        dat, paso, _ = _lote(tpl, amp, por_fase, ruido['sigma_n'],
                             ruido['sigma_bl'] if con_base else 0.0,
                             ruido['tau_c'], rng)
        ev, _ = r2.eventos_mc(dat, c)
        fila = ev['i_par'] // paso
        ok = np.diff(np.concatenate(([-1], fila))) > 0
        perdidos += por_fase - int(ok.sum())
        if not ok.any():
            continue
        i0, t_pico = ev['i0'][ok], ev['t_pico'][ok]
        sal['pico'].append(ev['pico'][ok].astype(float))
        sal['pico_par'].append(_parabolico(dat, i0 + t_pico))
        sal['q_fija'].append(ev['q_tot'][ok].astype(float))
        sal['trapecio'].append(ev['trap'][ok].astype(float))
        fases.append(np.full(int(ok.sum()), i_f))
        largos.append(ev['largo'][ok].astype(float))
    if not fases:
        return None
    return {e: np.concatenate(v) for e, v in sal.items()} | \
           {'_fase': np.concatenate(fases), '_perdidos': perdidos,
            '_largo': np.concatenate(largos),
            '_n': int(np.concatenate(fases).size)}


def corrida(familia, fwhm_s, amp, n_ev, ruido, rng, n_fase=32,
            cfg0=None, cfg1=None, con_base=True):
    """Devuelve, por estimador, el array de estimaciones y su bin de fase.

    La fase se barre estratificada: `n_fase` valores equiespaciados en [0,1),
    `n_ev//n_fase` eventos cada uno. Con eso la media sobre fases ES la
    esperanza de la uniforme (no una muestra de ella), y la descomposición
    intra/entre bins de la varianza es exacta.
    """
    cfg0 = cfg0 or pu.CFG_MODO0
    cfg1 = cfg1 or pu.CFG_MODO1
    por_fase = max(int(n_ev // n_fase), 1)
    if 'trapecio' in ESTIMADORES:
        return _corrida_mca2(familia, fwhm_s, amp, ruido, rng, n_fase, por_fase,
                             cfg1, con_base)
    sal = {e: [] for e in ESTIMADORES}
    fases, largos = [], []
    perdidos = 0

    for i_f, fase in enumerate(np.arange(n_fase) / n_fase):
        tpl = (plantilla_ref(fwhm_s, fase) if familia == 'referencia'
               else plantilla(familia, fwhm_s, fase))
        dat, paso, lead = _lote(tpl, amp, por_fase, ruido['sigma_n'],
                                ruido['sigma_bl'] if con_base else 0.0,
                                ruido['tau_c'], rng)

        ev0 = pu.segmentar_rapido(dat, **cfg0)
        ev1 = pu.compuertas_rapido(dat, **cfg1)

        # un evento por fila: el que disparó dentro de la fila, y que cerró
        fila0 = ev0['i0'] // paso
        ok0 = ev0['cerrado'] & (np.diff(np.concatenate(([-1], fila0))) > 0)
        fila1 = ev1['i0'] // paso
        ok1 = np.diff(np.concatenate(([-1], fila1))) > 0

        f0, f1 = fila0[ok0], fila1[ok1]
        comun = np.intersect1d(f0, f1)
        perdidos += por_fase - comun.size
        if comun.size == 0:
            continue
        s0 = np.searchsorted(f0, comun)
        s1 = np.searchsorted(f1, comun)
        i0 = ev0['i0'][ok0][s0]
        k = i0 + ev0['t_pico'][ok0][s0]

        sal['pico'].append(ev0['pico'][ok0][s0].astype(float))
        sal['pico_par'].append(_parabolico(dat, k))
        sal['q_hist'].append(ev0['q_tot'][ok0][s0].astype(float))
        sal['q_fija'].append(ev1['q_tot'][ok1][s1].astype(float))
        fases.append(np.full(comun.size, i_f))
        largos.append(ev0['largo'][ok0][s0].astype(float))

    if not fases:
        return None
    return {e: np.concatenate(v) for e, v in sal.items()} | \
           {'_fase': np.concatenate(fases), '_perdidos': perdidos,
            '_largo': np.concatenate(largos),
            '_n': int(np.concatenate(fases).size)}


def anova(valores, fase):
    """(sigma_total, sigma_ruido, sigma_fase, media) del lote.

    Descomposición de la varianza en la parte que vive DENTRO de cada bin de
    fase (ruido) y la que vive ENTRE bins (fase). Lo de 'entre' no es ruido de
    muestreo: la grilla de fases es determinista, así que su dispersión es la
    varianza poblacional, no una estimación de la de una uniforme.

    **La corrección que hay que hacer sí o sí**: la media de cada bin tiene su
    propio error de muestreo `v_dentro/n_bin`, que infla `v_entre` aunque la
    fase no haga absolutamente nada. Sin restarlo, un término de fase nulo se
    mide como `sigma_ruido/sqrt(n_bin)` — que con estos lotes es del orden de
    los términos que se quieren resolver. Es el estimador insesgado clásico de
    la componente entre grupos; se trunca en 0 porque la varianza no es
    negativa aunque su estimador pueda serlo.
    """
    m_tot = float(np.mean(valores))
    bins = np.unique(fase)
    medias = np.array([valores[fase == b].mean() for b in bins])
    n_bin = float(np.mean([np.count_nonzero(fase == b) for b in bins]))
    v_dentro = float(np.mean([valores[fase == b].var(ddof=1) for b in bins]))
    v_entre = max(float(medias.var()) - v_dentro / n_bin, 0.0)
    return (float(np.sqrt(v_dentro + v_entre)), float(np.sqrt(v_dentro)),
            float(np.sqrt(v_entre)), m_tot)


def ganancia_teorica(estimador, geo):
    """Cuántas cuentas de salida da el estimador por cuenta de amplitud.

    Es la ganancia IDEAL, calculada de la geometría y no del lote: 1 para los
    estimadores de pico, el área/pico para los de carga. Usarla en vez de la
    ganancia medida es lo que permite que el sesgo signifique algo — si se
    normaliza por la media del propio lote, el sesgo da cero por construcción.
    """
    return 1.0 if estimador in ('pico', 'pico_par') else geo['Sf']


def analizar(familia, fwhm_s, amp, n_ev, ruido, rng, n_fase=32, cfg1=None):
    """Todo lo de una familia: geometría, ANOVA por estimador y cota de C-R."""
    sigma_rel = ruido['sigma_n'] / amp
    geo = geometria(familia, fwhm_s, sigma_rel)
    base = corrida(familia, fwhm_s, amp, n_ev, ruido, rng, n_fase=n_fase,
                   cfg1=cfg1)
    sin_bl = corrida(familia, fwhm_s, amp, n_ev, ruido, rng, n_fase=n_fase,
                     cfg1=cfg1, con_base=False)
    if base is None:
        return dict(geo=geo, est={}, rinde=0.0, crb=np.nan)

    # la cota: con forma y fase conocidas, Var(Â) = sigma_n^2 / Sf2
    crb = ruido['sigma_n'] / np.sqrt(geo['Sf2']) / amp

    est = {}
    for e in ESTIMADORES:
        if not np.any(base[e]):              # el trapecio que no entró en la compuerta
            continue
        s_tot, s_rui, s_fas, med = anova(base[e], base['_fase'])
        _, s_blanco, _, _ = anova(sin_bl[e], sin_bl['_fase'])
        s_base = float(np.sqrt(max(s_rui ** 2 - s_blanco ** 2, 0.0)))
        # FWHM real del histograma, que para los términos no gaussianos NO es
        # 2.355 sigma: es la advertencia de la sección 1 del documento, medida.
        fw = _fwhm_hist(base[e])
        # Los anchos van relativos al CENTROIDE medido, que es la definición de
        # laboratorio de la resolución; el sesgo, en cambio, va contra la
        # ganancia teórica, que es la única forma de que signifique algo.
        # El trapecio no tiene una ganancia de geometría: sale de k, M y sh, y la
        # meseta de las formas sin cola no es plana. Sin sesgo que informar.
        sesgo = float('nan') if e == 'trapecio' else (med / ganancia_teorica(e, geo) - amp) / amp
        est[e] = dict(sigma=s_tot / med, ruido=s_rui / med,
                      blanco=s_blanco / med, base=s_base / med,
                      fase=s_fas / med, sesgo=sesgo,
                      fwhm=fw / med, sigma_cuentas=s_tot / (med / amp),
                      ganancia=med / amp)
    return dict(geo=geo, est=est, crb=crb,
                largo_vent=float(np.mean(base['_largo'])),
                largo_vent_sd=float(np.std(base['_largo'])),
                rinde=base['_n'] / (n_ev // n_fase * n_fase))


def _fwhm_hist(v, n_bins=80, suave=3):
    """FWHM del histograma del estimador, en las unidades del estimador.

    Dos cuidados que no son opcionales: el bin no puede ser más angosto que la
    cuantización del estimador (los valores son enteros; con bins de 0.3 cuentas
    el histograma sale peine y el "máximo" es un diente), y el pico se suaviza
    con una media móvil corta antes de buscar la media altura. Los cruces se
    interpolan linealmente.

    Lo que se le pide a este número es distinguir 'gaussiano' (FWHM = 2.355 σ)
    de 'uniforme disfrazada' (FWHM = ancho completo), que es la advertencia de
    la sección 1 del documento. No es un ajuste de pico.
    """
    v = np.asarray(v, dtype=float)
    rango = float(v.max() - v.min())
    if rango <= 0:
        return 0.0
    ancho = max(rango / n_bins, 1.0)                 # nunca por debajo de 1 cuenta
    bordes = np.arange(v.min() - ancho, v.max() + 2 * ancho, ancho)
    h, bordes = np.histogram(v, bins=bordes)
    if suave > 1:
        k = np.ones(suave) / suave
        h = np.convolve(h.astype(float), k, mode='same')
    c = 0.5 * (bordes[:-1] + bordes[1:])
    k = int(np.argmax(h))
    mitad = h[k] / 2.0

    def _cruce(i_ini, paso):
        i = i_ini
        while 0 <= i + paso < h.size and h[i + paso] >= mitad:
            i += paso
        j = i + paso
        if not (0 <= j < h.size) or h[i] == h[j]:
            return float(c[i])
        f = (h[i] - mitad) / (h[i] - h[j])
        return float(c[i] + f * (c[j] - c[i]))

    return _cruce(k, +1) - _cruce(k, -1)


# =============================================================================
# 4. Salida
# =============================================================================

def _pct(x, dec=3):
    return '—' if not np.isfinite(x) else f'{100*x:.{dec}f}'


def tablas(res, ruido, amp, fwhm_s):
    fwhm_pts = fwhm_s * pu.FS_HZ
    print('\n### Modelo de ruido (medido; ruido.py sobre el canal en vacío)\n')
    print(f'    sigma_w (blanco, por muestra)   = {ruido["sigma_n"]:.2f} cuentas')
    print(f'    sigma_c (correlacionado)        = {ruido["sigma_bl"]:.2f} cuentas'
          f'   tau = {ruido["tau_c_us"]:.1f} µs '
          f'({ruido["tau_c"]:.0f} muestras, codo {ruido["f_codo_khz"]:.1f} kHz)')
    print(f'    sigma total por muestra         = {ruido["sigma_tot"]:.2f} cuentas')
    print(f'    pre-disparo: {ruido["sigma_pre_senal"]:.2f} con generador, '
          f'{ruido["sigma_pre_vacio"]:.2f} en vacío (el generador no aporta)')
    print(f'    sobre {ruido["n_ventanas"]} ventanas, '
          f'{ruido["n_muestras"]/1e6:.2f} M muestras de base pura')

    print('\n### Geometría de cada familia\n')
    print(f'FWHM = {fwhm_pts:.0f} muestras, amplitud {amp:.0f} cuentas\n')
    print('| familia | Σf [muestras] | Σf/FWHM | √Σf² | Σf²/FWHM | M_ef | '
          'caída máx. [cuentas] | largo | ventana |')
    print('|---|---|---|---|---|---|---|---|---|')
    for f, r in res.items():
        g = r['geo']
        print(f'| {ETIQUETA[f]} | {g["Sf"]:.0f} | {g["Sf"]/fwhm_pts:.3f} | '
              f'{np.sqrt(g["Sf2"]):.2f} | {g["Sf2"]/fwhm_pts:.3f} | '
              f'{g["M_ef"]:.0f} | {amp*g["caida_max"]:.2f} | {g["n"]} | '
              f'{r.get("largo_vent", float("nan")):.0f} ± '
              f'{r.get("largo_vent_sd", float("nan")):.0f} |')

    for e in ESTIMADORES:
        print(f'\n### {NOMBRE_EST[e]} — descomposición de σ/A [%]\n')
        print('| familia | blanco | base | fase | **σ total** | FWHM | '
              'sesgo | σ/C-R |')
        print('|---|---|---|---|---|---|---|---|')
        for f, r in res.items():
            if e not in r['est']:
                print(f'| {ETIQUETA[f]} | — | — | — | — | — | — | — |')
                continue
            d = r['est'][e]
            print(f'| {ETIQUETA[f]} | {_pct(d["blanco"])} | {_pct(d["base"])} '
                  f'| {_pct(d["fase"])} | **{_pct(d["sigma"])}** | '
                  f'{_pct(d["fwhm"])} | {_pct(d["sesgo"], 2)} | '
                  f'{d["sigma"]/r["crb"]:.0f}× |')

    print('\n### Resumen: resolución FWHM/centroide [%] por estimador\n')
    print('| familia | ' + ' | '.join(NOMBRE_EST[e] for e in ESTIMADORES)
          + ' | cota C-R | eventos medidos |')
    print('|---|' + '---|' * (len(ESTIMADORES) + 2))
    for f, r in res.items():
        cel = []
        for e in ESTIMADORES:
            cel.append(_pct(r['est'][e]['fwhm']) if e in r['est'] else '—')
        print(f'| {ETIQUETA[f]} | ' + ' | '.join(cel)
              + f' | {_pct(2.355*r["crb"])} | {100*r["rinde"]:.0f} % |')

def tabla_validacion(ref, amp_ref):
    """Predicho vs medido sobre los 7054 pulsos reales, en las dos unidades.

    La comparación de fondo es la de CUENTAS equivalentes de amplitud: el % de
    resolución depende de la amplitud del conjunto (2415 cuentas ahí, 1920 en la
    campaña del espectro) y arrastra el offset de la calibración, mientras que
    las cuentas son la magnitud que el modelo predice.
    """
    print('\n### Validación: predicho vs medido sobre los 7054 pulsos reales\n')
    print(f'(forma real del estímulo, amplitud {amp_ref:.0f} cuentas)\n')
    print('| estimador | FWHM predicho [%] | offline, mismas trazas [%] | '
          'cociente | en placa [%] | σ predicho [cuentas] |')
    print('|---|---|---|---|---|---|')
    for e in ESTIMADORES:
        d = ref['est'].get(e)
        if d is None:
            continue
        p = 100 * d['fwhm']
        off = MEDIDO_OFFLINE.get(e)
        pla = MEDIDO_PLACA.get(e)
        print(f'| {NOMBRE_EST[e]} | {p:.3f} | '
              f'{"—" if off is None else f"{off:.3f}"} | '
              f'{"—" if off is None else f"{p/off:.2f}×"} | '
              f'{"—" if pla is None else f"{pla:.3f}"} | '
              f'{d["sigma_cuentas"]:.2f} |')


def inl_estimador(familia, fwhm_s, amps, n_ev, ruido, rng, n_fase=32):
    """La INL que pone el ESTIMADOR, sobre el mismo barrido que la campaña.

    Misma definición que `API/analisis.energy_calibration`: se ajusta una recta
    `estimación = a·A + b` sobre las amplitudes barridas y se informa el residuo
    máximo como % del rango recorrido. Así el número es directamente comparable
    con el `inl_pct` medido en `formas_inl.npz` (1.04–1.09 % FS según la
    familia), y la comparación contesta una pregunta que la campaña dejó
    abierta: cuánto de esa INL es del MCA y cuánto del generador.

    Un estimador perfectamente proporcional da 0. Lo que la rompe son los sesgos
    que NO escalan con la amplitud (el del máximo de M gaussianas, el del ruido
    rectificado por `xc = max(x,0)`) y los que escalan de otra manera (el largo
    de la ventana por histéresis, que crece con el logaritmo de la amplitud).
    """
    medias = {e: [] for e in ESTIMADORES}
    for A in amps:
        r = corrida(familia, fwhm_s, A, n_ev, ruido, rng, n_fase=n_fase)
        for e in ESTIMADORES:
            medias[e].append(np.nan if r is None else float(np.mean(r[e])))
    A = np.asarray(amps, dtype=float)
    sal = {}
    for e in ESTIMADORES:
        c = np.asarray(medias[e], dtype=float)
        if not np.all(np.isfinite(c)):
            sal[e] = float('nan')
            continue
        a, b = np.polyfit(A, c, 1)
        resid = c - (a * A + b)
        sal[e] = float(100.0 * np.abs(resid).max() / (c.max() - c.min()))
    return sal


def tabla_inl(inl, medido_inl):
    print('\n### No linealidad que pone el estimador [% FS]\n')
    print('Mismo barrido y misma definición que la campaña de formas '
          '(residuo máximo del ajuste lineal, en % del rango recorrido)\n')
    print('| familia | ' + ' | '.join(NOMBRE_EST[e] for e in ESTIMADORES)
          + ' | INL medida en placa |')
    print('|---|' + '---|' * (len(ESTIMADORES) + 1))
    for f, d in inl.items():
        cel = ['—' if not np.isfinite(d[e]) else f'{d[e]:.2f}'
               for e in ESTIMADORES]
        med = medido_inl.get(f)
        print(f'| {ETIQUETA[f]} | ' + ' | '.join(cel)
              + f' | {"—" if med is None else f"{med:.2f}"} |')


def inl_medida(npz=None):
    """La INL por familia que dejó la campaña de formas, para comparar."""
    import glob as _g
    if npz is None:
        c = sorted(_g.glob(os.path.join(_RAIZ, 'datos', 'formas_*',
                                        'formas_inl.npz')))
        if not c:
            return {}
        npz = c[-1]
    z = np.load(npz, allow_pickle=True)
    sal = {}
    for f in FAMILIAS:
        k = f'inl_{f}_pico'
        if k in z.files and np.isfinite(z[k]):
            sal[f] = float(z[k])
    return sal


def cfg_escalada(fwhm_s, base=pu.CFG_MODO1, fwhm_ref=pu.FWHM_S):
    """La compuerta fija, reescalada al ancho del pulso.

    `CFG_MODO1` (corta 32, larga 384) está puesta para el pulso de 2 µs de la
    campaña. Comparar estimadores a otros anchos con esa misma compuerta mide
    una compuerta mal puesta, no el estimador: con pulsos más largos trunca la
    cola (déficit balístico) y con pulsos más cortos integra ruido de más. Se
    escala con el ancho, que es como se configuraría en serio.
    """
    k = float(fwhm_s) / float(fwhm_ref)
    return dict(base, corta=max(int(round(base['corta'] * k)), 4),
                larga=max(int(round(base['larga'] * k)), 16))


def barrido_ancho(familias, anchos_s, amp, n_ev, ruido, rng, n_fase=32):
    """σ de cada estimador contra el ancho del pulso.

    Es donde se ve el cruce que la campaña no pudo medir (el ARB no baja de
    ~0.2 µs): con el pulso cada vez más corto quedan menos muestras sobre el
    ápice, el término de fase del estimador de pico crece como 1/FWHM² y en
    algún punto la carga pasa a ganar.
    """
    sal = {}
    for f in familias:
        for w in anchos_s:
            r = analizar(f, w, amp, n_ev, ruido, rng, n_fase=n_fase,
                         cfg1=cfg_escalada(w))
            sal[(f, w)] = r
    return sal


def figura_barrido(bar, familias, anchos_s, out):
    """σ contra ancho de pulso, un panel por familia."""
    col = {'pico': AZUL, 'pico_par': VERDE, 'q_hist': ROJO, 'q_fija': NARAN,
           'trapecio': '#7a5bbd'}
    us = np.array(anchos_s) * 1e6
    fig, axes = plt.subplots(1, len(familias), figsize=(4.4 * len(familias), 4.0),
                             sharey=True)
    axes = np.atleast_1d(axes)
    for ax, f in zip(axes, familias):
        for e in ESTIMADORES:
            y = [100 * bar[(f, w)]['est'][e]['sigma']
                 if e in bar[(f, w)]['est'] else np.nan for w in anchos_s]
            ax.plot(us, y, 'o-', color=col[e], lw=1.6, ms=5,
                    label=NOMBRE_EST[e].replace('Q fija 384', 'Q fija escalada'))
        y = [100 * bar[(f, w)]['crb'] for w in anchos_s]
        ax.plot(us, y, ls='--', color=TINTA2, lw=1.2, label='cota de Cramér-Rao')
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.set_xlabel('FWHM del pulso [µs]')
        ax.set_title(ETIQUETA[f], loc='left', color=TINTA2, fontsize=9.5)
        for lado in ('top', 'right'):
            ax.spines[lado].set_visible(False)
    axes[0].set_ylabel('σ del estimador  [% de la amplitud]')
    axes[-1].legend(loc='upper right', fontsize=8.5)
    fig.tight_layout()
    p = os.path.join(out, f'13_estimadores_vs_ancho{_sufijo()}.png')
    fig.savefig(p, bbox_inches='tight')
    plt.close(fig)
    print(f'figura: {os.path.relpath(p)}')


def tabla_barrido(bar, familias, anchos_s):
    print('\n### σ/A [%] contra ancho de pulso\n')
    print('La compuerta fija se escala con el ancho (`cfg_escalada`): comparar '
          'estimadores\ncon la compuerta de 2 µs a todo ancho mediría una '
          'compuerta mal puesta.\n')
    for f in familias:
        print(f'\n**{ETIQUETA[f]}**\n')
        print('| FWHM [µs] | muestras | ' +
              ' | '.join(NOMBRE_EST[e] for e in ESTIMADORES).replace(
                  'Q fija 384', 'Q fija escalada') +
              ' | fase del pico | cota C-R |')
        print('|---|---|' + '---|' * (len(ESTIMADORES) + 2))
        for w in anchos_s:
            r = bar[(f, w)]
            cel = [_pct(r['est'][e]['sigma']) if e in r['est'] else '—'
                   for e in ESTIMADORES]
            fase = (_pct(r['est']['pico']['fase']) if 'pico' in r['est'] else '—')
            print(f'| {1e6*w:g} | {w*pu.FS_HZ:.0f} | ' + ' | '.join(cel)
                  + f' | {fase} | {_pct(r["crb"])} |')


def figura(res, out, amp, ruido):
    """Dos paneles: dónde queda cada estimador, y de qué está hecha su varianza.

    El segundo panel va en FRACCIÓN de la varianza y no en σ apilado: los tres
    términos se suman en cuadratura, así que apilar sus σ dibujaría una suma que
    no es la que vale (y en escala logarítmica, que es la única donde entran los
    tres, apilar directamente no significa nada). La fracción sí es aditiva; el
    total, que es el otro dato, va escrito arriba de cada barra.
    """
    fams = [f for f in res if res[f]['est']]
    col = {'pico': AZUL, 'pico_par': VERDE, 'q_hist': ROJO, 'q_fija': NARAN,
           'trapecio': '#7a5bbd'}
    mk = {'pico': 'o', 'pico_par': '.', 'q_hist': 'v', 'q_fija': 'D', 'trapecio': 's'}
    ms = {'pico': 11, 'pico_par': 7, 'q_hist': 8, 'q_fija': 7, 'trapecio': 7}

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 4.8),
                                 gridspec_kw=dict(width_ratios=(1.15, 1)))

    y = np.arange(len(fams))
    for e in ESTIMADORES:
        relleno = 'none' if e == 'pico' else col[e]
        a1.plot([100 * res[f]['est'][e]['sigma'] if e in res[f]['est'] else np.nan
                 for f in fams], y,
                mk[e], mfc=relleno, mec=col[e], mew=1.6, ms=ms[e],
                label=NOMBRE_EST[e], ls='none')
    a1.plot([100 * res[f]['crb'] for f in fams], y, '|', color=TINTA2, ms=16,
            mew=1.6, label='cota de Cramér-Rao')
    a1.set_yticks(y, [ETIQUETA[f] for f in fams])
    a1.set_xscale('log')
    a1.set_xlim(0.012, 0.42)
    a1.set_xticks([0.02, 0.05, 0.1, 0.2, 0.4], ['0.02', '0.05', '0.1', '0.2',
                                                '0.4'])
    a1.set_xlabel('σ del estimador  [% de la amplitud]')
    a1.invert_yaxis()
    a1.legend(loc='upper center', bbox_to_anchor=(0.5, -0.17), ncol=5,
              fontsize=8.5, handletextpad=0.3, columnspacing=1.2)

    muestra = [f for f in ('cr', 'trapezoidal', 'referencia') if f in res]
    ancho = 0.78 / max(len(muestra), 1)
    for i, f in enumerate(muestra):
        for j, e in enumerate(ESTIMADORES):
            if e not in res[f]['est']:       # el trapecio que no entró en la compuerta
                continue
            d = res[f]['est'][e]
            v = np.array([d['blanco'], d['base'], d['fase']]) ** 2
            v = v / v.sum() if v.sum() > 0 else v
            x = j + (i - (len(muestra) - 1) / 2) * ancho
            abajo = 0.0
            for frac, c in zip(v, (AZUL, NARAN, ROJO)):
                a2.bar(x, 100 * frac, ancho * 0.88, bottom=100 * abajo,
                       color=c, ec=SUP, lw=0.8)
                abajo += frac
            a2.text(x, 102, f'{100*d["sigma"]:.3f}', ha='center', va='bottom',
                    fontsize=7, color=TINTA2, rotation=90)
    a2.set_xticks(range(len(ESTIMADORES)),
                  [NOMBRE_EST[e] for e in ESTIMADORES], fontsize=9)
    a2.set_ylim(0, 128)
    a2.set_yticks([0, 25, 50, 75, 100])
    a2.set_ylabel('fracción de la varianza  [%]')
    a2.set_xlabel('por estimador, izq→der: '
                  + ', '.join(ETIQUETA[f] for f in muestra)
                  + '\n(arriba de cada barra, σ total en % de la amplitud)')
    for c, t in ((AZUL, 'ruido blanco'), (NARAN, 'ruido correlacionado (τ = 12 µs)'),
                 (ROJO, 'fase de muestreo')):
        a2.bar(0, 0, color=c, label=t)
    a2.legend(loc='upper center', bbox_to_anchor=(0.5, -0.17), ncol=3,
              fontsize=8.5, handletextpad=0.3, columnspacing=1.2)

    for ax in (a1, a2):
        for lado in ('top', 'right'):
            ax.spines[lado].set_visible(False)
    fig.tight_layout()
    p = os.path.join(out, f'12_varianza_estimadores{_sufijo()}.png')
    fig.savefig(p, bbox_inches='tight')
    plt.close(fig)
    print(f'\nfigura: {os.path.relpath(p)}')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n', type=int, default=16000, help='eventos por familia')
    ap.add_argument('--amp', type=float, default=1920.0, help='amplitud [cuentas]')
    ap.add_argument('--amp-ref', type=float, default=2415.0,
                    help='amplitud del conjunto real, para la validación')
    ap.add_argument('--fwhm', type=float, default=2e-6, help='FWHM [s]')
    ap.add_argument('--n-fase', type=int, default=32, help='bins de fase')
    ap.add_argument('--out', default=FIGURAS)
    ap.add_argument('--sin-figura', action='store_true')
    ap.add_argument('--sin-barrido', action='store_true')
    ap.add_argument('--semilla', type=int, default=11)
    ap.add_argument('--mapa', default='MCA2', choices=['MCA2', 'MCA1'])
    a = ap.parse_args()

    if a.mapa == 'MCA1':
        global ESTIMADORES
        ESTIMADORES = ESTIMADORES_MCA1
    ruido = modelo_ruido()
    rng = np.random.default_rng(a.semilla)
    print(f'=== varianza de los estimadores ===')
    print(f'amplitud {a.amp:.0f} cuentas, FWHM {1e6*a.fwhm:g} µs, '
          f'{a.n} eventos × {len(FAMILIAS)+1} familias')

    todas = FAMILIAS + ('referencia',)
    res = {}
    for f in todas:
        res[f] = analizar(f, a.fwhm, a.amp, a.n, ruido, rng, n_fase=a.n_fase)
        print(f'  {f:<12} ok ({100*res[f]["rinde"]:.0f} % de los eventos)')
    ref = analizar('referencia', a.fwhm, a.amp_ref, a.n, ruido, rng,
                   n_fase=a.n_fase)

    # El mismo barrido de amplitud de la campaña de formas: 12 niveles de
    # 0.1 a 1.0 Vpp, o sea pico de 410 a 4096 cuentas con el jumper LV.
    amps_inl = np.linspace(0.1, 1.0, 12) / 2.0 * pu.ADC_CNT_PER_V
    print('\n(barrido de amplitud para la INL…)')
    inl = {f: inl_estimador(f, a.fwhm, amps_inl, max(a.n // 4, 1600), ruido,
                            rng, n_fase=a.n_fase) for f in todas}

    tablas(res, ruido, a.amp, a.fwhm)
    tabla_inl(inl, inl_medida())
    tabla_validacion(ref, a.amp_ref)

    bar, fams_bar, anchos = None, ('referencia', 'cr', 'trapezoidal'), None
    if not a.sin_barrido:
        anchos = [1e-7, 2e-7, 5e-7, 1e-6, 2e-6, 4e-6]
        print('\n(barrido en ancho de pulso…)')
        bar = barrido_ancho(fams_bar, anchos, a.amp, max(a.n // 2, 3200),
                            ruido, rng, n_fase=a.n_fase)
        tabla_barrido(bar, fams_bar, anchos)

    if not a.sin_figura:
        os.makedirs(a.out, exist_ok=True)
        figura(res, a.out, a.amp, ruido)
        if bar:
            figura_barrido(bar, fams_bar, anchos, a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
