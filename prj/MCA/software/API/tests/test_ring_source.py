"""Tests offline de RingSource. NO necesitan la Red Pitaya.

Se le da un espacio de registros y una DDR falsos (bytearrays), así se puede
ejercitar la lógica que de otro modo sólo se vería en placa:

  - el prefetch en LOTE (que es lo que hace que el ring rinda: leer slot por slot
    cuesta 27 µs contra 2.3 µs en lotes de 64 KB, medido en la placa)
  - la validación de footer, que es lo que impide entregar un slot a medio
    escribir cuando WR_SLOT ya avanzó
  - el corte del lote en el borde del ring
  - la conversión a volts, para que el resto del pipeline no note el cambio

Correr:  python3 -m pytest test_ring_source.py -v
"""

import os
import struct
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

# Acá había un stub de `multitrigger_utils` en sys.modules, porque ese módulo
# hacía `import rp` (la librería de RedPitaya, que sólo existe en la placa) y
# eso lo volvía inimportable en la PC. Ya no hace falta: RingSource toma
# BIT_ADC_P0 de `API.multitrigger`, que no importa `rp` en absoluto.
#
# Y además el stub hacía daño: se quedaba en sys.modules para el resto del
# proceso, así que cualquier otro test del mismo `pytest` veía ese módulo falso
# en vez del real. Con `pytest API/tests/placa/ API/tests/test_compat_api.py` eso daba
# cuatro fallos fantasma.

from mca.ring_source import (  # noqa: E402
    ADC_CNT_PER_V, HDR_BYTES, MAGIC, R_CTRL, R_MAGIC, R_N_SLOTS, R_PRE,
    R_POST, R_RD_SLOT, R_RING_SZ, R_SLOT_BASE, R_SLOT_SHIFT, R_WR_SLOT,
    RingSource,
)

SLOT_SHIFT = 9
SLOT_SZ = 1 << SLOT_SHIFT
N_SLOTS = 16
DDR_SIZE = N_SLOTS * SLOT_SZ
DDR_PHYS = 0x0A00_0000
PRE, POST, N_CH = 8, 24, 2
NS = PRE + POST


class FakeRegs(bytearray):
    """Espacio de registros que deriva N_SLOTS igual que el RTL."""

    def __setitem__(self, key, val):
        super().__setitem__(key, val)
        if isinstance(key, slice) and key.start in (R_RING_SZ, R_SLOT_SHIFT):
            rs = struct.unpack_from("<I", self, R_RING_SZ)[0]
            sh = struct.unpack_from("<I", self, R_SLOT_SHIFT)[0]
            if sh:
                struct.pack_into("<I", self, R_N_SLOTS, rs >> sh)


class FakeScope:
    def arm_for_adc_trigger(self, **kw):
        self.armed = kw

    def disarm(self):
        self.armed = None


def make_src():
    regs = FakeRegs(0x1000)
    struct.pack_into("<I", regs, R_MAGIC, MAGIC)
    ddr = bytearray(DDR_SIZE)
    src = RingSource(FakeScope(), regs, ddr, DDR_PHYS, DDR_SIZE,
                     pre=PRE, post=POST, n_ch=N_CH, slot_shift=SLOT_SHIFT)
    src.arm()
    return src, regs, ddr


def write_slot(ddr, seq, *, good_footer=True, base_val=0):
    """Escribe el slot que le toca a `seq` tal como lo haría el RTL."""
    off = (seq % N_SLOTS) * SLOT_SZ
    struct.pack_into("<Q", ddr, off, 1000 + seq)                    # timestamp
    struct.pack_into("<Q", ddr, off + 8,
                     (seq & 0xFFFFFFFF) | (NS << 32) | (N_CH << 48))
    struct.pack_into("<Q", ddr, off + 16, 0x5)                      # snapshot
    inter = np.empty(NS * N_CH, dtype="<i2")
    inter[0::2] = np.arange(NS) + base_val          # ch0
    inter[1::2] = -(np.arange(NS) + base_val)       # ch1
    ddr[off + HDR_BYTES:off + HDR_BYTES + inter.nbytes] = inter.tobytes()
    foot_seq = seq if good_footer else (seq + 12345)
    struct.pack_into("<Q", ddr, off + SLOT_SZ - 8,
                     (foot_seq & 0xFFFFFFFF) | ((~foot_seq & 0xFFFFFFFF) << 32))


def set_wr(regs, n):
    struct.pack_into("<I", regs, R_WR_SLOT, n)


class Batch:
    def __init__(self, cap=64):
        self.wave = np.zeros((cap, N_CH, NS), dtype=np.float32)


