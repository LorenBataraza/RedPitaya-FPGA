#!/usr/bin/env python3
"""`sweep_rate` con pasada de vuelta, contra un MCA SIMULADO con deriva conocida.

Lo que se valida no es que el barrido corra, sino que **atribuya bien la causa**.
Es un test de verdad-de-campo: el MCA falso mueve su centroide con una ley que
el test elige, y el análisis tiene que recuperarla.

Los dos escenarios son las dos respuestas posibles a la pregunta abierta de §17
de `resultados_validacion_hw.md` — si el +1.28 % medido es función de la tasa o
del tiempo — y el test exige que se distingan:

  A) deriva PURAMENTE TEMPORAL: el centroide sube con el reloj y no le importa
     la tasa. La ida sola reporta un corrimiento con la tasa que es un ARTEFACTO
     (y el test lo verifica, porque ése es el error que la vuelta viene a
     corregir); el análisis tiene que decir DERIVA TEMPORAL, recuperar la
     pendiente, y dejar el corrimiento corregido en ~0.
  B) dependencia PURAMENTE CON LA TASA: sin término temporal. La ida y la vuelta
     se superponen, el veredicto tiene que ser REPRODUCIBLE EN TASA, y el
     corrimiento corregido tiene que quedar igual al crudo.

El reloj es VIRTUAL: se reemplaza `time` dentro de testbench_mca por un
contador. Sin eso el test tardaría lo que tarda la campaña (~2 min de sleeps)
y la deriva dependería de la carga de la máquina, o sea que sería un test
distinto en cada corrida.

Uso:
    python3 test_deriva_sweep_sim.py
"""
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(_AQUI))   # campanas/, donde vive testbench_mca

import testbench_mca as tb        # noqa: E402

H_AW = 13                        # el eje nuevo: 8192 canales
N_CANALES = 1 << H_AW
FALLAS = []


