#!/usr/bin/env python3
"""Las figuras de mérito del MCA con el generador de pulsos de la FPGA (`gen_pulsos`).

Es generación interna (docs/etapas_de_validacion.md): `gen_pulsos` maneja el MCA por el
lazo digital, sin el Rigol. A diferencia de `make verificar-placa-generadores`, que
exige que la placa dé lo mismo que la réplica, esta campaña mide el MCA contra lo que
se generó: cuántos pulsos, a qué tasa y de qué altura. Es lo que el Rigol no deja medir
(docs/resultados_validacion_hw.md §20.3).

Dos etapas:

  tasa   arribos de Poisson (el motor aleatorio, con `dt_min`) de 10 k/s a 3 M/s, con
         dos líneas (500 y 1300 cuentas, 60/40). Por punto: la tasa de entrada exacta,
         dónde se pierde cada pulso (sin disparo, sin ranura, en el publicador), los
         aceptados y los "buenos" por segundo, el tiempo muerto y el error de λ̂. Es
         la curva m(n) y el techo del MCA. Las líneas son chicas a propósito: con τ =
         2 µs, a 3 M/s el apilamiento medio es 6 pulsos, y con 1500 y 4000 cuentas la
         salida de 14 bits se recorta (cada punto trae el nivel por Campbell, y avisa).
  par    pares de pulsos (4000 y después 2400 cuentas) a Δt de 2 a 512 ciclos. Por
         punto: cuántos disparos y cuántos eventos da cada par, y cuántas veces cada
         pulso se mide donde va. Es la resolución par-pulso del disparo y del MCA, y la
         recuperación de la amplitud del banco de trapecios.

**Las tres fuentes de disparo** dejan la ventana en el mismo lugar respecto del pie del
pulso (`PRE_DLY`, comprobado en la réplica), así que comparar fuentes aísla el disparo:

  asg        la fuente ASG del multitrigger: un disparo por pulso generado, sin mirar la
             señal. Sólo pierde los pulsos a menos de 3 ciclos del último aceptado: lo
             que se pierde después es del MCA.
  pz         el disparo con polo-cero, el del banco.
  pendiente  el disparo por pendiente, el de antes del banco.

El MCA es el banco de trapecios de la placa (`BANCO_PZ`), con la base fija en 0 y
el MCA y el multitrigger en el tap ADC: ven la muestra del generador tal cual.

**Cómo se arma el estímulo del par.** El generador corre periódico con `PERIODO` = Δt y
la tabla en orden: `[A1, A2, 0, 0, …]`, con K entradas (`AMP_N` = K). Los pulsos de
altura 0 no disparan por pendiente ni por polo-cero, así que cada K·Δt ciclos sale un
par aislado. K se elige para que entre pares haya `--hueco` ciclos (12 τ con el
default). El ASG dispara también en los ceros: la etapa par no lo usa.

**Contra qué se mide.** La entrada es exacta: N pulsos (`GEN_CNT`), y el instante de
cada uno sale del motor (`predecir`), así que la tasa de entrada es N / T_gen, con T_gen
del arranque al último pulso. El MCA corre desde antes del arranque hasta después del
último pulso: el tiempo en que no hay generador es vivo y no entra en las tasas. Un
pulso es **bueno** si su `F_TRAP` (o `F_PEAK`) cae a ±2 % de su línea, medida antes con
pulsos aislados (la referencia de cada fuente). Es el criterio de
`docs/mca/figuras/trapecio/banco_placa.py`.

**Dos placas.** `--simulada` corre lo mismo sobre el modelo del generador
(`gen_pulsos_model.py`) y la réplica del MCA (`replica_mca2.py`), que la placa reproduce
evento por evento: es la simulación con la que se compara cada número (etapa 1), y la
que usan los tests. Por tiempo, la simulada recorta N a `--ciclos-max` ciclos por punto.
`--comparar placa.json simulada.json` pone las dos lado a lado.

**Lo que se comprueba en cada corrida** (lo que no cierra es una anomalía y el script
sale con 1): GEN_CNT = N sin desborde, `cross = open + lost_active + dropped +
lost_veto`, `total = open`, el teselado de los relojes (en la placa), que el espectro
sume los aceptados y, como el generador es determinista, que los contadores de las
corridas de un punto (una por espectro) sean iguales.

Uso (en la Pitaya, con un bitstream con el generador: el MCA cce7b66b o el ring
78e26188 en adelante):

    python3 campanas/run_meritos_pulsos.py <outdir> [--etapas tasa,par]
        [--fuentes asg,pz,pendiente] [--n-acc 1,2,3] [--tasas 1e4,1e5,1e6]
        [--dts 2,4,8,16] [--seg 1] [--n-pares 2000]

En la PC, la misma campaña simulada y la comparación:

    python3 campanas/run_meritos_pulsos.py datos/meritos_sim --simulada
    python3 campanas/run_meritos_pulsos.py --comparar datos/meritos/meritos.json \
        datos/meritos_sim/meritos.json

Deja `<outdir>/meritos.json`, que se reescribe después de cada punto (una corrida
cortada conserva lo medido), y la tabla del resumen. `make campana-meritos-pulsos` desde
`software/`, o `-remoto` desde la PC.
"""
import argparse
import functools
import json
import math
import os
import platform
import sys
import time
from datetime import datetime

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.join(_RAIZ, 'monte-carlo'))

import API.generadores as G                                          # noqa: E402
import replica_mca2 as r2                                            # noqa: E402
from API.mca import BANCO_PZ, mca_banco_config                       # noqa: E402

FS_HZ = 125e6
TOL_BUENO = 0.02          # ±2 % de la línea: el criterio de banco_placa.py
VENTANA_CENTROIDE = 0.10  # el centroide de una línea se toma a ±10 %
DEB_LEN_RESET = 62500

