#!/usr/bin/env python3
"""Tests offline de BramSource y del lazo por evento de libmca, contra un modelo del
scope. NO necesitan la placa.

Existe por un error que los demás tests no podían ver, porque usan `FakeSource`:
`BramSource` escribía las máscaras (0x240/0x244) y leía el snapshot (0x218) en el
slot 1, y esos registros se mudaron al slot 3 (`mt_cfg.sv`). `osc_cfg` ya no los
decodifica: la escritura se pierde y la lectura da 0.

Lo que hace visible el error es el modelo de `mt_trig_src`: en single-shot la
máscara activa se BORRA al disparar, y sólo vuelve con una escritura real de
`R_OR_MASK_CH*`. Sin esa escritura, el scope captura un evento y no dispara más.

Desde la Parte 6 el lazo es de C (`osciloscope_leer_lote`), y llega al modelo por el
backend de callbacks: lo que se comprueba es el C de verdad. La onda son cuentas
calibradas, y se comparan contra la cuenta de librp (`datos_ref/calib_rp.npy`).

Del hardware real se usan las clases de verdad (`MultiTriggerScope`,
`MultiTrigger`, `multitrigger_arm`); lo falso son las dos regiones de registros.

Correr:  python3 -m pytest API/tests/test_bram_source.py -v
"""

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

import API.osciloscope as O                                          # noqa: E402
from API.multitrigger import (BIT_ADC_P0, MultiTrigger, R_FLAGS,   # noqa: E402
                              R_OR_MASK_CH0, R_OR_MASK_CH1, R_SHIELD_CFG,
                              R_TRIG_SNAP)
from API.osciloscope_store import (AcquisitionSession, BramSource,  # noqa: E402
                                   DeadTimeAnnotator, archivos_de_corrida,
                                   load_chunk, scope_regs)
from API.osciloscope_store.events import BASE_FIELDS, EventBatch     # noqa: E402
from multitrigger_utils import MultiTriggerScope                    # noqa: E402

PRE, POST = 8, 24
S = PRE + POST
N_BUF = 16384           # la geometría por defecto: el modelo no publica el mapa canónico

# Lo que el slot 1 dejó de decodificar: `osc_cfg` ignora la escritura y lee 0.
MUDADOS_AL_SLOT_3 = (0x210, 0x214, 0x218, 0x21C, 0x240, 0x244, 0x248, 0x24C)

WP_INICIAL = 1000
PASO_WP = 137           # como un wp real: avanza y da la vuelta

TABLA = np.load(os.path.join(_RAIZ, 'API', 'tests', 'datos_ref', 'calib_rp.npy'))
FILAS = (1, 2)          # la calibración de cada canal: +2 % con -64, y -2 % con +37
CALIB = [{'gain': int(TABLA[f]['gain']), 'base': int(TABLA[f]['base']),
          'offset': int(TABLA[f]['offset'])} for f in FILAS]

# Lo que tiene la BRAM: palabras crudas de 14 bits, distintas por canal.
BRAM = (np.arange(N_BUF, dtype=np.uint32) % (1 << 14),
        (np.arange(N_BUF, dtype=np.uint32) * 7 + 3) % (1 << 14))


def esperado(ch, wp, pre=PRE, n=S):
    """La ventana de `wp` del canal `ch`, calibrada como librp."""
    pos = (wp - pre + np.arange(n)) % N_BUF
    return TABLA[FILAS[ch]]['m'][BRAM[ch][pos]]


