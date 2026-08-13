#!/usr/bin/env python3
"""Fase 0 — validación de plumbing PL -> DDR. SE CORRE EN LA RED PITAYA.

Valida lo caro (device tree, mapeo, coherencia de cache, throughput real) antes
de confiar en nada. Cada paso es independiente y se puede correr solo:

    python3 hw_ring_plumbing.py dt        # ¿existe la región reservada?
    python3 hw_ring_plumbing.py regs      # ¿responde el event_ring del slot 2?
    python3 hw_ring_plumbing.py bw        # throughput de lectura DDR vs BRAM
    python3 hw_ring_plumbing.py capture   # una corrida corta y decodificar slots
    python3 hw_ring_plumbing.py all

REGION RESERVADA. El PL escribe por HP2 sin pasar por la MMU ni por la cache, así
que Linux no puede estar usando esa memoria. Hay que reservarla en el device
tree, p.ej.:

    reserved-memory {
        #address-cells = <1>; #size-cells = <1>; ranges;
        event_ring: buffer@1e000000 {
            no-map;
            reg = <0x1e000000 0x02000000>;   /* 32 MB */
        };
    };

COHERENCIA DE CACHE. Los puertos HP NO son coherentes con L1/L2. Este script
mapea con O_SYNC (no cacheable), que es lo simple y correcto; es más lento que
cacheable-con-invalidación pero sigue siendo muchísimo más rápido que leer la
BRAM por GP0. El paso `bw` mide exactamente esa diferencia, que es el número que
justifica toda la Fase 1.
"""

import mmap
import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ring_format import credits_used, decode_slot, ring_slot_offset  # noqa: E402

# --- mapa de registros del event_ring (slot 2) -----------------------------
RING_PHYS = 0x4020_0000
RING_SIZE = 0x1000

R_CTRL, R_STATUS = 0x00, 0x04
R_SLOT_BASE, R_RING_SZ, R_SLOT_SHIFT = 0x08, 0x0C, 0x10
R_PRE, R_POST = 0x14, 0x18
R_WR_SLOT, R_RD_SLOT, R_SEQ, R_N_SLOTS = 0x20, 0x24, 0x28, 0x2C
R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_LVL = 0x30, 0x34, 0x38, 0x3C
R_TS_LO, R_TS_HI, R_AXI_ADDR, R_MAGIC = 0x40, 0x44, 0x48, 0x50

MAGIC = 0x45564E54  # "EVNT"

# --- región de DDR reservada (ajustar al device tree real) -----------------
DDR_PHYS = 0x1E00_0000
DDR_SIZE = 0x0200_0000      # 32 MB

# Baseline del camino viejo, medido: ~45.6 us por canal por llamada a
# rp_AcqGetDataPosV sobre BRAM (docs/arquitectura_adquisicion_software.md).
BRAM_BASELINE_US_PER_CALL = 45.6

_U32 = struct.Struct("<I")


class NotOnPitaya(RuntimeError):
    pass


def _open_mem(phys, size):
    if not os.path.exists("/dev/mem"):
        raise NotOnPitaya(
            "no hay /dev/mem: este script se corre EN la Red Pitaya, no en la PC")
    try:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    except PermissionError as exc:
        raise NotOnPitaya(
            "/dev/mem sin permiso: correr como root EN la Red Pitaya "
            "(en la PC de escritorio este script no aplica)") from exc
    try:
        return mmap.mmap(fd, size, mmap.MAP_SHARED,
                         mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)
    finally:
        os.close(fd)


def r32(m, off):
    return _U32.unpack_from(m, off)[0]


