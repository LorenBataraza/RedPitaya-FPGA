#!/usr/bin/env python3
"""Las figuras de mérito del MCA con el generador de pulsos de la FPGA (`gen_pulsos`).

Es generación interna (docs/etapas_de_validacion.md): `gen_pulsos` maneja el MCA por el
lazo digital, sin el Rigol. A diferencia de `make verificar-placa-generadores`, que
exige que la placa dé lo mismo que la réplica, esta campaña mide el MCA contra lo que
se generó: cuántos pulsos, a qué tasa y de qué altura. Es lo que el Rigol no deja medir
(docs/resultados_validacion_hw.md §20.3).

Las etapas:

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
  histeresis
         la campaña de deriva del Rigol (resultados_validacion_hw.md §19.2-19.4) con
         el pulser digital: tren periódico a las mismas 16 tasas, de ida y de vuelta,
         5 s por punto, el MCA de esa campaña (una ranura, compuerta 384, el pico) y la
         base leída en vuelo. Con el Rigol el centroide difería 10.9 canales entre la
         ida y la vuelta. El generador de la FPGA arranca igual en cada punto, así que
         si acá no aparece, la histéresis era del DG4162 o del frente analógico. Dos
         modos: con el seguidor de base (como en el Rigol) y con la base fija.
  walk   pulsos aislados de 20 a 8000 cuentas, con cada fuente. t_subida (del disparo
         al pico) contra el del ASG da el walk del disparo; la eficiencia del disparo,
         la curva S del umbral; el trapecio y el pico, la linealidad de la cadena
         digital.
  ruido  la resolución contra el ruido inyectado: una línea (1500 cuentas) a tasa baja
         y el ruido del generador de σ = 0 a 148 cuentas (`ruido_sh` 8 a 0), con el
         disparo del ASG, que no depende del ruido. Por estimador (el pico y cada forma
         del banco sola): el desvío, la FWHM, la resolución, los bits efectivos y el
         corrimiento del centroide; y el ajuste σ² = (k σ_ruido)² + σ₀², con k la
         ganancia de ruido del estimador y σ₀ el piso (en el digital, la cuantización;
         en el analógico, además, el ADC). Cada punto se corre dos veces: con el
         histograma entero, para encontrar la línea, y con el zoom que la abre en la
         mayor cantidad de canales.
  forma  el largo del trapecio contra la tasa: una forma sola del banco de subida k (8 a
         512), una línea con Poisson y ruido blanco que manda en la resolución. FWHM/ε²
         (el tiempo hasta una precisión dada) contra la ocupación ρ = n·(antes +
         despues)/f_s: parametros_de_merito.md §8 predice el mínimo en ρ = 1/4.
  apilamiento
         el continuo de apilamiento y el par (eficiencia, rechazo) de cada corte del
         discriminador (dt_anterior, solape, t_subida, ancho_inv), con Poisson y las dos
         líneas de la etapa tasa. Cada corte es una corrida sobre el mismo estímulo.
  dnl    la no linealidad diferencial: amplitudes uniformes con el ruido como dither, el
         trapecio y el pico con un código por canal (en el analógico, la densidad de
         códigos del ADC).
  psd    la FOM de separación de formas sobre Q_cola/Q_total, entre dos caídas, contra
         la amplitud.
  polo_cero
         el error del segundo pulso de un par sobre la cola del primero contra el error
         de M del trapecio: la pendiente y la M que cancela la cola que llega al MCA.
  ventana_ciega
         los pares de la etapa par desde Δt = 2 con los cortes por forma: el mayor Δt
         donde el apilado que el disparo no separa pasa el corte.
  deriva el mismo tren de dos alturas cada minuto, durante horas: la deriva del offset y
         de la ganancia con el tiempo y con la temperatura del Zynq. Larga: en la placa,
         con nohup (ver `etapa_deriva`).

**El modo analógico** (`--modo analogico`, con un coaxial de OUT1 a IN1 y el jumper de
IN1 en LV): las mismas etapas con el lazo digital apagado. Antes de la primera se mide el
canal (`canal_analogico.py`, con la BRAM: el piso, la respuesta y la diafonía), y de ahí
salen dos ajustes del MCA:
  - la base fija es el offset de IN1 (en el lazo es 0);
  - con el disparo del ASG, que no mira la señal, el pulso llega `lat_asg` muestras más
    tarde que en el lazo: las ventanas del banco se corren eso dentro de la compuerta
    (`pre_dly` no puede ser negativo).
Las líneas de referencia se miden en el mismo modo, así que el criterio de "bueno" no
cambia. `--comparar analogico.json digital.json` da la diferencia punto por punto: es lo
que agrega la parte analógica. Con ruido real los contadores ya no se repiten entre las
corridas de un punto, y esa comprobación no se hace.

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

    python3 campanas/run_meritos_pulsos.py <outdir> [--etapas tasa,par,histeresis,walk,ruido,...]
        [--fuentes asg,pz,pendiente] [--n-acc 1,2,3] [--tasas 1e4,1e5,1e6]
        [--dts 2,4,8,16] [--seg 1] [--n-pares 2000] [--modo analogico]

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
sys.path.insert(0, os.path.join(_RAIZ, 'campanas'))

import API.generadores as G                                          # noqa: E402
import canal_analogico as CA                                         # noqa: E402
import replica_mca2 as r2                                            # noqa: E402
from API.mca import BANCO_PZ, BANCO_PZ_4, FEATURES, mca_banco_config  # noqa: E402

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
ETAPAS = ('tasa', 'par', 'histeresis', 'walk', 'ruido', 'forma', 'apilamiento', 'dnl', 'psd',
          'polo_cero', 'ventana_ciega', 'deriva')
MODOS = ('digital', 'analogico')
# Los espectros que se pueden pedir. `t_subida` (F_TRISE: del disparo al pico) es el que
# ve dónde cae la ventana y el walk del disparo; con zoom 3 el canal es el valor.
# `ancho_inv` (pico/Q) y `dt_anterior` son las features de los cortes de la etapa
# apilamiento; `psd` (Q_cola/Q_total), la de la etapa psd.
ESPECTROS = {'pico': r2.F_PEAK, 'trapecio': r2.F_TRAP, 't_subida': r2.F_TRISE,
             'psd': r2.F_PSD, 'ancho_inv': r2.F_INVW, 'dt_anterior': r2.F_DTPREV}
ZOOM = {'pico': 0, 'trapecio': 0, 't_subida': 3, 'psd': 0, 'ancho_inv': 3, 'dt_anterior': 3}

TASAS = (1e4, 3e4, 1e5, 2e5, 4e5, 7e5, 1e6, 1.5e6, 2e6, 3e6)
DTS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64,
       96, 128, 192, 256, 384, 512)
PERIODO_REF = 3000        # ciclos entre pulsos de la referencia de la etapa tasa
# La histéresis: las 16 tasas de la campaña del Rigol (testbench_mca.sweep_rate), de
# 100 Hz a 794 kHz, con tren periódico (el modo PULSE era periódico).
HIST_TASAS = tuple(float(x) for x in np.logspace(2, 5.9, 16))
# El walk y la curva S: desde abajo de los dos umbrales (50 cuentas el polo-cero, 75 la
# pendiente) hasta el fondo de escala.
WALK_AMPS = (20, 30, 40, 50, 60, 75, 90, 110, 150, 200, 300, 500, 800, 1300, 2000, 3200,
             5000, 8000)
# El ruido: −1 es sin ruido; de 8 (σ = 0.58 cuentas) a 0 (147.8). Con sh ≥ 9 el ruido
# del generador es menos de 0.3 cuentas y el redondeo lo come.
RUIDOS_SH = (-1, 8, 7, 6, 5, 4, 3, 2, 1, 0)
# Cada estimador: la forma del banco con que se corre (sola) y el espectro.
ESTIMADORES = {'pico': (0, 'pico'), 'forma0': (0, 'trapecio'), 'forma1': (1, 'trapecio'),
               'forma2': (2, 'trapecio')}
FONDO_ESCALA = G.AMP_MAX + 1   # para los bits efectivos, log2(FS / FWHM): 8192 cuentas
# La forma: el largo del trapecio contra la tasa (parametros_de_merito.md §8). Las
# tasas donde ρ_opt = 1/4 cae en k de ~11 a ~380 con L ≈ 2.75 k.
FORMA_KS = (8, 16, 32, 64, 128, 256, 512)
FORMA_TASAS = (3e4, 1e5, 3e5, 1e6)
# El apilamiento: los cortes por dt_anterior (muestras) y la fracción de los aislados
# que deja pasar cada corte por t_subida y por ancho_inv.
APIL_TASAS = (1e5, 3e5, 1e6)
APIL_CORTES_DT = (50, 100, 200, 400, 800)
APIL_CUANTILES = (0.999, 0.99, 0.9, 0.5)
# El polo-cero: el error relativo de M del trapecio contra el del generador.
PZ_DM = (-0.1, -0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.05, 0.1)
PZ_DTS = (100, 200, 400)
# La ventana ciega del corte por forma: pares a Δt de 2 ciclos (el período mínimo del
# generador) hasta donde los dos disparos se separan con holgura.
CIEGA_DTS = tuple(range(2, 17)) + (18, 20, 24, 28, 32, 40, 48)
CIEGA_CUANTILES = (0.99, 0.9)


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


def base_de(canal, base=0):
    """La base fija del MCA para una base `base` del generador: la misma en el lazo; en
    el analógico, lo que el canal hace de ella (el offset de IN1 más la ganancia)."""
    if not canal:
        return int(base)
    return int(round(canal['offset'] + canal['ganancia'] * float(base)))


def lat_de(canal, fuente):
    """Cuántas muestras más tarde llega el pulso respecto del disparo, contra el lazo
    digital: sólo con el ASG, que no mira la señal (los otros disparan sobre ella)."""
    return int(canal['lat_asg']) if canal and fuente == 'asg' else 0


def mca_de(fuente, decae, n_acc, canal=None, formas=BANCO_PZ, seguidor=None, mq=None):
    """El MCA: el banco de la placa con la Mq del generador y el pre_dly de la fuente.
    Las claves son las de `replica_mca2.CFG`, que `mca_configure` también acepta.

    Con el canal analógico y el ASG, el pulso llega `lat_asg` muestras tarde: el
    pre_dly baja eso y, si no alcanza (no hay pre_dly negativo), las ventanas del banco
    se corren lo que falta dentro de la compuerta (`mca_banco_config` las corre con su
    `pre_dly`, y la compuerta crece con ellas).

    `seguidor` = (bl_k, bl_holdoff) prende el seguidor de línea de base en lugar de la
    base fija (arranca en la fija). `mq` reemplaza la M·16 del generador en el trapecio
    (no en el disparo): la etapa polo_cero la corre."""
    pre = PRE_DLY[fuente] - lat_de(canal, fuente)
    kw = mca_banco_config(G.mq_de(decae) if mq is None else int(mq),
                          pre_dly=PRE_DLY['pz'] + max(0, -pre), formas=formas)
    kw.update(pre_dly=max(0, pre), n_acc=int(n_acc), baseline=base_de(canal), amp_min=0,
              amp_max=0xFFFF, amp_src=0, q_shift=0)
    if seguidor:
        kw.update(bl_auto=True, bl_k=int(seguidor[0]), bl_holdoff=int(seguidor[1]))
    return kw


def mca_campana(fuente, modo, base=0, canal=None):
    """El MCA de la campaña del Rigol (testbench_mca.DEFAULT_CFG): una ranura, la
    compuerta de 384 y el pico, con el seguidor de línea de base (modo 'seguidor', como
    se midió la histéresis) o la base fija en `base` (modo 'fija'). El pico en 384
    muestras no depende de dónde cae el pie: con el ASG en el analógico alcanza con
    bajar el pre_dly hasta 0."""
    kw = dict(baseline=base_de(canal, base), amp_min=0, amp_max=0xFFFF, amp_src=0,
              q_shift=0, gate_short=32, gate_long=384, n_acc=1,
              pre_dly=max(0, PRE_DLY[fuente] - lat_de(canal, fuente)), n_formas=1)
    if modo == 'seguidor':
        kw.update(bl_auto=True, bl_k=12, bl_holdoff=64)
    elif modo != 'fija':
        raise ValueError(f"modo {modo!r}: 'seguidor' o 'fija'")
    return kw


def forma_k(k):
    """La forma del banco `(k, m, lw, c, antes, despues)` de subida k: la de la placa
    (`BANCO_PZ_4`) para k = 8..64 y, para las otras, la misma regla: m = 3k/4 (k si
    k ≤ 8), la ventana de 2^lw = k/4 muestras centrada en la meseta [k − 1, k + m), con
    `c` contado desde el disparo del polo-cero (LAT_PZ después del pie), y los umbrales
    de separacion_trapezoidal.md §2: antes = 2k + m − 1 − w₀ (+2 de margen) y despues =
    w₀ + 2^lw, con w₀ el primer punto de la ventana desde el pie. La regla da las de la
    placa salvo antes en k = 8 y 16 (una muestra menos)."""
    k = int(k)
    for f in BANCO_PZ_4:
        if f[0] == k:
            return tuple(int(v) for v in f)
    if k < 2 or k & (k - 1) or k > 512:
        raise ValueError(f'k = {k}: una potencia de 2 de 2 a 512 (k + m ≤ 1023)')
    m = k if k <= 8 else 3 * k // 4
    lw = max(1, int(math.log2(k)) - 2)
    w0 = k - 1 + -(-(m + 1 - (1 << lw)) // 2)
    return (k, m, lw, w0 - r2.LAT_PZ, 2 * k + m + 1 - w0, w0 + (1 << lw))


def tabla_uniforme(lo, hi):
    """La tabla del modo `amp_aleat` con las 1024 amplitudes repartidas parejas de lo a
    hi: con el ruido como dither, la entrada de la DNL es una densidad uniforme."""
    return np.round(np.linspace(float(lo), float(hi), G.N_TABLA)).astype(np.int16)


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
    if not d['aleatorio']:
        # Periódico: el primero en PERIODO − 1, y de ahí cada PERIODO (gen_disparos.c).
        # Sin simular el motor: un punto de 5 s son 6·10⁸ ciclos, segundos en el ARM.
        per = max(int(d['periodo']), 2)
        t = (np.arange(n, dtype=np.int64) + 1) * per - 1 + G.LAT_TRIG
        _INSTANTES.clear()
        _INSTANTES[clave] = t
        return t
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


def satura_adc(nivel, canal):
    """¿Un nivel del generador (en sus cuentas) pasa el fondo de escala? En el
    analógico, también el del ADC después del canal."""
    if nivel > G.AMP_MAX:
        return True
    return bool(canal) and canal['offset'] + canal['ganancia'] * nivel > G.AMP_MAX


def apilamiento(n_in_hz, tau, lineas, pesos, canal=None):
    """El nivel medio del apilamiento y su desvío, en cuentas (Campbell: μ = λ τ E[A],
    σ² = λ τ E[A²] / 2 para h = e^(−t/τ), con λ por muestra y τ en muestras). Si
    μ + 3σ pasa de 8191, la salida del generador (14 bits) se recorta seguido: el
    estímulo satura, como saturaría el ADC con esa señal."""
    w = np.asarray(pesos, float) / np.sum(pesos)
    a = np.asarray(lineas, float)
    lt = n_in_hz / FS_HZ * float(tau)
    mu = lt * float((w * a).sum())
    sigma = math.sqrt(lt * float((w * a * a).sum()) / 2.0)
    return dict(nivel_medio=mu, nivel_sigma=sigma, satura=satura_adc(mu + 3.0 * sigma, canal))


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


def temperatura_zynq():
    """La temperatura del Zynq en °C, del XADC por IIO, o None si no está (la PC, o un
    kernel sin el driver)."""
    import glob
    for d in sorted(glob.glob('/sys/bus/iio/devices/iio:device*')):
        try:
            with open(os.path.join(d, 'name')) as fh:
                if 'xadc' not in fh.read():
                    continue
            v = {}
            for n in ('raw', 'offset', 'scale'):
                with open(os.path.join(d, f'in_temp0_{n}')) as fh:
                    v[n] = float(fh.read().strip())
            return (v['raw'] + v['offset']) * v['scale'] / 1000.0
        except (OSError, ValueError):
            continue
    return None


def zoom_rango(lo, hi, h_aw):
    """El zoom (z, k) más fino cuya ventana contiene los valores de la feature [lo, hi]."""
    for z in range(16 - int(h_aw), -1, -1):
        W = 1 << (16 - z)
        k = int(lo // W)
        if lo >= 0 and hi < (k + 1) * W and k <= 0xFF:
            return (z, k)
    return (0, 0)


def centroides_lineas(hist, n=2, hueco=3):
    """Las n líneas de un espectro de pulsos aislados, sin continuo, de menor a mayor:
    cada una es el tramo ocupado alrededor de un máximo (huecos de hasta `hueco` canales
    vacíos adentro), sin el primer ni el último canal (con zoom, ahí se junta lo de
    afuera). Por línea: centroide (canales fraccionarios), su error y las cuentas."""
    h = np.asarray(hist, float).copy()
    h[0] = h[-1] = 0
    out = []
    for _ in range(int(n)):
        i = int(np.argmax(h))
        if h[i] <= 0:
            break
        lo = hi = i
        while lo > 0 and h[max(lo - hueco - 1, 0):lo].any():
            lo -= 1
        while hi < h.size - 1 and h[hi + 1:hi + hueco + 2].any():
            hi += 1
        c = np.arange(lo, hi + 1)
        w = h[lo:hi + 1]
        mu = float((c * w).sum() / w.sum())
        var = float(((c - mu) ** 2 * w).sum() / w.sum())
        out.append(dict(centroide=mu, error=math.sqrt((var + 1 / 12) / w.sum()), n=int(w.sum())))
        h[lo:hi + 1] = 0
    return sorted(out, key=lambda d: d['centroide'])


def cortes_forma(corridas, espectros, cuantiles, h_aw):
    """Los cortes del discriminador sobre las features de forma: por feature y por q, el
    intervalo central que deja pasar la fracción q de los aislados (de los dos lados: un
    pulso montado corre la feature para cualquier lado, y ancho_inv satura en 0xFFFF si
    Q ≤ pico). `corridas` son los espectros de los aislados con zoom 3 (un valor por
    canal). Devuelve [(feature, q, (feature, min, max))]."""
    out = []
    for (nombre, z), r in zip(espectros, corridas):
        h = np.asarray(r['hist'], float)
        cdf = np.cumsum(h) / max(h.sum(), 1)
        ancho = 1 << (16 - int(_zoom(z)[0]) - int(h_aw))
        for q in cuantiles:
            c_lo = int(np.searchsorted(cdf, (1.0 - q) / 2.0, side='right'))
            c_hi = int(np.searchsorted(cdf, (1.0 + q) / 2.0))
            out.append((nombre, q, (nombre, c_lo * ancho, (c_hi + 1) * ancho - 1)))
    return out


# =============================================================================
# Las dos placas
# =============================================================================
# `correr(gen, tabla, mca, disparo, espectros)` corre el generador una vez por
# espectro, con el MCA desde antes del arranque hasta después del último pulso, y
# devuelve {'gen', 't_gen', 'corridas': [{'cnt', 'hist'}]}. `cnt` trae los contadores
# con los nombres de mca_read_counters y los relojes en ciclos. Cada espectro es
# (nombre, zoom), con zoom un z o un (z, k): la ventana k-ésima de 2^(16 − z) valores.
# `caracterizar_canal()` mide el canal analógico (None en el modo digital) y lo deja en
# `canal`, que la campaña usa para configurar el MCA.


def _zoom(z):
    return (int(z[0]), int(z[1])) if isinstance(z, (tuple, list)) else (int(z), 0)

PASO_BASE_S = 0.25       # un paso de la base dinámica (`--base-tasa dinamica`)
CLAVES_CNT = ('total', 'accepted', 'rej_amp', 'rej_psd', 'pileup', 'dropped', 'cross',
              'open', 'lost_active', 'lost_veto', 'windows', 'trig_edges', 'rej_discr')
RELOJES = ('realtime', 'livetime', 'vetotime', 't_win', 't_div', 't_rearm')
# Lo del seguidor de línea de base: lo acepta mca_configure, no la réplica.
CLAVES_BASE = ('bl_auto', 'bl_k', 'bl_holdoff')


class NoModelado(RuntimeError):
    """La placa simulada no tiene eso (el seguidor de base, por ejemplo)."""


class PlacaSimulada:
    """El modelo del generador y la réplica del MCA: lo que la placa tiene que dar. En
    modo analógico, la traza pasa antes por un canal: el de juguete
    (`canal_analogico.CanalSimulado`), que sirve para recorrer el código y no para
    comparar números con la placa, o el medido (`canal_analogico.CanalMedido`), que sí
    se compara."""

    nombre = 'simulada'

    def __init__(self, h_aw=13, n_acc_max=3, ciclos_max=4_000_000, modo='digital',
                 canal=None):
        mod = os.path.join(_RAIZ, '..', 'modulos', 'gen_eventos', 'modelos', 'python_model')
        sys.path.insert(0, os.path.abspath(mod))
        import gen_pulsos_model as gp
        import volcado_pulsos as vp
        self.gp, self.vp = gp, vp
        self.h_aw, self.n_acc_max, self.ciclos_max = int(h_aw), int(n_acc_max), int(ciclos_max)
        if modo not in MODOS:
            raise ValueError(f'modo {modo!r}: uno de {MODOS}')
        self.modo = modo
        self.canal_sim = canal if canal is not None else CA.CanalSimulado()
        self.canal = None
        self._cache = {}

    def caracterizar_canal(self, semilla=1):
        """El canal con las capturas simuladas de run_fidelidad_osc: el mismo análisis
        que en la placa, sobre el canal de juguete."""
        if self.modo != 'analogico':
            return None
        from run_fidelidad_osc import CapturaSimulada, capturar_canal
        cap = CapturaSimulada(['bram'], n_buf=16384, modo='analogico', canal=self.canal_sim)
        self.canal = CA.caracterizar(**capturar_canal(cap, semilla))
        return self.canal

    def recortar(self, gen, n_min=3):
        """El N que entra en `ciclos_max` (la placa corre el N pedido), y al menos
        `n_min`: con un tren lento (100 Hz son 1.25·10⁶ ciclos entre pulsos) el recorte
        no dejaría ninguno."""
        d = disparos_cfg(gen)
        t = G.predecir(self.ciclos_max, G.LAT_TRIG, n_max=int(d['n']), **d)
        return int(max(t.size, min(int(d['n']), n_min)))

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
            if self.modo == 'analogico':
                x = self.canal_sim.aplicar(x, 0)
            self._cache = {clave: (x, t)}           # una por vez: son grandes
        return self._cache[clave]

    def correr(self, gen, tabla, mca, disparo, espectros, base=False, dinamica=None):
        if mca.get('bl_auto'):
            raise NoModelado('el seguidor de línea de base no está en la réplica '
                             '(la base es fija)')
        if dinamica is not None:
            raise NoModelado('la base dinámica escribe la base en vuelo: la réplica '
                             'no lo tiene')
        discr = mca.get('discr')
        mca = {k: v for k, v in mca.items() if k not in CLAVES_BASE + ('discr',)}
        x, t = self._traza(gen, tabla)
        if disparo['fuente'] == 'asg':
            trig = self.vp.disparos_asg(t['trig']) + LAT_ASG_TOP + self.vp.PAD
            extra = {}
        else:
            trig = None
            extra = dict(disparo)
        c = r2.cfg(**mca, **extra)
        m = r2.medir(x, c, trig=trig)
        # Lo último que midió, para los análisis por evento (sim_corrimiento_canal.py).
        self.ultima = dict(x=x, t=t, trig=trig, cfg=c, medida=m)
        k, n_acc = m['cnt'], int(mca['n_acc'])
        # El discriminador (no está en la réplica): sobre las features de los
        # publicados, como en el RTL, que lo pone después de los divisores.
        pasa = np.ones(m['eventos']['feat'].shape[0], bool)
        if discr is not None:
            fv = m['eventos']['feat'][:, FEATURES[discr[0]]]
            pasa = (fv >= int(discr[1])) & (fv <= int(discr[2]))
            if len(discr) > 3 and discr[3]:
                pasa = ~pasa
        to = [int(v) for v in m['t_ocup'][:self.n_acc_max + 1]]
        # cnt_accepted cuenta en el publicador, antes del discriminador (mca_top.sv):
        # accepted = espectro + rej_discr.
        cnt = dict(total=k['total'], accepted=int(pasa.size), rej_amp=k['rej_amp'],
                   rej_psd=k['rej_psd'], pileup=k['pileup'], dropped=k['lost_busy'],
                   cross=k['cross'], open=k['open'], lost_active=k['lost_active'],
                   lost_veto=k['lost_veto'], windows=k['windows'], trig_edges=k['trig'],
                   realtime=int(x.size), vetotime=0, t_win=to[n_acc], t_div=0,
                   t_rearm=None, livetime=sum(to[:n_acc]), t_ocup=to,
                   rej_discr=int((~pasa).sum()))
        corridas = []
        for nombre, z in espectros:
            feat = m['eventos']['feat'][pasa, ESPECTROS[nombre]]
            zz, kk = _zoom(z)
            canal = self.vp.canal_1d(feat, zz, kk, aw=self.h_aw)
            corridas.append({'cnt': dict(cnt), 'hist': np.bincount(canal, minlength=1 << self.h_aw)})
        gen_est = dict(gen_cnt=int(t['trig'].size), terminado=True, desborde=bool(t['desborde']))
        out = {'gen': gen_est, 't_gen': int(t['trig'][-1]) + 1, 'corridas': corridas}
        if base:
            b = int(mca.get('baseline', 0))
            for r in corridas:
                r['base'] = dict(base_ahora=b, base_evento=b)
        return out

    def temperatura(self):
        return None

    def close(self):
        self._cache = {}


class PlacaReal:
    """El generador por el lazo digital (o por OUT1 → IN1 en el modo analógico), el MCA
    y el multitrigger en la Pitaya."""

    nombre = 'placa'

    def __init__(self, ch=0, modo='digital'):
        from API import mca as M
        from API import multitrigger as MT
        from API import osciloscope as O
        from API import integration as I
        if modo not in MODOS:
            raise ValueError(f'modo {modo!r}: uno de {MODOS}')
        self.M, self.MT, self.O, self.I = M, MT, O, I
        self.ch, self.modo, self.canal = int(ch), modo, None
        self.g = G.GenPulsos.open()                  # GenPulsosNotPresent sin generador
        self.h = M.mca_open()
        self.mtr = MT.MtRegion.open()
        self.osc = O.osciloscope_open()
        self.ig = I.integration_open()
        self.h_aw = int(self.h.h_aw)
        self.n_acc_max = int(M.mca_get_n_acc_max(self.h))
        self._rutas()

    def _rutas(self):
        I = self.I
        I.integration_set_route_mca(self.ig, I.TAP_ADC)
        I.integration_set_route_mtrg(self.ig, I.TAP_ADC)
        self.g.lazo = self.modo == 'digital'

    def caracterizar_canal(self, semilla=1):
        """El canal analógico con la BRAM (run_fidelidad_osc.capturar_canal: el piso y
        el estímulo con y sin el lazo). Abre sus propios handles y, al cerrarlos,
        resetea las rutas: se vuelven a poner."""
        if self.modo != 'analogico':
            return None
        from run_fidelidad_osc import CapturaPlaca, capturar_canal
        cap = CapturaPlaca(['bram'], modo='analogico')
        try:
            d = capturar_canal(cap, semilla)
        finally:
            cap.close()
            self._rutas()
        self.canal = CA.caracterizar(**d)
        return self.canal

    def recortar(self, gen):
        return int(gen['n'])

    def temperatura(self):
        return temperatura_zynq()

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

    def _ley(self, mca, dinamica, nombre):
        """La base dinámica de una corrida (`API/base_dinamica.py`), cebada con el
        estímulo: λ y ⟨A⟩ de entrada conocidos, así el espectro no junta el transitorio
        del promedio. Con un espectro que no es de amplitud (t_subida), ⟨A⟩ queda en el
        cebado: el histograma no dice nada de la amplitud."""
        from API import base_dinamica as BD
        ley = BD.BaseDinamica(dinamica['caida'], dinamica['ganancia_mca'][nombre],
                              int(mca.get('baseline', 0)), dinamica.get('kappa', 1.0),
                              suavizado_s=dinamica.get('suavizado_s', 0.5))
        ley.cebar(dinamica['lam0'], dinamica['a0'], BD.tau_de_mq(mca['trap_mq']))
        ley.fijar_a = nombre == 't_subida'
        return ley

    def _esperar_con_ley(self, ley, z, plazo):
        """Hasta que el generador termina, un paso de la ley cada PASO_BASE_S: lee los
        contadores y el histograma y escribe la base fija. Devuelve el estado del
        generador y los pasos (Δb, λ̂, ⟨A⟩, base)."""
        from API import base_dinamica as BD
        M, h, g = self.M, self.h, self.g
        v = BD.valores_de_canales(1 << self.h_aw, self.h_aw, *_zoom(z))
        tau = BD.tau_de_mq(M.mca_get_trap_mq(h))
        pasos, fin = [], time.monotonic() + plazo
        while True:
            time.sleep(PASO_BASE_S)
            ley.paso(M.mca_read_counters(h), M.mca_read_histogram(h), v, tau)
            M.mca_set_baseline(h, ley.base())
            e = ley.estado()
            pasos.append({k: e[k] for k in ('delta_b', 'lam_hz', 'a_adu', 'base')})
            est = g.estado()
            if est['terminado'] or time.monotonic() > fin:
                return est, pasos

    def correr(self, gen, tabla, mca, disparo, espectros, base=False, dinamica=None):
        """`base=True` lee la línea de base EN VUELO, a mitad del tren de pulsos: el
        registro del seguidor (`baseline_now`) y la del último evento publicado, que
        es la que se restó. Después del stop no sirve: con run = 0 el seguidor deja de
        congelarse en los pulsos y promedia el tren entero
        (resultados_validacion_hw.md §19.5, punto 3).

        `dinamica` (la etapa tasa con `--base-tasa dinamica`): la caída, G_F por
        espectro, κ y el cebado (lam0, a0); la base fija se mueve en vuelo con la ley
        (`_ley`, `_esperar_con_ley`) y la corrida guarda sus pasos."""
        M, h, g = self.M, self.h, self.g
        g.configurar(**gen)
        g.cargar_tabla(tabla)
        t_k = instantes(gen)
        plazo = 2.0 * t_k[-1] / FS_HZ + 2.0
        corridas, est = [], None
        for nombre, z in espectros:
            M.mca_configure(h, **mca, sel_1d=nombre, zoom_1d=_zoom(z))
            self._armar(disparo)
            b, ley, pasos = None, None, None
            try:
                M.mca_clear(h)
                if dinamica is not None:
                    ley = self._ley(mca, dinamica, nombre)
                    M.mca_set_baseline(h, ley.base())
                M.mca_start(h)
                time.sleep(0.002)
                g.arrancar()
                if base:
                    time.sleep(0.5 * t_k[-1] / FS_HZ)
                    b = dict(base_ahora=int(M.mca_get_baseline_now(h)),
                             base_evento=int(M.mca_read_last_event(h)['baseline']))
                if ley is not None:
                    est, pasos = self._esperar_con_ley(ley, z, plazo)
                else:
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
            if b is not None:
                corridas[-1]['base'] = b
            if ley is not None:
                M.mca_set_baseline(h, int(mca.get('baseline', 0)))
                corridas[-1]['base_dinamica'] = dict(pasos=pasos, final=ley.estado())
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

def valor_de_canal(canal, h_aw, z=0, k=0):
    """El valor de la feature (16 bits) en el centro de un canal (fraccionario, como
    un centroide): con el zoom (z, k), el canal c junta los valores
    k · 2^(16 − z) + [c, c + 1) · 2^(16 − z − h_aw)."""
    return ((np.asarray(canal, float) + 0.5) * float(1 << (16 - int(z) - int(h_aw)))
            + float(int(k) << (16 - int(z))))


def fwhm_hist(w):
    """El ancho a media altura de un histograma de una línea, en canales, con los
    cruces interpolados. None si la línea ocupa menos de 3 canales."""
    w = np.asarray(w, float)
    i = int(np.argmax(w))
    m = w[i] / 2.0
    if m <= 0 or (w > m).sum() < 3:
        return None
    lo = i
    while lo > 0 and w[lo - 1] > m:
        lo -= 1
    hi = i
    while hi < w.size - 1 and w[hi + 1] > m:
        hi += 1
    if lo == 0 or hi == w.size - 1:
        return None
    xl = lo - 1 + (m - w[lo - 1]) / (w[lo] - w[lo - 1])
    xr = hi + (w[hi] - m) / (w[hi] - w[hi + 1])
    return float(xr - xl)


def estadistica_linea(hist, h_aw, z=0, k=0):
    """Una línea sola (pulsos aislados de una altura): centroide, desvío y FWHM en
    unidades de la feature, sin el primer ni el último canal (con zoom, ahí se juntan
    los que caen fuera de la ventana; sin zoom, el canal 0 son los marcados).

    La feature es entera, y algunas van en pasos de más de 1 (el pico, alineado a la
    izquierda, de a 4): el `paso` es el MCD de las distancias entre canales ocupados.
    Si el canal es más ancho que el paso de la feature (paso 1 con ancho > 1), el
    desvío lleva la corrección de Sheppard, (ancho² − 1)/12; si no, el histograma es la
    distribución exacta y no se corrige.

    La FWHM se mide sobre el histograma suavizado con una gaussiana de σ_k = max(σ/4,
    paso/2) canales, y se le resta el ancho del núcleo en cuadratura: con unos miles de
    cuentas el canal más alto fluctúa, y la media altura del histograma crudo (o de una
    línea en púas) no es la de la línea. None si la línea ocupa menos de 1.5 canales de
    desvío: ahí la FWHM no está definida y vale 2.355 σ."""
    h = np.asarray(hist, float)
    w = h.copy()
    w[0] = w[-1] = 0
    n = float(w.sum())
    if n == 0:
        return None
    c = np.arange(h.size)
    mu_c = float((c * w).sum() / n)
    var_c = float(((c - mu_c) ** 2 * w).sum() / n)
    ancho = float(1 << (16 - int(z) - int(h_aw)))
    occ = np.flatnonzero(w)
    paso = int(np.gcd.reduce(np.diff(occ))) if occ.size > 1 else 1
    corr = (ancho * ancho - 1.0) / 12.0 if paso == 1 else 0.0
    sc = math.sqrt(var_c)
    fw = None
    if sc >= 1.5:
        hk = max(0.25 * sc, paso / 2.0)
        xs = np.arange(-int(4 * hk) - 1, int(4 * hk) + 2, dtype=float)
        ker = np.exp(-0.5 * (xs / hk) ** 2)
        ker /= ker.sum()
        sk = math.sqrt(float((xs * xs * ker).sum()))          # el σ del núcleo discreto
        fs = fwhm_hist(np.concatenate([[0.0], np.convolve(w, ker, mode='same'), [0.0]]))
        if fs is not None:
            fw = math.sqrt(max(fs * fs - (2.3548 * sk) ** 2, 0.0)) * ancho
    sigma = math.sqrt(max(var_c * ancho * ancho - corr, 0.0))
    return dict(n=int(n), fuera=int(h[0] + h[-1]),
                centroide=float(valor_de_canal(mu_c, h_aw, z, k)), sigma=sigma,
                sigma_bruto=math.sqrt(var_c) * ancho, fwhm=fw, fwhm_gauss=2.3548 * sigma,
                ancho_canal=ancho, paso=paso * ancho, canales=int(occ.size))


def zoom_para(st, h_aw, n_sigma=6.0):
    """El zoom (z, k) más fino cuya ventana contiene la línea a ±n_sigma (y 4 canales
    de margen), desde la estadística de una corrida sin zoom."""
    mu = st['centroide']
    s = max(st['sigma_bruto'], st['ancho_canal'])
    for z in range(16 - int(h_aw), -1, -1):
        W = 1 << (16 - z)
        bw = W >> int(h_aw)
        lo, hi = mu - n_sigma * s - 4 * bw, mu + n_sigma * s + 4 * bw
        k = int(lo // W)
        if lo >= 0 and hi < (k + 1) * W and k <= 0xFF:
            return (z, k)
    return (0, 0)


def analizar_ruido(filas):
    """Por estimador, en cuentas de amplitud: la ganancia de la feature sale del punto
    de menos ruido (centroide / A), y con ella el desvío, la FWHM, la resolución (FWHM /
    centroide), los bits efectivos (log2(8192 / FWHM)) y el corrimiento del centroide
    contra el de menos ruido. El ajuste σ² = (k σ_ruido)² + σ₀² es por cuadrados mínimos
    sobre σ², con peso 1/σ² (el error relativo de σ² es el mismo en todos los puntos).
    Quedan afuera los puntos con eventos fuera de la ventana del zoom."""
    por = {}
    for f in filas:
        por.setdefault(f['estimador'], []).append(f)
    out = {}
    for e, fs in por.items():
        ok = sorted((f for f in fs if f['medida'] and f['medida']['fuera'] == 0),
                    key=lambda f: f['sigma_in'])
        if not ok:
            out[e] = dict(puntos=[])
            continue
        ref = ok[0]['medida']
        A = float(ok[0]['amplitud'])
        gan = ref['centroide'] / A
        pts = []
        for f in ok:
            m = f['medida']
            s = m['sigma'] / gan
            fw = m['fwhm'] / gan if m.get('fwhm') else 2.3548 * s
            amp = m['centroide'] / gan
            pts.append(dict(ruido_sh=f['ruido_sh'], sigma_in=f['sigma_in'], sigma=s, fwhm=fw,
                            resolucion=fw / amp, bits=(math.log2(FONDO_ESCALA / fw)
                                                       if fw > 0 else None),
                            sesgo=m['centroide'] / ref['centroide'] - 1.0, n=m['n']))
        d = dict(ganancia_feature=gan, amplitud=A, puntos=pts,
                 sigma_sin_ruido=next((p['sigma'] for p in pts if p['sigma_in'] == 0), None))
        si = np.array([p['sigma_in'] for p in pts])
        so = np.array([p['sigma'] for p in pts])
        sel = so > 0
        if (si[sel] > 0).sum() >= 2:
            A_ = np.vstack([si[sel] ** 2, np.ones(sel.sum())]).T / (so[sel] ** 2)[:, None]
            (k2, s02), *_ = np.linalg.lstsq(A_, np.ones(sel.sum()), rcond=None)
            d.update(ganancia_ruido=math.sqrt(max(k2, 0.0)), sigma_0=math.sqrt(max(s02, 0.0)))
        out[e] = d
    return out


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


def linea_principal(hist, ancho=VENTANA_CENTROIDE):
    """La línea más alta de un espectro (sin el canal 0): centroide y desvío en
    canales, a ±`ancho` del máximo, y el error del centroide. El error lleva el
    1/12 del binado: una línea que cae entera en un canal no tiene desvío, y su
    centroide igual se conoce sólo a ±1/√12 canal."""
    h = np.asarray(hist, float)
    if h.size < 2 or h[1:].sum() == 0:
        return None
    i = int(np.argmax(h[1:])) + 1
    lo = max(1, int(math.floor(i * (1 - ancho))))
    hi = min(h.size - 1, int(math.ceil(i * (1 + ancho))))
    w = h[lo:hi + 1]
    c = np.arange(lo, hi + 1)
    n = float(w.sum())
    mu = float((c * w).sum() / n)
    s = float(math.sqrt(((c - mu) ** 2 * w).sum() / n))
    return dict(centroide=mu, sigma=s, n=int(n), error=math.sqrt((s * s + 1 / 12) / n))


def pico_periodico(amp, periodo, tau, base=0):
    """El máximo de un tren periódico de pulsos h = e^(−t/τ) de altura `amp`: cada
    pulso monta en las colas de todos los anteriores, A / (1 − e^(−T/τ))."""
    return float(base) + float(amp) / (1.0 - math.exp(-float(periodo) / float(tau)))


def analizar_histeresis(filas):
    """La ida contra la vuelta de un modo, tasa por tasa.

    - `h` = centroide de la vuelta − el de la ida, en canales, con su error
      estadístico; `h_sig` en unidades de ese error.
    - `efecto_tasa`: el recorrido del centroide de la ida con la tasa (sin los puntos
      que saturan). Es la escala contra la que se lee `h`, como en testbench_mca
      (`_analizar_deriva`): no es un estimador de ruido.
    - La pendiente de `h` contra la separación entre visitas es la deriva con el
      tiempo; `corr_h_muerto` es lo que con el Rigol daba +0.40 (§19.4).
    """
    ida = {f['tasa']: f for f in filas if f['pasada'] == 'ida'}
    vue = {f['tasa']: f for f in filas if f['pasada'] == 'vuelta'}
    tasas = sorted(set(ida) & set(vue))
    pares = [(r, ida[r]['medida'], vue[r]['medida']) for r in tasas
             if ida[r]['medida']['linea'] and vue[r]['medida']['linea']]
    out = dict(tasas=[p[0] for p in pares])
    if not pares:
        return out
    li = [p[1]['linea'] for p in pares]
    lv = [p[2]['linea'] for p in pares]
    h = np.array([b['centroide'] - a['centroide'] for a, b in zip(li, lv)])
    err = np.array([math.hypot(a['error'], b['error']) for a, b in zip(li, lv)])
    dt = np.array([p[2]['t_s'] - p[1]['t_s'] for p in pares])
    dmuerto = np.array([p[2]['muerto'] - p[1]['muerto'] for p in pares])
    dbase = np.array([p[2]['base_evento'] - p[1]['base_evento'] for p in pares])
    sat = np.array([p[1]['satura'] for p in pares])
    cen_i = np.array([a['centroide'] for a in li])
    ok = ~sat if (~sat).sum() >= 2 else np.ones(sat.shape, bool)
    out.update(h=h.tolist(), h_err=err.tolist(), dt_s=dt.tolist(), dmuerto=dmuerto.tolist(),
               dbase=dbase.tolist(), cen_ida=cen_i.tolist(),
               cen_vuelta=[b['centroide'] for b in lv],
               h_max=float(np.max(np.abs(h))), h_sig_max=float(np.max(np.abs(h) / err)),
               efecto_tasa=float(np.ptp(cen_i[ok])),
               corrimiento=float(cen_i[ok][-1] / cen_i[ok][0] - 1))
    if len(pares) >= 3 and np.ptp(dt) > 0:
        m, b = np.polyfit(dt, h, 1)
        out.update(deriva_canales_hora=float(m * 3600.0), ordenada=float(b))
    if len(pares) >= 3 and np.ptp(h) > 0 and np.ptp(dmuerto) > 0:
        out['corr_h_muerto'] = float(np.corrcoef(h, dmuerto)[0, 1])
    out['veredicto'] = ('sin histéresis' if out['h_sig_max'] < 3.0
                        else 'histéresis' if out['h_max'] > 0.05 * max(out['efecto_tasa'], 1e-9)
                        else 'histéresis chica (< 5 % del efecto de la tasa)')
    return out


def cruce(xs, ys, y0):
    """El x (interpolado en log x) donde `ys`, creciente, cruza `y0` por primera vez."""
    for (x0, a), (x1, b) in zip(zip(xs, ys), list(zip(xs, ys))[1:]):
        if a < y0 <= b:
            f = (y0 - a) / (b - a)
            return float(math.exp(math.log(x0) + f * (math.log(x1) - math.log(x0))))
    return None


def analizar_walk(filas, amin_inl=200):
    """Por fuente: la curva S (eficiencia del disparo contra la amplitud, y la
    amplitud del 50 %), el walk (t_subida menos el del ASG a la misma amplitud: el
    ASG dispara sin mirar la señal, así que lo que difiere es del disparo) y la no
    linealidad del trapecio (residuo de una recta por las amplitudes desde
    `amin_inl` donde dispara siempre, en % del fondo de escala)."""
    por = {}
    for f in filas:
        por.setdefault(f['fuente'], []).append(f)
    ref = {f['amplitud']: f['medida'] for f in por.get('asg', [])}
    out = {}
    for fuente, fs in por.items():
        fs = sorted(fs, key=lambda f: f['amplitud'])
        a = [f['amplitud'] for f in fs]
        m = [f['medida'] for f in fs]
        ef = [x['efic_disparo'] for x in m]
        d = dict(amplitudes=a, efic=ef, a50=cruce(a, ef, 0.5), a99=cruce(a, ef, 0.99))
        walk = {}
        for A, x in zip(a, m):
            r = ref.get(A)
            if (x['efic_disparo'] >= 0.99 and x.get('t_subida') and r
                    and r.get('t_subida')):
                walk[A] = x['t_subida']['media'] - r['t_subida']['media']
        d['walk'] = walk
        d['walk_rango'] = float(np.ptp(list(walk.values()))) if walk else None
        sel = [(A, x['trapecio']) for A, x in zip(a, m)
               if A >= amin_inl and x['efic_disparo'] >= 0.99 and x.get('trapecio')]
        if len(sel) >= 3:
            xa = np.array([s[0] for s in sel], float)
            y = np.array([s[1] for s in sel], float)
            g, b = np.polyfit(xa, y, 1)
            res = y - (g * xa + b)
            d.update(ganancia=float(g), ordenada=float(b),
                     inl_fs=float(np.max(np.abs(res)) / (g * G.AMP_MAX)),
                     inl=dict(zip([int(v) for v in xa], (res / (g * G.AMP_MAX)).tolist())))
        out[fuente] = d
    return out


def analizar_forma(filas):
    """Por tasa: T = FWHM/ε² contra la ocupación ρ = n·L/f_s de cada forma, y el
    mínimo. `rho_opt` interpola una parábola en (ln ρ, ln T) por el mínimo y sus
    vecinos; parametros_de_merito.md §8 predice 1/4 con ruido blanco (FWHM ∝ L^(−1/2),
    ε = e^(−ρ))."""
    por = {}
    for f in filas:
        if f['eps'] > 0 and f['fwhm_rel']:
            por.setdefault(f['tasa'], []).append(f)
    out = {}
    for tasa, fs in sorted(por.items()):
        fs = sorted(fs, key=lambda f: f['rho'])
        rho = np.array([f['rho'] for f in fs])
        T = np.array([f['T'] for f in fs])
        i = int(np.argmin(T))
        d = dict(ks=[f['k'] for f in fs], rho=rho.tolist(), T=T.tolist(),
                 eps=[f['eps'] for f in fs], limpios=[f['limpios'] for f in fs],
                 fwhm_rel=[f['fwhm_rel'] for f in fs], k_opt=fs[i]['k'],
                 rho_min=float(rho[i]), n_in_hz=float(np.mean([f['n_in_hz'] for f in fs])))
        if 0 < i < len(fs) - 1:
            x, y = np.log(rho[i - 1:i + 2]), np.log(T[i - 1:i + 2])
            a2, a1, _ = np.polyfit(x, y, 2)
            if a2 > 0:
                d['rho_opt'] = float(math.exp(-a1 / (2 * a2)))
        out[str(tasa)] = d
    return out


def meritos_apilamiento(hist, n, lineas, cnt):
    """Lo que deja pasar un corte, con N pulsos generados: los que caen en las líneas
    (±TOL_BUENO), los marcados (canal 0) y el resto, que es el continuo de apilamiento.
    `eps` = en las líneas / N; `fondo` = continuo / (líneas + continuo), la fracción del
    espectro que no es línea; `arriba` = cuentas sobre la línea alta / en las líneas."""
    h = np.asarray(hist, np.int64)
    picos = sum(contar_linea(h, q, TOL_BUENO) for q in lineas)
    marc = int(h[0])
    acc = int(h.sum())
    cont = acc - picos - marc
    alto = int(math.ceil(lineas[-1] * (1 + TOL_BUENO)))
    return dict(eps=picos / n, picos=picos, continuo=cont, marcados=marc, aceptados=acc,
                fondo=cont / max(picos + cont, 1), arriba=int(h[alto + 1:].sum()) / max(picos, 1),
                apilados=cnt['pileup'] / max(cnt['total'], 1),
                rej_discr=cnt.get('rej_discr'))


def analizar_dnl(hist, margen=0.04, grado=3, periodos=10):
    """La DNL de un espectro de entrada uniforme: h/ĥ − 1, con ĥ un polinomio de grado
    `grado` ajustado sobre la meseta (sin el `margen` de cada borde, donde el dither la
    redondea). Contra la estadística: el rms que daría Poisson, √⟨1/ĥ⟩, y χ²/canal. Para
    ver estructura de códigos (los pesos de los bits de un ADC), la DNL plegada con
    período 2^p: el rms de las medias por resto, contra el que daría el ruido."""
    h = np.asarray(hist, float).copy()
    h[0] = h[-1] = 0
    if h.max() <= 0:
        return None
    alto = h > 0.2 * h.max()
    nivel = float(np.median(h[alto]))
    sobre = np.flatnonzero(h >= 0.5 * nivel)
    c_lo, c_hi = int(sobre[0]), int(sobre[-1])
    m = int(round(margen * (c_hi - c_lo)))
    c = np.arange(c_lo + m, c_hi - m + 1)
    if c.size < 50:
        return None
    y = h[c]
    x = (c - c.mean()) / max(np.ptp(c), 1)
    ajuste = np.polyval(np.polyfit(x, y, int(grado)), x)
    dnl = y / ajuste - 1.0
    esperado = float(math.sqrt(np.mean(1.0 / ajuste)))
    out = dict(canales=[int(c[0]), int(c[-1])], n_canales=int(c.size),
               cuentas_por_canal=float(ajuste.mean()), rms=float(dnl.std()),
               esperado=esperado, chi2=float(np.mean((y - ajuste) ** 2 / ajuste)),
               max_abs=float(np.max(np.abs(dnl))), plegado={})
    for p in range(1, int(periodos) + 1):
        P = 1 << p
        if c.size < 8 * P:
            break
        r = c % P
        med = np.bincount(r, dnl, minlength=P) / np.bincount(r, minlength=P)
        out['plegado'][str(P)] = dict(rms=float(med.std()),
                                      esperado=esperado / math.sqrt(c.size / P))
    return out


def analizar_psd(filas):
    """La FOM de separación de formas, Δcentroide / (FWHM₁ + FWHM₂), por amplitud, entre
    las dos caídas (las dos primeras de `taus`)."""
    por = {}
    for f in filas:
        if f['medida']:
            por.setdefault(f['amplitud'], {})[f['tau']] = f['medida']
    out = {}
    for A, d in sorted(por.items()):
        if len(d) < 2:
            continue
        (t1, m1), (t2, m2) = sorted(d.items())[:2]
        f1 = m1['fwhm'] or m1['fwhm_gauss']
        f2 = m2['fwhm'] or m2['fwhm_gauss']
        out[str(A)] = dict(taus=[t1, t2], centroides=[m1['centroide'], m2['centroide']],
                           fwhm=[f1, f2], fom=abs(m2['centroide'] - m1['centroide']) / (f1 + f2))
    return out


def analizar_polo_cero(filas):
    """Por Δt: el error del segundo pulso (sobre la cola del primero) contra ΔM, la
    pendiente y el ΔM donde se anula. Es el M que cancela la cola que llega al MCA: en
    el lazo, el del generador; en el analógico, el del canal. La curva no es recta (con
    ±10 % el error de ΔM < 0 es mayor que el de ΔM > 0), así que el cero sale de
    interpolar entre los dos puntos que lo encierran y la pendiente, de los puntos con
    |ΔM| ≤ 2 %; una recta por todos corre el cero ~0.3 %."""
    por = {}
    for f in filas:
        if f.get('err_a2') is not None:
            por.setdefault(f['dt'], []).append(f)
    out = {}
    for dt, fs in sorted(por.items()):
        fs = sorted(fs, key=lambda f: f['dm'])
        dm = np.array([f['dm'] for f in fs])
        e2 = np.array([f['err_a2'] for f in fs])
        d = dict(dm=dm.tolist(), err_a2=e2.tolist(),
                 err_a1=[f.get('err_a1') for f in fs])
        if len(fs) >= 2 and np.ptp(dm) > 0:
            cerca = np.abs(dm) <= 0.02
            if cerca.sum() < 2 or np.ptp(dm[cerca]) == 0:
                cerca = np.ones(dm.size, bool)
            m, b = np.polyfit(dm[cerca], e2[cerca], 1)
            cero = float(-b / m) if m else None
            # el cambio de signo más cerca de ΔM = 0, interpolado
            cambios = [i for i in range(dm.size - 1) if e2[i] == 0 or e2[i] * e2[i + 1] < 0]
            if cambios:
                i = min(cambios, key=lambda j: abs(dm[j] + dm[j + 1]))
                cero = (float(dm[i]) if e2[i] == 0 else
                        float(dm[i] - e2[i] * (dm[i + 1] - dm[i]) / (e2[i + 1] - e2[i])))
            d.update(pendiente=float(m), dm_cero=cero)
        out[str(dt)] = d
    return out


def meritos_ciega(hist, n_pares, lineas, cnt):
    """Por par, lo que deja un corte: los eventos en cada línea (A1 la alta), los
    aceptados fuera de las dos (el apilado que el disparo no separó y el corte no vio),
    los marcados y los que rechazó el discriminador."""
    h = np.asarray(hist, np.int64)
    bajo, alto = (contar_linea(h, q, TOL_BUENO) for q in sorted(lineas))
    marc = int(h[0])
    acc = int(h.sum())
    return dict(disparos_par=cnt['cross'] / n_pares, eventos_par=acc / n_pares,
                a1=alto / n_pares, a2=bajo / n_pares, marcados=marc / n_pares,
                apilado_aceptado=(acc - alto - bajo - marc) / n_pares,
                rechazados=(cnt.get('rej_discr') or 0) / n_pares)


def analizar_ciega(filas, pasa=0.5, limpio=0.01):
    """Por (subida, fuente, corte): desde qué Δt el disparo separa los dos pulsos (2
    disparos por par); la ventana ciega, el mayor Δt con un solo disparo por par donde
    el apilado pasa el corte en más de `pasa` de los pares (con dos disparos lo que cae
    fuera de las líneas ya no es apilamiento no detectado, es el error de las formas
    cortas); desde qué Δt queda menos de `limpio` por par; y `conserva`, la fracción de
    los dos pulsos que el corte deja en su línea en el Δt más largo."""
    por = {}
    for f in filas:
        por.setdefault((f['subida'], f['fuente'], f['corte'], f['umbral']), []).append(f)
    out = {}
    for (sub, fu, corte, q), fs in sorted(por.items(), key=lambda kv: str(kv[0])):
        fs = sorted(fs, key=lambda f: f['dt'])
        dts = [f['dt'] for f in fs]
        me = [f['meritos'] for f in fs]
        ap = [m['apilado_aceptado'] for m in me]
        ciega = [dt for dt, v, m in zip(dts, ap, me) if v > pasa and m['disparos_par'] < 1.5]
        out[f'{sub}/{fu}/{corte}/{q}'] = dict(
            subida=sub, fuente=fu, corte=corte, umbral=q, dts=dts, apilado_aceptado=ap,
            disparos_par=[m['disparos_par'] for m in me],
            separa_desde=umbral_desde(dts, [m['disparos_par'] for m in me], lambda y: y >= 1.99),
            ciega_hasta=max(ciega) if ciega else None,
            limpio_desde=umbral_desde(dts, ap, lambda y: y <= limpio),
            conserva=(me[-1]['a1'] + me[-1]['a2']) / 2.0)
    return out


def analizar_deriva(filas):
    """La deriva de las dos líneas con el tiempo, en cuentas del generador (con la
    ganancia del primer punto): la de cada línea, la del offset y la de la ganancia
    (en ppm). Por serie, la pendiente (por hora), el recorrido y el desvío; con la
    temperatura, si cambió, el coeficiente por °C y la correlación."""
    fs = [f for f in filas if f.get('lineas') and len(f['lineas']) == 2]
    if len(fs) < 2:
        return dict(puntos=len(fs))
    t = np.array([f['t_s'] for f in fs]) / 3600.0
    v1 = np.array([f['lineas'][0]['valor'] for f in fs])
    v2 = np.array([f['lineas'][1]['valor'] for f in fs])
    a1, a2 = fs[0]['amplitudes']
    g = (v2 - v1) / (a2 - a1)
    o = v1 - g * a1
    g0 = g[0]
    series = dict(linea1=(v1 - v1[0]) / g0, linea2=(v2 - v2[0]) / g0,
                  offset=(o - o[0]) / g0, ganancia_ppm=1e6 * (g / g0 - 1.0))
    T = np.array([np.nan if f.get('temp') is None else f['temp'] for f in fs], float)
    out = dict(puntos=len(fs), horas=float(t[-1] - t[0]), amplitudes=[a1, a2],
               temp=None if not np.isfinite(T).any() else
               dict(min=float(np.nanmin(T)), max=float(np.nanmax(T))))
    for k, y in series.items():
        d = dict(rango=float(np.ptp(y)), desvio=float(y.std()), serie=y.tolist())
        if np.ptp(t) > 0:
            d['por_hora'] = float(np.polyfit(t, y, 1)[0])
        ok = np.isfinite(T)
        if ok.sum() >= 3 and np.ptp(T[ok]) > 0.2 and np.ptp(y[ok]) > 0:
            d['por_grado'] = float(np.polyfit(T[ok], y[ok], 1)[0])
            d['corr_temp'] = float(np.corrcoef(T[ok], y[ok])[0, 1])
        out[k] = d
    out['t_h'] = t.tolist()
    out['temp_serie'] = [None if not np.isfinite(x) else float(x) for x in T]
    return out


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


def comprobar(res, n, determinista=True):
    """Las identidades de cada corrida. Devuelve la lista de lo que no cierra. Con
    `determinista` (el lazo digital), además, los contadores de las corridas de un
    punto tienen que ser iguales; con el ruido del ADC, no.

    Una corrida que lee el histograma en vuelo (la base dinámica: `base_dinamica`)
    pierde los eventos que coinciden con una lectura del bus, que gana el puerto
    (mca_hist.sv): van a cnt_dropped sin pasar por cnt_cross ni por el espectro. Ahí
    la diferencia `perd − cross` es esa pérdida (`perd_lectura`), y tiene que ser la
    misma que le falta al espectro."""
    mal = []
    g = res['gen']
    if g['gen_cnt'] != n or not g['terminado'] or g['desborde']:
        mal.append(f'generador: {g} con N = {n}')
    base = None
    for i, r in enumerate(res['corridas']):
        c = r['cnt']
        perd = c['open'] + c['lost_active'] + c['dropped'] + c['lost_veto']
        lect = perd - c['cross'] if 'base_dinamica' in r and perd >= c['cross'] else 0
        if lect:
            c['perd_lectura'] = lect
        if c['cross'] + lect != perd:
            mal.append(f'corrida {i}: cross {c["cross"]} != open + lost_active + dropped '
                       f'+ lost_veto = {perd}')
        if c['total'] != c['open']:
            mal.append(f'corrida {i}: total {c["total"]} != open {c["open"]}')
        if c['t_rearm'] is not None:
            suma = c['vetotime'] + c['t_win'] + c['t_div'] + c['t_rearm'] + c['livetime']
            if suma != c['realtime']:
                mal.append(f'corrida {i}: el teselado da {suma}, realtime {c["realtime"]}')
        suma_h = int(np.asarray(r['hist']).sum())
        # cnt_accepted cuenta antes del discriminador: al espectro llegan accepted − rej_discr.
        al_espectro = c['accepted'] - (c.get('rej_discr') or 0) - lect
        if c['rej_amp'] == c['rej_psd'] == 0 and suma_h != al_espectro:
            mal.append(f'corrida {i}: el espectro suma {suma_h}, aceptados {c["accepted"]} '
                       f'menos {c.get("rej_discr") or 0} del discriminador'
                       + (f' y {lect} de las lecturas en vuelo' if lect else ''))
        cuenta = {k: c[k] for k in CLAVES_CNT}
        if base is None:
            base = cuenta
        elif determinista and cuenta != base:
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
        self.modo = getattr(placa, 'modo', 'digital')
        self.canal = getattr(placa, 'canal', None)
        self.meta = dict(fecha=datetime.now().isoformat(timespec='seconds'),
                         placa=placa.nombre, host=platform.node(), h_aw=placa.h_aw,
                         n_acc_max=placa.n_acc_max, modo=self.modo, canal=self.canal,
                         args={k: v for k, v in vars(a).items() if k != 'comparar'},
                         pre_dly=PRE_DLY, tol_bueno=TOL_BUENO)
        if self.modo == 'analogico' and self.placa.nombre == 'simulada':
            self.meta['canal_simulado'] = placa.canal_sim.describir()
        self.referencias, self.filas, self.anomalias = {}, [], []

    def mca(self, fuente, decae, n_acc, **kw):
        return mca_de(fuente, decae, n_acc, self.canal, **kw)

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

    def _correr(self, tag, gen, tabla, mca, disparo, espectros, base=False, dinamica=None):
        kw = {} if dinamica is None else {'dinamica': dinamica}
        res = self.placa.correr(gen, tabla, mca, disparo, espectros, base=base, **kw)
        mal = comprobar(res, int(gen['n']), determinista=self.modo == 'digital')
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
        res = self._correr(f'ref tasa {fuente}', gen, tabla,
                           self.mca(fuente, decae, 1, seguidor=self.seguidor_tasa()),
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

    def seguidor_tasa(self):
        """La base del MCA de la etapa tasa: None (fija) o (bl_k, bl_holdoff)."""
        a = self.a
        return (a.bl_k, a.bl_holdoff) if a.base_tasa == 'seguidor' else None

    def calibracion_dinamica(self):
        """La caída del canal y κ para `--base-tasa dinamica`: los del `.json` de la
        pestaña «Calibration» (`--calibracion`, la medición lenta, bien determinada), o
        la caída de la medición rápida de esta corrida, que sale poco determinada."""
        a = self.a
        cal = {}
        if a.calibracion:
            with open(a.calibracion) as f:
                cal = json.load(f)
        caida = a.caida if a.caida is not None else cal.get('caida')
        if caida is None:
            caida = (self.canal or {}).get('caida_lenta')
            print('[tasa] base dinámica sin --calibracion: la caída es la de la medición '
                  f'rápida de esta corrida ({100 * (caida or 0):+.2f} %)', flush=True)
        if caida is None:
            raise RuntimeError('--base-tasa dinamica: no hay caída del canal (¿modo '
                               'analógico?)')
        kappa = a.kappa if a.kappa is not None else float(cal.get('kappa', 1.0))
        origen = ('--caida' if a.caida is not None else a.calibracion
                  or 'medición rápida de esta corrida')
        return dict(caida=float(caida), kappa=kappa, origen=origen)

    def dinamica_de(self, ref, gen, tabla, cal):
        """Lo que `PlacaReal.correr` necesita para la base dinámica en un punto: G_F por
        espectro (la ganancia de la referencia, feature por ADU del generador, sobre la
        del canal: feature por ADU de IN1) y el cebado (la tasa pedida y la amplitud
        media de la tabla en IN1)."""
        g_canal = float((self.canal or {}).get('ganancia', 1.0))
        gf = {}
        for nombre, r in ref.items():
            gan = r.get('ganancia')
            gf[nombre] = float(np.mean(gan)) / g_canal if gan else 1.0
        a0 = float(np.mean(np.asarray(tabla, float))) * g_canal
        return dict(cal, ganancia_mca=gf, lam0=float(G.tasa(**disparos_cfg(gen))), a0=a0)

    def etapa_tasa(self):
        a = self.a
        if self.placa.nombre == 'simulada' and a.base_tasa in ('seguidor', 'dinamica'):
            print(f'\n[tasa] con la base {a.base_tasa}: no se simula (la réplica no la '
                  'tiene)')
            return
        cal = self.calibracion_dinamica() if a.base_tasa == 'dinamica' else None
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
            ap = apilamiento(gen['n'] * FS_HZ / (int(t_k[-1]) + 1), a.tau, a.lineas, a.pesos,
                             self.canal)
            print(f'\n[tasa] {tasa:g}/s pedidos: {gen["n"]} pulsos; apilamiento '
                  f'{ap["nivel_medio"]:.0f} ± {ap["nivel_sigma"]:.0f} cuentas'
                  + (' (SATURA)' if ap['satura'] else ''), flush=True)
            for fuente in a.fuentes:
                ref = refs[fuente]
                for n_acc in a.n_acc or range(1, self.placa.n_acc_max + 1):
                    tag = f'tasa {fuente} n_acc={n_acc} {tasa:g}/s'
                    t0 = time.time()
                    din = None if cal is None else self.dinamica_de(ref, gen, tabla, cal)
                    res = self._correr(tag, gen, tabla,
                                       self.mca(fuente, gen['decae'], n_acc,
                                                seguidor=self.seguidor_tasa()),
                                       disparo_de(fuente, gen['decae'], a.subida),
                                       _esp(a.espectros_tasa), dinamica=din)
                    fila = dict(etapa='tasa', clave=['tasa', fuente, n_acc, tasa],
                                fuente=fuente, n_acc=n_acc, tasa=tasa,
                                base_mca=a.base_tasa,
                                tasa_cfg_hz=G.tasa(**disparos_cfg(gen)), gen=gen,
                                gen_estado=res['gen'], t_gen=res['t_gen'],
                                perdidos_rearme_asg=rearme, apilamiento=ap, corridas=[])
                    if din is not None:
                        fila['dinamica'] = {k: din[k] for k in ('caida', 'kappa', 'origen',
                                                                'ganancia_mca', 'lam0', 'a0')}
                    for (nombre, z), r in zip(_esp(a.espectros_tasa), res['corridas']):
                        m = meritos_tasa({**res, 'corridas': [r]}, gen['n'],
                                         ref[nombre]['lineas'])
                        if nombre == 't_subida':
                            m['t_subida'] = momentos(r['hist'])
                        c = dict(espectro=nombre, zoom=z, cnt=r['cnt'],
                                 hist=_sparse(r['hist']), meritos=m)
                        if 'base_dinamica' in r:
                            c['base_dinamica'] = r['base_dinamica']
                        fila['corridas'].append(c)
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
        res = self._correr(f'ref par {fuente}', gen, tabla, self.mca(fuente, decae, 1),
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
                    res = self._correr(tag, gen, tabla, self.mca(fuente, gen['decae'], n_acc),
                                       disparo_de(fuente, gen['decae'], a.subida),
                                       _esp(a.espectros_par))
                    fila = dict(etapa='par', clave=['par', fuente, n_acc, dt],
                                fuente=fuente, n_acc=n_acc, dt=dt, k=k,
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

    # -- histéresis --

    def etapa_histeresis(self):
        """La campaña de deriva del Rigol (§19.2-19.4) con el pulser digital: tren
        periódico, las 16 tasas de ida y de vuelta, la base leída en vuelo. Si con el
        generador de la FPGA no aparece la histéresis de 10.9 canales, era del DG4162;
        si aparece, es del MCA. El modo 'fija' (sin seguidor) dice qué aporta el
        seguidor de base."""
        a = self.a
        gb = gen_base(a) | {'tau': a.tau_hist, 'base': int(a.base_hist)}
        g0 = G.config(**gb)
        decae, tau = g0['decae'], G.tau_de(g0['decae'])
        disparo = disparo_de(a.fuente_hist, decae, a.subida)
        tabla = np.array([a.a_hist], np.int16)
        self.meta['histeresis'] = {}
        for modo in a.modos_hist:
            mca = mca_campana(a.fuente_hist, modo, a.base_hist, self.canal)
            if self.placa.nombre == 'simulada' and mca.get('bl_auto'):
                print(f'\n[histéresis] {modo}: no se simula (la réplica no tiene el '
                      'seguidor de base)')
                continue
            print(f'\n[histéresis] {modo}: {a.fuente_hist}, A = {a.a_hist}, '
                  f'τ = {tau:.0f} muestras, '
                  f'{len(a.tasas_hist)} tasas de ida y de vuelta, {a.seg_hist:g} s cada una')
            t0 = time.time()
            filas = []
            orden = [('ida', r) for r in a.tasas_hist] + [('vuelta', r)
                                                         for r in a.tasas_hist[::-1]]
            for pasada, tasa in orden:
                periodo = max(2, int(round(FS_HZ / tasa)))
                n = int(max(a.n_min_hist, round(a.seg_hist * FS_HZ / periodo)))
                gen = G.config(periodo=periodo, n=n, amp_n=1, semilla=a.semilla, **gb)
                gen['n'] = self.placa.recortar(gen)
                ti = time.time() - t0
                res = self._correr(f'histéresis {modo} {pasada} {tasa:g}/s', gen, tabla,
                                   mca, disparo, _esp(['pico']), base=True)
                r = res['corridas'][0]
                c, T = r['cnt'], res['t_gen']
                rearm = c['t_rearm'] or 0
                med = dict(linea=linea_principal(r['hist']),
                           t_s=ti + 0.5 * (time.time() - t0 - ti),
                           muerto=(c['t_win'] + c['t_div'] + rearm) / T,
                           aceptados_hz=c['accepted'] * FS_HZ / T,
                           efic=c['accepted'] / gen['n'],
                           satura=satura_adc(pico_periodico(a.a_hist, periodo, tau,
                                                            a.base_hist), self.canal),
                           **r.get('base', {}))
                fila = dict(etapa='histeresis', clave=['histeresis', modo, pasada, tasa],
                            modo=modo, pasada=pasada, tasa=FS_HZ / periodo,
                            tasa_pedida=tasa, fuente=a.fuente_hist, gen=gen,
                            gen_estado=res['gen'], t_gen=T, medida=med,
                            corridas=[dict(espectro='pico', zoom=0, cnt=c,
                                           hist=_sparse(r['hist']))])
                filas.append(fila)
                self.filas.append(fila)
                self.guardar()
                ln = med['linea']
                print(f'    {pasada:6s} {FS_HZ / periodo:9.0f} Hz: '
                      + (f'centroide {ln["centroide"]:8.2f} ± {ln["error"]:.2f}, '
                         if ln else 'sin línea, ')
                      + f'base {med.get("base_evento", 0):+5d}, muerto '
                      f'{100 * med["muerto"]:5.1f} %' + (' (SATURA)' if med['satura'] else ''),
                      flush=True)
            an = analizar_histeresis(filas)
            self.meta['histeresis'][modo] = an
            print(f'  [{modo}] {an.get("veredicto")}: |h| máx {an.get("h_max", 0):.2f} '
                  f'canales ({an.get("h_sig_max", 0):.1f} σ), efecto de la tasa '
                  f'{an.get("efecto_tasa", 0):.2f} canales '
                  f'({100 * an.get("corrimiento", 0):+.2f} %)', flush=True)

    # -- walk --

    def etapa_walk(self):
        """La amplitud contra el disparo: por amplitud, pulsos aislados (periódicos a
        `PERIODO_REF`) y tres espectros. t_subida (del disparo al pico) da el walk; el
        trapecio y el pico, la linealidad; los disparos sobre los pulsos, la curva S
        del umbral. El ASG es la referencia: dispara sin mirar la señal."""
        a = self.a
        for amp in a.amps_walk:
            gen = G.config(periodo=PERIODO_REF, n=a.n_walk, amp_n=1, semilla=a.semilla,
                           **gen_base(a))
            tabla = np.array([amp], np.int16)
            print(f'\n[walk] A = {amp}', flush=True)
            for fuente in a.fuentes:
                res = self._correr(f'walk {fuente} A={amp}', gen, tabla,
                                   self.mca(fuente, gen['decae'], 1),
                                   disparo_de(fuente, gen['decae'], a.subida),
                                   _esp(['t_subida', 'trapecio', 'pico']))
                c = res['corridas'][0]['cnt']
                med = dict(efic_disparo=min(c['cross'], a.n_walk) / a.n_walk,
                           extra_disparos=max(0, c['cross'] - a.n_walk),
                           t_subida=momentos(res['corridas'][0]['hist']))
                for k, nombre in ((1, 'trapecio'), (2, 'pico')):
                    ln = linea_principal(res['corridas'][k]['hist'])
                    med[nombre] = (None if ln is None else
                                   float(valor_de_canal(ln['centroide'], self.placa.h_aw)))
                    med[f'{nombre}_sigma'] = None if ln is None else ln['sigma']
                fila = dict(etapa='walk', clave=['walk', fuente, amp], fuente=fuente,
                            amplitud=amp, amplitud_adc=(amp * self.canal['ganancia']
                                                        if self.canal else amp),
                            gen=gen, gen_estado=res['gen'],
                            t_gen=res['t_gen'], medida=med,
                            corridas=[dict(espectro=e, zoom=z, cnt=r['cnt'],
                                           hist=_sparse(r['hist']))
                                      for (e, z), r in zip(_esp(['t_subida', 'trapecio',
                                                                 'pico']),
                                                           res['corridas'])])
                self.filas.append(fila)
                self.guardar()
                ts = med['t_subida']
                print(f'    {fuente:9s} disparo {100 * med["efic_disparo"]:5.1f} %'
                      + (f', t_subida {ts["media"]:6.2f} ± {ts["sigma"]:.2f} ciclos' if ts
                         else '')
                      + (f', trapecio {med["trapecio"] / amp:.4f}/cuenta'
                         if med['trapecio'] else ''), flush=True)
        self.meta['walk'] = analizar_walk([f for f in self.filas if f['etapa'] == 'walk'])

    # -- ruido --

    def etapa_ruido(self):
        """La resolución contra el ruido inyectado. Por punto de ruido y por forma del
        banco (sola), dos corridas: sin zoom, para encontrar la línea, y con el zoom
        que la abre más (`zoom_para`). El disparo es el del ASG: uno por pulso, sin
        disparos falsos aunque el ruido sea grande."""
        a = self.a
        fuente = a.fuente_ruido
        tabla = np.array([a.a_ruido], np.int16)
        grupos = {}
        for e in a.estimadores:
            f, esp = ESTIMADORES[e]
            grupos.setdefault(f, []).append((e, esp))
        filas = []
        for sh in a.ruidos_sh:
            con = sh >= 0
            gen = G.config(periodo=PERIODO_REF, n=a.n_ruido, amp_n=1, semilla=a.semilla,
                           **(gen_base(a) | dict(ruido=con, ruido_sh=sh if con else 0)))
            gen['n'] = self.placa.recortar(gen)
            s_in = float(G.sigma_ruido(sh)) if con else 0.0
            print(f'\n[ruido] ' + (f'sh {sh}: σ = {s_in:.3f} cuentas' if con else 'sin ruido')
                  + f', A = {a.a_ruido}, {gen["n"]} pulsos', flush=True)
            disparo = disparo_de(fuente, gen['decae'], a.subida)
            for forma, ests in sorted(grupos.items()):
                mca = self.mca(fuente, gen['decae'], 1, formas=(BANCO_PZ[forma],))
                tag = f'ruido sh={sh} forma{forma}'
                grueso = self._correr(tag + ' sin zoom', gen, tabla, mca, disparo,
                                      [(esp, (0, 0)) for _, esp in ests])
                zooms = []
                for r in grueso['corridas']:
                    st = estadistica_linea(r['hist'], self.placa.h_aw)
                    zooms.append(zoom_para(st, self.placa.h_aw) if st else (0, 0))
                fino = grueso
                if any(z != (0, 0) for z in zooms):
                    fino = self._correr(tag + ' con zoom', gen, tabla, mca, disparo,
                                        [(esp, z) for (_, esp), z in zip(ests, zooms)])
                for i, ((e, esp), z) in enumerate(zip(ests, zooms)):
                    rg, rf = grueso['corridas'][i], fino['corridas'][i]
                    med = estadistica_linea(rf['hist'], self.placa.h_aw, *z)
                    if med:
                        med.update(zoom=list(z), efic=rf['cnt']['accepted'] / gen['n'])
                    fila = dict(etapa='ruido', clave=['ruido', e, sh], estimador=e,
                                espectro=esp, forma=forma, ruido_sh=sh, sigma_in=s_in,
                                amplitud=a.a_ruido, fuente=fuente, gen=gen,
                                gen_estado=fino['gen'], t_gen=fino['t_gen'], medida=med,
                                corridas=[dict(espectro=esp, zoom=[0, 0], cnt=rg['cnt'],
                                               hist=_sparse(rg['hist'])),
                                          dict(espectro=esp, zoom=list(z), cnt=rf['cnt'],
                                               hist=_sparse(rf['hist']))])
                    filas.append(fila)
                    self.filas.append(fila)
                    print(f'    {e:7s} ' + (
                        f'σ {med["sigma"]:8.2f} (feature), centroide {med["centroide"]:9.1f}, '
                        f'zoom {z}, {med["fuera"]} fuera de la ventana' if med else
                        'sin línea'), flush=True)
                self.guardar()
        self.meta['ruido'] = analizar_ruido(filas)

    def _linea(self, tag, gen, tabla, mca, disparo, esp='trapecio', zoom=None):
        """Una línea sola, con el zoom que la abre: sin `zoom`, una corrida antes sin
        zoom para encontrarla. Devuelve (estadística, zoom, resultado de la corrida)."""
        h_aw = self.placa.h_aw
        if zoom is None:
            grueso = self._correr(tag + ' sin zoom', gen, tabla, mca, disparo, [(esp, (0, 0))])
            st = estadistica_linea(grueso['corridas'][0]['hist'], h_aw)
            zoom = zoom_para(st, h_aw) if st else (0, 0)
            if zoom == (0, 0):
                return st, (0, 0), grueso
        fino = self._correr(tag, gen, tabla, mca, disparo, [(esp, tuple(zoom))])
        return (estadistica_linea(fino['corridas'][0]['hist'], h_aw, *zoom), tuple(zoom),
                fino)

    # -- forma --

    def etapa_forma(self):
        """El largo del trapecio contra la tasa: parametros_de_merito.md §8 dice que el
        tiempo hasta una precisión dada va como T ∝ FWHM/ε² y que el mínimo cae en la
        ocupación ρ = n·L/f_s = 1/4. Una forma sola del banco de subida k (8 a 512),
        ruido blanco del generador que manda en la resolución y una línea con arribos de
        Poisson. L = antes + despues es lo que la forma necesita limpio alrededor de
        cada pulso, así que con Poisson ε ≈ e^(−ρ) (`limpios` es la fracción exacta,
        de los instantes del generador). La FWHM se mide con el zoom de los aislados de
        esa forma, y ε son los eventos dentro de esa ventana sobre los pulsos generados."""
        a = self.a
        fuente = a.fuente_forma
        gb = gen_base(a) | dict(ruido=True, ruido_sh=int(a.ruido_forma))
        tabla = np.array([a.a_forma], np.int16)
        n_acc = self.placa.n_acc_max
        g0 = G.config(**gb)
        disparo = disparo_de(fuente, g0['decae'], a.subida)
        print(f'\n[forma] una forma sola, k {list(a.ks_forma)}; línea {a.a_forma}, ruido σ '
              f'{G.sigma_ruido(a.ruido_forma):.2f} cuentas, disparo {fuente}', flush=True)
        filas = []
        for k in a.ks_forma:
            f = forma_k(k)
            L = f[4] + f[5]
            mca = self.mca(fuente, g0['decae'], n_acc, formas=(f,))
            per = max(PERIODO_REF, 2 * (L + int(mca['gate_long'])))
            gen = G.config(periodo=per, n=a.n_ref, amp_n=1, semilla=a.semilla, **gb)
            gen['n'] = self.placa.recortar(gen)
            ref, z, _ = self._linea(f'forma k={k} aislados', gen, tabla, mca, disparo)
            if not ref:
                self.anomalias.append(f'forma k={k}: sin línea en los aislados')
                continue
            fw = ref['fwhm'] or ref['fwhm_gauss']
            self.referencias[f'forma/{k}'] = dict(medida=ref, zoom=list(z), forma=list(f),
                                                  fwhm_rel=fw / ref['centroide'])
            print(f'  k {k:3d}, m {f[1]:3d}, L {L:4d}: aislados FWHM '
                  f'{100 * fw / ref["centroide"]:.3f} %, zoom {z}', flush=True)
            for tasa in a.tasas_forma:
                if tasa * L / FS_HZ > a.rho_max_forma:
                    continue
                n = int(max(a.n_min_forma, tasa * a.seg_forma))
                gen = G.config(aleatorio=True, tasa=tasa, dt_min=a.dt_min, n=n, amp_n=1,
                               semilla=a.semilla, **gb)
                gen['n'] = self.placa.recortar(gen)
                t_k = instantes(gen)
                n_in = gen['n'] * FS_HZ / (int(t_k[-1]) + 1)
                d = np.diff(t_k)
                antes = np.concatenate(([1 << 30], d))
                despues = np.concatenate((d, [1 << 30]))
                limpios = float(((antes >= f[4]) & (despues >= f[5])).mean())
                st, _, res = self._linea(f'forma k={k} {tasa:g}/s', gen, tabla, mca, disparo,
                                         zoom=z)
                r = res['corridas'][0]
                eps = st['n'] / gen['n'] if st else 0.0
                fwr = ((st['fwhm'] or st['fwhm_gauss']) / st['centroide']) if st else None
                fila = dict(etapa='forma', clave=['forma', k, tasa], fuente=fuente, k=k,
                            forma=list(f), L=L, tasa=tasa, n_in_hz=n_in,
                            rho=n_in * L / FS_HZ, limpios=limpios, eps=eps, fwhm_rel=fwr,
                            T=(fwr / eps ** 2) if (fwr and eps > 0) else None,
                            medida=st, gen=gen, gen_estado=res['gen'], t_gen=res['t_gen'],
                            corridas=[dict(espectro='trapecio', zoom=list(z), cnt=r['cnt'],
                                           hist=_sparse(r['hist']))])
                filas.append(fila)
                self.filas.append(fila)
                self.guardar()
                print(f'    {tasa:9g}/s: ρ {fila["rho"]:6.3f}, ε {100 * eps:5.1f} % (limpios '
                      f'{100 * limpios:5.1f} %)' + (f', FWHM {100 * fwr:.3f} %, '
                                                    f'FWHM/ε² {fila["T"]:.4f}' if fila['T']
                                                    else ''), flush=True)
        self.meta['forma'] = analizar_forma(filas)

    # -- apilamiento --

    def etapa_apilamiento(self):
        """El continuo de apilamiento y el par (eficiencia, rechazo) de cada corte: Poisson
        con las dos líneas de la etapa tasa, el banco con todas las ranuras, y el
        discriminador sobre una feature por corrida. Con el mismo estímulo en todas
        (el generador es determinista), cada corte es un punto de la curva:
          dt_anterior ≥ c   el disparo anterior lejos (c en muestras);
          t_subida          del disparo al pico como en los aislados;
          ancho_inv         pico/Q como en los aislados (un pulso montado lo corre);
          solape = 0        sin otra ranura abierta ni otro disparo en la ventana.
        Los cortes de t_subida y ancho_inv son el intervalo central que deja pasar la
        fracción q de los aislados. Lo ideal para dt_anterior sale de los instantes."""
        a = self.a
        n_acc = self.placa.n_acc_max
        h_aw = self.placa.h_aw
        tabla = tabla_lineas(a.lineas, a.pesos)
        esp_ref = [('trapecio', 0), ('t_subida', 3), ('ancho_inv', 3)]
        for fuente in a.fuentes_apil:
            gen = G.config(periodo=PERIODO_REF, n=a.n_ref, amp_aleat=True, semilla=a.semilla,
                           **gen_base(a))
            decae = gen['decae']
            mca = self.mca(fuente, decae, n_acc)
            disparo = disparo_de(fuente, decae, a.subida)
            res = self._correr(f'apilamiento {fuente} aislados', gen, tabla, mca, disparo,
                               esp_ref)
            lineas = lineas_ref(res['corridas'][0]['hist'], len(a.lineas))
            cortes = [('sin', None, None), ('solape', 0, ('solape', 0, 0))]
            cortes += [('dt_anterior', int(c), ('dt_anterior', int(c), 0xFFFF))
                       for c in a.cortes_dt]
            ref = dict(lineas=lineas, hist={e: _sparse(r['hist'])
                                            for (e, _), r in zip(esp_ref[1:], res['corridas'][1:])})
            cortes += cortes_forma(res['corridas'][1:], esp_ref[1:], a.cuantiles_apil, h_aw)
            ref['cortes'] = [[n, q, list(d) if d else None] for n, q, d in cortes]
            self.referencias[f'apilamiento/{fuente}'] = ref
            print(f'\n[apilamiento] {fuente}: líneas {", ".join(f"{q:.1f}" for q in lineas)}; '
                  + '; '.join(f'{n} {q}: {list(d[1:])}' for n, q, d in cortes[2 + len(a.cortes_dt):]),
                  flush=True)
            for tasa in a.tasas_apil:
                n = int(max(a.n_min, tasa * a.seg_apil))
                gen = G.config(aleatorio=True, tasa=tasa, dt_min=a.dt_min, n=n, amp_aleat=True,
                               semilla=a.semilla, **gen_base(a))
                gen['n'] = self.placa.recortar(gen)
                t_k = instantes(gen)
                n_in = gen['n'] * FS_HZ / (int(t_k[-1]) + 1)
                dprev = np.concatenate(([1 << 30], np.diff(t_k)))
                print(f'  {tasa:g}/s ({gen["n"]} pulsos):', flush=True)
                for nombre, q, d in cortes:
                    m_c = dict(mca, discr=d) if d else mca
                    res = self._correr(f'apilamiento {fuente} {tasa:g}/s {nombre} {q}', gen,
                                       tabla, m_c, disparo, [('trapecio', 0)])
                    r = res['corridas'][0]
                    me = meritos_apilamiento(r['hist'], gen['n'], lineas, r['cnt'])
                    if nombre == 'dt_anterior':
                        me['ideal'] = float((dprev >= q).mean())
                    fila = dict(etapa='apilamiento', clave=['apilamiento', fuente, tasa, nombre, q],
                                fuente=fuente, tasa=tasa, n_in_hz=n_in, corte=nombre, umbral=q,
                                discr=list(d) if d else None, meritos=me, gen=gen,
                                gen_estado=res['gen'], t_gen=res['t_gen'],
                                corridas=[dict(espectro='trapecio', zoom=0, cnt=r['cnt'],
                                               hist=_sparse(r['hist']))])
                    self.filas.append(fila)
                    self.guardar()
                    print(f'    {nombre:11s} {str(q):6s}: ε {100 * me["eps"]:5.1f} %, fondo '
                          f'{100 * me["fondo"]:5.2f} %, arriba {100 * me["arriba"]:5.2f} %, '
                          f'marcados {me["marcados"]}', flush=True)

    # -- dnl --

    def etapa_dnl(self):
        """La no linealidad diferencial: amplitudes uniformes (la tabla de 1024 de lo a
        hi, sorteada) con el ruido del generador como dither, un tren periódico sin
        apilamiento (τ corta, cada pulso con su ranura) y dos espectros: el trapecio,
        que promedia muchas muestras, y el pico con zoom 1, un código por canal: en el
        analógico es una prueba de densidad de códigos del ADC. Se corre en tandas de
        semillas distintas (si no, cada tanda repite la misma secuencia) y se suman."""
        a = self.a
        lo, hi = a.rango_dnl
        tabla = tabla_uniforme(lo, hi)
        gb = gen_base(a) | dict(tau=a.tau_dnl, ruido=True, ruido_sh=int(a.ruido_dnl))
        n_acc = self.placa.n_acc_max
        esp = [('trapecio', (0, 0)), ('pico', (1, 0))]
        sumas = [np.zeros(1 << self.placa.h_aw, np.int64) for _ in esp]
        n_tot = 0
        print(f'\n[dnl] amplitudes uniformes de {lo} a {hi}, τ {a.tau_dnl:g}, período '
              f'{a.periodo_dnl}, dither σ {G.sigma_ruido(a.ruido_dnl):.1f} cuentas, '
              f'{a.tandas_dnl} tandas de {a.seg_dnl:g} s', flush=True)
        for i in range(a.tandas_dnl):
            # De a 2: gen_pulsos fuerza a impar las semillas de la amplitud y del ruido
            # ((SEMILLA ^ K) | 1), así que 2k y 2k+1 dan la misma secuencia.
            gen = G.config(periodo=a.periodo_dnl, n=int(a.seg_dnl * FS_HZ / a.periodo_dnl),
                           amp_aleat=True, semilla=a.semilla + 2 * i, **gb)
            gen['n'] = self.placa.recortar(gen)
            mca = self.mca(a.fuente_dnl, gen['decae'], n_acc)
            disparo = disparo_de(a.fuente_dnl, gen['decae'], a.subida)
            res = self._correr(f'dnl tanda {i}', gen, tabla, mca, disparo, esp)
            n_tot += gen['n']
            for s_, r in zip(sumas, res['corridas']):
                s_ += np.asarray(r['hist'], np.int64)
            fila = dict(etapa='dnl', clave=['dnl', i], tanda=i, gen=gen, gen_estado=res['gen'],
                        t_gen=res['t_gen'],
                        corridas=[dict(espectro=e, zoom=list(z), cnt=r['cnt'],
                                       hist=_sparse(r['hist']))
                                  for (e, z), r in zip(esp, res['corridas'])])
            self.filas.append(fila)
            self.guardar()
            print(f'  tanda {i}: {gen["n"]} pulsos, {res["corridas"][0]["cnt"]["accepted"]} '
                  'eventos', flush=True)
        self.meta['dnl'] = {}
        for (e, z), s_ in zip(esp, sumas):
            an = analizar_dnl(s_)
            if an:
                an['zoom'] = list(z)
                an['hist'] = _sparse(s_)
                an['pulsos'] = n_tot
            self.meta['dnl'][e] = an

    # -- psd --

    def etapa_psd(self):
        """La FOM de separación de formas sobre F_PSD = Q_cola/Q_total: pulsos aislados
        de una altura con dos caídas, el MCA de la campaña del Rigol (una ranura, la
        compuerta de 384) con la cola desde `gate_short`, y FOM = Δcentroide / (FWHM₁ +
        FWHM₂) en función de la amplitud. Cada corrida tiene una sola forma: la FOM
        sale de juntar corridas, y vale para tasa baja."""
        a = self.a
        fuente = a.fuente_psd
        filas = []
        print(f'\n[psd] caídas {list(a.taus_psd)}, amplitudes {list(a.amps_psd)}, ruido σ '
              f'{G.sigma_ruido(a.ruido_psd):.2f}, compuerta corta {a.gate_short_psd}',
              flush=True)
        for tau in a.taus_psd:
            gb = gen_base(a) | dict(tau=tau, ruido=True, ruido_sh=int(a.ruido_psd))
            for amp in a.amps_psd:
                gen = G.config(periodo=PERIODO_REF, n=a.n_psd, amp_n=1, semilla=a.semilla, **gb)
                gen['n'] = self.placa.recortar(gen)
                mca = mca_campana(fuente, 'fija', 0, self.canal) | dict(gate_short=a.gate_short_psd)
                disparo = disparo_de(fuente, gen['decae'], a.subida)
                st, z, res = self._linea(f'psd τ={tau:g} A={amp}', gen,
                                         np.array([amp], np.int16), mca, disparo, esp='psd')
                r = res['corridas'][0]
                fila = dict(etapa='psd', clave=['psd', tau, amp], fuente=fuente, tau=tau,
                            amplitud=amp, medida=st, zoom=list(z), gen=gen,
                            gen_estado=res['gen'], t_gen=res['t_gen'],
                            corridas=[dict(espectro='psd', zoom=list(z), cnt=r['cnt'],
                                           hist=_sparse(r['hist']))])
                filas.append(fila)
                self.filas.append(fila)
                self.guardar()
                print(f'  τ {tau:5g} A {amp:5d}: ' + (
                    f'psd {st["centroide"] / 65536:.4f}, FWHM {(st["fwhm"] or st["fwhm_gauss"]) / 65536:.4f}'
                    if st else 'sin línea'), flush=True)
        self.meta['psd'] = analizar_psd(filas)

    # -- polo-cero --

    def etapa_polo_cero(self):
        """El error del polo-cero: el par de la etapa par (A1 y después A2 sobre su cola)
        a unos Δt, con la M del trapecio corrida ΔM del valor del generador (el disparo
        queda con la nominal). Por ΔM, las líneas de los aislados con esa misma M, y el
        error de cada pulso del par contra su aislado. Con M exacta la cola se cancela
        y A2 mide lo mismo que solo; la pendiente da cuánto cuesta el error de M, y el
        cero, la M que cancela la cola que de verdad llega al MCA."""
        a = self.a
        fuente = a.fuente_pz
        n_acc = self.placa.n_acc_max
        gb = gen_base(a)
        g0 = G.config(**gb)
        decae = g0['decae']
        mq0 = G.mq_de(decae)
        disparo = disparo_de(fuente, decae, a.subida)
        filas = []
        print(f'\n[polo_cero] Mq del generador {mq0} (M = {mq0 / 16:.2f}); ΔM {list(a.dm_pz)}; '
              f'Δt {list(a.dts_pz)}', flush=True)
        for dm in a.dm_pz:
            mq = int(round(mq0 * (1.0 + dm)))
            mca = self.mca(fuente, decae, n_acc, mq=mq)
            gen = G.config(periodo=a.hueco // 2, n=4 * a.n_ref // 2, amp_n=4, **gb)
            gen['n'] = self.placa.recortar(gen)
            gen['n'] -= gen['n'] % 4
            res = self._correr(f'polo_cero ΔM={dm:+g} aislados', gen,
                               np.array([a.a1, 0, a.a2, 0], np.int16), mca, disparo,
                               [('trapecio', 0)])
            h = res['corridas'][0]['hist']
            ls = lineas_ref(h, 2)
            if len(ls) < 2:
                self.anomalias.append(f'polo_cero ΔM={dm:+g}: {len(ls)} líneas en los aislados')
                continue
            iso = (centroide(h, ls[1], 0.2), centroide(h, ls[0], 0.2))
            self.referencias[f'polo_cero/{dm}'] = dict(mq=mq, lineas=ls, a1=iso[0], a2=iso[1])
            for dt in a.dts_pz:
                k = k_par(dt, a.hueco)
                gen = G.config(periodo=dt, n=k * a.n_pares_pz, amp_n=k, **gb)
                n = self.placa.recortar(gen)
                gen['n'] = n - n % k
                res = self._correr(f'polo_cero ΔM={dm:+g} Δt={dt}', gen, tabla_par(a.a1, a.a2, k),
                                   mca, disparo, [('trapecio', 0)])
                r = res['corridas'][0]
                c1, c2 = centroide(r['hist'], iso[0], 0.2), centroide(r['hist'], iso[1], 0.2)
                fila = dict(etapa='polo_cero', clave=['polo_cero', dm, dt], fuente=fuente, dm=dm,
                            mq=mq, dt=dt, k=k, n_pares=gen['n'] // k, a1=c1, a2=c2, iso=list(iso),
                            err_a1=None if c1 is None else c1 / iso[0] - 1,
                            err_a2=None if c2 is None else c2 / iso[1] - 1,
                            gen=gen, gen_estado=res['gen'], t_gen=res['t_gen'],
                            corridas=[dict(espectro='trapecio', zoom=0, cnt=r['cnt'],
                                           hist=_sparse(r['hist']))])
                filas.append(fila)
                self.filas.append(fila)
                self.guardar()
                print(f'  ΔM {dm:+6.3f} Δt {dt:4d}: A1 {100 * (fila["err_a1"] or 0):+6.3f} %, '
                      f'A2 {100 * (fila["err_a2"] or 0):+6.3f} %', flush=True)
        self.meta['polo_cero'] = analizar_polo_cero(filas)

    # -- ventana ciega --

    def etapa_ventana_ciega(self):
        """Desde qué Δt un corte por forma ve el apilamiento que el disparo no separa. Los
        pares de la etapa par (A1 y después A2) a Δt de 2 ciclos en adelante, el banco con
        todas las ranuras y, por corrida, el discriminador sobre t_subida o ancho_inv con
        el intervalo central de los aislados (como en la etapa apilamiento). Mientras el
        disparo da uno solo por par, el evento mide la suma: si el corte lo deja pasar,
        es apilamiento no detectado. La ventana ciega es el mayor Δt donde eso pasa en
        más de la mitad de los pares. Con subida 0 el pulso sube en una muestra y
        cualquier Δt corre el pico: por eso se repite con subidas más lentas."""
        a = self.a
        n_acc = self.placa.n_acc_max
        h_aw = self.placa.h_aw
        esp_ref = [('trapecio', 0), ('t_subida', 3), ('ancho_inv', 3)]
        filas = []
        for subida in a.subidas_ciega:
            gb = gen_base(a) | dict(subida=int(subida))
            decae = G.config(**gb)['decae']
            for fuente in a.fuentes_ciega:
                mca = self.mca(fuente, decae, n_acc)
                disparo = disparo_de(fuente, decae, int(subida))
                gen = G.config(periodo=a.hueco // 2, n=4 * a.n_ref // 2, amp_n=4, **gb)
                gen['n'] = self.placa.recortar(gen)
                gen['n'] -= gen['n'] % 4
                res = self._correr(f'ventana_ciega subida={subida} {fuente} aislados', gen,
                                   np.array([a.a1, 0, a.a2, 0], np.int16), mca, disparo, esp_ref)
                lineas = lineas_ref(res['corridas'][0]['hist'], 2)
                if len(lineas) < 2:
                    self.anomalias.append(f'ventana_ciega subida={subida} {fuente}: '
                                          f'{len(lineas)} líneas en los aislados')
                    continue
                cortes = [('sin', None, None)] + cortes_forma(res['corridas'][1:], esp_ref[1:],
                                                              a.cuantiles_ciega, h_aw)
                self.referencias[f'ventana_ciega/{subida}/{fuente}'] = dict(
                    lineas=lineas, cortes=[[n, q, list(d) if d else None] for n, q, d in cortes],
                    hist={e: _sparse(r['hist']) for (e, _), r in zip(esp_ref[1:],
                                                                      res['corridas'][1:])})
                print(f'\n[ventana_ciega] subida {subida}, {fuente}: líneas '
                      f'{", ".join(f"{q:.1f}" for q in lineas)}; '
                      + '; '.join(f'{n} {q}: {list(d[1:])}' for n, q, d in cortes[1:]), flush=True)
                for dt in a.dts_ciega:
                    k = k_par(dt, a.hueco)
                    gen = G.config(periodo=dt, n=k * a.n_pares_ciega, amp_n=k, **gb)
                    n = self.placa.recortar(gen)
                    gen['n'] = n - n % k
                    n_pares = gen['n'] // k
                    tabla = tabla_par(a.a1, a.a2, k)
                    partes = []
                    for nombre, q, d in cortes:
                        res = self._correr(f'ventana_ciega subida={subida} {fuente} Δt={dt} '
                                           f'{nombre} {q}', gen, tabla,
                                           dict(mca, discr=d) if d else mca, disparo,
                                           [('trapecio', 0)])
                        r = res['corridas'][0]
                        me = meritos_ciega(r['hist'], n_pares, lineas, r['cnt'])
                        fila = dict(etapa='ventana_ciega',
                                    clave=['ventana_ciega', subida, fuente, dt, nombre, q],
                                    subida=subida, fuente=fuente, dt=dt, k=k, n_pares=n_pares,
                                    corte=nombre, umbral=q, discr=list(d) if d else None,
                                    meritos=me, gen=gen, gen_estado=res['gen'],
                                    t_gen=res['t_gen'],
                                    corridas=[dict(espectro='trapecio', zoom=0, cnt=r['cnt'],
                                                   hist=_sparse(r['hist']))])
                        filas.append(fila)
                        self.filas.append(fila)
                        partes.append(f'{nombre}{"" if q is None else " " + str(q)} '
                                      f'{me["apilado_aceptado"]:.2f}')
                    self.guardar()
                    print(f'  Δt {dt:3d}: {me["disparos_par"]:.2f} disparos por par; apilado '
                          'aceptado por par: ' + ', '.join(partes), flush=True)
        self.meta['ventana_ciega'] = analizar_ciega(filas)

    # -- deriva --

    def etapa_deriva(self):
        """La deriva con el tiempo: cada `cada_deriva` segundos, durante `horas_deriva`, el
        mismo tren de pulsos aislados que alterna dos alturas (A1, A2) y el trapecio con el
        zoom que abre las dos líneas. Con dos líneas la deriva se separa en offset (las
        dos corren lo mismo) y ganancia (corren en proporción). Por punto, también la
        temperatura del Zynq (el XADC). En el lazo digital el generador es determinista y
        la deriva tiene que dar cero: es el control. En el analógico corre lo que corre el
        canal (el DAC, el front-end, el ADC).

        Es larga: en la placa conviene correrla desprendida de la sesión ssh, para que un
        corte de la red no la mate (meritos.json se reescribe en cada punto):
            nohup python3 campanas/run_meritos_pulsos.py datos/deriva --etapas deriva \
                --modo analogico > deriva.log 2>&1 &"""
        a = self.a
        a1, a2 = (int(v) for v in a.amps_deriva)
        tabla = np.array([a1, a2], np.int16)
        gb = gen_base(a)
        n = max(2, int(round(a.seg_deriva * FS_HZ / a.periodo_deriva)))
        gen = G.config(periodo=a.periodo_deriva, n=n - n % 2, amp_n=2, semilla=a.semilla, **gb)
        gen['n'] = self.placa.recortar(gen)
        gen['n'] -= gen['n'] % 2
        mca = self.mca(a.fuente_deriva, gen['decae'], self.placa.n_acc_max)
        disparo = disparo_de(a.fuente_deriva, gen['decae'], a.subida)
        h_aw = self.placa.h_aw
        # El zoom: el que abre las dos líneas, desde una corrida sin zoom.
        grueso = self._correr('deriva sin zoom', gen, tabla, mca, disparo, [('trapecio', (0, 0))])
        ls = lineas_ref(grueso['corridas'][0]['hist'], 2)
        if len(ls) < 2:
            self.anomalias.append(f'deriva: {len(ls)} líneas sin zoom')
            return
        ancho = 1 << (16 - h_aw)
        z = zoom_rango((ls[0] - 40) * ancho, (ls[1] + 40) * ancho, h_aw)
        print(f'\n[deriva] {a1} y {a2} alternados cada {a.periodo_deriva} ciclos, {gen["n"]} '
              f'pulsos por punto, un punto cada {a.cada_deriva:g} s durante '
              f'{a.horas_deriva:g} h; zoom {z}', flush=True)
        filas = []
        t0 = time.time()
        i = 0
        while True:
            tp = time.time() - t0
            if i and (tp >= a.horas_deriva * 3600 or (a.puntos_deriva and i >= a.puntos_deriva)):
                break
            temp = self.placa.temperatura()
            res = self._correr(f'deriva punto {i}', gen, tabla, mca, disparo, [('trapecio', z)])
            r = res['corridas'][0]
            ln = centroides_lineas(r['hist'], 2)
            for d in ln:
                d['valor'] = float(valor_de_canal(d['centroide'], h_aw, *z))
            fila = dict(etapa='deriva', clave=['deriva', i], punto=i, t_s=tp, temp=temp,
                        fecha=datetime.now().isoformat(timespec='seconds'),
                        amplitudes=[a1, a2], lineas=ln, zoom=list(z), gen=gen,
                        gen_estado=res['gen'], t_gen=res['t_gen'],
                        corridas=[dict(espectro='trapecio', zoom=list(z), cnt=r['cnt'],
                                       hist=_sparse(r['hist']))])
            filas.append(fila)
            self.filas.append(fila)
            self.meta['deriva'] = analizar_deriva(filas)
            self.guardar()
            print(f'  {tp / 60:7.1f} min' + (f', {temp:.1f} °C' if temp is not None else '')
                  + ': ' + ', '.join(f'{d["valor"]:.2f} ± {d["error"] * (1 << (16 - z[0] - h_aw)):.2f}'
                                     for d in ln), flush=True)
            i += 1
            espera = t0 + i * a.cada_deriva - time.time()
            if espera > 0 and not (a.puntos_deriva and i >= a.puntos_deriva):
                time.sleep(espera)
        self.meta['deriva'] = analizar_deriva(filas)


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
            f' λ̂ {100 * m["err_lam"]:+6.2f} %' + _txt_dinamica(f['corridas'][0]))


def _txt_dinamica(c):
    """Δb medio de la base dinámica en una corrida, o nada."""
    pasos = (c.get('base_dinamica') or {}).get('pasos') or []
    if not pasos:
        return ''
    return f', Δb {np.mean([p["delta_b"] for p in pasos]):+.1f} ADU'


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


def resumen(filas, meta=None):
    lineas = []
    meta = meta or {}
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
    for modo, an in (meta.get('histeresis') or {}).items():
        if not an.get('tasas'):
            continue
        txt = (f'\n== histéresis, {modo} ==\n  {an["veredicto"]}: |vuelta − ida| máx '
               f'{an["h_max"]:.2f} canales ({an["h_sig_max"]:.1f} σ); con la tasa el '
               f'centroide corre {an["efecto_tasa"]:.2f} canales '
               f'({100 * an["corrimiento"]:+.2f} %)')
        if 'deriva_canales_hora' in an:
            txt += f'; deriva con el tiempo {an["deriva_canales_hora"]:+.2f} canales/hora'
        if 'corr_h_muerto' in an:
            txt += f'; corr(histéresis, Δmuerto) = {an["corr_h_muerto"]:+.2f}'
        lineas.append(txt)
    w = meta.get('walk') or {}
    if w:
        lineas.append('\n== walk, curva S y linealidad ==')
    for fuente, d in w.items():
        if d['a50'] is not None:
            txt = f'  {fuente:9s}: dispara la mitad en A = {d["a50"]:.0f}'
        elif d['efic'] and min(d['efic']) >= 0.99:
            txt = f'  {fuente:9s}: dispara siempre (desde A = {d["amplitudes"][0]})'
        else:
            txt = f'  {fuente:9s}: no llega a disparar la mitad'
        if d.get('a99') is not None:
            txt += f', el 99 % desde {d["a99"]:.0f}'
        if d.get('walk_rango') is not None:
            txt += f'; walk {d["walk_rango"]:.2f} ciclos ({8 * d["walk_rango"]:.1f} ns)'
        if 'inl_fs' in d:
            txt += f'; INL del trapecio {100 * d["inl_fs"]:.3f} % FS'
        lineas.append(txt)
    rd = meta.get('ruido') or {}
    if rd:
        lineas.append('\n== ruido: la resolución de cada estimador (cuentas de amplitud) ==')
    for e, d in rd.items():
        pts = d.get('puntos') or []
        if not pts:
            lineas.append(f'  {e:7s}: sin puntos')
            continue
        txt = f'  {e:7s}:'
        if 'ganancia_ruido' in d:
            txt += (f' σ_salida² = ({d["ganancia_ruido"]:.3f} σ_ruido)² + '
                    f'{d["sigma_0"]:.3f}²;')
        if d.get('sigma_sin_ruido') is not None:
            txt += f' sin ruido σ {d["sigma_sin_ruido"]:.3f};'
        # El punto del default de las otras etapas (sh 6), o el de más ruido.
        p = next((q for q in pts if q['ruido_sh'] == 6), pts[-1])
        txt += (f' con σ_ruido {p["sigma_in"]:.2f}: FWHM {p["fwhm"]:.2f} '
                f'({100 * p["resolucion"]:.3f} %'
                + (f', {p["bits"]:.1f} bits' if p['bits'] else '') + ')')
        txt += f'; con el máximo ({pts[-1]["sigma_in"]:.0f}) el centroide corre ' \
               f'{100 * pts[-1]["sesgo"]:+.2f} %'
        lineas.append(txt)
    fo = meta.get('forma') or {}
    if fo:
        lineas.append('\n== forma: FWHM/ε² contra la ocupación (§8: mínimo en ρ = 1/4) ==')
    for tasa, d in fo.items():
        lineas.append(f'  {float(tasa):9g}/s: mínimo en k = {d["k_opt"]} (ρ {d["rho_min"]:.3f})'
                      + (f'; interpolado ρ_opt = {d["rho_opt"]:.3f}' if 'rho_opt' in d else ''))
    ap = [f for f in filas if f['etapa'] == 'apilamiento']
    if ap:
        lineas.append('\n== apilamiento: (ε, fondo) de cada corte ==')
    for fu, tasa in sorted({(f['fuente'], f['tasa']) for f in ap}):
        fs = [f for f in ap if (f['fuente'], f['tasa']) == (fu, tasa)]
        sin = next(f for f in fs if f['corte'] == 'sin')['meritos']
        mejor = min(fs, key=lambda f: f['meritos']['fondo'])
        lineas.append(f'  {fu:9s} {tasa:9g}/s: sin corte ε {100 * sin["eps"]:5.1f} %, fondo '
                      f'{100 * sin["fondo"]:5.2f} %; el más limpio, {mejor["corte"]} '
                      f'{mejor["umbral"]}: ε {100 * mejor["meritos"]["eps"]:5.1f} %, fondo '
                      f'{100 * mejor["meritos"]["fondo"]:5.2f} %')
    for e, d in (meta.get('dnl') or {}).items():
        if not d:
            continue
        pl = d.get('plegado') or {}
        peor = max(pl.items(), key=lambda kv: kv[1]['rms'] / kv[1]['esperado'], default=None)
        lineas.append(f'\n== dnl, {e} ==\n  canales {d["canales"][0]}-{d["canales"][1]}, '
                      f'{d["cuentas_por_canal"]:.0f} cuentas/canal: rms {100 * d["rms"]:.2f} % '
                      f'(Poisson {100 * d["esperado"]:.2f} %, χ²/canal {d["chi2"]:.2f}), '
                      f'máx {100 * d["max_abs"]:.1f} %'
                      + (f'; plegada, la mayor contra el ruido: período {peor[0]}, rms '
                         f'{100 * peor[1]["rms"]:.3f} % (ruido {100 * peor[1]["esperado"]:.3f} %)'
                         if peor else ''))
    ps = meta.get('psd') or {}
    if ps:
        lineas.append('\n== psd: FOM de separación de formas ==')
    for A, d in ps.items():
        lineas.append(f'  A {int(float(A)):5d}: τ {d["taus"][0]:g} contra {d["taus"][1]:g}: '
                      f'FOM {d["fom"]:.2f}')
    vc = meta.get('ventana_ciega') or {}
    if vc:
        lineas.append('\n== ventana ciega del corte por forma (Δt en ciclos) ==')
    for d in vc.values():
        q = '' if d['umbral'] is None else f' {d["umbral"]}'
        lineas.append(f'  subida {d["subida"]} {d["fuente"]:9s} {d["corte"]}{q}: el disparo separa '
                      f'desde {_nunca(d["separa_desde"])}; el apilado pasa hasta '
                      f'{d["ciega_hasta"] if d["ciega_hasta"] is not None else "ninguno"}; '
                      f'limpio desde {_nunca(d["limpio_desde"])}; con Δt largo deja '
                      f'{100 * d["conserva"]:.0f} % de los pulsos en su línea')
    de = meta.get('deriva') or {}
    if de.get('puntos', 0) >= 2:
        lineas.append(f'\n== deriva: {de["puntos"]} puntos en {de["horas"]:.2f} h'
                      + (f', {de["temp"]["min"]:.1f} a {de["temp"]["max"]:.1f} °C'
                         if de.get('temp') else '') + ' (cuentas del generador) ==')
        for k in ('linea1', 'linea2', 'offset', 'ganancia_ppm'):
            d = de[k]
            lineas.append(f'  {k:12s}: recorrido {d["rango"]:.3f}, desvío {d["desvio"]:.3f}'
                          + (f', {d["por_hora"]:+.3f}/h' if 'por_hora' in d else '')
                          + (f', {d["por_grado"]:+.3f}/°C (r {d["corr_temp"]:+.2f})'
                             if 'por_grado' in d else ''))
    pc = meta.get('polo_cero') or {}
    if pc:
        lineas.append('\n== polo_cero: el error de A2 contra ΔM ==')
    for dt, d in pc.items():
        if 'pendiente' in d:
            lineas.append(f'  Δt {dt:>4s}: {d["pendiente"]:+.4f} por unidad de ΔM; se anula en '
                          f'ΔM = {100 * (d["dm_cero"] or 0):+.2f} %')
    return '\n'.join(lineas)


def _clave(f):
    """La clave de una fila para emparejar dos corridas (tasa y par, de antes de
    guardarla, la arman de sus campos)."""
    if 'clave' in f:
        return tuple(f['clave'])
    return (f['etapa'], f['fuente'], f['n_acc'], f.get('tasa', f.get('dt')))


def _medidas_comparables(f):
    """{(espectro, nombre): valor} de una fila, para --comparar."""
    if f['etapa'] in ('tasa', 'par'):
        claves = (('perd_disparo', 'perd_ranura', 'perd_publicador', 'eficiencia',
                   'frac_buenos', 'muerto_mca', 'err_lam') if f['etapa'] == 'tasa' else
                  ('disparos_par', 'eventos_par', 'frac_a1', 'frac_a2'))
        return {(c['espectro'], k): c['meritos'].get(k) for c in f['corridas']
                for k in claves}
    if f['etapa'] == 'forma':
        return {('', 'eps'): f['eps'], ('', 'fwhm_rel'): f['fwhm_rel']}
    if f['etapa'] == 'apilamiento':
        return {('trapecio', k): f['meritos'][k] for k in ('eps', 'fondo', 'arriba')}
    if f['etapa'] == 'dnl':
        return {}
    if f['etapa'] == 'psd':
        m = f['medida'] or {}
        return {('psd', 'centroide'): m.get('centroide'), ('psd', 'sigma'): m.get('sigma')}
    if f['etapa'] == 'ventana_ciega':
        return {('trapecio', k): f['meritos'][k] for k in ('disparos_par', 'apilado_aceptado')}
    if f['etapa'] == 'deriva':
        return {}
    if f['etapa'] == 'polo_cero':
        return {('trapecio', 'err_a1'): f['err_a1'], ('trapecio', 'err_a2'): f['err_a2']}
    m = f['medida']
    if f['etapa'] == 'ruido':
        m = m or {}
        return {(f['estimador'], 'sigma'): m.get('sigma'),
                (f['estimador'], 'centroide'): m.get('centroide'),
                (f['estimador'], 'efic'): m.get('efic')}
    if f['etapa'] == 'histeresis':
        ln = m.get('linea') or {}
        return {('pico', 'centroide'): ln.get('centroide'), ('pico', 'muerto'): m['muerto'],
                ('pico', 'base_evento'): m.get('base_evento')}
    ts = m.get('t_subida') or {}
    return {('', 'efic_disparo'): m['efic_disparo'], ('t_subida', 'media'): ts.get('media'),
            ('trapecio', 'valor'): m.get('trapecio'), ('pico', 'valor'): m.get('pico')}


def comparar(p_placa, p_sim):
    """Las figuras de mérito de la placa y de la simulación, punto por punto."""
    with open(p_placa) as f:
        a = json.load(f)
    with open(p_sim) as f:
        b = json.load(f)
    sim = {_clave(f): f for f in b['filas']}
    print(f'placa: {p_placa} ({a["meta"]["placa"]}, {a["meta"]["fecha"]})')
    print(f'simulación: {p_sim} ({b["meta"]["placa"]}, {b["meta"]["fecha"]})')
    for f in a['filas']:
        s = sim.get(_clave(f))
        if s is None:
            continue
        ma, mb = _medidas_comparables(f), _medidas_comparables(s)
        por_esp = {}
        for (esp, k), va in ma.items():
            vb = mb.get((esp, k))
            if va is None or vb is None:
                continue
            fmt = '{:.2%}' if f['etapa'] == 'tasa' else '{:.3f}'
            por_esp.setdefault(esp, []).append(f'{k} {fmt.format(va)}/{fmt.format(vb)}')
        for esp, partes in por_esp.items():
            print(f'  {" ".join(str(x) for x in _clave(f))} {esp}: ' + ', '.join(partes))
    return 0


# =============================================================================

def _lista(tipo):
    return lambda txt: [tipo(float(x)) if tipo is int else tipo(x) for x in txt.split(',') if x]


def _ruidos(txt):
    """'sin,6,3,0' -> [-1, 6, 3, 0]: 'sin' (o -1) es el punto sin ruido."""
    return [-1 if x.strip() in ('sin', '-1') else int(x) for x in txt.split(',') if x.strip()]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('outdir', nargs='?', help='dónde dejar meritos.json')
    ap.add_argument('--etapas', type=_lista(str), default=list(ETAPAS))
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
    ap.add_argument('--base-tasa', default='fija', choices=('fija', 'seguidor', 'dinamica'),
                    help='tasa: la base del MCA. Con el seguidor, el corrimiento de la '
                         'línea con la tasa en el analógico (la caída lenta del canal) '
                         'tendría que bajar, si el seguidor alcanza a ver la base entre '
                         'pulsos. Con la dinámica, la base fija se corre en vuelo con '
                         'la caída del canal (API/base_dinamica.py; sólo analógico)')
    ap.add_argument('--calibracion', default=None,
                    help='tasa con la base dinámica: el .json de la pestaña «Calibration» '
                         '(la caída y κ); sin él, la caída de la medición rápida')
    ap.add_argument('--caida', type=float, default=None,
                    help='tasa con la base dinámica: la caída lenta Σd/Σc (p. ej. '
                         '-0.073), en lugar de la de --calibracion')
    ap.add_argument('--kappa', type=float, default=None,
                    help='tasa con la base dinámica: κ (por defecto el de --calibracion, '
                         'o 1)')
    ap.add_argument('--bl-k', type=int, default=12,
                    help='tasa con el seguidor: la constante, 2^k muestras')
    ap.add_argument('--bl-holdoff', type=int, default=1000,
                    help='tasa con el seguidor: muestras congelado después de cada '
                         'ventana (4 τ: que no siga la cola del pulso)')
    ap.add_argument('--espectros-par', type=_lista(str), default=['trapecio', 'pico'])
    ap.add_argument('--tasas-hist', type=_lista(float), default=list(HIST_TASAS),
                    help='histéresis: las tasas del tren periódico (las del Rigol)')
    ap.add_argument('--seg-hist', type=float, default=5.0,
                    help='histéresis: segundos por punto (los del Rigol)')
    ap.add_argument('--n-min-hist', type=int, default=200,
                    help='histéresis: pulsos mínimos por punto')
    ap.add_argument('--a-hist', type=int, default=2000,
                    help='histéresis: la altura de los pulsos (con τ = 2 µs, el tren '
                         'a 794 kHz no satura)')
    ap.add_argument('--base-hist', type=int, default=0,
                    help='histéresis: la base del generador (y la fija del MCA)')
    ap.add_argument('--modos-hist', type=_lista(str), default=['seguidor', 'fija'])
    ap.add_argument('--tau-hist', type=float, default=25.0,
                    help='histéresis: la caída, en muestras. Corta (200 ns) como los pulsos '
                         'del modo PULSE del Rigol: con τ = 2 µs, a 794 kHz cada pulso '
                         'monta en las colas de los anteriores y el pico corre +113 %%')
    ap.add_argument('--fuente-hist', default='pendiente',
                    help='histéresis: el disparo (el de la campaña del Rigol)')
    ap.add_argument('--amps-walk', type=_lista(int), default=list(WALK_AMPS))
    ap.add_argument('--n-walk', type=int, default=400, help='walk: pulsos por amplitud')
    ap.add_argument('--ruidos-sh', type=_ruidos, default=list(RUIDOS_SH),
                    help="ruido: los ruido_sh del barrido ('sin' o -1 sin ruido; 0 es el "
                         "máximo, σ = 147.8 cuentas), p. ej. sin,6,3,0")
    ap.add_argument('--a-ruido', type=int, default=1500, help='ruido: la altura de la línea')
    ap.add_argument('--n-ruido', type=int, default=4000, help='ruido: pulsos por punto')
    ap.add_argument('--fuente-ruido', default='asg',
                    help='ruido: el disparo (el ASG: sin disparos falsos por el ruido)')
    ap.add_argument('--estimadores', type=_lista(str), default=list(ESTIMADORES),
                    help=f'ruido: de {tuple(ESTIMADORES)}')
    ap.add_argument('--ks-forma', type=_lista(int), default=list(FORMA_KS),
                    help='forma: las subidas k del trapecio (potencias de 2, hasta 512)')
    ap.add_argument('--tasas-forma', type=_lista(float), default=list(FORMA_TASAS))
    ap.add_argument('--ruido-forma', type=int, default=4,
                    help='forma: ruido_sh (4: σ 9.2 cuentas, que manda sobre la cuantización)')
    ap.add_argument('--a-forma', type=int, default=1500, help='forma: la altura de la línea')
    ap.add_argument('--seg-forma', type=float, default=0.5, help='forma: segundos por punto')
    ap.add_argument('--n-min-forma', type=int, default=20_000)
    ap.add_argument('--rho-max-forma', type=float, default=4.0,
                    help='forma: no corre los puntos con ρ mayor (ε < 2 %%)')
    ap.add_argument('--fuente-forma', default='asg',
                    help='forma: el disparo (el ASG: ve todos los pulsos, como supone §8)')
    ap.add_argument('--tasas-apil', type=_lista(float), default=list(APIL_TASAS))
    ap.add_argument('--fuentes-apil', type=_lista(str), default=['pz', 'pendiente'])
    ap.add_argument('--seg-apil', type=float, default=0.5, help='apilamiento: segundos por punto')
    ap.add_argument('--cortes-dt', type=_lista(int), default=list(APIL_CORTES_DT),
                    help='apilamiento: los cortes dt_anterior ≥ c, en muestras')
    ap.add_argument('--cuantiles-apil', type=_lista(float), default=list(APIL_CUANTILES),
                    help='apilamiento: la fracción de los aislados que pasa cada corte de '
                         't_subida y de ancho_inv')
    ap.add_argument('--rango-dnl', type=_lista(int), default=[500, 6000],
                    help='dnl: la amplitud mínima y la máxima (con el sobrepico del canal '
                         'analógico, 6000 no satura el ADC)')
    ap.add_argument('--tau-dnl', type=float, default=50.0,
                    help='dnl: la caída (corta: con el período de 300 no hay colas)')
    ap.add_argument('--periodo-dnl', type=int, default=300)
    ap.add_argument('--ruido-dnl', type=int, default=3,
                    help='dnl: ruido_sh del dither (3: σ 18.5 cuentas)')
    ap.add_argument('--seg-dnl', type=float, default=5.0, help='dnl: segundos por tanda')
    ap.add_argument('--tandas-dnl', type=int, default=6)
    ap.add_argument('--fuente-dnl', default='asg')
    ap.add_argument('--taus-psd', type=_lista(float), default=[200.0, 250.0],
                    help='psd: las dos caídas, en muestras')
    ap.add_argument('--amps-psd', type=_lista(int), default=[50, 100, 200, 500, 1000, 2000, 4000])
    ap.add_argument('--ruido-psd', type=int, default=4, help='psd: ruido_sh (4: σ 9.2)')
    ap.add_argument('--n-psd', type=int, default=4000, help='psd: pulsos por punto')
    ap.add_argument('--gate-short-psd', type=int, default=32,
                    help='psd: dónde empieza la cola, en muestras desde el disparo')
    ap.add_argument('--fuente-psd', default='asg')
    ap.add_argument('--dm-pz', type=_lista(float), default=list(PZ_DM),
                    help='polo_cero: los errores relativos de M del trapecio')
    ap.add_argument('--dts-pz', type=_lista(int), default=list(PZ_DTS))
    ap.add_argument('--n-pares-pz', type=int, default=1000)
    ap.add_argument('--fuente-pz', default='pz')
    ap.add_argument('--dts-ciega', type=_lista(int), default=list(CIEGA_DTS))
    ap.add_argument('--subidas-ciega', type=_lista(int), default=[0, 2],
                    help='ventana_ciega: las SUBIDA del generador (0: el pulso sube en una '
                         'muestra; 2: unas 9 muestras de 10 a 90 %%)')
    ap.add_argument('--fuentes-ciega', type=_lista(str), default=['pz', 'pendiente'])
    ap.add_argument('--cuantiles-ciega', type=_lista(float), default=list(CIEGA_CUANTILES))
    ap.add_argument('--n-pares-ciega', type=int, default=1000)
    ap.add_argument('--horas-deriva', type=float, default=2.0)
    ap.add_argument('--cada-deriva', type=float, default=60.0, help='deriva: segundos entre puntos')
    ap.add_argument('--seg-deriva', type=float, default=2.0, help='deriva: segundos de pulsos por punto')
    ap.add_argument('--puntos-deriva', type=int, default=0,
                    help='deriva: corta a estos puntos (0: sólo por las horas)')
    ap.add_argument('--amps-deriva', type=_lista(int), default=[1500, 4000])
    ap.add_argument('--periodo-deriva', type=int, default=3000)
    ap.add_argument('--fuente-deriva', default='asg')
    ap.add_argument('--modo', default='digital', choices=MODOS,
                    help='digital: el lazo; analogico: OUT1 → coaxial → IN1 (jumper LV)')
    ap.add_argument('--canal-sim', default='',
                    help="el canal de juguete de --simulada --modo analogico, p. ej. "
                         "'ganancia=0.97,offset=-12,lat=9,polo=0.45,ruido=1.3'")
    ap.add_argument('--canal-medido', default='', metavar='CANAL_NPZ',
                    help='--simulada --modo analogico con el canal de la placa: el FIR y '
                         'los polos lentos ajustados al canal.npz de run_fidelidad_osc.py')
    ap.add_argument('--sin-lentos', action='store_true',
                    help='con --canal-medido, el FIR solo (sin la caída lenta)')
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
        if e not in ETAPAS:
            ap.error(f'etapa {e!r}: una de {ETAPAS}')
    for m in a.modos_hist:
        if m not in ('seguidor', 'fija'):
            ap.error(f"modo {m!r}: 'seguidor' o 'fija'")
    if a.fuente_hist not in FUENTES:
        ap.error(f'--fuente-hist {a.fuente_hist!r}: una de {FUENTES}')
    if a.fuente_ruido not in FUENTES:
        ap.error(f'--fuente-ruido {a.fuente_ruido!r}: una de {FUENTES}')
    for e in a.estimadores:
        if e not in ESTIMADORES:
            ap.error(f'estimador {e!r}: uno de {tuple(ESTIMADORES)}')
    for s in a.ruidos_sh:
        if not -1 <= s <= 15:
            ap.error(f'--ruidos-sh {s}: de -1 (sin ruido) a 15')
    for f in a.fuentes + a.fuentes_apil + a.fuentes_ciega + [
            a.fuente_forma, a.fuente_dnl, a.fuente_psd, a.fuente_pz, a.fuente_deriva]:
        if f not in FUENTES:
            ap.error(f'fuente {f!r}: una de {FUENTES}')
    for k in a.ks_forma:
        try:
            forma_k(k)
        except ValueError as e:
            ap.error(f'--ks-forma: {e}')
    if len(a.rango_dnl) != 2 or not 0 < a.rango_dnl[0] < a.rango_dnl[1] <= G.AMP_MAX:
        ap.error('--rango-dnl: lo,hi con 0 < lo < hi ≤ 8191')
    if len(a.taus_psd) < 2:
        ap.error('--taus-psd: dos caídas')
    if len(a.amps_deriva) != 2 or a.amps_deriva[0] >= a.amps_deriva[1]:
        ap.error('--amps-deriva: dos alturas, de menor a mayor')
    if min(a.dts_ciega, default=2) < 2:
        ap.error('--dts-ciega: el período mínimo del generador es 2 ciclos')
    for e in a.espectros_tasa + a.espectros_par:
        if e not in ESPECTROS:
            ap.error(f'espectro {e!r}: uno de {tuple(ESPECTROS)}')
    if len(a.lineas) != len(a.pesos):
        ap.error('--lineas y --pesos: el mismo largo')
    if min(a.dts, default=2) < 2:
        ap.error('--dts: el período mínimo del generador es 2 ciclos')
    if a.canal_medido and not (a.simulada and a.modo == 'analogico'):
        ap.error('--canal-medido: es el canal de --simulada --modo analogico')
    if a.canal_medido and a.canal_sim:
        ap.error('--canal-medido o --canal-sim, no los dos')
    if a.sin_lentos and not a.canal_medido:
        ap.error('--sin-lentos: va con --canal-medido')
    if a.base_tasa == 'dinamica' and a.modo != 'analogico':
        ap.error('--base-tasa dinamica: es para el modo analógico (en el digital no hay '
                 'caída lenta que compensar)')
    if a.calibracion and not os.path.isfile(a.calibracion):
        ap.error(f'--calibracion {a.calibracion}: no existe')
    if a.comparar is None and not a.outdir:
        ap.error('falta outdir')
    return a


def main(argv=None, placa=None):
    a = parse_args(argv)
    if a.comparar:
        return comparar(*a.comparar)
    if placa is None:
        if a.simulada:
            if a.canal_medido:
                canal = CA.CanalMedido.desde_capturas(
                    a.canal_medido, lentos=() if a.sin_lentos else CA.LENTOS, semilla=a.semilla)
            else:
                canal = CA.CanalSimulado.desde_texto(a.canal_sim, a.semilla)
            placa = PlacaSimulada(h_aw=a.h_aw, ciclos_max=int(a.ciclos_max), modo=a.modo,
                                  canal=canal)
        else:
            try:
                placa = PlacaReal(modo=a.modo)
            except G.GenPulsosNotPresent as e:
                print(f'  {e}\n  Hace falta un bitstream con gen_pulsos (el MCA cce7b66b o '
                      'el ring 78e26188 en adelante).')
                return 2
    if a.modo == 'analogico':
        from run_fidelidad_osc import texto_canal
        print('[canal] OUT1 → IN1: el piso y la respuesta, con la BRAM', flush=True)
        try:
            canal = placa.caracterizar_canal(a.semilla)
        except Exception:
            placa.close()
            raise
        print(texto_canal(canal), flush=True)
        p = CA.problema(canal)
        if p:
            print(f'  SIN CANAL: {p}\n  La campaña analógica no corre así.')
            placa.close()
            return 3
        if canal['no_causal'] > 0.01:
            print('  OJO: el FIR tiene energía antes del pulso: las capturas con y sin el '
                  'lazo no estaban alineadas')
    camp = Campana(placa, a, a.outdir)
    print(f'{placa.nombre} ({camp.modo}): {1 << placa.h_aw} canales, {placa.n_acc_max} '
          f'ranuras; τ = {a.tau:g} muestras, subida {a.subida}, ruido sh {a.ruido_sh}')
    try:
        if 'tasa' in a.etapas:
            camp.etapa_tasa()
        if 'par' in a.etapas:
            camp.etapa_par()
        if 'histeresis' in a.etapas:
            camp.etapa_histeresis()
        if 'walk' in a.etapas:
            camp.etapa_walk()
        if 'ruido' in a.etapas:
            camp.etapa_ruido()
        for e in ('forma', 'apilamiento', 'dnl', 'psd', 'polo_cero', 'ventana_ciega', 'deriva'):
            if e in a.etapas:
                getattr(camp, f'etapa_{e}')()
    finally:
        placa.close()
        camp.guardar()
    print(resumen(camp.filas, camp.meta))
    if camp.anomalias:
        print(f'\n{len(camp.anomalias)} ANOMALÍAS:')
        for m in camp.anomalias:
            print(f'  {m}')
    if a.outdir:
        print(f'\n  -> {os.path.join(a.outdir, "meritos.json")}')
    return 1 if camp.anomalias else 0


if __name__ == '__main__':
    sys.exit(main())
