#!/usr/bin/env python3
"""Tests offline de BramSource contra un modelo del scope. NO necesitan la placa.

Existe por un error que los demás tests no podían ver, porque usan `FakeSource`:
`BramSource` escribía las máscaras (0x240/0x244) y leía el snapshot (0x218) en el
slot 1, y esos registros se mudaron al slot 3 (`mt_cfg.sv`). `osc_cfg` ya no los
decodifica: la escritura se pierde y la lectura da 0.

Lo que hace visible el error es el modelo de `mt_trig_src`: en single-shot la
máscara activa se BORRA al disparar, y sólo vuelve con una escritura real de
`R_OR_MASK_CH*`. Sin esa escritura, el scope captura un evento y no dispara más.

Del hardware real se usan las clases de verdad (`MultiTriggerScope`,
`MultiTrigger`, `multitrigger_arm`); lo falso son las dos regiones de registros y
el módulo `rp`.

Correr:  python3 -m pytest API/tests/test_bram_source.py -v
"""

import ctypes
import glob
import os
import struct
import sys
import threading
import time
import types

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.multitrigger import (BIT_ADC_P0, MultiTrigger, R_FLAGS,   # noqa: E402
                              R_OR_MASK_CH0, R_OR_MASK_CH1, R_SHIELD_CFG,
                              R_TRIG_SNAP)
from API.osciloscope_store import (AcquisitionSession, BramSource,  # noqa: E402
                                   load_chunk, scope_regs)
from API.osciloscope_store.sources import N_BUF                     # noqa: E402
from multitrigger_utils import MultiTriggerScope                    # noqa: E402

PRE, POST = 8, 24
S = PRE + POST

# Lo que el slot 1 dejó de decodificar: `osc_cfg` ignora la escritura y lee 0.
MUDADOS_AL_SLOT_3 = (0x210, 0x214, 0x218, 0x21C, 0x240, 0x244, 0x248, 0x24C)

WP_INICIAL = 1000
PASO_WP = 137           # como un wp real: avanza y da la vuelta


class Region(bytearray):
    """Una región de registros. `w32` entra por la asignación por slice, y las
    lecturas (`unpack_from`) leen estos bytes: el modelo los mantiene al día."""

    def __init__(self, size, al_escribir):
        super().__init__(size)
        self._al_escribir = al_escribir

    def __setitem__(self, clave, valor):
        if isinstance(clave, slice) and clave.stop - clave.start == 4:
            self._al_escribir(clave.start, struct.unpack('<I', valor)[0])
        else:
            super().__setitem__(clave, valor)

    def poner(self, off, v):
        struct.pack_into('<I', self, off, v & 0xFFFFFFFF)

    def leer(self, off):
        return struct.unpack_from('<I', self, off)[0]


class PlacaFalsa:
    """El scope (slot 1) y el multitrigger (slot 3), en single-shot.

    Modela lo que `BramSource` necesita de `rp_bram_sm` y `mt_trig_src`:

      - 0x00 bit 0 armar: `adc_we` = 1, el buffer corre. bit 1: reset de la FSM, que
        también borra la máscara activa y el snapshot. bit 3: `we_keep`.
      - `R_OR_MASK_CH*` es lo único que carga la máscara activa. Su relectura da la
        guardada (`trg_src_stored`), no la activa.
      - Un pulso con la FSM armada y su bit en la máscara congela el buffer, avanza
        `wp_trig` y, sin `we_keep`, BORRA la máscara activa.
    """

    def __init__(self):
        self.osc = Region(0x1000, self._w_osc)
        self.mt = Region(0x1000, self._w_mt)
        self.activa = [0, 0]
        self.we_keep = False
        self.wp = WP_INICIAL
        self.escrituras = []            # ('osc' | 'mt', off, valor), en orden
        self.osc.poner(0x1C, self.wp)
        self.osc.poner(0x11C, self.wp)

    def _w_osc(self, off, v):
        self.escrituras.append(('osc', off, v))
        if off in MUDADOS_AL_SLOT_3:
            return                      # no decodificado: se pierde
        if off == 0x00:
            self.we_keep = bool(v & 0x8)
            if v & 0x2:                 # adc_rst_do
                self.osc.poner(0x00, 0)
                self.activa = [0, 0]
                self.mt.poner(R_TRIG_SNAP, 0)
            elif v & 0x1:               # arm: adc_we = 1
                self.osc.poner(0x00, 1)
            return
        if off == 0x94:                 # trig_dis_clr también borra el snapshot
            self.mt.poner(R_TRIG_SNAP, 0)
            return
        self.osc.poner(off, v)

    def _w_mt(self, off, v):
        self.escrituras.append(('mt', off, v))
        self.mt.poner(off, v)           # trg_src_stored: la relectura
        if off == R_OR_MASK_CH0:
            self.activa[0] = v
        elif off == R_OR_MASK_CH1:
            self.activa[1] = v

    def pulso(self, bit=BIT_ADC_P0):
        """Un flanco. Dispara si la FSM está armada y la máscara lo deja pasar."""
        armada = self.osc.leer(0x00) & 1
        if not armada or not ((self.activa[0] | self.activa[1]) & bit):
            return False
        self.wp = (self.wp + PASO_WP) % N_BUF
        self.osc.poner(0x1C, self.wp)
        self.osc.poner(0x11C, self.wp)
        self.mt.poner(R_TRIG_SNAP, bit)
        if not self.we_keep:
            self.osc.poner(0x00, 0)     # post-trigger completo: buffer congelado
            self.activa = [0, 0]
        return True