def w32(m, off, val):
    # Asignación por slice, NUNCA struct.pack_into: pack_into hace un memset
    # previo que sale como stores de a byte -> external abort -> SIGBUS.
    # (multitrigger_utils.py:393-403 documenta el mismo cuidado.)
    m[off:off + 4] = _U32.pack(val & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
def step_dt():
    """¿Está la región reservada y Linux la está respetando?"""
    print("== device tree / reserved-memory ==")
    ok = True

    dt = "/sys/firmware/devicetree/base/reserved-memory"
    if os.path.isdir(dt):
        print(f"  reserved-memory presente: {sorted(os.listdir(dt))}")
    else:
        print("  AVISO: no hay nodo reserved-memory en el device tree")
        ok = False

    # /proc/iomem: la región NO debería aparecer como 'System RAM' usable
    try:
        with open("/proc/iomem") as fh:
            iomem = fh.read()
        hit = [ln for ln in iomem.splitlines()
               if f"{DDR_PHYS:08x}" in ln.lower()]
        print(f"  /proc/iomem en {DDR_PHYS:#x}: {hit or 'sin entrada explicita'}")
    except PermissionError:
        print("  /proc/iomem requiere root")

    total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    print(f"  RAM visible por Linux: {total/2**20:.0f} MB "
          f"(si reservaste {DDR_SIZE/2**20:.0f} MB, deberia ser ~"
          f"{512 - DDR_SIZE/2**20:.0f} MB de 512)")
    return ok


def step_regs():
    """¿Responde el event_ring y la geometría se congela con la adquisición parada?"""
    print("== registros del event_ring (slot 2) ==")
    m = _open_mem(RING_PHYS, RING_SIZE)

    magic = r32(m, R_MAGIC)
    print(f"  MAGIC = {magic:#010x} ({'OK' if magic == MAGIC else 'MAL'})")
    if magic != MAGIC:
        print("  -> el bitstream cargado no tiene el event_ring en el slot 2")
        return False

    w32(m, R_CTRL, 0)                       # parar
    w32(m, R_CTRL, 0x2)                     # clr
    w32(m, R_SLOT_BASE, DDR_PHYS)
    w32(m, R_RING_SZ, DDR_SIZE)
    w32(m, R_SLOT_SHIFT, 9)
    w32(m, R_PRE, 8)
    w32(m, R_POST, 24)

    n_slots = r32(m, R_N_SLOTS)
    print(f"  slot_base={r32(m, R_SLOT_BASE):#x} ring_sz={r32(m, R_RING_SZ):#x} "
          f"slot_shift={r32(m, R_SLOT_SHIFT)} -> N_SLOTS={n_slots}")
    ok = n_slots == DDR_SIZE // 512
    if not ok:
        print(f"  MAL: N_SLOTS deberia ser {DDR_SIZE // 512}")

    # La geometría tiene que rebotar con la adquisición corriendo
    w32(m, R_CTRL, 0x1)
    time.sleep(0.01)
    w32(m, R_SLOT_SHIFT, 12)
    got = r32(m, R_SLOT_SHIFT)
    st = r32(m, R_STATUS)
    print(f"  slot_shift tras intentar cambiarlo corriendo: {got} "
          f"(esperado 9), err_cfg={bool(st & (1 << 5))}")
    ok &= (got == 9) and bool(st & (1 << 5))
    w32(m, R_CTRL, 0)
    return ok


def step_bw():
    """El número que justifica la Fase 1: cuánto más rápido es leer DDR que BRAM."""
    print("== throughput de lectura ==")
    m = _open_mem(DDR_PHYS, min(DDR_SIZE, 4 << 20))
    size = min(DDR_SIZE, 4 << 20)

    for nbytes in (512, 4096, 64 * 1024, 1 << 20):
        reps = max(4, min(2000, (8 << 20) // nbytes))
        t0 = time.perf_counter()
        for i in range(reps):
            off = (i * nbytes) % (size - nbytes)
            _ = np.frombuffer(m, dtype=np.int16, count=nbytes // 2,
                              offset=off).copy()
        dt = (time.perf_counter() - t0) / reps
        print(f"  {nbytes:>8} B: {dt*1e6:8.2f} us  ->  {nbytes/dt/1e6:7.1f} MB/s")

    print(f"\n  Referencia del camino viejo (BRAM por GP0): "
          f"{BRAM_BASELINE_US_PER_CALL:.1f} us por llamada y canal,")
    print("  con ~35 us de overhead fijo. Un slot de 512 B leido de DDR deberia")
    print("  costar bastante menos de 45 us; si no, revisar el mapeo de cache.")
    return True


def step_capture(seconds=2.0):
    """Corrida corta: arrancar, dejar que dispare, decodificar los slots."""
    print("== captura y decodificacion ==")
    reg = _open_mem(RING_PHYS, RING_SIZE)
    if r32(reg, R_MAGIC) != MAGIC:
        print("  bitstream sin event_ring")
        return False

    slot_shift = r32(reg, R_SLOT_SHIFT)
    n_slots = r32(reg, R_N_SLOTS)
    mem = _open_mem(DDR_PHYS, DDR_SIZE)

    w32(reg, R_CTRL, 0x3)      # run + clr
    w32(reg, R_CTRL, 0x1)
    t0 = time.perf_counter()
    time.sleep(seconds)

    wr = r32(reg, R_WR_SLOT)
    rd = r32(reg, R_RD_SLOT)
    ev = r32(reg, R_EV_CNT)
    db = r32(reg, R_DROP_BUSY)
    df = r32(reg, R_DROP_FULL)
    st = r32(reg, R_STATUS)
    w32(reg, R_CTRL, 0)
    dt = time.perf_counter() - t0

    print(f"  {dt:.2f} s: capturados={ev} drop_busy={db} drop_full={df}")
    print(f"  wr_slot={wr} rd_slot={rd} ocupados={credits_used(wr, rd)}/{n_slots}")
    print(f"  tasa capturada = {ev/dt:.0f} ev/s")
    print(f"  STATUS={st:#010x}  no_credit={bool(st & (1<<4))} "
          f"err_cfg={bool(st & (1<<5))} err_slot_ovf={bool(st & (1<<6))} "
          f"fifo_ovf={bool(st & (1<<7))}")

    # EL INVARIANTE: con el ring, la perdida deja de ser invisible.
    print(f"  invariante  capturados+drop_busy+drop_full = {ev+db+df}"
          "  (comparar contra los triggers inyectados por el generador)")

    ok = True
    n_read = min(wr, 8)
    for i in range(n_read):
        off = ring_slot_offset(i, n_slots, slot_shift)
        try:
            meta, samples = decode_slot(
                mem[off:off + (1 << slot_shift)], slot_shift, expect_seq=i)
            print(f"    slot {i}: seq={meta['seq']} ts={meta['timestamp']} "
                  f"snap={meta['snapshot']:#x} ventana={samples.shape} "
                  f"pico={samples.max()}")
        except Exception as exc:                     # noqa: BLE001
            print(f"    slot {i}: ERROR {exc}")
            ok = False
    if wr == 0:
        print("    (no disparo nada: revisar umbral y OR-mask del scope)")
    return ok


STEPS = {"dt": step_dt, "regs": step_regs, "bw": step_bw, "capture": step_capture}


def main(argv):
    which = argv[1] if len(argv) > 1 else "all"
    names = list(STEPS) if which == "all" else [which]
    if any(n not in STEPS for n in names):
        print(f"uso: {argv[0]} [{'|'.join(STEPS)}|all]")
        return 2
    rc = 0
    for n in names:
        try:
            if not STEPS[n]():
                rc = 1
        except NotOnPitaya as exc:
            print(f"  {exc}")
            return 3
        print()
    print("RESULT:", "PASS" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
