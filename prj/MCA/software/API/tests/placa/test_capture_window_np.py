#!/usr/bin/env python3
"""El mismo buffer congelado, leído por `rp` y por libmca: tienen que dar lo mismo.

Es la comprobación de la Parte 6 del plan de libmca, que sacó `rp` de la lectura: el
lazo por evento (`BramSource`), `capture_window_np` y `read_buffers` leen la BRAM por
C y calibran con la cuenta de librp (`cmn_CalibCntsSigned`) y los números de la
EEPROM. Congela el buffer con un disparo por software y exige, en las dos aperturas:

  1. el anillo entero: `rint(V·8192)` de `rp_AcqGetDataPosV` == la cuenta de C,
     muestra por muestra;
  2. la ventana del disparo y una que da la vuelta al anillo, igual;
  3. `read_buffers` == `rp_AcqGetOldestDataV`, en float, exacto.

Y muestra, sin aprobar ni reprobar:

  - lo que `rp_Init()` deja escrito (`scope_regs` antes y después): el filtro de
    ecualización, el promediado. Con `EN_FILT = 0` el ecualizador no está en el
    camino, así que esos coeficientes no cambian las formas;
  - el lazo de C con disparos por software: eventos, tasa y `dead_ns` (del disparo
    visto al re-armado), contra los 252.7 µs del lazo de Python.

No necesita el Rigol. Uso (en la Pitaya, con el bitstream multitrigger o MCA cargado):
    python3 API/tests/placa/test_capture_window_np.py      # o make verificar-placa-buffer
"""
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rp                                                          # noqa: E402
from API.osciloscope import Osciloscope, _fb_to_np                 # noqa: E402
from API.osciloscope_store import BramSource, scope_regs           # noqa: E402
from API.osciloscope_store.events import BASE_FIELDS, EventBatch   # noqa: E402
from multitrigger_utils import BIT_SW, MultiTriggerScope           # noqa: E402

PRE, POST = 2000, 2000
N_RP = 16384            # el anillo que supone librp: más allá del real, la apertura aliasea

_pass = _fail = 0


def check(nombre, cond, extra=''):
    global _pass, _fail
    print(f'  [{"PASS" if cond else "FAIL"}] {nombre}{("  " + extra) if extra else ""}')
    if cond:
        _pass += 1
    else:
        _fail += 1


def leer_rp(ch, start, n):
    """n muestras desde start, en volts, por rp_AcqGetDataPosV. Las posiciones son las
    de librp (módulo 16384): con un anillo menor, la apertura repite el mismo."""
    start %= N_RP
    end = (start + n - 1) % N_RP
    fb = rp.fBuffer(n)
    res = rp.rp_AcqGetDataPosV(ch, start, end, fb, n)
    rc = res[0] if isinstance(res, (list, tuple)) else res
    if rc != rp.RP_OK:
        raise RuntimeError(f'rp_AcqGetDataPosV(ch={ch}, {start}, {end}) devolvió {rc}')
    return _fb_to_np(fb, n)


def comparar(nombre, v_rp, cuentas):
    m_rp = np.rint(v_rp.astype(np.float64) * 8192).astype(np.int64)
    distintas = int(np.count_nonzero(m_rp != cuentas))
    peor = int(np.max(np.abs(m_rp - cuentas))) if len(cuentas) else 0
    check(nombre, distintas == 0 and len(cuentas) == len(v_rp),
          f'({len(cuentas)} muestras, {distintas} distintas, máx {peor} cuentas)')


def regs_de_rp_init(sc):
    antes = scope_regs(sc)
    rp.rp_Init()
    despues = scope_regs(sc)
    cambios = {k: (antes[k], despues[k]) for k in antes if antes[k] != despues[k]}
    print('\n--- lo que rp_Init() dejó escrito (informativo) ---')
    if not cambios:
        print('  nada: ya estaba así (otro proceso lo llamó desde que se cargó el bitstream)')
    for k, (a, d) in cambios.items():
        print(f'  {k:16s} {a:#010x} -> {d:#010x}')