def _volts(ch, pos):
    """El contenido de la BRAM falsa, distinto por canal y por posición."""
    return (ch + 1) * 0.1 + (pos % 64) * 0.001


class _FBuffer:
    def __init__(self, n):
        self.a = (ctypes.c_float * n)()

    def cast(self):
        return ctypes.addressof(self.a)


@pytest.fixture
def rp_falso(monkeypatch):
    """`monkeypatch` lo saca de sys.modules al terminar: un stub que queda ahí hace
    fallar a los tests siguientes (ver test_ring_source.py)."""
    rp = types.ModuleType('rp')
    rp.RP_CH_1, rp.RP_CH_2, rp.RP_CH_3, rp.RP_CH_4 = 0, 1, 2, 3
    rp.fBuffer = _FBuffer

    def get(ch, start, end, fb, n):
        assert (start + n - 1) % N_BUF == end, 'end_pos es inclusivo'
        for i in range(n):
            fb.a[i] = _volts(ch, (start + i) % N_BUF)
        return 0
    rp.rp_AcqGetDataPosV = get
    monkeypatch.setitem(sys.modules, 'rp', rp)
    return rp


@pytest.fixture
def placa():
    return PlacaFalsa()


def scope_de(placa):
    sc = MultiTriggerScope(placa.osc, -1)
    sc._mt = MultiTrigger(placa.mt, -1)
    return sc


def fuente(placa, **kw):
    kw.setdefault('pre', PRE)
    kw.setdefault('post', POST)
    return BramSource(scope_de(placa), **kw)


class _Batch:
    def __init__(self, n_ch, cap=8):
        self.wave = np.zeros((cap, n_ch, S), dtype=np.float32)


def _esperar(src, ms=50):
    return src.wait_event(time.perf_counter_ns() + ms * 1_000_000)


# -----------------------------------------------------------------------------
# El error: un evento y no dispara más
# -----------------------------------------------------------------------------

def test_dispara_mas_de_un_evento(placa, rp_falso):
    src = fuente(placa)
    src.arm()
    for k in range(5):
        assert placa.pulso(), f'evento {k}: el pulso no encontró la máscara cargada'
        assert _esperar(src) == placa.wp, f'evento {k}'
        src.rearm()


def test_el_modelo_muerde_si_la_mascara_va_al_slot_1(placa, rp_falso):
    """El test de arriba sólo vale si esta falla es la que el modelo produce."""
    src = fuente(placa)
    src.arm()
    assert placa.pulso()
    assert _esperar(src) == placa.wp
    sc = src.sc
    sc.w32(0x00, 0x101)                  # el re-armado de antes
    sc.w32(0x240, src.mask)
    sc.w32(0x244, src.mask)
    assert not placa.pulso()
    assert _esperar(src, ms=5) is None


