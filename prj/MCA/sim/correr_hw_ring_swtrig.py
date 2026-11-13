#!/usr/bin/env python3
"""Corre hw_ring_swtrig.py sin placa, contra el RTL de tb_ring_sistema.sv.

El script de placa no se toca. Lo único que cambia es por dónde salen sus accesos:
`_open_mem`, `r32` y `w32` van por dos FIFOs hasta el TB, y `time.sleep` espera
ciclos de simulación. `discover_ddr` devuelve la región que encuentra en la placa.

Después del script, esto revisa lo que él no mira: todos los slots en vez de los
primeros 6, las muestras, los errores de STATUS, que él imprime sin chequear, y que
la cabecera de cada slot diga qué fuente disparó ese evento.

Lo lanza el TB; a mano no tiene sentido. Uso: make -C prj/MCA/sim tb_ring_sistema
"""

import os
import sys
import time

import numpy as np

CICLOS_POR_S = 125_000_000
DDR_BASE, DDR_SIZE = 0x0A00_0000, 32 << 20       # labuf, como en la placa
BITS_ADC = 14


class Simulador:
    """El otro extremo de los FIFOs: un pedido por línea, una respuesta por línea."""

    def __init__(self, cmd, rsp):
        self._tx = open(cmd, "w", buffering=1)   # el mismo orden de apertura que el TB
        self._rx = open(rsp, "r")

    def pedir(self, linea):
        self._tx.write(linea + "\n")
        self._tx.flush()
        return self._rx.readline().strip()


class Region:
    """Lo que `_open_mem` devuelve en la placa, pero contra el simulador."""

    def __init__(self, sim, phys):
        self.sim, self.phys = sim, phys

    def r32(self, off):
        return int(self.sim.pedir(f"R {self.phys + off:08x}"), 16)

    def w32(self, off, val):
        self.sim.pedir(f"W {self.phys + off:08x} {val & 0xFFFFFFFF:08x}")

    def __getitem__(self, s):                    # mem[a:b]: lectura de la DDR
        n = s.stop - s.start
        txt = self.sim.pedir(f"D {self.phys + s.start:08x} {n}")
        palabras = [txt[i:i + 16] for i in range(0, len(txt), 16)]
        return b"".join(int(p, 16).to_bytes(8, "little") for p in palabras)


def verificar_ddr(mem, sw, n, decode_slot):
    """Revisa los slots que quedaron en la DDR. Devuelve la cantidad de problemas.

    Después del script, los slots de 64 en adelante son del escenario A, con 65536
    slots, y los primeros 64 son de B y C, que dan la vuelta a un ring de 64. Con
    pérdida contada puede haber menos eventos, pero nunca un hueco.
    """
    malos = 0

    def mal(msg):
        nonlocal malos
        malos += 1
        if malos <= 10:
            print(f"       FAIL {msg}")

    mod = 1 << BITS_ADC
    fases, leidos, fin_de_a = set(), 0, None
    for i in range(max(n, 64)):
        off = i << sw.SLOT_SHIFT
        buf = mem[off:off + (1 << sw.SLOT_SHIFT)]
        try:
            meta, s = decode_slot(buf, sw.SLOT_SHIFT)
        except ValueError as exc:
            if i >= 64 and "footer" in str(exc):     # A terminó acá
                fin_de_a = i
                continue
            mal(f"slot {i}: {exc}")
            continue
        if fin_de_a is not None:
            mal(f"slot {i} escrito después de un hueco en {fin_de_a}")
        if meta["seq"] % (64 if i < 64 else 65536) != i:
            mal(f"slot {i}: seq {meta['seq']}")
        if meta["n_samp"] != sw.PRE + sw.POST or meta["n_ch"] != 2:
            mal(f"slot {i}: ventana {meta['n_samp']}x{meta['n_ch']}")
            continue
        c0, c1 = s[0].astype(int), s[1].astype(int)
        if np.any((np.diff(c0) - 1) % mod):
            mal(f"slot {i}: la rampa de ch0 salta")
        if np.any(c1 != ~c0):
            mal(f"slot {i}: ch1 no es el complemento de ch0")
        # La rampa y `timestamp` suben 1 por ciclo: su diferencia en la muestra del
        # trigger es la misma en todos los eventos de una corrida.
        fases.add((c0[sw.PRE] - meta["timestamp"]) % mod)
        leidos += 1
    if len(fases) > 2:                               # una por corrida: A, y B con C
        mal(f"la ventana no queda anclada al trigger: fases {sorted(fases)[:6]}")
    print(f"       {leidos} slots leidos, fases rampa-timestamp {sorted(fases)}")
    return malos


