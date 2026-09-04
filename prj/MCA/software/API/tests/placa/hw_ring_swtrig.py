#!/usr/bin/env python3
"""Fase 0 — el ring punta a punta con trigger por SOFTWARE. Corre en la placa.

POR QUE TRIGGER POR SOFTWARE. El invariante que justifica toda la arquitectura

    EV_CNT + DROP_BUSY + DROP_FULL == triggers inyectados

sólo se puede verificar si se conoce EXACTAMENTE cuántos triggers entraron. Con
el Rigol hay que inferirlo de la frecuencia y el tiempo, que arrastra error. El
`adc_trig_sw` (0x04 del slot 1) da un trigger por escritura, contado sin
ambigüedad — así que el invariante se verifica de forma exacta y sin depender de
ningún generador externo.

Escenarios:
  A. N triggers espaciados, con el PS drenando -> cero pérdida, datos decodifican
  B. N triggers > N_SLOTS SIN drenar -> los créditos frenan, la pérdida QUEDA
     CONTADA (hoy esa pérdida es invisible: docs/arquitectura_adquisicion_software.md)
  C. al devolver créditos, el ring retoma solo

Uso:  python3 hw_ring_swtrig.py [n_triggers]
"""

import mmap
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # hermano hw_ring_plumbing

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from hw_ring_plumbing import (  # noqa: E402
    MAGIC, R_CTRL, R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_LVL, R_N_SLOTS,
    R_POST, R_PRE, R_RD_SLOT, R_RING_SZ, R_SEQ, R_SLOT_BASE, R_SLOT_SHIFT,
    R_STATUS, R_WR_SLOT, RING_PHYS, RING_SIZE, _open_mem, discover_ddr, r32, w32,
)
from API.modelo_rtl.ring_format import (                             # noqa: E402
    credits_used, decode_slot, ring_slot_offset)

# --- slot 1: scope multitrigger ---
SCOPE_PHYS = 0x4010_0000
SCOPE_SIZE = 0x1000
S_CTRL, S_TRIG_SW, S_TRIG_DIS_CLR = 0x00, 0x04, 0x94
S_THR0, S_THR1, S_DLY0, S_DLY1 = 0x08, 0x0C, 0x10, 0x110
S_HYST0, S_HYST1, S_SHIELD = 0x20, 0x24, 0x210
S_MASK0, S_MASK1 = 0x240, 0x244
BIT_SW = 1 << 0

SLOT_SHIFT = 9
PRE, POST = 8, 24


def scope_setup(sc):
    """Deja el scope emitiendo trigger_event con cada escritura a 0x04.

    we_keep=1 para que la máscara NO se auto-limpie en single-shot, y el
    trigger_shield con dur=0 para el clear inmediato de adc_trg_dis. Sin esas
    dos cosas el primer trigger deja el bloque trabado y no vuelve a disparar.
    """
    w32(sc, S_CTRL, 0x0000_0202)         # reset FSM
    w32(sc, S_TRIG_DIS_CLR, 0x0000_0101)  # destrabar adc_trg_dis
    w32(sc, S_THR0, 0); w32(sc, S_THR1, 0)
    w32(sc, S_HYST0, 80); w32(sc, S_HYST1, 80)
    w32(sc, S_DLY0, 1);  w32(sc, S_DLY1, 1)   # set_dly nunca puede ser 0
    w32(sc, S_SHIELD, (0 << 16) | (0x3 << 8) | 0x3)   # auto-rearm inmediato
    w32(sc, S_CTRL, 0x0909)              # arm + we_keep, ch0+ch1
    # SOLO ch0 en la máscara. trigger_event es el OR de los adc_trig de TODOS
    # los canales (multitrigger_event_logic.v:123-127), asi que con los dos
    # canales enmascarados una sola escritura a 0x04 produce DOS pulsos de
    # trigger (llegan con un ciclo de diferencia). Eso rompe la cuenta exacta de
    # triggers inyectados, que es justamente lo que este test necesita.
    w32(sc, S_MASK0, BIT_SW)             # máscara DESPUÉS del arm
    w32(sc, S_MASK1, 0)


def scope_off(sc):
    w32(sc, S_CTRL, 0)
    w32(sc, S_SHIELD, 0)
    w32(sc, S_TRIG_DIS_CLR, 0x0000_0101)
    w32(sc, S_CTRL, 0x0000_0202)


def ring_setup(rg, base, size, slot_shift=SLOT_SHIFT):
    w32(rg, R_CTRL, 0)
    w32(rg, R_CTRL, 0x2)                 # clr: contadores y sticky
    w32(rg, R_SLOT_BASE, base)
    w32(rg, R_RING_SZ, size)
    w32(rg, R_SLOT_SHIFT, slot_shift)
    w32(rg, R_PRE, PRE)
    w32(rg, R_POST, POST)
    w32(rg, R_CTRL, 0x1)                 # run


def fire(sc, n, gap_s=0.0):
    for _ in range(n):
        w32(sc, S_TRIG_SW, 0x1)
        if gap_s:
            time.sleep(gap_s)