class Region(bytearray):
    """Una región de registros. `w32` entra por la asignación por slice, y las
    lecturas leen estos bytes: el modelo los mantiene al día."""

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
    """El scope (slot 1, con sus dos aperturas de BRAM) y el multitrigger (slot 3).

    Modela lo que `BramSource` necesita de `rp_bram_sm` y `mt_trig_src`:

      - 0x00 bit 0 armar: `adc_we` = 1, el buffer corre. bit 1: reset de la FSM, que
        también borra la máscara activa y el snapshot. bit 3: `we_keep`.
      - `R_OR_MASK_CH*` es lo único que carga la máscara activa. Su relectura da la
        guardada (`trg_src_stored`), no la activa.
      - Un pulso con la FSM armada y su bit en la máscara avanza `wp_trig` y, sin
        `we_keep`, congela el buffer y BORRA la máscara activa.
    """

    def __init__(self):
        self.osc = Region(0x30000, self._w_osc)
        self.mt = Region(0x1000, self._w_mt)
        self.activa = [0, 0]
        self.we_keep = False
        self.wp = WP_INICIAL
        self.escrituras = []            # ('osc' | 'mt', off, valor), en orden
        self.osc.poner(0x1C, self.wp)
        self.osc.poner(0x11C, self.wp)
        palabras = np.frombuffer(self.osc, dtype='<u4')
        for ch in (0, 1):
            base = (0x10000 + ch * 0x10000) // 4
            palabras[base:base + N_BUF] = BRAM[ch]
        self.lock = threading.Lock()

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
    kw.setdefault('calib', CALIB)
    return BramSource(scope_de(placa), **kw)


def lote(n_ch=2, cap=8, campos=BASE_FIELDS, samples=S):
    return EventBatch(cap, n_ch, samples, campos, wave_dtype=np.int16)


def _plazo(ms=20):
    return time.perf_counter_ns() + ms * 1_000_000


def _leer(src, b, ms=20):
    """Un `read_batch` como el del lector: llena desde b.n y avanza b.n."""
    n, d, a = src.read_batch(b, _plazo(ms))
    if b is not None:
        b.n += n
        b.dropped += a
    return n, d, a


# -----------------------------------------------------------------------------
# El error: un evento y no dispara más
# -----------------------------------------------------------------------------

def test_dispara_mas_de_un_evento(placa):
    src = fuente(placa)
    src.arm()
    b = lote()
    for k in range(5):
        assert placa.pulso(), f'evento {k}: el pulso no encontró la máscara cargada'
        assert _leer(src, b) == (1, 0, 0), f'evento {k}'
        assert b.wp[k] == placa.wp


def test_el_modelo_muerde_si_la_mascara_va_al_slot_1(placa):
    """El test de arriba sólo vale si esta falla es la que el modelo produce."""
    src = fuente(placa)
    src.arm()
    assert placa.pulso()
    sc = src.sc
    sc.w32(0x00, 0x101)                  # el re-armado de antes
    sc.w32(0x240, src.mask)
    sc.w32(0x244, src.mask)
    assert not placa.pulso()
    assert _leer(src, lote(), ms=5) == (0, 0, 0)


def test_rearm_arma_primero_y_escribe_la_mascara_en_el_slot_3(placa):
    src = fuente(placa, mask=0x2)
    src.arm()
    placa.escrituras.clear()
    placa.pulso()
    assert _leer(src, lote())[0] == 1
    assert placa.escrituras == [('osc', 0x00, 0x101),
                                ('mt', R_OR_MASK_CH0, 0x2),
                                ('mt', R_OR_MASK_CH1, 0x2)]


def test_nada_va_a_los_registros_que_se_mudaron(placa):
    src = fuente(placa)
    src.arm()
    b = lote()
    for _ in range(3):
        placa.pulso()
        _leer(src, b)
    assert not [e for e in placa.escrituras if e[0] == 'osc' and e[1] in MUDADOS_AL_SLOT_3]


# -----------------------------------------------------------------------------
# El snapshot
# -----------------------------------------------------------------------------

def test_snapshot_sale_del_slot_3(placa):
    src = fuente(placa)
    src.arm()
    b = lote()
    assert placa.pulso(BIT_ADC_P0)
    assert _leer(src, b)[0] == 1
    assert b.snap[0] == BIT_ADC_P0


