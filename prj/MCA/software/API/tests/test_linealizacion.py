#!/usr/bin/env python3
"""Tests de la linealizacion del eje de amplitud. Corren en la PC, sin placa.

Verifican las funciones de mca_utils que invierten el modelo

    Ahat = G*A + INL(A)

y corrigen un espectro con ellas. Lo que se comprueba, en orden:

  1. CONSERVACION   ninguna correccion puede crear ni destruir cuentas
  2. IDENTIDAD      con INL == 0 el espectro corregido es el original
  3. RECUPERACION   con una INL conocida, los centroides corregidos vuelven a
                    la recta ideal y la INL residual baja un orden
  4. RECHAZO        una INL que pliega el eje tiene que FALLAR con un mensaje,
                    no devolver un numero. Es el criterio de aceptacion de todo
                    el proyecto: que el test rechace cuando el dato no da.
  5. CONMUTACION    replayando pulsos REALES, una f monotona sobre las muestras
                    tiene que dar exactamente P' = f(P) para el pico. Es el
                    unico resultado analitico disponible y valida el replay
                    antes de creerle lo que dice de la integral, donde NO hay
                    formula cerrada.
  6. DATOS REALES   sobre la campana ya medida: margen de inversibilidad, INL
                    antes y despues, DNL introducida, y la curva de INL residual
                    contra numero de nodos de la LUT.

Los tests 5 y 6 necesitan los .npz de datos/; si no estan, se saltean con
aviso en vez de fallar.

    python3 test_linealizacion.py
"""
import glob
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))

_RAIZ = AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import mca_utils as mu

FAILS = []

DIR_CHUNKS = os.path.join(_RAIZ, 'datos', 'e2e_20260528_013404', 'principal')
NPZ_CAMPANA = os.path.join(_RAIZ, 'datos', 'mca_gate_esp_v2',
                           'sweep_gate_espectro.npz')


def check(nombre, cond, extra=''):
    print(f'  {"OK  " if cond else "FALLA"} {nombre} {extra}')
    if not cond:
        FAILS.append(nombre)


# =============================================================================
# Utilidades del test
# =============================================================================

N_CANALES = 4096
GAIN  = 3500.0          # canales por unidad de referencia
OFF   = 120.0


def _sintetico(inl_fn, amps, sigma=8.0, cuentas=20000, n=N_CANALES, seed=0):
    """Espectro de picos gaussianos ubicados segun Ahat = G*A + INL(A).

    Devuelve (espectro, centroides_verdaderos). El espectro es la SUMA de los
    picos, que es lo que ve el MCA: no hay forma de separarlos salvo ajustando.
    """
    rng = np.random.default_rng(seed)
    spec = np.zeros(n, dtype=float)
    cen = []
    for a in amps:
        c = GAIN * a + OFF + inl_fn(a)
        cen.append(c)
        x = rng.normal(c, sigma, cuentas)
        h, _ = np.histogram(x, bins=n, range=(0, n))
        spec += h
    return spec, np.asarray(cen)


def _cal_desde(inl_fn, amps, **kw):
    """Calibracion construida desde los centroides EXACTOS del modelo."""
    cen = np.asarray([GAIN * a + OFF + inl_fn(a) for a in amps])
    return mu.axis_calibration(amps, cen, **kw)


# =============================================================================
# 1-2. Conservacion e identidad
# =============================================================================

def test_conservacion():
    print('\n=== 1. conservacion de cuentas ===')
    amps = np.linspace(0.1, 1.0, 12)

    # Tres INL distintas, todas monotonas: una suave, una con ondulacion, y una
    # fuerte pero todavia invertible.
    casos = {
        'cuadratica':  lambda a: 40.0 * (a - 0.55) ** 2,
        'ondulada':    lambda a: 25.0 * np.sin(6.0 * np.pi * a),
        'fuerte':      lambda a: 300.0 * (a - 0.55) ** 3,
    }
    for nombre, fn in casos.items():
        cal = _cal_desde(fn, amps)
        spec, _ = _sintetico(fn, amps)
        r = mu.linearize_spectrum(spec, cal)
        total_in, total_out = spec.sum(), r['spec'].sum() + r['counts_out']
        rel = abs(total_out - total_in) / total_in
        check(f'{nombre}: se conservan las cuentas', rel < 1e-9,
              f'(rel {rel:.2e}, fuera del eje {100*r["frac_out"]:.2f}%)')