def buffer_congelado(sc):
    print('\n--- el mismo buffer, por rp y por C ---')
    cal = [sc.calibracion(ch) for ch in (0, 1)]
    for ch, c in enumerate(cal):
        print(f'  calibración canal {ch}: gain={c["gain"]} base={c["base"]} '
              f'offset={c["offset"]}')
    d1_c, d2_c, _snap = sc.acq_capture_sw(thr=0.5)       # congela, y lee por C
    n = sc.n_buf
    ref = sc.r32(0x1C)
    print(f'  anillo de {n} muestras, wp_trig={ref}')
    for ch in (0, 1):
        cuentas = sc.read_cal(ch, 0, n)
        check(f'canal {ch}: el buffer no está vacío', np.ptp(cuentas) > 0,
              f'(de {cuentas.min()} a {cuentas.max()})')
        comparar(f'canal {ch}: el anillo entero', leer_rp(ch, 0, n), cuentas)

    data, r = sc.capture_window_np(pre=PRE, post=POST)
    check('capture_window_np toma wp_trig', r == ref, f'({r})')
    for ch in (0, 1):
        comparar(f'canal {ch}: la ventana del disparo', leer_rp(ch, ref - PRE, PRE + POST),
                 np.rint(data[ch].astype(np.float64) * 8192).astype(np.int64))
        comparar(f'canal {ch}: una ventana que da la vuelta', leer_rp(ch, n - 100, 400),
                 sc.read_cal(ch, n - 100, 400))

    wp_cur = sc.r32(0x18)
    for ch, d_c in ((0, d1_c), (1, d2_c)):
        fb = rp.fBuffer(n)
        rp.rp_AcqGetOldestDataV((rp.RP_CH_1, rp.RP_CH_2)[ch], n, fb)
        v = _fb_to_np(fb, n)
        # Oldest lee desde wp_cur + 1 en el anillo de 16384: con uno menor, la misma
        # posición módulo n.
        check(f'canal {ch}: read_buffers == rp_AcqGetOldestDataV',
              np.array_equal(d_c, v), f'(wp_cur={wp_cur}, máx '
              f'{float(np.max(np.abs(d_c - v))):.3g} V)')
    sc.disarm()


def lazo_con_disparos_por_software(sc, n_eventos=2000, segundos=3.0):
    print('\n--- el lazo de C, con disparos por software (informativo) ---')
    src = BramSource(sc, pre=8, post=24, n_ch=2, mask=BIT_SW)
    b = EventBatch(n_eventos, 2, src.samples, BASE_FIELDS + (('dead_ns', np.int64),),
                   np.int16)
    gatillo = Osciloscope.open()          # otro handle: el lazo no comparte el suyo
    parar = threading.Event()

    def disparar():
        while not parar.is_set():
            gatillo.w32(0x04, 0x101)
            time.sleep(100e-6)

    src.arm()
    t = threading.Thread(target=disparar, daemon=True)
    t0 = time.perf_counter()
    t.start()
    try:
        while b.n < n_eventos and time.perf_counter() - t0 < segundos:
            k, _, _ = src.read_batch(b, time.perf_counter_ns() + 50_000_000)
            b.n += k
    finally:
        parar.set()
        t.join(1)
        dur = time.perf_counter() - t0
        src.close()
        gatillo.close()
    if b.n < 2:
        print(f'  {b.n} eventos: el disparo por software no se re-arma en este '
              'bitstream; el lazo se mide con el Rigol (run_poisson_loss.py)')
        return
    d = b.dead_ns[:b.n] / 1e3
    print(f'  {b.n} eventos en {dur:.2f} s ({b.n / dur:.0f} ev/s, limitado por el '
          'hilo que dispara)')
    print(f'  dead_ns: mediana {np.median(d):.1f} µs, p99 {np.percentile(d, 99):.1f} µs, '
          f'máx {d.max():.1f} µs   (lazo de Python: 252.7 µs)')


def main():
    sc = MultiTriggerScope.open()
    try:
        if not sc.verify_bitstream(verbose=False)['ok']:
            raise SystemExit('no se lee un scope multitrigger válido: cargar el bitstream')
        regs_de_rp_init(sc)
        buffer_congelado(sc)
        lazo_con_disparos_por_software(sc)
    finally:
        try:
            sc.disarm()
        finally:
            sc.close()
            rp.rp_Release()
    print(f'\nRESULT: {"PASS" if _fail == 0 else "FAIL"} ({_pass} ok, {_fail} fallas)')
    sys.exit(1 if _fail else 0)


if __name__ == '__main__':
    main()
