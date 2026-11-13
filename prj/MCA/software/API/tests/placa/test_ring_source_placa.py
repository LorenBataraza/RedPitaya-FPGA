#!/usr/bin/env python3
"""`RingSource` en la placa: el lector de C contra el event_ring, con disparos por SW.

Es la prueba de la Parte 7 del plan de libmca, que pasó la lectura del ring a C
(`osciloscope_ring_leer_lote`). `hw_ring_swtrig.py` prueba el ring registro por
registro, desde Python; esto prueba el camino que usa la adquisición: `RingSource`
arma, configura y lee por lote.

Necesita el bitstream con el ring (`make bitstream-event-ring`). No usa el Rigol: cada
disparo es una escritura a TRIG_SW, así que se sabe exactamente cuántos entraron.

  A. N disparos espaciados, leyendo: llegan N eventos, `seq` de 0 a N−1 sin huecos,
     `gap` en cero, `ts_hw` creciente, `snap` con el bit de SW. El hardware cuenta N
     eventos y ningún descarte.
  B. La onda: cada evento de A, calibrado en C, contra el slot crudo de la DDR
     decodificado en Python (`decode_slot`) y calibrado con la cuenta de librp.
  C. Una ráfaga de más disparos que slots, sin leer: el hardware se frena en N_SLOTS
     ocupados, con hasta E = 4 eventos más esperando en el stage, y cuenta el resto.
     EV_CNT + DROP_BUSY + DROP_FULL = disparos, y al leer llegan los EV_CNT.
  D. Después de la ráfaga, retoma: K disparos más llegan todos.

Con la máscara en los dos canales, como la arma `RingSource`: si una escritura a
TRIG_SW diera dos pulsos (uno por canal), A lo muestra como DROP_BUSY = N.

Uso (en la Pitaya):
    python3 API/tests/placa/test_ring_source_placa.py [N]    # o make verificar-placa-ring-c
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

from API._libmca import Mem                                        # noqa: E402
from API.modelo_rtl.ring_format import decode_slot                 # noqa: E402
from API.multitrigger import BIT_SW                                # noqa: E402
from API.osciloscope import osciloscope_sw_trigger                 # noqa: E402
from API.osciloscope_ring import OsciloscopeRing, RingSource       # noqa: E402
from API.osciloscope_store.events import EventBatch                # noqa: E402
from multitrigger_utils import MultiTriggerScope                   # noqa: E402

PRE, POST = 16, 48
ESPERA_S = 0.002          # entre disparos de A: muy por encima de lo que tarda un slot
RAFAGA_EXTRA = 50         # disparos de C por encima de N_SLOTS
SLOT_SHIFT_C = 9          # slots de 512 B en un ring chico, para llenarlo rápido
RING_C = 64 * 512

_pass = _fail = 0


def check(nombre, cond, extra=''):
    global _pass, _fail
    print(f'  [{"PASS" if cond else "FAIL"}] {nombre}{("  " + extra) if extra else ""}')
    if cond:
        _pass += 1
    else:
        _fail += 1
    return cond


def disparar(sc, n, espera_s=ESPERA_S):
    for _ in range(n):
        osciloscope_sw_trigger(sc)
        if espera_s:
            time.sleep(espera_s)


def leer(src, b, plazo_s=0.3):
    """Lee hasta que pasa `plazo_s` sin que llegue nada. Devuelve los descartes."""
    descartes = 0
    while b.n < b.capacity:
        n, d, _ = src.read_batch(b, time.perf_counter_ns() + int(plazo_s * 1e9))
        b.n += n
        descartes += d
        if n == 0:
            break
    return descartes


def calibrar(c, s):
    """`cmn_CalibCntsSigned` de librp, como `osc_calibrar` de libmca: trunca hacia
    cero y recorta a ±8192."""
    m = c['gain'] * (s.astype(np.int64) - c['offset'])
    q = np.sign(m) * (np.abs(m) // c['base'])
    return np.clip(q, -8192, 8192).astype(np.int16)


def fuente(sc, slot_shift=None, ring_bytes=None):
    return RingSource(sc, pre=PRE, post=POST, n_ch=2, thr=0.5, hyst=0.02, mask=BIT_SW,
                      slot_shift=slot_shift, ring_bytes=ring_bytes)


def lote(src, capacidad):
    return EventBatch(capacidad, src.n_ch, src.samples, src.scalar_fields,
                      wave_dtype=src.wave_dtype)


def escenario_a(sc, n):
    print(f'\n[A] {n} disparos espaciados {ESPERA_S * 1e3:g} ms, leyendo')
    src = fuente(sc)
    src.arm()
    try:
        b = lote(src, n + 16)
        disparar(sc, n)
        descartes = leer(src, b)
        hw = src.hw_counters()
        ddr_phys, _ = src.ring.ddr
        slot_sz, n_slots = src.slot_sz, src.n_slots
        calib = src.calib
    finally:
        src.close()

    seq = b.scalars['seq'][:b.n]
    ts = b.scalars['ts_hw'][:b.n]
    snap = b.scalars['snap'][:b.n]
    gap = b.scalars['gap'][:b.n]
    print(f'  hardware: ev={hw["hw_ev_cnt"]} drop_busy={hw["hw_drop_busy"]} '
          f'drop_full={hw["hw_drop_full"]} wr_slot={hw["hw_wr_slot"]} '
          f'status={hw["hw_status"]:#x}; {n_slots} slots de {slot_sz} B')
    check('llegan todos', b.n == n, f'{b.n} de {n}')
    check('el hardware contó los mismos', hw['hw_ev_cnt'] == n, f'EV_CNT={hw["hw_ev_cnt"]}')
    check('sin descartes', hw['hw_drop_busy'] == 0 and hw['hw_drop_full'] == 0
          and descartes == 0 and int(gap.sum()) == 0,
          f'busy={hw["hw_drop_busy"]} full={hw["hw_drop_full"]} gap={int(gap.sum())}')
    check('seq de 0 a N-1, sin huecos', np.array_equal(seq, np.arange(b.n)))
    dts = np.diff(ts.astype(np.int64)) * 8e-9
    check('ts_hw creciente', b.n < 2 or bool((dts > 0).all()),
          f'entre disparos: mediana {np.median(dts) * 1e3:.2f} ms' if b.n > 1 else '')
    check('snap: el bit de SW', b.n > 0 and bool(((snap & BIT_SW) != 0).all()),
          f'snap[0]={int(snap[0]):#x}' if b.n else '')

    print('\n[B] la onda de C contra el slot crudo, decodificado en Python')
    if b.n > n_slots:
        print(f'  (sólo los últimos {n_slots}: el resto ya se pisó)')
    mem = Mem.devmem(ddr_phys, n_slots * slot_sz)
    distintas = revisados = 0
    malos = []
    try:
        for i in range(max(0, b.n - n_slots), b.n):
            s = int(seq[i])
            crudo = mem.read((s % n_slots) * slot_sz, slot_sz)
            meta, muestras = decode_slot(bytes(crudo), src.slot_shift, expect_seq=s)
            if int(meta['timestamp']) != int(ts[i]):
                malos.append(f'seq {s}: ts {meta["timestamp"]} != {int(ts[i])}')
            for k in range(2):
                esperado = calibrar(calib[k], muestras[k])
                distintas += int((esperado != b.wave[i, k]).sum())
            revisados += 1
    finally:
        mem.close()
    check('la cabecera dice lo mismo que las columnas', not malos,
          '; '.join(malos[:3]))
    check('la onda calibrada en C == la del slot crudo', distintas == 0,
          f'{revisados} eventos, {distintas} muestras distintas')
    return hw


def escenario_c_d(sc, k_despues=20):
    src = fuente(sc, slot_shift=SLOT_SHIFT_C, ring_bytes=RING_C)
    src.arm()
    try:
        n_slots = src.n_slots
        n = n_slots + RAFAGA_EXTRA
        print(f'\n[C] ráfaga de {n} disparos sin leer, en {n_slots} slots')
        disparar(sc, n)
        time.sleep(0.05)
        antes = src.hw_counters()
        b = lote(src, n + k_despues + 16)
        descartes = leer(src, b)
        tras_c = b.n
        gap_c = int(b.scalars['gap'][:b.n].sum())
        print(f'  hardware: ev={antes["hw_ev_cnt"]} drop_busy={antes["hw_drop_busy"]} '
              f'drop_full={antes["hw_drop_full"]} ocupados='
              f'{antes["hw_wr_slot"] - antes["hw_rd_slot"]}')
        suma = antes['hw_ev_cnt'] + antes['hw_drop_busy'] + antes['hw_drop_full']
        ocupados = (antes['hw_wr_slot'] - antes['hw_rd_slot']) & 0xFFFFFFFF
        check('los créditos frenan en N_SLOTS', ocupados == n_slots,
              f'{ocupados} ocupados; EV_CNT={antes["hw_ev_cnt"]}, el resto en el stage')
        check('EV + DROP_BUSY + DROP_FULL = disparos', suma == n, f'{suma} de {n}')
        check('se leen los EV_CNT, también los del stage', tras_c == antes['hw_ev_cnt'],
              f'{tras_c}')

        print(f'\n[D] {k_despues} disparos más: ¿retoma?')
        disparar(sc, k_despues)
        descartes += leer(src, b)
        despues = src.hw_counters()
        perdidos = despues['hw_drop_busy'] + despues['hw_drop_full']
        gap = int(b.scalars['gap'][:b.n].sum())
        check('llegan los K', b.n - tras_c == k_despues, f'{b.n - tras_c}')
        check('los gap suman los descartes del hardware', gap == perdidos,
              f'gap={gap} (en C: {gap_c}), hardware={perdidos}, lector={descartes}')
        seq = b.scalars['seq'][:b.n]
        check('seq sin huecos', np.array_equal(seq, np.arange(b.n)))
    finally:
        src.close()


def main(argv):
    n = int(argv[1]) if len(argv) > 1 else 200
    sc = MultiTriggerScope.open()
    try:
        r = OsciloscopeRing.open()
    except Exception as e:
        sc.close()
        print(f'no hay ring: {e}')
        print('cargar el bitstream de make bitstream-event-ring')
        return 2
    r.close()
    try:
        escenario_a(sc, n)
        escenario_c_d(sc)
    finally:
        sc.disarm()
        sc.close()
    print(f'\nRESULT: {"PASS" if _fail == 0 else "FAIL"} ({_pass} ok, {_fail} fallas)')
    return 1 if _fail else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