def test_identidad():
    print('\n=== 2. identidad con INL == 0 ===')
    amps = np.linspace(0.1, 1.0, 12)
    cero = lambda a: np.zeros_like(np.asarray(a, dtype=float))
    cal = _cal_desde(cero, amps)

    check('INL nula -> inl_pct_fs ~ 0', cal['inl_pct_fs'] < 1e-9,
          f'({cal["inl_pct_fs"]:.2e} % FS)')
    check('INL nula -> margen == G', abs(cal['margen'] - cal['gain']) < 1e-6 * cal['gain'],
          f'(margen {cal["margen"]:.1f}, G {cal["gain"]:.1f})')

    # apply_calibration tiene que ser la identidad sobre el rango calibrado.
    b = np.linspace(GAIN * amps[0] + OFF, GAIN * amps[-1] + OFF, 50)
    err = np.abs(mu.apply_calibration(b, cal) - b).max()
    check('apply_calibration es la identidad', err < 1e-6, f'(err max {err:.2e} canales)')

    spec, _ = _sintetico(cero, amps)
    r = mu.linearize_spectrum(spec, cal)
    err = np.abs(r['spec'] - spec).max()
    check('el espectro corregido es el original', err < 1e-6,
          f'(err max {err:.2e} cuentas)')


# =============================================================================
# 3. Recuperacion
# =============================================================================

def test_recuperacion():
    print('\n=== 3. recuperacion de la recta ideal ===')
    amps = np.linspace(0.1, 1.0, 16)
    inl = lambda a: 45.0 * np.sin(3.0 * np.pi * a)      # ~1.2 % FS

    cal = _cal_desde(inl, amps)
    print(f'  G = {cal["gain"]:.1f} canales/ref   INL = {cal["inl_pct_fs"]:.3f} % FS'
          f'   margen = {cal["margen"]:.1f}')
    check('el eje es invertible', cal['invertible'], f'(margen {cal["margen"]:.1f})')

    # Los centroides medidos, corregidos, tienen que caer sobre G*A + b.
    medidos = np.asarray([GAIN * a + OFF + inl(a) for a in amps])
    corr = mu.apply_calibration(medidos, cal)
    ideal = cal['gain'] * amps + cal['offset']
    err = np.abs(corr - ideal).max()
    check('los centroides vuelven a la recta ideal', err < 0.5,
          f'(err max {err:.3f} canales)')

    # Y la INL medida sobre los centroides corregidos tiene que desplomarse.
    _, _, _, inl_post = mu.energy_calibration(corr, amps)
    check('la INL residual baja al menos un orden',
          inl_post < cal['inl_pct_fs'] / 10,
          f'({cal["inl_pct_fs"]:.3f} % FS -> {inl_post:.4f} % FS)')

    # Lo mismo pero pasando por el espectro entero: ajustar los picos del
    # espectro CORREGIDO tiene que dar los centroides ideales. Esto ejercita el
    # rebinning, no solo el mapa escalar.
    spec, _ = _sintetico(inl, amps, sigma=6.0, cuentas=40000)
    r = mu.linearize_spectrum(spec, cal)
    errs = []
    for a, ci in zip(amps, ideal):
        lo, hi = int(ci - 30), int(ci + 30)
        g = mu.gauss_fit_peak(r['spec'], max(0, lo), min(N_CANALES, hi))
        if np.isfinite(g['centroid']):
            errs.append(abs(g['centroid'] - ci))
    peor = max(errs) if errs else float('inf')
    check('los picos del espectro corregido caen en la recta ideal',
          len(errs) == len(amps) and peor < 1.5,
          f'({len(errs)}/{len(amps)} ajustados, err max {peor:.2f} canales)')


# =============================================================================
# 4. Rechazo del eje plegado
# =============================================================================