# ---------------------------------------------------------------------------
def test_geometria_y_arm():
    src, regs, _ = make_src()
    assert src.n_slots == N_SLOTS
    assert struct.unpack_from("<I", regs, R_SLOT_BASE)[0] == DDR_PHYS
    assert struct.unpack_from("<I", regs, R_PRE)[0] == PRE
    assert struct.unpack_from("<I", regs, R_POST)[0] == POST
    assert struct.unpack_from("<I", regs, R_CTRL)[0] == 0x1   # corriendo


def test_slot_que_no_entra_es_rechazado():
    regs = FakeRegs(0x1000)
    struct.pack_into("<I", regs, R_MAGIC, MAGIC)
    with pytest.raises(ValueError, match="hacen"):
        RingSource(FakeScope(), regs, bytearray(DDR_SIZE), DDR_PHYS, DDR_SIZE,
                   pre=200, post=200, n_ch=2, slot_shift=SLOT_SHIFT)


def test_sin_eventos_devuelve_none():
    src, _, _ = make_src()
    assert src.wait_event(0) is None


def test_lectura_y_conversion_a_volts():
    src, regs, ddr = make_src()
    write_slot(ddr, 0, base_val=100)
    set_wr(regs, 1)
    b = Batch()

    seq = src.wait_event(10**18)
    assert seq == 0
    src.read_into(b, 0, seq)

    esperado_ch0 = (np.arange(NS) + 100) / ADC_CNT_PER_V
    np.testing.assert_allclose(b.wave[0][0], esperado_ch0, rtol=1e-6)
    np.testing.assert_allclose(b.wave[0][1], -esperado_ch0, rtol=1e-6)
    # el snapshot sale de la cabecera, sin leer ningún registro
    assert src.snapshot() == 0x5


def test_prefetch_es_en_LOTE():
    """Un solo prefetch tiene que traer todos los slots disponibles.

    Es la propiedad que da el 20x: si `wait_event` volviera a leer memoria por
    cada evento, el costo por evento sería el de la lectura suelta (27 µs) en
    vez del amortizado (2.3 µs).
    """
    src, regs, ddr = make_src()
    for s in range(8):
        write_slot(ddr, s, base_val=s * 10)
    set_wr(regs, 8)

    b = Batch()
    lecturas = []
    orig = src._prefetch

    def contar():
        lecturas.append(1)
        return orig()

    src._prefetch = contar
    for k in range(8):
        seq = src.wait_event(10**18)
        assert seq == k
        src.read_into(b, k, seq)

    assert len(lecturas) == 1, f"hubo {len(lecturas)} lecturas, esperaba 1"
    for k in range(8):
        np.testing.assert_allclose(
            b.wave[k][0], (np.arange(NS) + k * 10) / ADC_CNT_PER_V, rtol=1e-6)


def test_footer_invalido_no_entrega_el_evento():
    """WR_SLOT puede ir adelante del dato: el footer es la única confirmación."""
    src, regs, ddr = make_src()
    write_slot(ddr, 0, good_footer=False)
    set_wr(regs, 1)                      # el registro dice que está listo...
    assert src.wait_event(0) is None     # ...pero el footer dice que no

    write_slot(ddr, 0, good_footer=True)  # ahora sí aterrizó
    assert src.wait_event(10**18) == 0


def test_slot_virgen_no_se_entrega():
    src, regs, _ = make_src()
    set_wr(regs, 3)                      # DDR en ceros: footer 0/0, no complementario
    assert src.wait_event(0) is None


def test_corte_en_el_borde_del_ring():
    """El lote no cruza el final del ring: se corta y sigue en la vuelta."""
    src, regs, ddr = make_src()
    src._next = N_SLOTS - 2              # arrancar cerca del borde
    src._published = src._next
    for s in range(N_SLOTS - 2, N_SLOTS + 3):
        write_slot(ddr, s, base_val=s)
    set_wr(regs, N_SLOTS + 3)

    b = Batch()
    for k, s in enumerate(range(N_SLOTS - 2, N_SLOTS + 3)):
        seq = src.wait_event(10**18)
        assert seq == s
        src.read_into(b, k, seq)
        np.testing.assert_allclose(
            b.wave[k][0], (np.arange(NS) + s) / ADC_CNT_PER_V, rtol=1e-6)


def test_rd_slot_se_publica_por_lote():
    """Publicar por evento devolvería el GP0 al camino crítico."""
    src, regs, ddr = make_src()
    for s in range(6):
        write_slot(ddr, s, base_val=s)
    set_wr(regs, 6)
    b = Batch()

    escrituras = []
    orig_w = src._w

    def espiar(off, val):
        if off == R_RD_SLOT:
            escrituras.append(val)
        orig_w(off, val)

    src._w = espiar
    for k in range(6):
        src.read_into(b, k, src.wait_event(10**18))
    # a lo sumo una publicación por prefetch, nunca una por evento
    assert len(escrituras) <= 2, escrituras


def test_rearm_es_noop():
    src, regs, _ = make_src()
    antes = bytes(regs)
    src.rearm()
    assert bytes(regs) == antes


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