def test_read_snap_false_no_lo_lee(placa):
    src = fuente(placa, read_snap=False)
    src.arm()
    b = lote()
    placa.pulso()
    assert _leer(src, b)[0] == 1
    assert b.snap[0] == 0 and placa.mt.leer(R_TRIG_SNAP) == BIT_ADC_P0


# -----------------------------------------------------------------------------
# La lectura
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('n_ch', [1, 2])
@pytest.mark.parametrize('wp', [5000, 3, N_BUF - 2])     # sin vuelta y con vuelta
def test_la_ventana_de_cada_canal_es_la_de_librp(placa, n_ch, wp):
    src = fuente(placa, n_ch=n_ch)
    src.arm()
    b = lote(n_ch)
    b.n = 2                              # llena desde la fila donde está el batch
    placa.wp = (wp - PASO_WP) % N_BUF
    placa.pulso()
    assert _leer(src, b)[0] == 1
    assert b.wp[2] == wp
    for k in range(n_ch):
        np.testing.assert_array_equal(b.wave[2, k], esperado(k, wp))
    assert not b.wave[:2].any(), 'las filas de antes no se tocan'


def test_t_ns_y_dead_ns_estan_en_el_reloj_de_python(placa):
    src = fuente(placa)
    src.arm()
    b = lote(campos=BASE_FIELDS + (('dead_ns', np.int64),))
    t0 = time.perf_counter_ns()
    placa.pulso()
    assert _leer(src, b)[0] == 1
    t1 = time.perf_counter_ns()
    assert t0 < b.t_ns[0] < t1
    assert 0 < b.dead_ns[0] < t1 - b.t_ns[0]


# -----------------------------------------------------------------------------
# Descartes, plazo y tamaño del lote
# -----------------------------------------------------------------------------

def test_sin_batch_cuenta_rearma_y_lo_anota_en_el_proximo_gap(placa):
    src = fuente(placa)
    src.arm()
    for _ in range(3):
        assert placa.pulso(), 'sin re-armar, el segundo pulso no dispararía'
        assert src._lector.leer(None, 0, 1, _plazo()) == (0, 1, 0)
    assert src.pending == 3
    b = lote()
    placa.pulso()
    assert _leer(src, b) == (1, 0, 3)
    assert b.gap[0] == 3 and b.dropped == 3 and src.pending == 0


def test_gap_satura_y_el_total_no(placa):
    src = fuente(placa, n_ch=1)
    src.arm()
    for _ in range(300):
        placa.pulso()
        src._lector.leer(None, 0, 1, _plazo())
    b = lote(1)
    placa.pulso()
    assert _leer(src, b) == (1, 0, 300)
    assert b.gap[0] == 255 and b.dropped == 300


def test_sin_eventos_vuelve_al_vencer_el_plazo(placa):
    src = fuente(placa)
    src.arm()
    t0 = time.perf_counter()
    assert _leer(src, lote(), ms=30) == (0, 0, 0)
    dt = time.perf_counter() - t0
    assert 0.03 <= dt < 1.0
    assert src.read_batch(None, 0) == (0, 0, 0), 'un plazo vencido vuelve enseguida'


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


def test_vuelve_con_el_lote_lleno_antes_del_plazo(placa):
    src = fuente(placa)
    src.arm()
    b = lote(cap=5)
    b.n = 2
    p = _Pulsador(placa)
    p.start()
    try:
        t0 = time.perf_counter()
        n, _, _ = src.read_batch(b, _plazo(5000))
        dt = time.perf_counter() - t0
    finally:
        p.parar.set()
        p.join(1)
    assert n == 3 and dt < 4.0
    wps = b.wp[2:5].tolist()
    assert all((y - x) % N_BUF == PASO_WP or (y - x) % N_BUF > 0 for x, y in zip(wps, wps[1:]))