def verificar_snapshot(sim, hp, sw, decode_slot):
    """Dos fuentes de hardware que se alternan. Devuelve cuántos slots dicen otra fuente.

    Con el trigger por software hay una sola fuente, así que el script no puede ver
    si el snapshot de la cabecera es el de ese evento. Acá ch0 dispara por flanco
    positivo al cruzar 0 y por negativo cuando la rampa da la vuelta.
    """
    bit_p, bit_n = 1 << 1, 1 << 5                # adc_p[0] y adc_n[0] en el snapshot
    rg, sc = Region(sim, hp.RING_PHYS), Region(sim, sw.SCOPE_PHYS)
    mt, mem = Region(sim, sw.MTRG_PHYS), Region(sim, DDR_BASE)
    sw.ring_setup(rg, DDR_BASE, 64 << sw.SLOT_SHIFT)
    sw.scope_setup(sc, mt)
    hp.w32(mt, sw.M_MASK0, (1 << 1) | (1 << 2))  # BIT_ADC_P0 y BIT_ADC_N0
    sim.pedir("I 90000")                         # la rampa da una vuelta cada 16384
    ev = hp.r32(rg, hp.R_EV_CNT)
    malos = 0
    for i in range(ev):
        off = i << sw.SLOT_SHIFT
        meta, s = decode_slot(mem[off:off + (1 << sw.SLOT_SHIFT)], sw.SLOT_SHIFT)
        hubo_salto = abs(int(s[0][sw.PRE])) >= 4096
        esperado, otro = (bit_n, bit_p) if hubo_salto else (bit_p, bit_n)
        if not meta["snapshot"] & esperado or meta["snapshot"] & otro:
            malos += 1
    hp.w32(rg, hp.R_CTRL, 0)
    sw.scope_off(sc, mt)
    print(f"       snapshot: {ev - malos}/{ev} eventos dicen la fuente que los disparo"
          f" {'OK' if ev and not malos else '<-- MAL'}")
    return malos if ev else 1


def main():
    cmd, rsp, n, tope = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    sim = Simulador(cmd, rsp)                    # antes que nada: el TB espera acá
    rc = 1
    try:
        placa = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "software", "API", "tests", "placa")
        sys.path.insert(0, placa)

        import hw_ring_plumbing as hp
        hp._open_mem = lambda phys, size: Region(sim, phys)
        hp.r32 = lambda m, off: m.r32(off)
        hp.w32 = lambda m, off, val: m.w32(off, val)
        hp.DDR_PHYS, hp.DDR_SIZE = DDR_BASE, DDR_SIZE
        time.sleep = lambda s: sim.pedir(f"I {min(int(s * CICLOS_POR_S), tope)}")

        import hw_ring_swtrig as sw
        from API.modelo_rtl.ring_format import decode_slot

        rc = sw.main(["hw_ring_swtrig.py", str(n)])

        print("\n[extra] lo que el script no mira")
        rg = Region(sim, hp.RING_PHYS)
        st = rg.r32(hp.R_STATUS)
        errores = st & 0xE0                      # fifo_ovf, slot_ovf, err_cfg
        print(f"       STATUS={st:#010x} {'OK' if not errores else '<-- ERROR PEGADO'}")
        rc = rc or int(errores != 0)

        malos = verificar_ddr(Region(sim, DDR_BASE), sw, n, decode_slot)
        print(f"       slots revisados con {malos} problemas")
        rc = rc or int(malos != 0)

        z = [int(x) for x in sim.pedir("Z").split()]
        sw_wr, flancos, ciclos_trig = z[0], z[1], z[2]
        print(f"       escrituras a TRIG_SW={sw_wr}, triggers en la entrada del ring: "
              f"{flancos} flancos en {ciclos_trig} ciclos")
        if flancos != sw_wr:
            print("       FAIL: cada escritura tiene que dar exactamente un trigger")
            rc = rc or 1

        mal_snap = verificar_snapshot(sim, hp, sw, decode_slot)   # corre siempre
        rc = rc or int(mal_snap != 0)
    except Exception:                            # noqa: BLE001
        import traceback
        traceback.print_exc()
        rc = rc or 1
    sim.pedir(f"Q {rc}")


if __name__ == "__main__":
    main()
