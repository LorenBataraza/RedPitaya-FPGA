#!/usr/bin/env python3
"""¿Un registro que cambia mientras se lo lee llega entero al PS?

`rtl/sys_bus_cdc.sv` pasaba el dato leído sin registrar de `adc_clk` a
`clk_fpga_0`, y los esclavos recalculan `sys_rdata` todos los ciclos: un registro
que avanza solo llegaba a veces con bits de antes y de después del cambio. En la
placa (2026-11-08) fue ~1 de cada 1000 lecturas de `wp_cur`, en el bitstream del
MCA y en el del ring; el lector de C del ring se cortaba por un `WR_SLOT` roto. El
arreglo congela el dato en el ack del esclavo (`reg_rdata`): ver
docs/TOP/bus_sistema_redpitaya.md §6.1.

  A. `wp_cur` del osciloscopio (0x4010_0018, 13 bits), con la BRAM escribiendo y
     sin disparar. Se mira de a tres lecturas seguidas: si entre la primera y la
     tercera pasó poco (sin una interrupción del kernel en el medio), la del medio
     tiene que caer entre las dos. Una lectura rota en un acarreo cae afuera.
  B. `TS_LO` del event_ring (0x4020_0040), el timestamp libre de 32 bits, si el
     bitstream tiene el ring: no puede retroceder.
  C. de control, un registro fijo (MAGIC del MCA): tiene que dar siempre lo mismo.

Las lecturas las hace C sin pausa (`Bus.sondear`, ~0.2 µs cada una): desde Python
cada una cuesta ~19 µs, y en ese tiempo `wp_cur` da casi media vuelta. Con el CDC
viejo, A y B fallan de a cientos; con el arreglo, cero. No necesita el Rigol. No
usar con el kernel de Jupyter usando `rp`.

Uso (en la Pitaya, como root):
    python3 API/tests/placa/test_bus_lectura_viva.py [N]   # o make verificar-placa-bus
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API._libmca import Bus                                        # noqa: E402
from API.mca import MAGIC, MCA_PHYS                                # noqa: E402
from multitrigger_utils import BIT_ADC_P0, MultiTriggerScope       # noqa: E402

OSC_PHYS, R_WP_CUR, MASK_WP = 0x4010_0000, 0x018, 0x1FFF
RING_PHYS, R_TS_LO = 0x4020_0000, 0x40
HUECO_MAX = 1024            # muestras entre la 1.ª y la 3.ª lectura para juzgar la terna

_pass = _fail = 0


def check(nombre, cond, extra=''):
    global _pass, _fail
    print(f'  [{"PASS" if cond else "FAIL"}] {nombre}{("  " + extra) if extra else ""}')
    if cond:
        _pass += 1
    else:
        _fail += 1
    return cond


def ternas_wp(v):
    """(juzgadas, rotas, ejemplos) sobre las lecturas seguidas de wp_cur.

    Una lectura está rota si cae fuera de lo que leyeron sus vecinas inmediatas Y
    de lo que leyeron las de dos lugares más allá: con una sola terna, una lectura
    buena al lado de una rota también quedaría afuera, y cada rota contaría dos
    veces."""
    v = np.asarray(v, dtype=np.int64)
    a2, a1, b, c1, c2 = v[:-4], v[1:-3], v[2:-2], v[3:-1], v[4:]

    def afuera(a, c):
        return ((b - a) & MASK_WP) > ((c - a) & MASK_WP)

    juzgar = ((c2 - a2) & MASK_WP) <= HUECO_MAX   # si no, hubo un hueco
    rota = juzgar & afuera(a1, c1) & afuera(a2, c2)
    ejemplos = [f'{a1[i]:#06x} {b[i]:#06x} {c1[i]:#06x}'
                for i in np.flatnonzero(rota)[:4]]
    return int(juzgar.sum()), int(rota.sum()), ejemplos


def ts_hacia_atras(v):
    """(retrocesos, ejemplos) de un contador libre de 32 bits leído sin pausa."""
    v = np.asarray(v, dtype=np.uint32)
    d = (v[1:] - v[:-1]).view(np.int32)
    atras = np.flatnonzero(d < 0)
    ejemplos = [f'{v[i]:#010x} -> {v[i + 1]:#010x}' for i in atras[:4]]
    return int(atras.size), ejemplos


def main(argv):
    n = int(argv[1]) if len(argv) > 1 else 2_000_000
    sc = MultiTriggerScope.open()
    osc = Bus.devmem(OSC_PHYS, 0x1000)
    mca = Bus.devmem(MCA_PHYS, 0x1000)
    try:
        print(f'\n[A] wp_cur del osciloscopio, {n} lecturas, con la BRAM escribiendo')
        # Umbral fuera de rango: la BRAM escribe en círculo y no dispara nunca.
        sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0, thr=0.9,
                               hyst=0.02, delay=1, we_keep_both=True, auto_rearm=True)
        time.sleep(0.05)
        v0 = osc.r32(R_WP_CUR)
        time.sleep(0.001)
        moviendo = check('wp_cur avanza', osc.r32(R_WP_CUR) != v0)
        if moviendo:
            t0 = time.perf_counter()
            v = osc.sondear(R_WP_CUR, n)
            dt = time.perf_counter() - t0
            juzgadas, rotas, ej = ternas_wp(v)
            check('las ternas que se pueden juzgar son la mayoría', juzgadas > n // 2,
                  f'{juzgadas} de {n - 4}; {dt / n * 1e6:.2f} µs por lectura')
            check('ninguna lectura rota de wp_cur', rotas == 0,
                  f'{rotas} en {juzgadas}' + (f'; ej. {", ".join(ej)}' if ej else ''))
        sc.disarm()

        try:
            from API.osciloscope_ring import RingSource
            src = RingSource(sc, pre=8, post=24, n_ch=2, thr=0.9, hyst=0.02,
                             mask=BIT_ADC_P0)
            src.arm()                   # corre: TS_LO cuenta; sin señal no dispara
        except Exception as e:
            print(f'\n[B] sin ring ({e}): se saltea')
            src = None
        if src is not None:
            print(f'\n[B] TS_LO del event_ring, {n} lecturas')
            ring = Bus.devmem(RING_PHYS, 0x1000)
            try:
                atras, ej = ts_hacia_atras(ring.sondear(R_TS_LO, n))
                check('TS_LO no retrocede nunca', atras == 0,
                      f'{atras} en {n} lecturas' + (f'; ej. {", ".join(ej)}' if ej else ''))
            finally:
                ring.close()
                src.close()

        print(f'\n[C] control: MAGIC del MCA, {n} lecturas')
        malas = int((mca.sondear(0, n) != MAGIC).sum())
        check('un registro fijo da siempre lo mismo', malas == 0, f'{malas} malas')
    finally:
        sc.disarm()
        sc.close()
        osc.close()
        mca.close()
    print(f'\nRESULT: {"PASS" if _fail == 0 else "FAIL"} ({_pass} ok, {_fail} fallas)')
    return 1 if _fail else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