def test_continuo_detecta_por_cambio_de_wp(placa):
    src = fuente(placa, single_shot=False)
    src.arm()
    assert placa.we_keep, 'arm_for_adc_trigger(we_keep_both=True)'
    b = lote()
    for k in range(3):
        assert placa.pulso()
        assert _leer(src, b)[0] == 1, f'evento {k}'
        assert b.wp[k] == placa.wp


# -----------------------------------------------------------------------------
# Lo que se rechaza
# -----------------------------------------------------------------------------

def test_sin_libmca_no_hay_lazo():
    sc = types.SimpleNamespace(mt=types.SimpleNamespace(_via='py', impl='py'),
                               _via='py', impl='py')
    with pytest.raises(TypeError, match='sólo en libmca'):
        BramSource(sc, calib=CALIB).arm()


def test_sin_calibracion_no_arma(placa, monkeypatch):
    """Nunca se guarda crudo sin avisar: en la PC no hay EEPROM."""
    monkeypatch.setitem(sys.modules, 'rp_hw_calib', None)
    monkeypatch.setattr(O, '_RP_PYTHON', '/no/existe')
    src = fuente(placa, calib=None)
    with pytest.raises(RuntimeError, match='calibración'):
        src.arm()
    assert placa.escrituras == [], 'falla antes de tocar el hardware'


@pytest.mark.parametrize('kw, exc, msg', [
    (dict(calib=CALIB[:1]), ValueError, '1 calibraciones para 2 canales'),
    (dict(calib=[(0, 1, 0)] * 2), ValueError, 'canal 0: gain=0'),
    (dict(n_ch=3, calib=CALIB * 2), ValueError, 'n_ch=3: este bitstream tiene 2'),
    (dict(wp_addr=0x18), ValueError, 'wp_off=0x018'),
    (dict(pre=10000, post=10000), ValueError, 'ventana de 20000'),
])
def test_una_configuracion_imposible_falla_al_armar(placa, kw, exc, msg):
    src = fuente(placa, **kw)
    with pytest.raises(exc, match=msg):
        src.arm()


def test_el_lector_valida_las_columnas(placa):
    src = fuente(placa)
    src.arm()
    lec = src._lector
    with pytest.raises(TypeError, match='int64'):
        lec.leer({'t_ns': np.zeros(4, np.int32)}, 0, 4, 0)
    with pytest.raises(ValueError, match='filas'):
        lec.leer({'t_ns': np.zeros(4, np.int64)}, 2, 4, 0)
    with pytest.raises(ValueError, match='wave'):
        lec.leer({'wave': np.zeros((4, 1, S), np.int16)}, 0, 4, 0)
    sin_mt = O.Lector(src.sc, None, PRE, POST, 2, 2, CALIB)
    with pytest.raises(ValueError, match='multitrigger'):
        sin_mt.leer(None, 0, 1, 0)


def test_meta_trae_la_calibracion(placa):
    m = fuente(placa, n_ch=1).meta()
    assert m['calib'] == CALIB[:1] and 'calibradas' in m['wave']
    assert m['adc_cnt_per_V'] == 8192 and m['lector'] == 'libmca'


# -----------------------------------------------------------------------------
# scope_regs
# -----------------------------------------------------------------------------

def test_scope_regs_lee_cada_registro_de_su_slot(placa):
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

