"""Tests offline del formato del slot. NO necesitan la Red Pitaya.

El test que importa es `test_contra_volcado_de_simulacion`: lee el volcado que
produce `prj/MCA/sim/tb_event_ring_top.sv` y lo decodifica con el MISMO código
que va a usar el lector real. Es el enganche RTL <-> software: un error de
endianness, de intercalado de canales o de posición del footer se cae acá, en
segundos y sin placa, en vez de aparecer como "datos raros" en una campaña.

Correr:
    cd prj/MCA/software && python3 -m pytest API/tests/test_ring_format.py -v
o sin pytest:
    python3 test_ring_format.py
"""

import os
import struct
import sys

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.modelo_rtl.ring_format import (                        # noqa: E402
    HDR_BYTES,
    SlotFormatError,
    credits_used,
    decode_slot,
    footer_is_valid,
    footer_seq,
    ring_slot_offset,
    slot_words,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, "datos_ref", "ring_dump.hex")

SLOT_SHIFT = 9        # tiene que coincidir con el TB
N_SLOTS = 4
N_CH = 2
N_SAMP = 32


# ---------------------------------------------------------------------------
# Constructor de slots sintéticos (el "modelo" del RTL del lado Python)
# ---------------------------------------------------------------------------
def build_slot(seq, ts, snapshot, ch0, ch1, slot_shift=SLOT_SHIFT):
    n_samp = len(ch0)
    body = bytearray(1 << slot_shift)
    struct.pack_into("<Q", body, 0, ts)
    struct.pack_into("<Q", body, 8, (seq & 0xFFFFFFFF) | (n_samp << 32) | (2 << 48))
    struct.pack_into("<Q", body, 16, snapshot & 0x1FFFF)
    inter = np.empty(n_samp * 2, dtype="<i2")
    inter[0::2] = ch0
    inter[1::2] = ch1
    body[HDR_BYTES:HDR_BYTES + inter.nbytes] = inter.tobytes()
    footer = (seq & 0xFFFFFFFF) | ((~seq & 0xFFFFFFFF) << 32)
    struct.pack_into("<Q", body, (1 << slot_shift) - 8, footer)
    return bytes(body)


# ---------------------------------------------------------------------------
def test_footer_detecta_slot_nunca_escrito():
    # Un slot virgen es todo ceros: hi=0, lo=0 -> no complementarios.
    assert not footer_is_valid(0)
    # Y uno bien formado sí
    assert footer_is_valid((0xFFFFFFFF << 32) | 0)
    assert footer_is_valid((0xFFFFFFFE << 32) | 1)
    assert footer_seq((0xFFFFFFFE << 32) | 1) == 1


def test_roundtrip_basico():
    ch0 = np.arange(N_SAMP, dtype="<i2")
    ch1 = (-np.arange(N_SAMP)).astype("<i2")
    buf = build_slot(seq=7, ts=123456, snapshot=0x5, ch0=ch0, ch1=ch1)

    meta, samples = decode_slot(buf, SLOT_SHIFT, expect_seq=7)
    assert meta["seq"] == 7
    assert meta["timestamp"] == 123456
    assert meta["n_samp"] == N_SAMP
    assert meta["n_ch"] == 2
    assert meta["snapshot"] == 0x5
    assert samples.shape == (2, N_SAMP)
    np.testing.assert_array_equal(samples[0], ch0)
    np.testing.assert_array_equal(samples[1], ch1)


def test_slot_incompleto_levanta():
    buf = bytes(1 << SLOT_SHIFT)          # todo ceros: nunca escrito
    with pytest.raises(SlotFormatError):
        decode_slot(buf, SLOT_SHIFT)


def test_seq_de_cabecera_y_footer_desalineados():
    """Cabecera de una vuelta y footer de otra = el slot se está reescribiendo.

    Es la condición de carrera que el footer existe para detectar, así que tiene
    que dar error y no datos plausibles.
    """
    ch = np.zeros(N_SAMP, dtype="<i2")
    buf = bytearray(build_slot(seq=7, ts=0, snapshot=0, ch0=ch, ch1=ch))
    # pisar el footer con el de otro evento (bien formado, pero de otro seq)
    struct.pack_into("<Q", buf, (1 << SLOT_SHIFT) - 8,
                     11 | ((~11 & 0xFFFFFFFF) << 32))
    with pytest.raises(SlotFormatError):
        decode_slot(bytes(buf), SLOT_SHIFT)


def test_ventana_que_no_entra():
    """Cabecera que declara más muestras de las que caben en el slot.

    Es el sintoma del lado software de err_slot_ovf en el RTL: si SLOT_SHIFT se
    configuró chico para la ventana, hay que gritar en vez de devolver un array
    que se comió parte del slot siguiente.
    """
    ch = np.zeros(N_SAMP, dtype="<i2")
    buf = bytearray(build_slot(seq=0, ts=0, snapshot=0, ch0=ch, ch1=ch))
    # el slot sigue midiendo lo correcto; lo que miente es n_samp
    struct.pack_into("<Q", buf, 8, 0 | (400 << 32) | (2 << 48))
    with pytest.raises(SlotFormatError, match="no entra"):
        decode_slot(bytes(buf), SLOT_SHIFT)


def test_aritmetica_del_ring():
    assert slot_words(9) == 64
    assert ring_slot_offset(0, 4, 9) == 0
    assert ring_slot_offset(4, 4, 9) == 0          # dio la vuelta
    assert ring_slot_offset(5, 4, 9) == 512
    # créditos con contadores libres que ya envolvieron 2^32
    assert credits_used(3, 1) == 2
    assert credits_used(1, 0xFFFFFFFF) == 2


# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.path.exists(DUMP),
                    reason="falta ring_dump.hex: correr `make tb_event_ring_top` en prj/MCA/sim")
def test_contra_volcado_de_simulacion():
    """Decodifica la DDR que produjo el RTL de verdad.

    El TB inyecta una rampa donde ch1 = -ch0 muestra a muestra. Si el
    intercalado, el endianness o el offset de datos estuvieran mal, esa relación
    se rompe — es una firma que no se satisface por casualidad.
    """
    with open(DUMP) as fh:
        words = [int(ln, 16) for ln in fh if not ln.startswith("#")]

    assert len(words) == N_SLOTS * slot_words(SLOT_SHIFT)
    raw = b"".join(struct.pack("<Q", w) for w in words)

    seqs_vistos = []
    for s in range(N_SLOTS):
        off = ring_slot_offset(s, N_SLOTS, SLOT_SHIFT)
        buf = raw[off:off + (1 << SLOT_SHIFT)]
        meta, samples = decode_slot(buf, SLOT_SHIFT)

        assert meta["n_ch"] == N_CH
        assert meta["n_samp"] == N_SAMP
        assert samples.shape == (N_CH, N_SAMP)
        # la firma de la rampa del TB
        np.testing.assert_array_equal(samples[1], -samples[0].astype(np.int32))
        # el slot físico s tiene que guardar un evento cuyo seq ≡ s (mod N_SLOTS)
        assert meta["seq"] % N_SLOTS == s
        seqs_vistos.append(meta["seq"])

    # todos distintos: ningún slot quedó con una copia de otro
    assert len(set(seqs_vistos)) == N_SLOTS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