def counters(rg):
    return dict(ev=r32(rg, R_EV_CNT), db=r32(rg, R_DROP_BUSY),
                df=r32(rg, R_DROP_FULL), wr=r32(rg, R_WR_SLOT),
                rd=r32(rg, R_RD_SLOT), seq=r32(rg, R_SEQ),
                st=r32(rg, R_STATUS))


def show(tag, c, n_trig):
    tot = c["ev"] + c["db"] + c["df"]
    print(f"  {tag}: ev={c['ev']} drop_busy={c['db']} drop_full={c['df']} "
          f"| suma={tot} vs triggers={n_trig} "
          f"{'OK' if tot == n_trig else '<-- NO CIERRA'}")
    print(f"       wr_slot={c['wr']} rd_slot={c['rd']} ocupados="
          f"{credits_used(c['wr'], c['rd'])} status={c['st']:#010x}")
    return tot == n_trig


def main(argv):
    n = int(argv[1]) if len(argv) > 1 else 200
    base, size = discover_ddr()
    rg = _open_mem(RING_PHYS, RING_SIZE)
    if r32(rg, 0x50) != MAGIC:
        print("el bitstream cargado no tiene el event_ring")
        return 2
    sc = _open_mem(SCOPE_PHYS, SCOPE_SIZE)
    mem = _open_mem(base, size)
    ok = True

    print(f"region DDR {base:#010x} {size/2**20:.0f} MB  slot={1<<SLOT_SHIFT} B  "
          f"ventana pre={PRE} post={POST}")

    # ---------------------------------------------------------------- A
    print(f"\n[A] {n} triggers espaciados, el PS drena")
    ring_setup(rg, base, size)
    scope_setup(sc)
    n_slots = r32(rg, R_N_SLOTS)
    for i in range(n):
        w32(sc, S_TRIG_SW, 0x1)
        if i % 32 == 31:                       # el PS publica por batch
            w32(rg, R_RD_SLOT, r32(rg, R_WR_SLOT))
    time.sleep(0.2)
    w32(rg, R_RD_SLOT, r32(rg, R_WR_SLOT))
    c = counters(rg)
    ok &= show("A", c, n)

    # decodificar los primeros slots
    nread = min(c["wr"], 6)
    slot_sz = 1 << SLOT_SHIFT
    bad = 0
    for i in range(nread):
        off = ring_slot_offset(i, n_slots, SLOT_SHIFT)
        try:
            meta, s = decode_slot(mem[off:off + slot_sz], SLOT_SHIFT, expect_seq=i)
            if i < 3:
                print(f"       slot {i}: seq={meta['seq']} ts={meta['timestamp']} "
                      f"snap={meta['snapshot']:#x} n={meta['n_samp']}x{meta['n_ch']} "
                      f"rango=[{s.min()},{s.max()}]")
        except Exception as exc:                # noqa: BLE001
            print(f"       slot {i}: ERROR {exc}")
            bad += 1
    print(f"       {nread - bad}/{nread} slots decodifican con seq correcto")
    ok &= (bad == 0)

    # ---------------------------------------------------------------- B
    # Ring CHICO a proposito: con los 65536 slots de 32 MB haria falta una
    # rafaga enorme para llegar a agotar creditos, y el punto del test es
    # justamente ver el freno. 64 slots se llenan en 64 triggers.
    small = 64 * (1 << SLOT_SHIFT)
    ring_setup(rg, base, small)
    scope_setup(sc)
    n_small = r32(rg, R_N_SLOTS)
    n_b = n_small + 50
    print(f"\n[B] ráfaga SIN drenar: {n_b} triggers, {n_small} créditos "
          f"(ring reducido a {small//1024} KB)")
    fire(sc, n_b)
    time.sleep(0.5)
    c = counters(rg)
    ok &= show("B", c, n_b)
    occupied = credits_used(c["wr"], c["rd"])
    print(f"       créditos frenaron: ocupados={occupied} <= N_SLOTS={n_small} "
          f"{'OK' if occupied <= n_small else '<-- SE PASO'}")
    ok &= occupied <= n_small
    print(f"       pérdida contada: {c['df']} (hoy seria INVISIBLE)")
    if c["df"] == 0 and c["db"] == 0:
        print("       AVISO: no hubo pérdida; el ring absorbió todo "
              "(subir la ráfaga para probar el freno)")

    # ---------------------------------------------------------------- C
    print("\n[C] devolver créditos: ¿retoma solo?")
    w32(rg, R_RD_SLOT, r32(rg, R_WR_SLOT))
    time.sleep(0.3)
    before = r32(rg, R_WR_SLOT)
    w32(rg, R_RD_SLOT, before)
    time.sleep(0.1)
    fire(sc, 10)
    time.sleep(0.2)
    after = r32(rg, R_WR_SLOT)
    print(f"       wr_slot {before} -> {after} (esperado +10)")
    ok &= (after - before) == 10

    w32(rg, R_CTRL, 0)
    scope_off(sc)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