# Del pulso del generador (trig_o) al flanco de trig_i por la fuente ASG, en el top:
# volcado_pulsos.LAT_ASG_TOP, medido en la placa el 2026-11-09.
LAT_ASG_TOP = 3
# Tras un disparo, el multitrigger no acepta otro por la fuente ASG hasta 3 ciclos
# después (volcado_pulsos.REARME).
REARME_ASG = 3
# pre_dly que deja la ventana en el mismo lugar respecto del pie del pulso con cada
# fuente. Con polo-cero el disparo llega 11 ciclos después del pie (LAT_PZ) y el banco
# está pensado para pre_dly 16; el del ASG llega 2 antes del pie y el de pendiente, con
# subida 0, 6 después. En la réplica las tres dan el mismo F_TRAP y el mismo F_TRISE.
PRE_DLY = {'pz': 16, 'asg': 3, 'pendiente': 11}
PZ_UMBRAL = 50.0          # cuentas de amplitud; el re-armado en la mitad
PENDIENTE = dict(L=8, G=4, thr=600, hyst=300)
FUENTES = ('asg', 'pz', 'pendiente')
# Los espectros que se pueden pedir. `t_subida` (F_TRISE: del disparo al pico) es el que
# ve dónde cae la ventana y el walk del disparo; con zoom 3 el canal es el valor.
ESPECTROS = {'pico': r2.F_PEAK, 'trapecio': r2.F_TRAP, 't_subida': r2.F_TRISE}
ZOOM = {'pico': 0, 'trapecio': 0, 't_subida': 3}

TASAS = (1e4, 3e4, 1e5, 2e5, 4e5, 7e5, 1e6, 1.5e6, 2e6, 3e6)
DTS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64,
       96, 128, 192, 256, 384, 512)
PERIODO_REF = 3000        # ciclos entre pulsos de la referencia de la etapa tasa


# =============================================================================
# El estímulo y la configuración
# =============================================================================

def forma_pulso(decae, subida, n=3000):
    """El pulso del generador normalizado al pico, en punto flotante: los dos polos de
    gen_pulsos sin los redondeos (difieren en menos del 0.3 %). Es para elegir el umbral
    del disparo con polo-cero, igual en las dos placas."""
    pd = int(decae) / 65536.0
    pr = 1.0 - 2.0 ** -int(subida) if int(subida) else 0.0
    out = np.empty(int(n))
    y1 = y2 = 0.0
    for i in range(int(n)):
        y1 = pd * y1 + (1.0 if i == 0 else 0.0)
        y2 = pr * y2 + (1.0 - pr) * y1
        out[i] = y2
    return out / out.max()


@functools.lru_cache(maxsize=8)
def _pz_de(decae, subida):
    d = r2.disparo_pz_para(forma_pulso(decae, subida), G.mq_de(decae), a_umbral=PZ_UMBRAL)
    d.pop('pre_dly')
    return tuple(d.items())


def disparo_de(fuente, decae, subida):
    """El disparo de una fuente, con los nombres de la réplica (`replica_mca2.CFG`)."""
    if fuente == 'asg':
        return {'fuente': 'asg'}
    if fuente == 'pendiente':
        return {'fuente': 'pendiente', **PENDIENTE}
    if fuente == 'pz':
        return dict(_pz_de(int(decae), int(subida)))
    raise ValueError(f'fuente {fuente!r}: una de {FUENTES}')


def mca_de(fuente, decae, n_acc):
    """El MCA: el banco de la placa con la Mq del generador y el pre_dly de la fuente.
    Las claves son las de `replica_mca2.CFG`, que `mca_configure` también acepta."""
    kw = mca_banco_config(G.mq_de(decae), pre_dly=PRE_DLY['pz'], formas=BANCO_PZ)
    kw.update(pre_dly=PRE_DLY[fuente], n_acc=int(n_acc), baseline=0, amp_min=0,
              amp_max=0xFFFF, amp_src=0, q_shift=0)
    return kw


def gen_base(a):
    """Lo del generador que no cambia entre puntos."""
    return dict(tau=a.tau, subida=a.subida, base=0, ruido=a.ruido_sh is not None,
                ruido_sh=a.ruido_sh or 0, salidas=G.SAL_OUT1)


def tabla_lineas(lineas, pesos):
    return G.tabla_cdf(lineas, pesos)


def tabla_par(a1, a2, k):
    t = np.zeros(int(k), np.int16)
    t[0], t[1] = a1, a2
    return t


def k_par(dt, hueco):
    """Entradas de la tabla del par: el par y ceros hasta `hueco` ciclos de silencio."""
    return int(min(G.N_TABLA, max(3, math.ceil((int(dt) + int(hueco)) / int(dt)))))


def disparos_cfg(gen):
    return {k: gen[k] for k in G.CLAVES_DISPAROS}


_INSTANTES = {}


def instantes(gen):
    """Los ciclos de trig_o de los N pulsos (desde el arranque), con el motor de C.
    Guarda el último: el mismo estímulo se corre con cada fuente y cada n_acc."""
    d = disparos_cfg(gen)
    clave = tuple(sorted((k, int(v)) for k, v in d.items()))
    if clave in _INSTANTES:
        return _INSTANTES[clave]
    n = int(d['n'])
    media = FS_HZ / G.tasa(**d)
    ciclos = int(1.3 * n * media) + 10_000
    while True:
        t = G.predecir(ciclos, G.LAT_TRIG, n_max=n, **d)
        if t.size >= n:
            break
        ciclos *= 2
    _INSTANTES.clear()
    _INSTANTES[clave] = t
    return t


def apilamiento(n_in_hz, tau, lineas, pesos):
    """El nivel medio del apilamiento y su desvío, en cuentas (Campbell: μ = λ τ E[A],
    σ² = λ τ E[A²] / 2 para h = e^(−t/τ), con λ por muestra y τ en muestras). Si
    μ + 3σ pasa de 8191, la salida del generador (14 bits) se recorta seguido: el
    estímulo satura, como saturaría el ADC con esa señal."""
    w = np.asarray(pesos, float) / np.sum(pesos)
    a = np.asarray(lineas, float)
    lt = n_in_hz / FS_HZ * float(tau)
    mu = lt * float((w * a).sum())
    sigma = math.sqrt(lt * float((w * a * a).sum()) / 2.0)
    return dict(nivel_medio=mu, nivel_sigma=sigma, satura=mu + 3.0 * sigma > G.AMP_MAX)


