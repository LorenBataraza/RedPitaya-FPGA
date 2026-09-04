"""Formato del slot del event_ring: decodificación pura, sin hardware.

Este módulo es la ÚNICA definición del layout del lado software, y está pensado
para que lo importe tanto el test offline como el lector real. Si el RTL y esto
se desincronizan, `test_ring_format.py` falla contra el volcado que produce la
simulación (`prj/MCA/sim/tb_event_ring_top.sv`), que es mucho más barato que
descubrirlo en la placa.

Layout, definido en `rtl/mine/event_ring/event_slot_writer.sv`:

    w0            timestamp[63:0]            (ciclos de adc_clk desde el start)
    w1            {flags[7:0], n_ch[7:0], n_samp[15:0], seq[31:0]}
    w2            {event_id[31:0], 15'b0, snapshot[16:0]}
    w3            0 (reservado)
    w4 ..         muestras int16, 4 por palabra, canales INTERCALADOS
    .. relleno    ceros
    última        FOOTER {~seq[31:0], seq[31:0]}

POR QUÉ EL FOOTER ES LA MARCA DE COMMIT. Todas las escrituras del ring salen por
un master con un único ID hacia el mismo esclavo, y AXI garantiza que las
escrituras con el mismo ID se observan en orden. El footer es la última palabra
del slot, así que si está bien formado y trae el `seq` esperado, todo lo que
está antes ya llegó a DDR. Eso evita depender del canal B (que ni axi_wr_fifo ni
axi_master exponen) y, sobre todo, deja al PS poleando DDR en vez del bus GP0.
"""

import numpy as np

HDR_WORDS = 4          # palabras de 64 b de cabecera
HDR_BYTES = HDR_WORDS * 8
FOOTER_WORDS = 1


class SlotFormatError(ValueError):
    pass


def slot_words(slot_shift: int) -> int:
    """Palabras de 64 b por slot."""
    return (1 << slot_shift) // 8


def footer_is_valid(footer: int) -> bool:
    """El footer vale {~seq, seq}: las dos mitades tienen que ser complementarias.

    Chequear la complementariedad (y no "distinto de cero") es lo que hace que un
    slot nunca escrito, o uno leído a medias, sea detectable sin depender de que
    algún valor particular sea especial.
    """
    lo = footer & 0xFFFFFFFF
    hi = (footer >> 32) & 0xFFFFFFFF
    return hi == (~lo) & 0xFFFFFFFF


def footer_seq(footer: int) -> int:
    return footer & 0xFFFFFFFF


def parse_header(words):
    """Decodifica las 4 palabras de cabecera. `words` es un iterable de 4 int."""
    w0, w1, w2, _w3 = words[0], words[1], words[2], words[3]
    return {
        "timestamp": w0,
        "seq":       w1 & 0xFFFFFFFF,
        "n_samp":    (w1 >> 32) & 0xFFFF,
        "n_ch":      (w1 >> 48) & 0xFF,
        "flags":     (w1 >> 56) & 0xFF,
        "snapshot":  w2 & 0x1FFFF,
        "event_id":  (w2 >> 32) & 0xFFFFFFFF,
    }


def decode_slot(buf: bytes, slot_shift: int, expect_seq=None):
    """Decodifica un slot completo.

    `buf` son exactamente 2^slot_shift bytes (el slot entero, tal como sale de un
    mmap de la región reservada de DDR).

    Devuelve (meta, muestras) donde `muestras` es un array (n_ch, n_samp) de
    int16 — vista de-intercalada, sin copia extra más allá del reshape.

    Levanta SlotFormatError si el footer no cierra: eso significa "este slot
    todavía no está completo", no "hay un bug".
    """
    nwords = slot_words(slot_shift)
    if len(buf) != (1 << slot_shift):
        raise SlotFormatError(
            f"el slot debe medir {1 << slot_shift} bytes, vinieron {len(buf)}")

    w = np.frombuffer(buf, dtype="<u8")

    footer = int(w[nwords - 1])
    if not footer_is_valid(footer):
        raise SlotFormatError(f"footer mal formado: {footer:#018x}")

    meta = parse_header([int(x) for x in w[:HDR_WORDS]])

    if expect_seq is not None and meta["seq"] != expect_seq:
        raise SlotFormatError(
            f"seq de cabecera {meta['seq']} != esperado {expect_seq}")
    if footer_seq(footer) != meta["seq"]:
        # Cabecera de una vuelta y footer de otra: el slot se está reescribiendo
        # justo ahora. Es la condición de carrera que el footer existe para
        # detectar.
        raise SlotFormatError(
            f"seq de cabecera {meta['seq']} != seq de footer {footer_seq(footer)}")

    n_ch, n_samp = meta["n_ch"], meta["n_samp"]
    total = n_ch * n_samp
    if HDR_BYTES + total * 2 > (1 << slot_shift) - 8 * FOOTER_WORDS:
        raise SlotFormatError(
            f"ventana de {total} muestras no entra en un slot de "
            f"{1 << slot_shift} B (revisar SLOT_SHIFT)")

    # Las muestras arrancan justo después de la cabecera. El RTL las emite
    # intercaladas (ch0[k], ch1[k], ch0[k+1], ...), así que el reshape de
    # (n_samp, n_ch) y la transposición dan un array por canal.
    samples = np.frombuffer(buf, dtype="<i2", count=total, offset=HDR_BYTES)
    return meta, samples.reshape(n_samp, n_ch).T


def ring_slot_offset(slot_idx: int, n_slots: int, slot_shift: int) -> int:
    """Byte de arranque del slot `slot_idx` (contador libre) dentro del ring."""
    return (slot_idx % n_slots) << slot_shift


def credits_used(wr_slot: int, rd_slot: int) -> int:
    """Slots ocupados. Contadores libres de 32 b: la resta cierra en módulo 2^32
    aunque hayan dado la vuelta, que es exactamente lo que hace el comparador de
    créditos en `event_ring_top.sv`."""
    return (wr_slot - rd_slot) & 0xFFFFFFFF