def test_rechazo():
    print('\n=== 4. rechazo: el eje que se pliega ===')
    amps = np.linspace(0.1, 1.0, 24)

    # Una INL cuya pendiente supera -G: el mapa A -> Ahat deja de crecer y dos
    # regiones no conexas de energia caen en el mismo canal. Amplitud tal que
    # dINL/dA ~ -1.5*G en el tramo mas empinado.
    amp_inl = 1.5 * GAIN / (2.0 * np.pi)
    inl = lambda a: amp_inl * np.sin(2.0 * np.pi * a)

    cal = _cal_desde(inl, amps)
    check('el eje plegado se detecta como NO invertible', not cal['invertible'],
          f'(margen {cal["margen"]:.1f}, G {cal["gain"]:.1f})')

    for nombre, fn in (('apply_calibration', lambda: mu.apply_calibration([100.0], cal)),
                       ('linearize_spectrum', lambda: mu.linearize_spectrum(np.ones(64), cal))):
        try:
            fn()
            check(f'{nombre} levanta ValueError', False, '(devolvio un numero!)')
        except ValueError as e:
            check(f'{nombre} levanta ValueError', 'invertible' in str(e).lower(),
                  f'({str(e)[:52]}...)')

    # Los otros errores explicitos.
    try:
        mu.axis_calibration([1.0, 2.0], [1.0, 2.0])
        check('menos de 3 puntos falla', False)
    except ValueError:
        check('menos de 3 puntos falla', True)

    try:
        mu.axis_calibration([1.0, 1.0, 2.0], [1.0, 2.0, 3.0])
        check('referencias repetidas falla', False)
    except ValueError:
        check('referencias repetidas falla', True)

    try:
        mu.axis_calibration([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
        check('ganancia negativa falla', False)
    except ValueError:
        check('ganancia negativa falla', True)


# =============================================================================
# 5. Conmutacion del pico sobre pulsos reales
# =============================================================================

def _cargar_ondas(directorio, max_chunks=4):
    fs = sorted(glob.glob(os.path.join(directorio, 'chunk_*.npz')))[:max_chunks]
    if not fs:
        return None
    w = [np.load(f, allow_pickle=True)['wave'][:, 0, :].astype(np.int64) for f in fs]
    return np.concatenate(w)


def test_conmutacion_pico():
    print('\n=== 5. conmutacion del pico sobre pulsos reales ===')
    ondas = _cargar_ondas(DIR_CHUNKS)
    if ondas is None:
        print(f'  SALTEADO: no hay chunks en {DIR_CHUNKS}')
        return
    print(f'  {ondas.shape[0]} ventanas x {ondas.shape[1]} muestras')

    try:
        from API.modelo_rtl import estimadores as est
    except ImportError as e:
        print(f'  SALTEADO: no se pudo importar estimadores ({e})')
        return

    base = float(ondas[:, :8].mean())

    def f(x):
        """Correccion de muestra monotona: ganancia + una compresion suave."""
        x = np.asarray(x, dtype=float)
        return 1.05 * x - 2e-6 * np.maximum(x, 0.0) ** 2

    def est_pico(w, bl):
        # El pico de la ventana entera, que es lo que el maximo del RTL calcula
        # sobre un unico pulso capturado.
        return np.maximum(w - bl, 0.0).max(axis=1)

    def est_integral(w, bl):
        out = []
        for fila in w:
            ev = est.integral_gates(np.rint(fila).astype(np.int64), baseline=int(round(bl)),
                                    thr=100, hyst=40, corta=32, larga=384)
            out.append(ev[0]['q_tot'] if ev else np.nan)
        return np.asarray(out, dtype=float)

    r = mu.propagar_calibracion_muestra(
        ondas, f, {'pico': est_pico, 'integral': est_integral}, baseline=base)

    # El resultado analitico: con f monotona, max(f(x)) == f(max(x)). Lo que se
    # compara es el pico calibrado contra f aplicada al pico crudo, los dos
    # relativos a su propia base.
    p_crudo = r['pico']['crudo']
    p_calib = r['pico']['calibrado']
    esperado = f(p_crudo + base) - f(np.array([base]))[0]
    err = np.abs(p_calib - esperado).max()
    check('el maximo conmuta con f: P\' == f(P)', err < 1e-6,
          f'(err max {err:.2e} cuentas sobre {p_crudo.size} pulsos)')

    # Y la integral NO conmuta: ese es el punto. Si el ratio de la integral
    # fuera igual al del pico, la propagacion seria un mapa escalar y toda la
    # funcion sobraria.
    rp, ri = r['pico']['ratio_medio'], r['integral']['ratio_medio']
    check('la integral NO escala como el pico', abs(rp - ri) > 1e-3,
          f'(ratio pico {rp:.4f} vs integral {ri:.4f})')


# =============================================================================
# 6. Datos reales de la campana
# =============================================================================

def test_datos_reales():
    print('\n=== 6. campana medida: mca_gate_esp_v2 ===')
    if not os.path.exists(NPZ_CAMPANA):
        print(f'  SALTEADO: no esta {NPZ_CAMPANA}')
        return
    z = np.load(NPZ_CAMPANA)
    amps = z['amps']

    for modo in ('hist', 'gate'):
        cen = z[f'cen_{modo}']
        cal = mu.axis_calibration(amps, cen)
        nombre = 'histeresis' if modo == 'hist' else 'compuerta '
        print(f'\n  --- {nombre} ---')
        print(f'  G = {cal["gain"]:.1f} canales/Vpp    INL = {cal["inl_pct_fs"]:.3f} % FS')
        print(f'  min dINL/dA = {cal["dinl_min"]:+.1f}   margen = G + min = '
              f'{cal["margen"]:.1f}   ({100*cal["margen"]/cal["gain"]:.1f} % de G)')

        check(f'{nombre}: el eje real es invertible', cal['invertible'],
              f'(margen {cal["margen"]:.1f})')

        # NO se mide "la INL despues de corregir" sobre los mismos puntos con
        # que se construyo la calibracion: eso da 0 POR CONSTRUCCION y no dice
        # nada. La pregunta util es si la calibracion GENERALIZA, y eso se
        # contesta dejando un punto afuera, calibrando con los otros, y viendo
        # cuanto erra al predecirlo.
        err_loo = []
        for i in range(len(amps)):
            m = np.ones(len(amps), dtype=bool)
            m[i] = False
            try:
                c_loo = mu.axis_calibration(amps[m], cen[m])
            except ValueError:
                continue
            pred = mu.apply_calibration(np.array([cen[i]]), c_loo)[0]
            err_loo.append(abs(pred - (c_loo['gain'] * amps[i] + c_loo['offset'])))
        # Los extremos requieren extrapolar y no son comparables: se reportan
        # aparte del interior, que es donde la calibracion de verdad se usa.
        err_int = np.asarray(err_loo[1:-1])
        fs = cal['fs_canales']
        loo_pct = 100.0 * float(err_int.max()) / fs
        print(f'  leave-one-out (interior): err max {err_int.max():.1f} canales '
              f'= {loo_pct:.3f} % FS   contra INL cruda {cal["inl_pct_fs"]:.3f} % FS')
        check(f'{nombre}: la calibracion generaliza (LOO < INL cruda)',
              loo_pct < cal['inl_pct_fs'],
              f'({cal["inl_pct_fs"]:.3f} -> {loo_pct:.3f} % FS)')

        k = mu.inl_residual_vs_knots(cal)
        print('  INL residual vs nodos de la LUT:')
        for n, v in zip(k['n_knots'], k['inl_pct_fs']):
            aviso = '  <-- por debajo de lo que resuelven 12 puntos' if v < loo_pct else ''
            print(f'    {n:4d} nodos -> {v:.4f} % FS{aviso}')
        check(f'{nombre}: mas nodos nunca empeoran',
              bool(np.all(np.diff(k['inl_pct_fs']) <= 1e-12)),
              f'({k["inl_pct_fs"][0]:.4f} -> {k["inl_pct_fs"][-1]:.4f} % FS)')

        # El peine de DNL que introduce la correccion, medido y no supuesto.
        # Espectro plano sintetico sobre el eje medido: si el rebinning no
        # metiera DNL, seguiria plano despues de corregir.
        n = 16384
        plano = np.ones(n, dtype=float) * 1000.0
        r = mu.linearize_spectrum(plano, cal)
        lo = int(max(cen.min(), 1)); hi = int(min(cen.max(), n - 1))
        d = mu.dnl(r['spec'], lo, hi, smooth=256, strict=False)
        print(f'  DNL introducida por el rebinning: {d["dnl_rms_pct"]:.3f} % rms, '
              f'{d["dnl_max_pct"]:.3f} % max')
        check(f'{nombre}: la DNL introducida se mantiene chica',
              d['dnl_rms_pct'] < 5.0, f'({d["dnl_rms_pct"]:.3f} % rms)')


def main():
    test_conservacion()
    test_identidad()
    test_recuperacion()
    test_rechazo()
    test_conmutacion_pico()
    test_datos_reales()
    print('\nRESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