def test_rearm_arma_primero_y_escribe_la_mascara_en_el_slot_3(placa, rp_falso):
    src = fuente(placa, mask=0x2)
    src.arm()
    placa.escrituras.clear()
    src.rearm()
    assert placa.escrituras == [('osc', 0x00, 0x101),
                                ('mt', R_OR_MASK_CH0, 0x2),
                                ('mt', R_OR_MASK_CH1, 0x2)]


# -----------------------------------------------------------------------------
# El snapshot
# -----------------------------------------------------------------------------

def test_snapshot_sale_del_slot_3(placa, rp_falso):
    src = fuente(placa)
    src.arm()
    assert placa.pulso(BIT_ADC_P0)
    assert _esperar(src) is not None
    assert src.snapshot() == BIT_ADC_P0


def test_read_snap_false_no_lee(placa, rp_falso):
    src = fuente(placa, read_snap=False)
    src.arm()
    placa.pulso()
    assert src.snapshot() == 0


# -----------------------------------------------------------------------------
# La lectura
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('n_ch', [1, 2])
@pytest.mark.parametrize('wp', [5000, 3, N_BUF - 2])     # sin vuelta y con vuelta
def test_read_into_lee_la_ventana_de_cada_canal(placa, rp_falso, n_ch, wp):
    src = fuente(placa, n_ch=n_ch)
    src.arm()
    b = _Batch(n_ch)
    src.read_into(b, 2, wp)
    for k in range(n_ch):
        esperado = [_volts(k, (wp - PRE + j) % N_BUF) for j in range(S)]
        np.testing.assert_allclose(b.wave[2, k], esperado, rtol=1e-6)


# -----------------------------------------------------------------------------
# scope_regs
# -----------------------------------------------------------------------------

def test_scope_regs_lee_cada_registro_de_su_slot(placa, rp_falso):
    src = fuente(placa, mask=0x2)
    src.arm()
    placa.pulso()
    placa.mt.poner(R_FLAGS, 0x33)        # ningún registro del slot 1 da esto
    r = scope_regs(src.sc)
    assert r['mask_ch0'] == r['mask_ch1'] == 0x2     # lo guardado, no lo activo
    assert r['snapshot'] == 0x2
    assert r['shield'] == placa.mt.leer(R_SHIELD_CFG) != 0
    assert r['dis_we'] == 0x33
    assert r['wp_trig0'] == placa.wp
    assert r['adc_state'] == 0


# -----------------------------------------------------------------------------
# De punta a punta, por el lector y el escritor reales
# -----------------------------------------------------------------------------

class _Pulsador(threading.Thread):
    """Pulsos hasta que lo paren, a la tasa que deje el lector: cada pulso que
    encuentra el scope ciego se pierde, como en la placa."""

    def __init__(self, placa):
        super().__init__(daemon=True)
        self.placa = placa
        self.parar = threading.Event()

    def run(self):
        while not self.parar.is_set():
            self.placa.pulso()
            time.sleep(50e-6)


@pytest.mark.parametrize('n_ch', [1, 2])
def test_sesion_completa(placa, rp_falso, tmp_path, n_ch):
    n_eventos = 40
    src = fuente(placa, n_ch=n_ch)
    pulsador = _Pulsador(placa)
    ses = AcquisitionSession(src, tmp_path, capacity=16, ram_budget_mb=1,
                             verbose=False)
    pulsador.start()
    try:
        with ses:
            motivo = ses.wait(duration_s=3.0, n_events=n_eventos, poll_s=0.01)
    finally:
        pulsador.parar.set()
        pulsador.join(1)

    assert motivo == 'events', f'{motivo}: {ses.stats}'
    assert ses.stats['n_read'] >= n_eventos

    chunks = sorted(glob.glob(os.path.join(str(tmp_path), 'chunk_*.npz')))
    assert chunks
    d, _meta = load_chunk(chunks[0])
    assert d['wave'].shape[1:] == (n_ch, S)
    assert set(d['snap'].tolist()) == {BIT_ADC_P0}
    assert ('d2' in d) == (n_ch == 2)
    # Cada evento trae la ventana de SU wp: el buffer se leyó congelado.
    for i in range(3):
        esperado = _volts(0, (int(d['wp'][i]) - PRE) % N_BUF)
        assert abs(d['wave_V'][i, 0, 0] - esperado) < 2 / 8192