def check(nombre, ok, detalle=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {nombre}' + (f'  {detalle}' if detalle else ''))
    if not ok:
        FALLAS.append(nombre)
    return ok


class Reloj:
    """Reloj virtual: `sleep` adelanta en vez de esperar."""

    def __init__(self, t0=1_000_000.0):
        self.t = t0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


class GenFalso:
    """Entrega exactamente lo que se le pide (el generador no es el sujeto acá)."""

    def __init__(self):
        self.period_s = None
        self.width_s = None

    def set_pulse_periodic(self, ch=1, period_s=1e-3, width_s=1e-6,
                           amp_vpp=1.0, offset_v=0.0, **kw):
        self.period_s, self.width_s = float(period_s), float(width_s)

    def output(self, ch, on, **kw):
        pass

    def disable_burst(self, ch=1, **kw):
        pass

    def query(self, cmd):
        if 'WIDT' in cmd.upper():
            return str(self.width_s)
        return str(1.0 / self.period_s)


class McaConDeriva:
    """Espectro gaussiano cuyo centroide sigue una ley `cen(rate_hz, t)` dada.

    No modela tiempo muerto: acá el sujeto es el centroide. La tasa de salida se
    devuelve igual a la de entrada, así que la guarda de validez del barrido
    (`total/realtime` tiene que coincidir con lo pedido) da siempre válido y
    todos los puntos entran al análisis.
    """

    def __init__(self, gen, reloj, ley, fwhm_can=8.0, cuentas=400_000, seed=7):
        self.gen, self.reloj, self.ley = gen, reloj, ley
        self.fwhm = fwhm_can
        self.cuentas = cuentas
        self.rng = np.random.default_rng(seed)

    def configure(self, **cfg):
        pass

    def last_event(self):
        # Base ficticia pero con HISTORIA: sigue a la tasa del punto anterior,
        # que es la hipótesis de §19.3. Acá sólo sirve para que el barrido
        # ejercite el camino de lectura; el veredicto no la usa.
        return {'baseline': -50.0 - 1e-4 * (1.0 / max(self.gen.period_s, 1e-9))}

    # Primitivas que usa `_acquire_con_base` para muestrear la base EN VUELO.
    # El falso las implementa por separado en vez de sólo `acquire()` para que
    # el test recorra el mismo camino que la placa. El instante que se le pasa a
    # la ley es el PUNTO MEDIO entre start y stop, que es lo que el barrido le
    # asigna al punto: se calcula de los dos, sin necesidad de saber `seconds`.
    _has_2d = False

    def stop(self):
        if getattr(self, '_t_ini', None) is not None:
            self._ultimo = self._medir(0.5 * (self._t_ini + self.reloj.time()),
                                       self.reloj.time() - self._t_ini)
            self._t_ini = None

    def clear(self):
        pass

    def start(self):
        self._t_ini = self.reloj.time()

    def spectrum(self):
        return self._ultimo[0]

    def counters(self):
        return self._ultimo[1]

    def map2d(self):
        return None

    def _medir(self, t_cen, dur):
        rate = 1.0 / self.gen.period_s
        cen = float(self.ley(rate, t_cen))
        sigma = self.fwhm / 2.3548
        x = np.arange(N_CANALES, dtype=float)
        perfil = np.exp(-0.5 * ((x - cen) / sigma) ** 2)
        perfil /= perfil.sum()
        spec = self.rng.poisson(self.cuentas * perfil).astype(np.int64)
        n = int(round(rate * dur))
        cnt = dict(total=n, accepted=n, dropped=0, pileup=0, rej_amp=0,
                   rej_psd=0, realtime_s=float(dur), livetime_s=float(dur),
                   deadtime_s=0.0)
        return spec, cnt

    def acquire(self, seconds, clear_first=True):
        rate = 1.0 / self.gen.period_s
        # El centroide se evalúa en el CENTRO de la adquisición, que es el mismo
        # instante que el barrido le asigna al punto.
        cen = float(self.ley(rate, self.reloj.time() + 0.5 * seconds))
        sigma = self.fwhm / 2.3548
        x = np.arange(N_CANALES, dtype=float)
        perfil = np.exp(-0.5 * ((x - cen) / sigma) ** 2)
        perfil /= perfil.sum()
        # Ruido de conteo: es lo que fija la repetibilidad del centroide, y por
        # lo tanto la escala contra la que el análisis decide si la histéresis
        # es significativa. Sin ruido el test no probaría ese criterio.
        spec = self.rng.poisson(self.cuentas * perfil).astype(np.int64)
        self.reloj.sleep(seconds)                      # la adquisición dura
        n = int(spec.sum())
        cnt = dict(total=n, accepted=n, dropped=0, pileup=0, rej_amp=0,
                   rej_psd=0, realtime_s=float(seconds),
                   livetime_s=float(seconds), deadtime_s=0.0)
        # La guarda del barrido compara total/realtime contra la tasa pedida.
        cnt['total'] = int(round(rate * seconds))
        cnt['accepted'] = cnt['total']
        return spec, None, cnt


RATES = np.array([1e3, 3e3, 1e4, 3e4, 1e5, 3e5])
CEN0 = 4000.0


def _correr(ley, seed=7, seconds=2.0, outdir=None):
    reloj = Reloj()
    gen = GenFalso()
    mca = McaConDeriva(gen, reloj, ley, seed=seed)
    orig = tb.time
    tb.time = reloj                     # reloj virtual dentro del barrido
    try:
        return tb.sweep_rate(mca, gen, ch=1, rates=RATES, seconds=seconds,
                             ida_y_vuelta=True, outdir=outdir), reloj
    finally:
        tb.time = orig


def _tramo_ancho_constante(res):
    """Las tasas que el análisis realmente compara: las de ancho nominal.

    El barrido descarta del corrimiento los puntos donde `set_pulse_periodic`
    tuvo que achicar el pulso (arriba de ~150 kHz con 2 us), así que el tramo
    efectivo NO va de rates[0] a rates[-1]. Calcularlo acá y no a mano evita que
    el test afirme un número que el barrido nunca prometió — que fue justamente
    el primer FAIL de este test.
    """
    anc = np.asarray(res['widths'])
    m = np.abs(anc - anc.max()) < 1e-9
    r = np.asarray(res['r_in'])[m]
    return r[0], r[-1]


def test_deriva_temporal_pura():
    print('\n== A) el centroide deriva con el TIEMPO y no con la tasa ==')
    # 4 canales/segundo: sobre el tramo de ancho constante de la ida (~9 s de
    # reloj virtual) son ~37 canales = ~0.9 % del centroide, o sea el orden del
    # +1.28 % medido en placa. La magnitud importa: el test tiene que ver el
    # ARTEFACTO con el mismo tamaño que tiene el efecto real bajo sospecha.
    M = 4.0
    t_ref = [None]

    def ley(rate, t):
        if t_ref[0] is None:
            t_ref[0] = t
        return CEN0 + M * (t - t_ref[0])

    res, _ = _correr(ley)
    d = res['deriva']

    check('detectó que la deriva es TEMPORAL',
          d['veredicto'].startswith('DERIVA TEMPORAL'), d['veredicto'][:60])
    err = abs(d['pendiente_can_s'] - M) / M
    check('recuperó la pendiente de la deriva', err < 0.05,
          f'{d["pendiente_can_s"]:.4f} can/s vs {M:.4f} puestos ({100*err:.1f}% de error)')
    check('la recta pasa por el origen, como predice el modelo aditivo',
          abs(d['ordenada_can']) < 3 * d['sigma_resid_can'] + 0.5,
          f'ordenada {d["ordenada_can"]:+.3f} can, sigma {d["sigma_resid_can"]:.3f}')

    # El punto del test: SIN la vuelta, el barrido habría reportado un
    # corrimiento con la tasa que no existe.
    crudo = res['centroid_shift_pct']
    corr = res['centroid_shift_pct_sin_deriva']
    check('la ida SOLA reporta un corrimiento con la tasa (el artefacto)',
          abs(crudo) > 0.5, f'{crudo:+.3f}% crudo, del orden del +1.28% medido')
    check('y al descontar la deriva el corrimiento se va a cero',
          abs(corr) < 0.05 * abs(crudo), f'{corr:+.4f}% corregido')


def test_dependencia_con_la_tasa_pura():
    print('\n== B) el centroide depende de la TASA y no del tiempo ==')
    # +1.28 % por década y media, del orden de lo medido: sin término temporal.
    K = 0.0128

    def ley(rate, t):
        return CEN0 * (1.0 + K * np.log10(rate / RATES[0]))

    res, _ = _correr(ley)
    d = res['deriva']

    check('NO inventó una deriva temporal',
          d['veredicto'].startswith('REPRODUCIBLE EN TASA'), d['veredicto'][:60])
    check('la histéresis es despreciable frente al efecto de la tasa',
          np.nanmax(np.abs(d['histeresis_can'])) < 1.0,
          f'máx |vuelta-ida| = {np.nanmax(np.abs(d["histeresis_can"])):.2f} can')

    crudo = res['centroid_shift_pct']
    corr = res['centroid_shift_pct_sin_deriva']
    r0, r1 = _tramo_ancho_constante(res)
    esperado = 100.0 * K * np.log10(r1 / r0)
    check('midió el corrimiento con la tasa que se le puso',
          abs(crudo - esperado) < 0.1,
          f'{crudo:+.3f}% vs {esperado:+.3f}% puesto (tramo {r0:.0f}-{r1:.0f} Hz)')
    check('la corrección no lo destruye (no hay deriva que sacar)',
          abs(corr - crudo) < 0.1, f'{corr:+.3f}% corregido vs {crudo:+.3f}% crudo')


def test_histeresis_en_arco_no_es_deriva():
    """El caso que los DATOS REALES encontraron, y que el criterio original
    clasificaba al revés.

    Medido en placa el 2026-09-08: histéresis de hasta +10.8 canales, contra una
    repetibilidad de 0.11, pero con forma de ARCO — cero en las dos puntas del
    barrido, máxima en el medio. Como la separación temporal entre visitas es
    monótona (máxima en la tasa más baja, mínima en el retorno), un arco NO es
    una deriva temporal: de hecho la histéresis vale 0.0 justo donde la
    separación es de 159 s, que es donde una deriva daría su efecto máximo.

    El criterio original se equivocó por dos razones acopladas: preguntaba
    primero "¿es despreciable?" y usaba como patrón la dispersión de los
    residuos del ajuste lineal — que un arco infla hasta 4.57 canales, porque el
    residuo se come el arco entero. Resultado: 10.8 canales de histéresis
    declarados "dentro del ruido", o sea la conclusión contraria.
    """
    print('\n== C) histéresis con forma de ARCO: ni tasa pura ni tiempo ==')
    # Las PROPORCIONES son las medidas en placa, no números inventados: arco de
    # ~11 canales contra un efecto de tasa de ~22, o sea la histéresis vale la
    # mitad del efecto que se está midiendo. Esa razón es lo que decide el
    # veredicto, así que es lo que el test tiene que reproducir.
    A = 11.0
    EFECTO = 22.0                                    # canales de punta a punta
    lo, hi = np.log10(RATES[0]), np.log10(RATES[-1])
    K = EFECTO / (CEN0 * (hi - lo))
    estado = {'prev': None}

    def ley(rate, t):
        prev = estado['prev']
        estado['prev'] = rate
        sentido = 0.0 if prev is None else (1.0 if rate > prev else -1.0)
        arco = np.sin(np.pi * (np.log10(rate) - lo) / (hi - lo))
        return CEN0 * (1 + K * np.log10(rate / RATES[0])) - sentido * (A / 2) * arco

    res, _ = _correr(ley)
    d = res['deriva']

    check('NO lo llama deriva temporal',
          not d['veredicto'].startswith('DERIVA TEMPORAL'), d['veredicto'][:45])
    check('NO lo llama reproducible en tasa (que fue el error original)',
          not d['veredicto'].startswith('REPRODUCIBLE'), d['veredicto'][:45])
    check('lo clasifica como histéresis sin estructura temporal',
          d['veredicto'].startswith('HISTÉRESIS SIN ESTRUCTURA'))
    check('la histéresis medida es del tamaño puesto',
          abs(d['histeresis_max_can'] - A) < 0.15 * A,
          f'{d["histeresis_max_can"]:.1f} can vs {A} puestos')
    check('la reporta como fracción del efecto, que es lo que decide',
          0.3 < d['histeresis_frac_efecto'] < 0.8,
          f'{100*d["histeresis_frac_efecto"]:.0f} % del efecto '
          f'({d["efecto_tasa_can"]:.1f} can)')


def test_guarda_y_grafica():
    print('\n== el .npz trae las columnas nuevas y plot_all las dibuja ==')
    out = os.path.join(_AQUI, '_out_deriva_sim')
    res, _ = _correr(lambda r, t: CEN0 + 0.2 * (t % 1e6), outdir=out)
    npz = os.path.join(out, 'sweep_rate.npz')
    check('guardó el .npz', os.path.exists(npz))
    if not os.path.exists(npz):
        return
    z = np.load(npz)
    check('trae las columnas de la vuelta',
          all(k in z.files for k in ('centroids_vuelta', 't_vuelta',
                                     'rates_deriva', 'centroids_ida',
                                     't_ida_deriva')),
          str(sorted(z.files)))
    check('y sigue trayendo las de siempre (los consumidores no se rompen)',
          all(k in z.files for k in ('r_in', 'r_out', 'centroids',
                                     'livetime_frac', 'widths')))
    tb.plot_all(out)
    png = os.path.join(out, 'deriva_tasa_tiempo.png')
    check('plot_all dibujó la figura de deriva',
          os.path.exists(png) and os.path.getsize(png) > 5000)
    check('y no rompió la de throughput',
          os.path.exists(os.path.join(out, 'throughput.png')))


def test_sin_vuelta_sigue_andando():
    print('\n== ida_y_vuelta=False: el comportamiento viejo, intacto ==')
    reloj = Reloj()
    gen = GenFalso()
    mca = McaConDeriva(gen, reloj, lambda r, t: CEN0)
    orig = tb.time
    tb.time = reloj
    try:
        res = tb.sweep_rate(mca, gen, ch=1, rates=RATES, seconds=2.0,
                            ida_y_vuelta=False, outdir=None)
    finally:
        tb.time = orig
    check('no analiza deriva si no hay vuelta', res['deriva'] is None)
    check('sigue devolviendo lo de antes',
          all(k in res for k in ('r_in', 'r_out', 'centroids', 'techo_cps',
                                 'centroid_shift_pct')))


if __name__ == '__main__':
    print('sweep_rate con pasada de vuelta (MCA simulado con deriva conocida)')
    test_deriva_temporal_pura()
    test_dependencia_con_la_tasa_pura()
    test_histeresis_en_arco_no_es_deriva()
    test_guarda_y_grafica()
    test_sin_vuelta_sigue_andando()
    print('\nRESULT:', 'PASS' if not FALLAS else f'FAIL ({len(FALLAS)}): {FALLAS}')
    sys.exit(1 if FALLAS else 0)