@pytest.mark.parametrize('n_ch', [1, 2])
def test_sesion_completa(placa, tmp_path, n_ch):
    n_eventos = 40
    src = fuente(placa, n_ch=n_ch)
    pulsador = _Pulsador(placa)
    muerto = DeadTimeAnnotator()
    ses = AcquisitionSession(src, tmp_path, capacity=16, ram_budget_mb=1,
                             annotators=[muerto], verbose=False)
    pool = list(ses.free_q.queue)
    assert {b.wave.dtype for b in pool} == {np.dtype(np.int16)}, 'cuentas desde C'
    pulsador.start()
    try:
        with ses:
            motivo = ses.wait(duration_s=5.0, n_events=n_eventos, poll_s=0.01)
    finally:
        pulsador.parar.set()
        pulsador.join(1)

    assert motivo == 'events', f'{motivo}: {ses.stats}'
    assert ses.stats['n_read'] >= n_eventos

    chunks = archivos_de_corrida(tmp_path)
    assert chunks
    d, meta = load_chunk(chunks[0])
    assert d['wave'].shape[1:] == (n_ch, S) and d['wave'].dtype == np.int16
    assert set(d['snap'].tolist()) == {BIT_ADC_P0}
    assert ('d2' in d) == (n_ch == 2)
    assert meta['source']['calib'] == CALIB[:n_ch]
    # Cada evento trae la ventana de SU wp, calibrada: el buffer se leyó congelado.
    for i in range(len(d['wp'])):
        for k in range(n_ch):
            np.testing.assert_array_equal(d['wave'][i, k], esperado(k, int(d['wp'][i])))
    assert (d['dead_ns'] > 0).all()
    assert muerto.n == ses.stats['n_read'] and muerto.total_ns > 0
    escritos = sum(load_chunk(c)[0]['wave'].shape[0] for c in chunks)
    assert escritos == ses.stats['n_written'] == ses.stats['n_read']


# -----------------------------------------------------------------------------
# El lector por lote, con una fuente guionada
# -----------------------------------------------------------------------------

class _Guion:
    """Una fuente por lote que devuelve lo que diga el guion, sin hardware. Cada paso
    es (eventos, descartados, asignados); sin batch, los eventos no se guardan."""

    scalar_fields = BASE_FIELDS
    n_ch, samples, wave_dtype = 1, 4, np.int16

    def __init__(self, pasos, pendientes_al_final=0):
        self.pasos = list(pasos)
        self.pending = pendientes_al_final
        self.llamadas = []

    def arm(self):
        pass

    def close(self):
        pass

    def meta(self):
        return dict(kind='guion', pre=1, post=3, dt_ns=8.0, adc_cnt_per_V=8192)

    def read_batch(self, batch, deadline_ns):
        self.llamadas.append(None if batch is None else batch.n)
        if not self.pasos:
            time.sleep(0.002)
            return 0, 0, 0
        n, d, a = self.pasos.pop(0)
        if batch is None:
            return 0, d, 0
        n = min(n, batch.capacity - batch.n)
        for i in range(batch.n, batch.n + n):
            batch.t_ns[i] = time.perf_counter_ns()
            batch.wp[i] = i
        return n, d, a


def _correr_lector(src, n_batches=2, cap=4, annotators=(), hasta=None, timeout_s=1.0):
    import queue
    from API.osciloscope_store.reader import ReaderThread
    from API.osciloscope_store.annotators import merge_fields

    campos = merge_fields(src, annotators)
    libres, llenos = queue.Queue(), queue.Queue()
    for _ in range(n_batches):
        libres.put(EventBatch(cap, src.n_ch, src.samples, campos, np.int16))
    stats = dict(n_read=0, n_dropped=0, n_timeouts=0, n_written=0, chunks=0)
    r = ReaderThread(src, libres, llenos, stats, annotators=annotators,
                     poll_timeout_s=timeout_s)
    r.start()
    t0 = time.perf_counter()
    while (hasta is None or not hasta(stats)) and time.perf_counter() - t0 < 2:
        time.sleep(0.005)
    r.stop()
    r.join(2)
    salida = []
    while True:
        b = llenos.get_nowait()
        if b is None:
            break
        salida.append(b)
    assert r.error is None, r.error
    return stats, salida, libres


def test_el_lector_por_lote_entrega_lotes_llenos_y_el_parcial():
    src = _Guion([(3, 0, 0), (1, 0, 0), (3, 0, 0)])
    stats, lotes, _ = _correr_lector(src, hasta=lambda s: s['n_read'] >= 7)
    assert [b.n for b in lotes] == [4, 3]
    assert stats['n_read'] == 7 and stats['n_dropped'] == 0
    assert lotes[0].wp.tolist() == [0, 1, 2, 3], 'sigue desde la fila donde quedó'