def perdidos_rearme_asg(t):
    """Los pulsos que la fuente ASG no acepta: a menos de REARME_ASG ciclos del último
    aceptado. Con intervalos de 2 o más ciclos, uno a 2 del anterior se pierde si el
    anterior se aceptó, así que en una racha de r intervalos de 2 se pierden ⌈r/2⌉."""
    d = np.diff(np.asarray(t, np.int64))
    if d.size and d.min() < 2:
        raise ValueError('intervalos de menos de 2 ciclos: el motor no los da')
    corto = np.concatenate(([False], d < REARME_ASG, [False])).astype(np.int8)
    ini = np.flatnonzero(np.diff(corto) == 1)
    fin = np.flatnonzero(np.diff(corto) == -1)
    return int(((fin - ini + 1) // 2).sum())


# =============================================================================
# Las dos placas
# =============================================================================
# `correr(gen, tabla, mca, disparo, espectros)` corre el generador una vez por
# espectro, con el MCA desde antes del arranque hasta después del último pulso, y
# devuelve {'gen', 't_gen', 'corridas': [{'cnt', 'hist'}]}. `cnt` trae los contadores
# con los nombres de mca_read_counters y los relojes en ciclos.

CLAVES_CNT = ('total', 'accepted', 'rej_amp', 'rej_psd', 'pileup', 'dropped', 'cross',
              'open', 'lost_active', 'lost_veto', 'windows', 'trig_edges')
RELOJES = ('realtime', 'livetime', 'vetotime', 't_win', 't_div', 't_rearm')


class PlacaSimulada:
    """El modelo del generador y la réplica del MCA: lo que la placa tiene que dar."""

    nombre = 'simulada'

    def __init__(self, h_aw=13, n_acc_max=3, ciclos_max=4_000_000):
        mod = os.path.join(_RAIZ, '..', 'modulos', 'gen_eventos', 'modelos', 'python_model')
        sys.path.insert(0, os.path.abspath(mod))
        import gen_pulsos_model as gp
        import volcado_pulsos as vp
        self.gp, self.vp = gp, vp
        self.h_aw, self.n_acc_max, self.ciclos_max = int(h_aw), int(n_acc_max), int(ciclos_max)
        self._cache = {}

    def recortar(self, gen):
        """El N que entra en `ciclos_max` (la placa corre el N pedido)."""
        d = disparos_cfg(gen)
        t = G.predecir(self.ciclos_max, G.LAT_TRIG, n_max=int(d['n']), **d)
        return int(t.size)

    def _traza(self, gen, tabla):
        clave = json.dumps([sorted((k, int(v)) for k, v in gen.items()),
                            [int(v) for v in tabla]])
        if clave not in self._cache:
            t_k = instantes(gen)
            kw = {k: int(v) for k, v in gen.items() if k != 'salidas'}
            t = self.gp.traza(int(t_k[-1]) + self.vp.FLUSH, list(tabla), **kw)
            if not np.array_equal(t['trig'], t_k):
                raise RuntimeError('el modelo del generador y predecir no coinciden')
            x = np.concatenate([np.zeros(self.vp.PAD, np.int64), t['dat']])
            self._cache = {clave: (x, t)}           # una por vez: son grandes
        return self._cache[clave]

    def correr(self, gen, tabla, mca, disparo, espectros):
        x, t = self._traza(gen, tabla)
        if disparo['fuente'] == 'asg':
            trig = self.vp.disparos_asg(t['trig']) + LAT_ASG_TOP + self.vp.PAD
            extra = {}
        else:
            trig = None
            extra = dict(disparo)
        m = r2.medir(x, r2.cfg(**mca, **extra), trig=trig)
        k, n_acc = m['cnt'], int(mca['n_acc'])
        to = [int(v) for v in m['t_ocup'][:self.n_acc_max + 1]]
        cnt = dict(total=k['total'], accepted=k['accepted'], rej_amp=k['rej_amp'],
                   rej_psd=k['rej_psd'], pileup=k['pileup'], dropped=k['lost_busy'],
                   cross=k['cross'], open=k['open'], lost_active=k['lost_active'],
                   lost_veto=k['lost_veto'], windows=k['windows'], trig_edges=k['trig'],
                   realtime=int(x.size), vetotime=0, t_win=to[n_acc], t_div=0,
                   t_rearm=None, livetime=sum(to[:n_acc]), t_ocup=to)
        corridas = []
        for nombre, z in espectros:
            feat = m['eventos']['feat'][:, ESPECTROS[nombre]]
            canal = self.vp.canal_1d(feat, int(z), aw=self.h_aw)
            corridas.append({'cnt': dict(cnt), 'hist': np.bincount(canal, minlength=1 << self.h_aw)})
        gen_est = dict(gen_cnt=int(t['trig'].size), terminado=True, desborde=bool(t['desborde']))
        return {'gen': gen_est, 't_gen': int(t['trig'][-1]) + 1, 'corridas': corridas}

    def close(self):
        self._cache = {}


class PlacaReal:
    """El generador por el lazo digital, el MCA y el multitrigger en la Pitaya."""

    nombre = 'placa'

    def __init__(self, ch=0):
        from API import mca as M
        from API import multitrigger as MT
        from API import osciloscope as O
        from API import integration as I
        self.M, self.MT, self.O, self.I = M, MT, O, I
        self.ch = int(ch)
        self.g = G.GenPulsos.open()                  # GenPulsosNotPresent sin generador
        self.h = M.mca_open()
        self.mtr = MT.MtRegion.open()
        self.osc = O.osciloscope_open()
        self.ig = I.integration_open()
        self.h_aw = int(self.h.h_aw)
        self.n_acc_max = int(M.mca_get_n_acc_max(self.h))
        I.integration_set_route_mca(self.ig, I.TAP_ADC)
        I.integration_set_route_mtrg(self.ig, I.TAP_ADC)
        self.g.lazo = True

    def recortar(self, gen):
        return int(gen['n'])

    def _armar(self, disparo):
        MT, osc, mtr, ch = self.MT, self.osc, self.mtr, self.ch
        f = disparo['fuente']
        if f == 'pendiente':
            MT.multitrigger_armar_mca(osc, mtr, ch=ch, L=disparo['L'], G=disparo['G'],
                                      thr=disparo['thr'], hyst=disparo['hyst'])
        elif f == 'pz':
            g = MT.pz_ganancia(disparo['pz_k'], disparo['pz_m'], disparo['pz_mq'],
                               disparo['pz_sh'])
            MT.multitrigger_armar_mca(osc, mtr, ch=ch, fuente='pz', mq=disparo['pz_mq'],
                                      k=disparo['pz_k'], m=disparo['pz_m'],
                                      sh=disparo['pz_sh'], thr_cuentas=disparo['pz_thr'] / g,
                                      hyst_cuentas=disparo['pz_hyst'] / g)
            p = mtr.get_pz(ch)
            if (p['thr'], p['hyst']) != (disparo['pz_thr'], disparo['pz_hyst']):
                raise RuntimeError(f'el polo-cero quedó con {p}, no con {disparo}')
        elif f == 'asg':
            # Como test_generadores_placa: el shield, we_keep y el arm del modo continuo,
            # y la máscara sólo con la fuente ASG. rp_ext_trig filtra también el ASG.
            MT.multitrigger_armar_mca(osc, mtr, ch=ch)
            mtr.set_or_mask(ch, 0)
            mtr.disable_slope(ch)
            osc.w32(self.O.R_DEB_LEN, 0)
            mtr.set_or_mask(ch, MT.BIT_ASG_P)
        else:
            raise ValueError(f'fuente {f!r}')

    def _desarmar(self):
        self.MT.multitrigger_desarmar_mca(self.osc, self.mtr, ch=self.ch)
        self.osc.w32(self.O.R_DEB_LEN, DEB_LEN_RESET)

    def correr(self, gen, tabla, mca, disparo, espectros):
        M, h, g = self.M, self.h, self.g
        g.configurar(**gen)
        g.cargar_tabla(tabla)
        t_k = instantes(gen)
        plazo = 2.0 * t_k[-1] / FS_HZ + 2.0
        corridas, est = [], None
        for nombre, z in espectros:
            M.mca_configure(h, **mca, sel_1d=nombre, zoom_1d=(int(z), 0))
            self._armar(disparo)
            try:
                M.mca_clear(h)
                M.mca_start(h)
                time.sleep(0.002)
                g.arrancar()
                est = g.esperar(timeout_s=plazo)
                time.sleep(0.02)                  # las últimas ventanas cierran
                M.mca_stop(h)
                time.sleep(0.01)
                c = M.mca_read_counters(h)
                hist = np.asarray(M.mca_read_histogram(h), np.int64)
            finally:
                g.parar()
                self._desarmar()
            cnt = {k: int(c[k]) for k in CLAVES_CNT}
            for r in RELOJES:
                cnt[r] = int(round(c[f'{r}_s'] * FS_HZ))
            cnt['t_ocup'] = [int(round(s * FS_HZ)) for s in c['t_ocup_s']]
            corridas.append({'cnt': cnt, 'hist': hist})
        return {'gen': {k: est[k] for k in ('gen_cnt', 'terminado', 'desborde')},
                't_gen': int(t_k[-1]) + 1, 'corridas': corridas}

    def close(self):
        for paso in (self.g.parar, lambda: setattr(self.g, 'lazo', False), self._desarmar,
                     lambda: self.M.mca_stop(self.h),
                     lambda: self.I.integration_reset_routes(self.ig)):
            try:
                paso()
            except Exception as e:                              # noqa: BLE001
                print(f'  (al cerrar: {type(e).__name__}: {e})')
        self.I.integration_close(self.ig)
        self.O.osciloscope_close(self.osc)
        self.mtr.close()
        self.M.mca_close(self.h)
        self.g.close()


# =============================================================================
# El análisis (no toca la placa)
# =============================================================================

def valor_de_canal(canal, h_aw, z=0):
    """El valor de la feature (16 bits) en el borde inferior de un canal."""
    return np.asarray(canal, float) * float(1 << (16 - int(z) - int(h_aw)))


def lineas_ref(hist, n_lineas, ancho=0.03):
    """Las `n_lineas` líneas de un espectro de pulsos aislados: los máximos, separados,
    con su centroide a ±`ancho`. En canales, de menor a mayor."""
    h = np.asarray(hist, float).copy()
    h[0] = 0                                  # F_TRAP = 0: marcados
    out = []
    for _ in range(int(n_lineas)):
        i = int(np.argmax(h))
        if h[i] <= 0:
            break
        lo, hi = max(1, int(i * (1 - ancho))), min(h.size, int(i * (1 + ancho)) + 2)
        c = np.arange(lo, hi)
        w = h[lo:hi]
        out.append(float((c * w).sum() / w.sum()))
        h[lo:hi] = 0
    return sorted(out)


def contar_linea(hist, c, tol):
    """Cuentas a ±tol de la línea en el canal c (bordes incluidos)."""
    lo = max(0, int(math.floor(c * (1 - tol))))
    hi = min(len(hist) - 1, int(math.ceil(c * (1 + tol))))
    return int(np.asarray(hist[lo:hi + 1]).sum())


def centroide(hist, c, ancho=VENTANA_CENTROIDE):
    lo = max(1, int(math.floor(c * (1 - ancho))))
    hi = min(len(hist) - 1, int(math.ceil(c * (1 + ancho))))
    w = np.asarray(hist[lo:hi + 1], float)
    if w.sum() == 0:
        return None
    return float((np.arange(lo, hi + 1) * w).sum() / w.sum())


def momentos(hist):
    """Media y desvío del canal de un espectro (para `t_subida`, en ciclos con zoom 3),
    sin el canal 0."""
    h = np.asarray(hist, float)
    c = np.arange(h.size)
    w = h.copy()
    w[0] = 0
    s = w.sum()
    if s == 0:
        return None
    mu = float((c * w).sum() / s)
    return dict(media=mu, sigma=float(math.sqrt(((c - mu) ** 2 * w).sum() / s)))


def comprobar(res, n):
    """Las identidades de cada corrida. Devuelve la lista de lo que no cierra."""
    mal = []
    g = res['gen']
    if g['gen_cnt'] != n or not g['terminado'] or g['desborde']:
        mal.append(f'generador: {g} con N = {n}')
    base = None
    for i, r in enumerate(res['corridas']):
        c = r['cnt']
        perd = c['open'] + c['lost_active'] + c['dropped'] + c['lost_veto']
        if c['cross'] != perd:
            mal.append(f'corrida {i}: cross {c["cross"]} != open + lost_active + dropped '
                       f'+ lost_veto = {perd}')
        if c['total'] != c['open']:
            mal.append(f'corrida {i}: total {c["total"]} != open {c["open"]}')
        if c['t_rearm'] is not None:
            suma = c['vetotime'] + c['t_win'] + c['t_div'] + c['t_rearm'] + c['livetime']
            if suma != c['realtime']:
                mal.append(f'corrida {i}: el teselado da {suma}, realtime {c["realtime"]}')
        suma_h = int(np.asarray(r['hist']).sum())
        if c['rej_amp'] == c['rej_psd'] == 0 and suma_h != c['accepted']:
            mal.append(f'corrida {i}: el espectro suma {suma_h}, aceptados {c["accepted"]}')
        cuenta = {k: c[k] for k in CLAVES_CNT}
        if base is None:
            base = cuenta
        elif cuenta != base:
            dif = {k: (base[k], cuenta[k]) for k in CLAVES_CNT if base[k] != cuenta[k]}
            mal.append(f'corrida {i}: el generador es determinista y los contadores '
                       f'cambiaron: {dif}')
    return mal


def meritos_tasa(res, n, lineas):
    """Las figuras de mérito de un punto de la etapa tasa, de su primera corrida.
    `lineas` son los canales de la referencia, o None."""
    T = res['t_gen']
    c, hist = res['corridas'][0]['cnt'], res['corridas'][0]['hist']
    seg = T / FS_HZ
    rearm = c['t_rearm'] or 0
    muerto = c['t_win'] + c['t_div'] + rearm
    out = dict(
        n=n, t_gen_s=seg, n_in_hz=n / seg,
        efic_disparo=c['cross'] / n, extra_disparos=max(0, c['cross'] - n),
        perd_disparo=max(0, n - c['cross']) / n, perd_ranura=c['lost_active'] / n,
        perd_publicador=c['dropped'] / n, perd_veto=c['lost_veto'] / n,
        eficiencia=c['accepted'] / n, aceptados_hz=c['accepted'] / seg,
        apilados=c['pileup'] / max(c['total'], 1), muerto=muerto / T,
        muerto_mca=(c['t_win'] + c['t_div']) / T, rearme=rearm / T,
        lam_hz=(c['cross'] - c['lost_veto']) * FS_HZ / max(T - c['vetotime'] - rearm, 1),
        rearme_modelado=c['t_rearm'] is not None)
    out['err_lam'] = out['lam_hz'] / out['n_in_hz'] - 1
    if lineas:
        b = sum(contar_linea(hist, q, TOL_BUENO) for q in lineas)
        out.update(buenos=b, frac_buenos=b / n, buenos_hz=b / seg,
                   marcados=int(hist[0]))
    return out


def meritos_par(res, n_pares, lineas):
    """Las figuras de mérito de un punto de la etapa par: por par, y por pulso (A1 es
    la línea alta). `lineas` son los canales de la referencia, de menor a mayor."""
    out = []
    for r in res['corridas']:
        c, hist = r['cnt'], r['hist']
        d = dict(disparos_par=c['cross'] / n_pares, ventanas_par=c['open'] / n_pares,
                 eventos_par=c['accepted'] / n_pares, apilados=c['pileup'] / max(c['total'], 1))
        if lineas and len(lineas) == 2:
            d['marcados'] = int(hist[0]) / n_pares
            for nombre, q in (('a1', lineas[1]), ('a2', lineas[0])):
                cen = centroide(hist, q)
                d[f'frac_{nombre}'] = contar_linea(hist, q, TOL_BUENO) / n_pares
                d[f'sesgo_{nombre}'] = None if cen is None else cen / q - 1
        out.append(d)
    return out


# =============================================================================
# Las etapas
# =============================================================================

def _esp(lista):
    """['trapecio', 'pico'] -> [('trapecio', 0), ('pico', 0)]: el zoom de cada uno. Sin
    zoom, con 8192 canales, el canal es una cuenta de amplitud del trapecio y dos del
    pico; `t_subida` con zoom 3 es el valor."""
    return [(e, ZOOM[e]) for e in lista]


def _sparse(hist):
    h = np.asarray(hist)
    nz = np.flatnonzero(h)
    return {str(int(i)): int(h[i]) for i in nz}


class Campana:
    def __init__(self, placa, a, outdir):
        self.placa, self.a, self.outdir = placa, a, outdir
        self.meta = dict(fecha=datetime.now().isoformat(timespec='seconds'),
                         placa=placa.nombre, host=platform.node(), h_aw=placa.h_aw,
                         n_acc_max=placa.n_acc_max,
                         args={k: v for k, v in vars(a).items() if k != 'comparar'},
                         pre_dly=PRE_DLY, tol_bueno=TOL_BUENO)
        self.referencias, self.filas, self.anomalias = {}, [], []

    def guardar(self):
        if not self.outdir:
            return
        os.makedirs(self.outdir, exist_ok=True)
        p = os.path.join(self.outdir, 'meritos.json')
        with open(p + '.tmp', 'w') as f:
            # Compacto: se reescribe después de cada punto, y en la placa va a la SD.
            json.dump(dict(meta=self.meta, referencias=self.referencias, filas=self.filas,
                           anomalias=self.anomalias), f, separators=(',', ':'),
                      default=lambda o: o.item() if hasattr(o, 'item') else str(o))
        os.replace(p + '.tmp', p)

    def _correr(self, tag, gen, tabla, mca, disparo, espectros):
        res = self.placa.correr(gen, tabla, mca, disparo, espectros)
        mal = comprobar(res, int(gen['n']))
        for m in mal:
            print(f'    ANOMALÍA {tag}: {m}', flush=True)
            self.anomalias.append(f'{tag}: {m}')
        return res

    # -- tasa --

    def referencia_tasa(self, fuente):
        a = self.a
        gen = G.config(periodo=PERIODO_REF, n=a.n_ref, amp_aleat=True, semilla=a.semilla,
                       **gen_base(a))
        tabla = tabla_lineas(a.lineas, a.pesos)
        decae = gen['decae']
        res = self._correr(f'ref tasa {fuente}', gen, tabla, mca_de(fuente, decae, 1),
                           disparo_de(fuente, decae, a.subida), _esp(a.espectros_tasa))
        ref = self._referencia(f'ref tasa {fuente}', res, _esp(a.espectros_tasa), a.lineas)
        self.referencias[f'tasa/{fuente}'] = ref
        return ref

    def _referencia(self, tag, res, espectros, amplitudes):
        """Por espectro: las líneas de los pulsos aislados (en canales, de menor a
        mayor) y la ganancia de cada una (valor de la feature por cuenta de amplitud).
        `t_subida` no tiene líneas de amplitud: queda sólo el espectro."""
        ref = {}
        for (nombre, z), r in zip(espectros, res['corridas']):
            if nombre == 't_subida':
                ref[nombre] = dict(lineas=None, hist=_sparse(r['hist']))
                continue
            ls = lineas_ref(r['hist'], len(amplitudes))
            ref[nombre] = dict(lineas=ls, hist=_sparse(r['hist']),
                               ganancia=[valor_de_canal(q, self.placa.h_aw, z) / v
                                         for q, v in zip(ls, sorted(amplitudes))])
            if len(ls) != len(amplitudes):
                self.anomalias.append(f'{tag} {nombre}: {len(ls)} líneas de '
                                      f'{len(amplitudes)}')
        return ref

    @staticmethod
    def _txt_ref(ref):
        return '; '.join(f'{k} ' + ', '.join(f'{q:.1f}' for q in v['lineas'])
                         for k, v in ref.items() if v['lineas'])

    def etapa_tasa(self):
        a = self.a
        refs = {}
        for fuente in a.fuentes:
            refs[fuente] = ref = self.referencia_tasa(fuente)
            print(f'[tasa] {fuente}: líneas de referencia {self._txt_ref(ref)}', flush=True)
        # El estímulo afuera: la simulada arma una traza por tasa, no una por fuente.
        for tasa in a.tasas:
            n_pedido = int(max(a.n_min, tasa * a.seg))
            gen = G.config(aleatorio=True, tasa=tasa, dt_min=a.dt_min, n=n_pedido,
                           amp_aleat=True, semilla=a.semilla, **gen_base(a))
            gen['n'] = self.placa.recortar(gen)
            tabla = tabla_lineas(a.lineas, a.pesos)
            t_k = instantes(gen)
            rearme = perdidos_rearme_asg(t_k)
            ap = apilamiento(gen['n'] * FS_HZ / (int(t_k[-1]) + 1), a.tau, a.lineas, a.pesos)
            print(f'\n[tasa] {tasa:g}/s pedidos: {gen["n"]} pulsos; apilamiento '
                  f'{ap["nivel_medio"]:.0f} ± {ap["nivel_sigma"]:.0f} cuentas'
                  + (' (SATURA)' if ap['satura'] else ''), flush=True)
            for fuente in a.fuentes:
                ref = refs[fuente]
                for n_acc in a.n_acc or range(1, self.placa.n_acc_max + 1):
                    tag = f'tasa {fuente} n_acc={n_acc} {tasa:g}/s'
                    t0 = time.time()
                    res = self._correr(tag, gen, tabla, mca_de(fuente, gen['decae'], n_acc),
                                       disparo_de(fuente, gen['decae'], a.subida),
                                       _esp(a.espectros_tasa))
                    fila = dict(etapa='tasa', fuente=fuente, n_acc=n_acc, tasa=tasa,
                                tasa_cfg_hz=G.tasa(**disparos_cfg(gen)), gen=gen,
                                gen_estado=res['gen'], t_gen=res['t_gen'],
                                perdidos_rearme_asg=rearme, apilamiento=ap, corridas=[])
                    for (nombre, z), r in zip(_esp(a.espectros_tasa), res['corridas']):
                        m = meritos_tasa({**res, 'corridas': [r]}, gen['n'],
                                         ref[nombre]['lineas'])
                        if nombre == 't_subida':
                            m['t_subida'] = momentos(r['hist'])
                        fila['corridas'].append(dict(espectro=nombre, zoom=z, cnt=r['cnt'],
                                                     hist=_sparse(r['hist']), meritos=m))
                    self.filas.append(fila)
                    self.guardar()
                    print('    ' + linea_tasa(fila) + f'   ({time.time() - t0:.1f} s)',
                          flush=True)

    # -- par --

    def referencia_par(self, fuente):
        a = self.a
        gen = G.config(periodo=a.hueco // 2, n=4 * a.n_ref // 2, amp_n=4, **gen_base(a))
        tabla = np.array([a.a1, 0, a.a2, 0], np.int16)
        decae = gen['decae']
        res = self._correr(f'ref par {fuente}', gen, tabla, mca_de(fuente, decae, 1),
                           disparo_de(fuente, decae, a.subida), _esp(a.espectros_par))
        ref = self._referencia(f'ref par {fuente}', res, _esp(a.espectros_par), (a.a1, a.a2))
        self.referencias[f'par/{fuente}'] = ref
        return ref

    def etapa_par(self):
        a = self.a
        refs = {}
        for fuente in a.fuentes:
            if fuente == 'asg':
                print('[par] asg: no aplica (dispara también en los pulsos de altura 0)')
                continue
            refs[fuente] = ref = self.referencia_par(fuente)
            print(f'[par] {fuente}: líneas de referencia {self._txt_ref(ref)}', flush=True)
        for dt in a.dts:
            k = k_par(dt, a.hueco)
            gen = G.config(periodo=dt, n=k * a.n_pares, amp_n=k, **gen_base(a))
            n = self.placa.recortar(gen)
            gen['n'] = n - n % k                     # pares enteros
            n_pares = gen['n'] // k
            tabla = tabla_par(a.a1, a.a2, k)
            for fuente, ref in refs.items():
                for n_acc in a.n_acc_par or sorted({1, self.placa.n_acc_max}):
                    tag = f'par {fuente} n_acc={n_acc} dt={dt}'
                    res = self._correr(tag, gen, tabla, mca_de(fuente, gen['decae'], n_acc),
                                       disparo_de(fuente, gen['decae'], a.subida),
                                       _esp(a.espectros_par))
                    fila = dict(etapa='par', fuente=fuente, n_acc=n_acc, dt=dt, k=k,
                                n_pares=n_pares, gen=gen, gen_estado=res['gen'],
                                t_gen=res['t_gen'], corridas=[])
                    for (nombre, z), r in zip(_esp(a.espectros_par), res['corridas']):
                        m = meritos_par({'corridas': [r]}, n_pares, ref[nombre]['lineas'])[0]
                        if nombre == 't_subida':
                            m['t_subida'] = momentos(r['hist'])
                        fila['corridas'].append(dict(espectro=nombre, zoom=z, cnt=r['cnt'],
                                                     hist=_sparse(r['hist']), meritos=m))
                    self.filas.append(fila)
                    self.guardar()
                    print('    ' + linea_par(fila), flush=True)


# =============================================================================
# El resumen y la comparación
# =============================================================================

def linea_tasa(f):
    m = f['corridas'][0]['meritos']
    b = (f'buenos {m["buenos_hz"] / 1e3:7.1f} k/s ({100 * m["frac_buenos"]:5.1f} %)'
         if 'buenos_hz' in m else '')
    return (f'{f["fuente"]:9s} n_acc={f["n_acc"]} entrada {m["n_in_hz"] / 1e3:7.1f} k/s: '
            f'sin disparo {100 * m["perd_disparo"]:5.2f} %, sin ranura '
            f'{100 * m["perd_ranura"]:5.2f} %, publicador {100 * m["perd_publicador"]:5.2f} %'
            f' -> {m["aceptados_hz"] / 1e3:7.1f} k/s, {b}, muerto {100 * m["muerto"]:5.1f} %,'
            f' λ̂ {100 * m["err_lam"]:+6.2f} %')


def linea_par(f):
    partes = []
    for c in f['corridas']:
        m = c['meritos']
        if 'frac_a1' in m:
            partes.append(f'{c["espectro"]}: A1 {100 * m["frac_a1"]:5.1f} % '
                          f'A2 {100 * m["frac_a2"]:5.1f} %')
    m0 = f['corridas'][0]['meritos']
    return (f'{f["fuente"]:9s} n_acc={f["n_acc"]} Δt={f["dt"]:4d} ({8 * f["dt"]:5d} ns): '
            f'{m0["disparos_par"]:.3f} disparos y {m0["eventos_par"]:.3f} eventos por par; '
            + ' | '.join(partes))


def _nunca(x):
    return 'nunca' if x is None else x


def umbral_desde(xs, ys, cumple):
    """El menor x desde el cual `cumple(y)` vale para ese x y todos los mayores."""
    out = None
    for x, y in sorted(zip(xs, ys), reverse=True):
        if not cumple(y):
            break
        out = x
    return out


def resumen(filas):
    lineas = []
    tasa = [f for f in filas if f['etapa'] == 'tasa']
    grupos = sorted({(f['fuente'], f['n_acc']) for f in tasa})
    if grupos:
        lineas.append('\n== tasa: el techo (aceptados y buenos, k/s) ==')
    for fu, na in grupos:
        fs = [f for f in tasa if (f['fuente'], f['n_acc']) == (fu, na)]
        m = [f['corridas'][0]['meritos'] for f in fs]
        i = int(np.argmax([x['aceptados_hz'] for x in m]))
        txt = (f'  {fu:9s} n_acc={na}: aceptados máx {m[i]["aceptados_hz"] / 1e3:7.1f} '
               f'(entrada {m[i]["n_in_hz"] / 1e3:.0f})')
        if all('buenos_hz' in x for x in m):
            j = int(np.argmax([x['buenos_hz'] for x in m]))
            txt += (f', buenos máx {m[j]["buenos_hz"] / 1e3:7.1f} '
                    f'(entrada {m[j]["n_in_hz"] / 1e3:.0f})')
        lam = max(abs(x['err_lam']) for x in m)
        txt += f'; |error de λ̂| ≤ {100 * lam:.2f} %'
        lineas.append(txt)
    par = [f for f in filas if f['etapa'] == 'par']
    grupos = sorted({(f['fuente'], f['n_acc']) for f in par})
    if grupos:
        lineas.append('\n== par: resolución (Δt mínimo desde el cual se cumple, en ciclos) ==')
    for fu, na in grupos:
        fs = [f for f in par if (f['fuente'], f['n_acc']) == (fu, na)]
        dts = [f['dt'] for f in fs]
        d2 = umbral_desde(dts, [f['corridas'][0]['meritos']['disparos_par'] for f in fs],
                          lambda y: y >= 1.99)
        txt = f'  {fu:9s} n_acc={na}: 2 disparos por par desde {_nunca(d2)}'
        for k, esp in enumerate(fs[0]['corridas']):
            ms = [f['corridas'][k]['meritos'] for f in fs]
            if 'frac_a1' in ms[0]:
                dr = umbral_desde(dts, ms, lambda m: m['frac_a1'] >= 0.99 and
                                  m['frac_a2'] >= 0.99)
                txt += f'; los dos buenos ({esp["espectro"]}) desde {_nunca(dr)}'
        lineas.append(txt)
    return '\n'.join(lineas)


def _clave(f):
    return (f['etapa'], f['fuente'], f['n_acc'], f.get('tasa', f.get('dt')))


def comparar(p_placa, p_sim):
    """Las figuras de mérito de la placa y de la simulación, punto por punto."""
    with open(p_placa) as f:
        a = json.load(f)
    with open(p_sim) as f:
        b = json.load(f)
    sim = {_clave(f): f for f in b['filas']}
    print(f'placa: {p_placa} ({a["meta"]["placa"]}, {a["meta"]["fecha"]})')
    print(f'simulación: {p_sim} ({b["meta"]["placa"]}, {b["meta"]["fecha"]})')
    claves = {'tasa': ('perd_disparo', 'perd_ranura', 'perd_publicador', 'eficiencia',
                       'frac_buenos', 'muerto_mca', 'err_lam'),
              'par': ('disparos_par', 'eventos_par', 'frac_a1', 'frac_a2')}
    for f in a['filas']:
        s = sim.get(_clave(f))
        if s is None:
            continue
        for ca, cb in zip(f['corridas'], s['corridas']):
            ma, mb = ca['meritos'], cb['meritos']
            partes = []
            for k in claves[f['etapa']]:
                if ma.get(k) is not None and mb.get(k) is not None:
                    fmt = '{:.3f}' if f['etapa'] == 'par' else '{:.2%}'
                    partes.append(f'{k} {fmt.format(ma[k])}/{fmt.format(mb[k])}')
            print(f'  {" ".join(str(x) for x in _clave(f))} {ca["espectro"]}: '
                  + ', '.join(partes))
    return 0


# =============================================================================

def _lista(tipo):
    return lambda txt: [tipo(float(x)) if tipo is int else tipo(x) for x in txt.split(',') if x]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('outdir', nargs='?', help='dónde dejar meritos.json')
    ap.add_argument('--etapas', type=_lista(str), default=['tasa', 'par'])
    ap.add_argument('--fuentes', type=_lista(str), default=list(FUENTES))
    ap.add_argument('--n-acc', type=_lista(int), default=None,
                    help='ranuras de la etapa tasa (por defecto, de 1 a las del bitstream)')
    ap.add_argument('--n-acc-par', type=_lista(int), default=None,
                    help='ranuras de la etapa par (por defecto, 1 y las del bitstream)')
    ap.add_argument('--tasas', type=_lista(float), default=list(TASAS))
    ap.add_argument('--seg', type=float, default=1.0, help='segundos de pulsos por punto')
    ap.add_argument('--n-min', type=int, default=20_000, help='pulsos mínimos por punto')
    ap.add_argument('--dt-min', type=int, default=2,
                    help='ciclos mínimos entre pulsos del motor aleatorio (2: el más '
                         'cercano a Poisson; con 3 el ASG no pierde ninguno)')
    ap.add_argument('--lineas', type=_lista(int), default=[500, 1300],
                    help='las líneas de la etapa tasa: chicas para que el apilamiento '
                         'no sature los 14 bits hasta ~2 M/s con τ = 2 µs')
    ap.add_argument('--pesos', type=_lista(float), default=[0.6, 0.4])
    ap.add_argument('--dts', type=_lista(int), default=list(DTS))
    ap.add_argument('--n-pares', type=int, default=2000)
    ap.add_argument('--a1', type=int, default=4000, help='el primer pulso del par')
    ap.add_argument('--a2', type=int, default=2400, help='el segundo pulso del par')
    ap.add_argument('--hueco', type=int, default=3000,
                    help='ciclos de silencio entre pares (12 τ con τ = 250)')
    ap.add_argument('--n-ref', type=int, default=2000, help='pulsos de cada referencia')
    ap.add_argument('--espectros-tasa', type=_lista(str), default=['trapecio'])
    ap.add_argument('--espectros-par', type=_lista(str), default=['trapecio', 'pico'])
    ap.add_argument('--tau', type=float, default=250.0, help='caída, en muestras')
    ap.add_argument('--subida', type=int, default=0, help='SUBIDA del generador (0..7)')
    ap.add_argument('--ruido-sh', type=int, default=6,
                    help='ruido de sigma 147.8/2^sh (6: 2.3 cuentas); -1 sin ruido')
    ap.add_argument('--semilla', type=int, default=1)
    ap.add_argument('--simulada', action='store_true',
                    help='el modelo del generador y la réplica del MCA, en la PC')
    ap.add_argument('--h-aw', type=int, default=13, help='canales de la simulada: 2^h_aw')
    ap.add_argument('--ciclos-max', type=float, default=4e6,
                    help='la simulada recorta cada punto a estos ciclos')
    ap.add_argument('--comparar', nargs=2, metavar=('PLACA', 'SIMULADA'),
                    help='compara dos meritos.json y sale')
    a = ap.parse_args(argv)
    if a.ruido_sh is not None and a.ruido_sh < 0:
        a.ruido_sh = None
    for e in a.etapas:
        if e not in ('tasa', 'par'):
            ap.error(f'etapa {e!r}: tasa o par')
    for f in a.fuentes:
        if f not in FUENTES:
            ap.error(f'fuente {f!r}: una de {FUENTES}')
    for e in a.espectros_tasa + a.espectros_par:
        if e not in ESPECTROS:
            ap.error(f'espectro {e!r}: uno de {tuple(ESPECTROS)}')
    if len(a.lineas) != len(a.pesos):
        ap.error('--lineas y --pesos: el mismo largo')
    if min(a.dts, default=2) < 2:
        ap.error('--dts: el período mínimo del generador es 2 ciclos')
    if a.comparar is None and not a.outdir:
        ap.error('falta outdir')
    return a


def main(argv=None, placa=None):
    a = parse_args(argv)
    if a.comparar:
        return comparar(*a.comparar)
    if placa is None:
        if a.simulada:
            placa = PlacaSimulada(h_aw=a.h_aw, ciclos_max=int(a.ciclos_max))
        else:
            try:
                placa = PlacaReal()
            except G.GenPulsosNotPresent as e:
                print(f'  {e}\n  Hace falta un bitstream con gen_pulsos (el MCA cce7b66b o '
                      'el ring 78e26188 en adelante).')
                return 2
    camp = Campana(placa, a, a.outdir)
    print(f'{placa.nombre}: {1 << placa.h_aw} canales, {placa.n_acc_max} ranuras; '
          f'τ = {a.tau:g} muestras, subida {a.subida}, ruido sh {a.ruido_sh}')
    try:
        if 'tasa' in a.etapas:
            camp.etapa_tasa()
        if 'par' in a.etapas:
            camp.etapa_par()
    finally:
        placa.close()
        camp.guardar()
    print(resumen(camp.filas))
    if camp.anomalias:
        print(f'\n{len(camp.anomalias)} ANOMALÍAS:')
        for m in camp.anomalias:
            print(f'  {m}')
    if a.outdir:
        print(f'\n  -> {os.path.join(a.outdir, "meritos.json")}')
    return 1 if camp.anomalias else 0


if __name__ == '__main__':
    sys.exit(main())