def test_el_lector_suma_descartes_y_los_asignados_de_cada_lote():
    src = _Guion([(4, 0, 0), (4, 0, 0), (0, 5, 0), (2, 0, 5)], pendientes_al_final=2)
    stats, lotes, _ = _correr_lector(src, n_batches=3,
                                     hasta=lambda s: s['n_read'] >= 10)
    assert stats['n_dropped'] == 5 and stats['pending_tail'] == 2
    assert [b.n for b in lotes] == [4, 4, 2]
    assert [b.dropped for b in lotes] == [0, 0, 5], 'los asignados van al lote del evento'


def test_sin_batch_libre_el_lector_pide_descartar():
    # El escritor no devuelve nada en este arnés: el único batch se queda lleno.
    src = _Guion([(4, 0, 0), (0, 3, 0)])
    stats, lotes, _ = _correr_lector(src, n_batches=1,
                                     hasta=lambda s: s['n_dropped'] >= 3)
    assert src.llamadas[:2] == [0, None], 'sin batch libre: read_batch(None)'
    assert stats['n_dropped'] == 3 and [b.n for b in lotes] == [4]


def test_el_lector_cuenta_un_timeout_por_periodo_quieto():
    src = _Guion([])
    stats, _, libres = _correr_lector(src, timeout_s=0.05,
                                      hasta=lambda s: s['n_timeouts'] >= 3)
    assert stats['n_timeouts'] >= 3 and stats['n_read'] == 0
    assert libres.qsize() == 2, 'el batch tomado vuelve a la cola de libres'


def test_los_annotators_corren_sobre_el_rango_recien_llenado():
    from API.osciloscope_store.annotators import CachedAnnotator, ConstantAnnotator

    class Fijo(CachedAnnotator):
        value_fields = (('x', np.float64),)
        prefix = 'x'
        interval_s = 0.001

        def poll(self):
            return {'x': 2.5}

    fijo, const = Fijo(), ConstantAnnotator(k=7.0)
    fijo.start()
    try:
        t = time.perf_counter()
        while not fijo._t_ns and time.perf_counter() - t < 1:
            time.sleep(0.001)
        src = _Guion([(2, 0, 0), (2, 0, 0)])
        _, lotes, _ = _correr_lector(src, annotators=(fijo, const),
                                     hasta=lambda s: s['n_read'] >= 4)
    finally:
        fijo.stop()
    b = lotes[0]
    assert b.scalars['k'].tolist() == [7.0] * 4
    assert b.scalars['x'].tolist() == [2.5] * 4
    edad = b.scalars['x_age_ns']
    assert (edad != 0).all() and (np.abs(edad) < 1e9).all()


def test_continuo_sin_pulsos_no_inventa_eventos(placa):
    """lote_iniciar toma el wp_trig de ahora: sin pulsos no hay cambio que ver."""
    src = fuente(placa, single_shot=False)
    src.arm()
    assert _leer(src, lote(), ms=10) == (0, 0, 0)


def test_con_eventos_sin_pausa_igual_respeta_el_plazo(placa):
    """En continuo, con wp_trig cambiando más rápido que el lazo, el sondeo nunca
    vence: el plazo se mira también después de cada evento."""
    src = fuente(placa, single_shot=False, n_ch=1)
    src.arm()
    parar = threading.Event()

    def girar():
        wp = 0
        while not parar.is_set():
            wp = (wp + 1) % N_BUF
            placa.osc.poner(0x1C, wp)

    t = threading.Thread(target=girar, daemon=True)
    t.start()
    try:
        b = lote(1, cap=10 ** 6)
        t0 = time.perf_counter()
        n, _, _ = src.read_batch(b, _plazo(30))
        dt = time.perf_counter() - t0
    finally:
        parar.set()
        t.join(1)
    assert n > 0 and dt < 1.0
