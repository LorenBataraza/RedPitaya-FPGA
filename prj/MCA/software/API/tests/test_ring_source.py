"""Tests offline del event_ring en libmca y de `RingSource`. NO necesitan la placa.

Desde la Parte 7 del plan de libmca el lector del ring es de C
(`osciloscope_ring_leer_lote`), y llega a un modelo del ring por los dos backends de
callbacks: los registros por `Bus.callbacks` y la DDR por `Mem.sobre`, que C lee y
escribe en el lugar. Lo que se comprueba es el C de verdad. El modelo sigue a
`event_ring_top.sv`:

  - la geometría se toma sólo parado; escrita corriendo se pierde y prende err_cfg;
  - parado (y con clr), WR_SLOT, RD_SLOT y SEQ vuelven a cero;
  - sin créditos (WR_SLOT - RD_SLOT == N_SLOTS) el evento se descarta y se cuenta en
    DROP_FULL;
  - el slot: cabecera, muestras intercaladas y el footer {~seq, seq} al final.

Las propiedades que importan, y que sin el modelo sólo se verían en la placa:

  - el footer es el commit: un slot con WR_SLOT adelante y el footer en vuelo no se
    entrega, ni el de la corrida anterior con el mismo seq;
  - el crédito se devuelve por bloque, y alcanza para que un ring chico no pierda;
  - `snap` es el del mismo evento (el lector por evento entregaba el del anterior);
  - la ventana, calibrada como librp (`datos_ref/calib_rp.npy`) y des-intercalada;
  - los descartes del hardware van al `gap`, con el total exacto.

Y dos contra referencias externas: el volcado de DDR del RTL (`ring_dump.hex`,
`tb_event_ring_top`) leído por C contra `decode_slot`, y el camino de mmap con
ficheros comunes (`Bus.archivo`, `Mem.archivo`).

Correr:  python3 -m pytest API/tests/test_ring_source.py -v
"""

import mmap
import os
import struct
import sys
import time

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import API.generadores as G                                          # noqa: E402
import API.osciloscope_ring as OR                                    # noqa: E402
from API._libmca import Bus, LibMCAError, Mem                        # noqa: E402
from API.modelo_rtl.ring_format import decode_slot                   # noqa: E402
from API.osciloscope_ring import (                                   # noqa: E402
    MAGIC, R_CTRL, R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_MAGIC, R_N_SLOTS, R_POST,
    R_PRE, R_RD_SLOT, R_RING_SZ, R_SEQ, R_SLOT_BASE, R_SLOT_SHIFT, R_STATUS, R_TS_HI,
    R_TS_LO, R_WR_SLOT, LectorRing, OsciloscopeRing, RingNotPresent, RingSource)
from API.osciloscope_store import (AcquisitionSession, archivos_de_corrida,  # noqa: E402
                                   load_chunk)
from API.osciloscope_store.events import EventBatch                 # noqa: E402
from API.ring_falso import RingFalso as _RingFalso                  # noqa: E402

SLOT_SHIFT = 9
SLOT_SZ = 1 << SLOT_SHIFT
N_SLOTS = 16
DDR_PHYS = 0x0A00_0000
PRE, POST = 8, 24
S = PRE + POST
M32 = 0xFFFFFFFF

_MODELOS = os.path.join(os.path.dirname(_RAIZ), 'modulos', 'gen_eventos', 'modelos',
                        'python_model')
sys.path.insert(0, _MODELOS)
try:
    import gen_eventos_model as ge                                   # noqa: E402
except ImportError:                 # en la placa: `make placa-sync` no copia modulos/
    ge = None
sin_modelo = pytest.mark.skipif(ge is None, reason='sin el modelo de gen_eventos')

TABLA = np.load(os.path.join(_RAIZ, 'API', 'tests', 'datos_ref', 'calib_rp.npy'))
FILAS = (1, 2)          # +2 % con -64, y -2 % con +37: las de test_bram_source
CALIB = [{'gain': int(TABLA[f]['gain']), 'base': int(TABLA[f]['base']),
          'offset': int(TABLA[f]['offset'])} for f in FILAS]
IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}


def codigos(seq, s=S):
    """Las palabras de 14 bits del evento `seq`, distintas por canal y por evento."""
    k = np.arange(s, dtype=np.int64)
    return ((seq * 37 + k * 11) % (1 << 14), (seq * 101 + k * 7 + 5) % (1 << 14))


def firmado(c):
    """La palabra de 14 bits con el signo extendido: lo que el ring escribe en DDR."""
    c = np.asarray(c, dtype=np.int64)
    return np.where(c >= 1 << 13, c - (1 << 14), c).astype('<i2')


def esperado(k, seq, s=S, filas=FILAS):
    """La ventana del canal k del evento seq, calibrada como librp."""
    return TABLA[filas[k]]['m'][codigos(seq, s)[k]]


class RingFalso(_RingFalso):
    """El ring simulado de la API (`API/ring_falso.py`) con las muestras de estos tests:
    los códigos de `codigos`, distintos por canal y por evento."""

    def __init__(self, ddr_bytes=N_SLOTS * SLOT_SZ, ddr_phys=DDR_PHYS):
        super().__init__(ddr_bytes=ddr_bytes, ddr_phys=ddr_phys)

    def muestras(self, seq, s):
        c0, c1 = codigos(seq, s)
        return firmado(c0), firmado(c1)


class FakeScope:
    def __init__(self, log):
        self.log = log

    def arm_for_adc_trigger(self, **kw):
        self.log.append(('scope', 'arm', kw))

    def disarm(self):
        self.log.append(('scope', 'disarm', None))


def fuente(rf, **kw):
    kw.setdefault('pre', PRE)
    kw.setdefault('post', POST)
    kw.setdefault('slot_shift', SLOT_SHIFT)
    kw.setdefault('calib', CALIB)
    return RingSource(FakeScope(rf.log), rf.handle(), **kw)


def armada(rf=None, **kw):
    rf = rf or RingFalso()
    src = fuente(rf, **kw)
    src.arm()
    return rf, src


def lote(n_ch=2, cap=64, s=S):
    return EventBatch(cap, n_ch, s, RingSource.scalar_fields, wave_dtype=np.int16)


def _plazo(ms=20):
    return time.perf_counter_ns() + ms * 1_000_000


def _leer(src, b, ms=20):
    n, d, a = src.read_batch(b, _plazo(ms))
    if b is not None:
        b.n += n
        b.dropped += a
    return n, d, a


# -----------------------------------------------------------------------------
# El mapa y la geometría
# -----------------------------------------------------------------------------

def test_registros_coinciden_con_libmca():
    nombres = {n[2:]: getattr(OR, n) for n in dir(OR) if n.startswith('R_')}
    assert OR.registros() == nombres


@pytest.mark.parametrize('pre, post, sh, entra', [
    (32, 992, 13, True),        # 1024 muestras, slot de 8 KB
    (1023, 1, 13, True),        # 1024 con el rezago más grande
    (512, 1023, 14, True),      # 2·pre + post = 2047: el borde exacto del RTL
    (512, 1024, 14, False),     # 2048: el RTL pisa muestras sin avisar
    (0, 2048, 14, False),       # no entra en el pre-buffer
])
def test_ventana_contra_el_limite_del_pre_buffer(pre, post, sh, entra):
    rf = RingFalso(ddr_bytes=1 << 16)
    if entra:
        assert fuente(rf, pre=pre, post=post, slot_shift=sh).samples == pre + post
    else:
        with pytest.raises(ValueError, match='rezago|11 bits'):
            fuente(rf, pre=pre, post=post, slot_shift=sh)


@pytest.mark.parametrize('kw, motivo', [
    (dict(pre=200, post=200, slot_shift=9), 'hacen falta'),
    (dict(slot_shift=5), 'de 6 a 18'),
    (dict(slot_shift=19), 'de 6 a 18'),
    (dict(n_ch=3), 'escribe 2 canales'),
    (dict(n_ch=0), 'escribe 2 canales'),
    (dict(pre=0, post=0), 'no tiene muestras'),
    (dict(pre=2048, post=0), '11 bits'),
])
# El stage (4096 muestras) no tiene caso: con 2 canales, si el rezago 2·pre + post
# entra en el pre-buffer de 2048, la ventana 2·(pre + post) entra en el stage.
def test_geometria_que_el_rtl_no_acepta(kw, motivo):
    with pytest.raises(ValueError, match=motivo):
        fuente(RingFalso(), **kw)


def test_1024_muestras_eligen_un_slot_de_8_kb():
    src = RingSource(FakeScope([]), RingFalso().handle(), pre=32, post=992)
    assert src.slot_sz == 8192
    assert OR.geometria(8, 24)['slot_bytes'] == 256       # 32 + 128 + 8 = 168 B


@pytest.mark.parametrize('ring_bytes, motivo', [
    (3 * SLOT_SZ + 8, 'múltiplo del slot'),
    (2 * N_SLOTS * SLOT_SZ, 'la región de DDR tiene'),
])
def test_ring_que_no_entra_en_la_region(ring_bytes, motivo):
    rf = RingFalso()
    src = fuente(rf, ring_bytes=ring_bytes)
    with pytest.raises(ValueError, match=motivo):
        src.arm()


def test_sin_el_ring_en_el_slot_2():
    rf = RingFalso()
    rf.reg[R_MAGIC] = 0
    with pytest.raises(RingNotPresent, match='EVNT'):
        rf.handle()


def test_calibracion_sin_leer_se_rechaza_al_armar():
    rf = RingFalso()
    src = fuente(rf, calib=[CALIB[0], {'gain': 0, 'base': 32768, 'offset': 0}])
    with pytest.raises(ValueError, match='canal 1: gain=0'):
        src.arm()


# -----------------------------------------------------------------------------
# Configurar y armar
# -----------------------------------------------------------------------------

def test_arm_configura_parado_y_corre_al_final():
    rf, src = armada()
    ring = [(off, v) for q, off, v in rf.log if q == 'ring']
    assert ring[:2] == [(R_CTRL, 0), (R_CTRL, 0x2)]          # parar, clr
    geo = dict(ring[2:7])
    assert geo == {R_SLOT_BASE: DDR_PHYS, R_RING_SZ: N_SLOTS * SLOT_SZ,
                   R_SLOT_SHIFT: SLOT_SHIFT, R_PRE: PRE, R_POST: POST}
    # el disparo se arma con el ring configurado, y recién después corre
    i_arm = next(i for i, e in enumerate(rf.log) if e[:2] == ('scope', 'arm'))
    assert rf.log[i_arm + 1:] == [('ring', R_CTRL, 1)]
    assert rf.log[i_arm][2]['we_keep_both'] and rf.log[i_arm][2]['auto_rearm']
    assert rf.gst == 1 and not rf.err_cfg
    assert src.n_slots == N_SLOTS


def test_configurar_espera_que_termine_de_drenar():
    rf, src = armada()
    rf.al_parar = 50                 # una ventana en vuelo: tarda en parar
    src.arm()                        # de nuevo, con el ring corriendo
    assert not rf.err_cfg, 'la geometría se escribió drenando: el RTL la pierde'


def test_configurar_falla_si_el_ring_no_para():
    rf, src = armada()
    rf.al_parar = 10 ** 9
    with pytest.raises(TimeoutError, match='drenar'):
        src.arm()


def test_configurar_borra_los_footers_de_la_corrida_anterior():
    rf, src = armada()
    for _ in range(5):
        rf.disparar()
    assert _leer(src, lote())[0] == 5
    # Otra corrida: el slot 0 todavía tiene el footer válido de seq 0.
    src.arm()
    assert rf.disparar(footer=False) == 0       # aceptado, todavía en vuelo
    assert _leer(src, lote(), ms=5)[0] == 0, 'entregó el slot 0 de la corrida anterior'
    rf.footer(0)
    assert _leer(src, lote())[0] == 1


# -----------------------------------------------------------------------------
# El lazo
# -----------------------------------------------------------------------------

def test_sin_eventos_vence_el_plazo():
    rf, src = armada()
    t0 = time.perf_counter()
    assert _leer(src, lote(), ms=10) == (0, 0, 0)
    assert 0.009 < time.perf_counter() - t0 < 1.0


def test_ventana_calibrada_y_columnas_del_mismo_slot():
    rf, src = armada()
    snaps = (0x1, 0x2, 0x10004)
    t0 = time.perf_counter_ns()
    for s in snaps:
        rf.disparar(snap=s)
    b = lote()
    assert _leer(src, b) == (3, 0, 0)
    t1 = time.perf_counter_ns()
    for i in range(3):
        for k in range(2):
            np.testing.assert_array_equal(b.wave[i, k], esperado(k, i))
    # El snap es el de SU slot. El lector por evento entregaba el del anterior.
    assert b.snap[:3].tolist() == list(snaps)
    assert b.seq[:3].tolist() == [0, 1, 2]
    assert b.ts_hw[:3].tolist() == [1000, 2007, 3021]
    assert (b.wp[:3] == -1).all()
    assert (t0 <= b.t_ns[:3]).all() and (b.t_ns[:3] <= t1).all()
    assert (b.gap[:3] == 0).all()


def test_un_canal_entrega_el_primero_con_el_slot_de_dos():
    rf, src = armada(n_ch=1, calib=CALIB[:1])
    assert OR.geometria(PRE, POST, 1) == OR.geometria(PRE, POST, 2)
    rf.disparar()
    b = lote(n_ch=1)
    assert _leer(src, b)[0] == 1
    np.testing.assert_array_equal(b.wave[0, 0], esperado(0, 0))


def test_footer_en_vuelo_no_se_entrega():
    """WR_SLOT avanza cuando el footer se ACEPTA, no cuando llega a DDR."""
    rf, src = armada()
    rf.disparar(footer=False)
    assert _leer(src, lote(), ms=5)[0] == 0
    rf.footer(0)
    assert _leer(src, lote())[0] == 1


def test_footer_roto_no_se_entrega():
    rf, src = armada()
    rf.disparar(footer=False)
    rf.footer(0, bueno=False)
    assert _leer(src, lote(), ms=5)[0] == 0


def test_el_bloque_se_corta_en_el_primer_footer_que_falta():
    rf, src = armada()
    rf.disparar()
    rf.disparar(footer=False)
    rf.disparar()
    b = lote()
    assert _leer(src, b, ms=5)[0] == 1
    rf.footer(1)
    assert _leer(src, b)[0] == 2
    assert b.seq[:3].tolist() == [0, 1, 2]


def test_footer_de_la_vuelta_anterior_no_se_entrega():
    rf, src = armada()
    b = lote(cap=N_SLOTS)
    for _ in range(N_SLOTS):
        rf.disparar()
    assert _leer(src, b)[0] == N_SLOTS
    rf.disparar(footer=False)                   # seq 16 en el slot 0: queda el de seq 0
    assert _leer(src, lote(), ms=5)[0] == 0


def test_da_la_vuelta_al_ring_en_orden():
    rf, src = armada()
    b = lote(cap=40)
    for _ in range(N_SLOTS - 2):
        rf.disparar()
    assert _leer(src, b)[0] == N_SLOTS - 2
    for _ in range(5):                          # seq 14..18: cruzan el final
        rf.disparar()
    assert _leer(src, b)[0] == 5
    assert b.seq[:b.n].tolist() == list(range(N_SLOTS + 3))
    for i in range(b.n):
        np.testing.assert_array_equal(b.wave[i, 1], esperado(1, i))


def test_el_credito_se_devuelve_por_bloque():
    rf, src = armada()
    for _ in range(6):
        rf.disparar()
    rf.log.clear()
    assert _leer(src, lote())[0] == 6
    assert [(off, v) for q, off, v in rf.log if off == R_RD_SLOT] == [(R_RD_SLOT, 6)]


def test_bloques_chicos_publican_uno_por_bloque():
    rf, src = armada()
    src._lector._cfg.lote_bytes = 2 * SLOT_SZ
    for _ in range(6):
        rf.disparar()
    rf.log.clear()
    assert _leer(src, lote())[0] == 6
    assert [v for q, off, v in rf.log if off == R_RD_SLOT] == [2, 4, 6]


def test_un_ring_chico_no_pierde_si_se_devuelve_el_credito():
    """Cuatro slots, y dos eventos por cada vez que el lazo mira WR_SLOT: sin el
    crédito por bloque, el ring se llena en la tercera mirada."""
    rf, src = armada(ring_bytes=4 * SLOT_SZ)
    producidos = []

    def dos(m):
        for _ in range(2):
            if len(producidos) < 30:
                producidos.append(m.disparar())

    rf.generar = dos
    b = lote(cap=30)
    for _ in range(100):
        if b.n >= 30:
            break
        _leer(src, b, ms=5)
    assert 'lleno' not in producidos and rf.full == 0
    assert b.seq[:b.n].tolist() == list(range(30))


def test_los_descartes_del_hardware_van_al_gap():
    rf, src = armada()
    b = lote()
    rf.disparar()
    assert _leer(src, b) == (1, 0, 0)
    rf.busy += 3
    rf.full += 297                              # 300: el gap satura, el total no
    rf.disparar()
    rf.disparar()
    assert _leer(src, b) == (2, 300, 300)
    assert b.gap[:3].tolist() == [0, 255, 0]
    assert b.dropped == 300 and src.pending == 0


def test_descartes_al_final_quedan_pendientes():
    rf, src = armada()
    rf.full += 7
    assert _leer(src, lote(), ms=5) == (0, 7, 0)
    assert src.pending == 7


def test_sin_batch_no_consume_y_cuenta_los_descartes():
    rf, src = armada()
    rf.disparar()
    rf.disparar()
    rf.full += 4
    t0 = time.perf_counter()
    assert src.read_batch(None, _plazo(10)) == (0, 4, 0)
    assert time.perf_counter() - t0 >= 0.009, 'sin batch tiene que esperar al plazo'
    assert rf.rd == 0, 'sin batch no se devuelve ningún crédito'
    b = lote()
    assert _leer(src, b) == (2, 0, 4)           # siguen en la DDR
    assert b.gap[:2].tolist() == [4, 0]


def test_el_plazo_corta_con_eventos_sin_pausa():
    rf, src = armada(pre=2, post=6)
    rf.generar = lambda m: m.disparar()
    cap = 200_000
    b = EventBatch(cap, 2, 8, RingSource.scalar_fields, wave_dtype=np.int16)
    t0 = time.perf_counter()
    n, _, _ = src.read_batch(b, _plazo(20))
    assert 0 < n < cap
    assert time.perf_counter() - t0 < 2.0


def test_cabecera_que_no_coincide_con_la_configuracion():
    rf, src = armada()
    rf.disparar(n_samp=S + 1)
    with pytest.raises(LibMCAError, match='trae 33 muestras'):
        _leer(src, lote())


def test_columnas_del_lote_se_validan():
    rf, src = armada()
    b = lote()
    b.scalars['ts_hw'] = np.zeros(b.capacity, np.uint32)
    with pytest.raises(TypeError, match='ts_hw'):
        src.read_batch(b, _plazo())
    with pytest.raises(ValueError, match='wave'):
        src.read_batch(lote(s=S + 2), _plazo())


def test_lector_sin_configurar():
    rf = RingFalso()
    lec = LectorRing(rf.handle(), PRE, POST, 2, CALIB)
    with pytest.raises(ValueError, match='no est'):
        lec.leer(None, 0, 1, _plazo(1))


# -----------------------------------------------------------------------------
# Cierre, metadatos y la sesión entera
# -----------------------------------------------------------------------------

def test_close_guarda_los_contadores_y_para():
    rf, src = armada()
    for _ in range(3):
        rf.disparar()
    _leer(src, lote())
    rf.disparar()                               # queda sin leer
    rf.busy += 2
    src.close()
    m = src.meta()
    assert m['kind'] == 'ring' and m['lector'] == 'libmca'
    assert m['hw_final']['hw_ev_cnt'] == 4 and m['hw_final']['hw_drop_busy'] == 2
    assert m['hw_final']['hw_no_leidos'] == 1
    assert m['ddr_phys'] == DDR_PHYS and m['n_slots'] == N_SLOTS
    assert m['calib'] == CALIB and m['dt_ns'] == 8.0
    assert rf.gst == 0 and rf.log[-1] == ('scope', 'disarm', None)


def test_detener_corta_el_disparo_y_vaciado_mira_el_hardware():
    """Lo que usa `AcquisitionSession.stop` antes de parar el lector: `detener` apaga la
    máscara OR con el ring corriendo (el resto del desarme queda para `close`), y
    `vaciado` dice si queda una ventana en vuelo o algo sin leer."""
    rf, src = armada()
    src.sc.set_or_mask = lambda m0, m1=None: rf.log.append(('scope', 'or_mask', (m0, m1)))
    rf.disparar()
    assert not src.vaciado()                    # escrito y sin leer
    _leer(src, lote())
    assert src.vaciado()
    rf.ev += 1                                  # una ventana que empezó y no terminó
    assert not src.vaciado()
    rf.ev -= 1
    src.detener()
    src.detener()                               # corta una vez
    assert [x[1:] for x in rf.log if x[0] == 'scope'][1:] == [('or_mask', (0, 0))]
    assert rf.gst == 1, 'el ring sigue corriendo: el lector se lleva lo que quedó'
    src.close()
    assert rf.gst == 0 and rf.log[-1] == ('scope', 'disarm', None)


def test_el_esquema_tiene_las_columnas_del_ring():
    nombres = [n for n, _ in RingSource.scalar_fields]
    assert nombres[-2:] == ['ts_hw', 'seq'] and 'wp' in nombres
    assert RingSource.wave_dtype is np.int16


def test_sesion_completa(tmp_path):
    rf = RingFalso()
    src = fuente(rf)
    estado = {'n': 0}

    def generar(m):
        # Un evento cada dos sondeos, y cada 7 eventos, 2 perdidos por el PL.
        estado['n'] += 1
        if estado['n'] % 2 == 0:
            if m.disparar() % 7 == 6:
                m.busy += 2

    rf.generar = generar
    ses = AcquisitionSession(src, tmp_path, capacity=16, ram_budget_mb=1, verbose=False)
    assert {b.wave.dtype for b in ses.free_q.queue} == {np.dtype(np.int16)}
    with ses:
        motivo = ses.wait(duration_s=5.0, n_events=60, poll_s=0.01)
    assert motivo == 'events', f'{motivo}: {ses.stats}'

    filas = [load_chunk(c) for c in archivos_de_corrida(tmp_path)]
    seq = np.concatenate([d['seq'] for d, _ in filas])
    assert seq.tolist() == list(range(len(seq))), 'un hueco o un evento repetido'
    ts = np.concatenate([d['ts_hw'] for d, _ in filas])
    assert (np.diff(ts) > 0).all()
    for d, meta in filas:
        assert meta['source']['kind'] == 'ring'
        for i, s in enumerate(d['seq']):
            np.testing.assert_array_equal(d['wave'][i, 0], esperado(0, int(s)))
            np.testing.assert_array_equal(d['wave'][i, 1], esperado(1, int(s)))
    gaps = sum(int(d['gap'].sum()) for d, _ in filas)
    assert gaps + ses.stats['pending_tail'] == ses.stats['n_dropped'] > 0
    assert len(seq) == ses.stats['n_written'] == ses.stats['n_read']


# -----------------------------------------------------------------------------
# Contra referencias de afuera
# -----------------------------------------------------------------------------

DUMP = os.path.join(_RAIZ, 'API', 'tests', 'datos_ref', 'ring_dump.hex')


@pytest.mark.skipif(not os.path.exists(DUMP),
                    reason='falta ring_dump.hex: `make tb_event_ring_top` en prj/MCA/sim')
def test_el_volcado_del_rtl_leido_por_c():
    """La DDR que escribió el RTL (tb_event_ring_top: 4 slots de 512 B, seq 3 a 6),
    leída por el lazo de C, contra `decode_slot`, el decodificador de referencia."""
    with open(DUMP) as fh:
        palabras = [int(ln, 16) for ln in fh if not ln.startswith('#')]
    crudo = b''.join(struct.pack('<Q', w) for w in palabras)
    ref = [decode_slot(crudo[i * 512:(i + 1) * 512], 9) for i in range(4)]
    seqs = sorted(m['seq'] for m, _ in ref)

    rf = RingFalso()
    src = fuente(rf, pre=8, post=24, ring_bytes=4 * 512, calib=[IDENTIDAD] * 2)
    src.arm()
    rf.ddr[:len(crudo)] = np.frombuffer(crudo, np.uint8)
    rf.wr = rf.rd = seqs[0]
    rf.wr += 4
    st = src._lector._st
    st.next = st.publicado = seqs[0]

    b = lote()
    assert _leer(src, b)[0] == 4
    for i, s in enumerate(seqs):
        meta, muestras = next(r for r in ref if r[0]['seq'] == s)
        assert b.seq[i] == s and b.ts_hw[i] == meta['timestamp']
        assert b.snap[i] == meta['snapshot']
        np.testing.assert_array_equal(b.wave[i], muestras)    # identidad: sin cambio
        np.testing.assert_array_equal(b.wave[i, 1], -b.wave[i, 0])   # la rampa del TB


def test_el_camino_de_mmap_con_ficheros(tmp_path):
    """Los registros y la DDR como ficheros comunes: el mismo open + mmap que en la
    placa (`mca_bus_open_file`, `mca_mem_open_file`), sin el modelo."""
    regs, ddr = tmp_path / 'regs', tmp_path / 'ddr'
    n = 8
    regs.write_bytes(bytes(0x1000))
    ddr.write_bytes(bytes(n * SLOT_SZ))
    with open(regs, 'r+b') as fr, open(ddr, 'r+b') as fd:
        r = mmap.mmap(fr.fileno(), 0x1000)
        d = mmap.mmap(fd.fileno(), n * SLOT_SZ)
        struct.pack_into('<I', r, R_MAGIC, MAGIC)
        struct.pack_into('<I', r, R_N_SLOTS, n)        # lo que derivaría el RTL
        ring = OsciloscopeRing.sobre(Bus.archivo(str(regs), 0, 0x1000),
                                     Mem.archivo(str(ddr), 0, n * SLOT_SZ))
        lec = LectorRing(ring, PRE, POST, 2, CALIB, SLOT_SHIFT)
        d[SLOT_SZ - 8:SLOT_SZ] = struct.pack('<Q', 0x1234)     # un footer viejo
        lec.configurar()
        assert d[SLOT_SZ - 8:SLOT_SZ] == bytes(8), 'configurar no borró los footers'
        # En un fichero, `phys` es el offset adentro: el SLOT_BASE que se escribe.
        assert struct.unpack_from('<I', r, R_SLOT_BASE)[0] == 0
        assert struct.unpack_from('<I', r, R_RING_SZ)[0] == n * SLOT_SZ

        c0, c1 = codigos(0)
        inter = np.empty(2 * S, '<i2')
        inter[0::2], inter[1::2] = firmado(c0), firmado(c1)
        d[0:32] = struct.pack('<QQQQ', 77, (S << 32) | (2 << 48), 0x4, 0)
        d[32:32 + inter.nbytes] = inter.tobytes()
        d[SLOT_SZ - 8:SLOT_SZ] = struct.pack('<Q', M32 << 32)     # {~0, 0}
        struct.pack_into('<I', r, R_WR_SLOT, 1)

        b = lote()
        assert lec.leer(b, 0, 64, _plazo())[0] == 1
        assert b.ts_hw[0] == 77 and b.snap[0] == 0x4
        np.testing.assert_array_equal(b.wave[0, 0], esperado(0, 0))
        assert struct.unpack_from('<I', r, R_RD_SLOT)[0] == 1
        ring.close()
        r.close()
        d.close()



# -----------------------------------------------------------------------------
# El generador de eventos (gen_eventos, EN_GEN = 1)
# -----------------------------------------------------------------------------

def _con_generador(rf=None):
    rf = rf or RingFalso()
    rf.reg[OR.R_GEN_MAGIC] = OR.GEN_MAGIC
    return rf


def _gen_escrituras(rf):
    return [(off, v) for q, off, v in rf.log if q == 'ring' and 0x100 <= off < 0x200]


def test_sin_el_generador_no_se_configura():
    rf = RingFalso()
    ring = rf.handle()
    assert ring.gen_presente() is False
    with pytest.raises(LibMCAError, match='EN_GEN = 0') as e:
        ring.gen_configurar(G.disparos(periodo=100))
    assert e.value.rc == -4                                  # MCA_ENOSYS
    assert _gen_escrituras(rf) == []
    assert ring.gen_estado()['gen_cnt'] == 0                 # lee 0, como el RTL
    ring.close()


@sin_modelo
def test_el_generador_se_configura_parado_y_queda_prendido():
    rf = _con_generador()
    ring = rf.handle()
    assert ring.gen_presente() is True
    d = G.disparos(aleatorio=True, tasa=500e3, dt_min=5, n=1000, semilla=7)
    ring.gen_configurar(d, patron=True)
    w = _gen_escrituras(rf)
    assert w[0] == (OR.R_GEN_CTRL, 0), 'tiene que apagarlo antes de escribir'
    assert w[-1] == (OR.R_GEN_CTRL, OR.GEN_CTRL_EN | OR.GEN_CTRL_ALEATORIO
                     | OR.GEN_CTRL_PATRON)
    assert (rf.reg[OR.R_GEN_UMBRAL], rf.reg[OR.R_GEN_DT_MIN], rf.reg[OR.R_GEN_N],
            rf.reg[OR.R_GEN_SEMILLA]) == (ge.umbral_para(500e3, dt_min=5), 5, 1000, 7)
    ring.gen_apagar()
    assert rf.reg[OR.R_GEN_CTRL] == 0
    ring.close()


def test_solo_el_patron_deja_los_disparos_del_multitrigger():
    rf = _con_generador()
    ring = rf.handle()
    ring.gen_configurar(None, patron=True)
    assert _gen_escrituras(rf) == [(OR.R_GEN_CTRL, 0), (OR.R_GEN_CTRL, OR.GEN_CTRL_PATRON)]
    ring.close()


def test_con_el_ring_corriendo_no_se_configura():
    rf = _con_generador()
    ring = rf.handle()
    ring.correr()
    with pytest.raises(ValueError, match='corriendo'):
        ring.gen_configurar(G.disparos(periodo=100))
    assert _gen_escrituras(rf) == []
    ring.close()


def test_una_configuracion_que_el_motor_no_hace():
    rf = _con_generador()
    ring = rf.handle()
    with pytest.raises(ValueError, match='periodo = 1'):
        ring.gen_configurar(G.disparos(periodo=1))
    assert OR._cargar().osciloscope_ring_gen_configurar(ring.c, None, 2) == -1   # EINVAL
    assert _gen_escrituras(rf) == []
    ring.close()


def test_el_estado_del_generador():
    rf = _con_generador()
    rf.reg[OR.R_GEN_CNT], rf.reg[OR.R_GEN_ESTADO] = 1234, 0b10
    ring = rf.handle()
    assert ring.gen_estado() == dict(gen_cnt=1234, estado=2, generando=False,
                                     terminado=True, desborde=False)
    ring.close()


def test_ringsource_con_el_generador_no_arma_el_scope():
    """La etapa C de campanas/run_etapas_ring.py: el estímulo es el generador, así
    que el scope no se toca (y puede ser None)."""
    rf = _con_generador()
    escribir = rf.w32

    def w32(off, v):                  # la ventana en vuelo termina al parar
        if off == R_CTRL and not v & 1 and rf.gst == 1:
            rf.ev += 1
        escribir(off, v)
    rf.w32 = w32
    d = G.disparos(periodo=100, n=10)
    src = RingSource(None, rf.handle(), pre=PRE, post=POST, slot_shift=SLOT_SHIFT,
                     calib=CALIB, generador=d)
    src.arm()
    assert [x for x in rf.log if x[0] == 'scope'] == []
    assert rf.reg[OR.R_GEN_CTRL] == OR.GEN_CTRL_EN | OR.GEN_CTRL_PATRON
    assert (rf.reg[OR.R_GEN_PERIODO], rf.reg[OR.R_GEN_N]) == (100, 10)
    assert rf.gst == 1, 'el ring corre después de configurar el generador'
    rf.reg[OR.R_GEN_CNT], rf.reg[OR.R_GEN_ESTADO] = 7, 0b01
    k = src.hw_counters()
    assert (k['hw_gen_cnt'], k['hw_gen_terminado']) == (7, False)
    rf.reg[OR.R_GEN_CNT], rf.reg[OR.R_GEN_ESTADO] = 10, 0b10
    rf.busy, rf.ev = 4, 5
    src.close()
    assert rf.reg[OR.R_GEN_CTRL] == 0, 'close apaga el generador'
    assert rf.gst == 0
    fin = src.meta()['hw_final']
    # Los de después de parar: con la ventana en vuelo, EV_CNT + DROP_BUSY = GEN_CNT.
    assert (fin['hw_gen_cnt'], fin['hw_gen_terminado'], fin['hw_ev_cnt'],
            fin['hw_drop_busy']) == (10, True, 6, 4)
    assert src.meta()['generador'] == G.disparos() | d
    src.ring.close()


def test_ringsource_con_el_generador_no_toca_el_scope_que_le_pasan():
    """El multitrigger puede estar disparando a otro (el MCA): con el generador, ni se
    arma ni se desarma."""
    rf = _con_generador()
    src = RingSource(FakeScope(rf.log), rf.handle(), pre=PRE, post=POST,
                     slot_shift=SLOT_SHIFT, calib=CALIB,
                     generador=G.disparos(periodo=100, n=10))
    src.arm()
    src.close()
    assert [x for x in rf.log if x[0] == 'scope'] == []
    src.ring.close()


def test_ringsource_sin_scope_ni_generador():
    with pytest.raises(ValueError, match='generador'):
        RingSource(None, RingFalso().handle(), pre=PRE, post=POST)


def test_ringsource_con_scope_sigue_sin_el_generador():
    rf, src = armada()
    assert [x[1] for x in rf.log if x[0] == 'scope'] == ['arm']
    assert OR.R_GEN_CTRL not in rf.reg
    assert 'hw_gen_cnt' not in src.hw_counters()
    src.close()
    assert [x[1] for x in rf.log if x[0] == 'scope'] == ['arm', 'disarm']
    assert src.meta()['generador'] is None


@sin_modelo
def test_el_patron_es_el_del_modelo():
    for ts in (0, 5, 8, 1000, (1 << 14) - 3, (1 << 14) + 17, 123456789):
        p = OR.patron_gen(ts, PRE, S)
        for j in range(S):
            m = ge.patron(ts - PRE + j)
            assert [int(v) & 0x3FFF for v in p[:, j]] == m, (ts, j)
            assert all(-8192 <= int(v) < 8192 for v in p[:, j])
    ts = np.array([3, 1 << 14, 99999])
    np.testing.assert_array_equal(OR.patron_gen(ts, PRE, S),
                                  np.stack([OR.patron_gen(t, PRE, S) for t in ts]))


def test_el_patron_se_lee_exacto_con_la_calibracion_identidad():
    """Lo que hace el test de placa: la ventana calibrada en identidad es el patrón
    del slot, muestra por muestra, y el snapshot dice cuál de los generados es."""
    rf = RingFalso()
    src = fuente(rf, calib=[IDENTIDAD] * 2)
    src.arm()
    b = lote()
    for k in range(5):
        seq = rf.disparar(snap=OR.GEN_SNAP_MARCA | k)
        off, _ = rf.slot(seq)
        inter = np.empty(2 * S, '<i2')
        p = OR.patron_gen(rf.ts, PRE, S)
        inter[0::2], inter[1::2] = p[0], p[1]
        rf.ddr[off + 32:off + 32 + inter.nbytes] = np.frombuffer(inter.tobytes(), np.uint8)
    assert _leer(src, b)[0] == 5
    for i in range(5):
        np.testing.assert_array_equal(b.wave[i], OR.patron_gen(b.ts_hw[i], PRE, S))
        assert b.snap[i] == OR.GEN_SNAP_MARCA | i


# -----------------------------------------------------------------------------
# Medir la tasa: osciloscope_ring_medir (las etapas de generador.md §6)
# -----------------------------------------------------------------------------

DATOS = (S * 2 * 2 + 7) & ~7            # lo que copia por slot, después de la cabecera


def _medidor(rf=None):
    rf = rf or RingFalso()
    ring = rf.handle()
    lec = LectorRing(ring, PRE, POST, 2, [IDENTIDAD] * 2, slot_shift=SLOT_SHIFT)
    lec.configurar()
    ring.correr()
    return rf, ring, lec


def gen_slot(rf, k, ts, snap=None, n_samp=None, footer=True):
    """Un slot como lo escribe el ring con el generador y el patrón: marca `ts` y
    snapshot {1, k}."""
    snap = OR.GEN_SNAP_MARCA | (k & 0xFFFF) if snap is None else snap
    seq = rf.disparar(snap=snap, footer=footer, n_samp=n_samp)
    assert isinstance(seq, int), seq
    off, _ = rf.slot(seq)
    rf.ddr[off:off + 8] = np.frombuffer(struct.pack('<Q', ts), np.uint8)
    p = OR.patron_gen(ts, PRE, S)
    inter = np.empty(2 * S, '<i2')
    inter[0::2], inter[1::2] = p[0], p[1]
    rf.ddr[off + 32:off + 32 + inter.nbytes] = np.frombuffer(inter.tobytes(), np.uint8)
    return seq, off


def ts_per(k, per):
    """La marca del disparo k del modo periódico."""
    return (k + 1) * per - 1 + OR.GEN_LAT_TS


def _errores(m):
    return {k: m[k] for k in ('err_cabecera', 'err_marca', 'err_k', 'err_ts', 'err_patron',
                              'muestras_malas') if m[k]}


def test_medir_creditos_devuelve_el_credito_sin_mirar_la_ddr():
    """Etapa A: cuenta lo que cerró el writer y lo devuelve, aunque el footer no haya
    llegado: no lee la DDR."""
    rf, ring, lec = _medidor()
    for k in range(10):
        gen_slot(rf, k, ts_per(k, 100), footer=False)
    m = lec.medir('creditos', _plazo(5))
    assert (m['eventos'], m['bytes'], rf.rd) == (10, 0, 10)
    assert m['ocupacion_max'] == 10 and m['bloques'] == 1
    assert m['errores'] == 0 and m['k_ultimo'] == -1    # no verifica nada
    ring.close()


def test_medir_copia_espera_el_footer_y_copia_cada_slot():
    rf, ring, lec = _medidor()
    for k in range(3):
        gen_slot(rf, k, ts_per(k, 100))
    gen_slot(rf, 3, ts_per(3, 100), footer=False)       # en vuelo
    m = lec.medir(OR.MEDIR_COPIA, _plazo(5))
    assert (m['eventos'], m['bytes'], rf.rd) == (3, 3 * (32 + DATOS), 3)
    rf.footer(3)
    m = lec.medir('copia', _plazo(5))
    assert (m['eventos'], rf.rd) == (4, 4)               # acumula
    ring.close()


def test_medir_verificar_periodico_sin_errores():
    rf, ring, lec = _medidor()
    d = G.disparos(periodo=1000, n=12)
    for k in range(12):
        gen_slot(rf, k, ts_per(k, 1000))
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert m['eventos'] == 12 and _errores(m) == {}
    assert (m['k_ultimo'], m['ts_ultimo'], m['k_saltos']) == (11, ts_per(11, 1000), 0)
    assert m['primer_error_seq'] is None
    ring.close()


def test_medir_cada_error_del_slot_se_cuenta_y_sigue():
    rf, ring, lec = _medidor()
    d = G.disparos(periodo=1000, n=100)
    gen_slot(rf, 0, ts_per(0, 1000))
    _, off = gen_slot(rf, 1, ts_per(1, 1000))
    rf.ddr[off + 32 + 2 * 3 * 2 + 1] ^= 0x01              # una muestra del canal 1
    gen_slot(rf, 2, ts_per(2, 1000), snap=0x5)           # no es del generador
    gen_slot(rf, 3, ts_per(3, 1000) + 1)                 # marca corrida
    gen_slot(rf, 3, ts_per(4, 1000))                     # k repetido
    gen_slot(rf, 5, ts_per(5, 1000), n_samp=S - 1)       # cabecera
    gen_slot(rf, 6, ts_per(6, 1000))                     # bien
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert m['eventos'] == 7
    assert _errores(m) == dict(err_patron=1, muestras_malas=1, err_marca=1, err_ts=1,
                               err_k=1, err_cabecera=1)
    assert m['primer_error_seq'] == 1
    assert m['k_ultimo'] == 6
    ring.close()


def test_medir_los_k_que_faltan_son_los_descartados():
    rf, ring, lec = _medidor()
    d = G.disparos(periodo=1000, n=12)
    llegan = [0, 1, 5, 6, 9]
    for k in llegan:
        gen_slot(rf, k, ts_per(k, 1000))
    rf.busy, rf.full = 4, 1                             # 2, 3, 4, 7, 8
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert _errores(m) == {}
    assert (m['k_saltos'], m['k_ultimo'], m['descartados']) == (5, 9, 5)
    rf.busy += 2                                        # 10 y 11, después del último
    m = lec.medir('verificar', _plazo(1), disparos=d)
    gen_cnt = 12
    assert m['k_saltos'] + (gen_cnt - 1 - m['k_ultimo']) == rf.busy + rf.full
    assert lec.estado['pendientes'] == 7                # medir no asigna gaps
    ring.close()


def test_medir_aleatorio_contra_la_prediccion_con_descartes():
    """El modo aleatorio de verdad: las marcas de `predecir`, con los slots que el
    ring descarta, y el ring dando la vuelta mientras C devuelve el crédito."""
    d = G.disparos(aleatorio=True, tasa=3e6, dt_min=5, n=300, semilla=7)
    pred = G.predecir(10 ** 6, OR.GEN_LAT_TS, n_max=300, **d)
    assert pred.size == 300
    perdidos = set(range(0, 300, 7)) | set(range(100, 140))
    cola = [k for k in range(300) if k not in perdidos]

    def generar(rf):
        if rf.gst != 1:
            return
        while cola and rf.wr - rf.rd < rf.n_slots:
            k = cola.pop(0)
            gen_slot(rf, k, int(pred[k]))
        # El hardware ya contó los perdidos de antes del próximo que entra.
        sig = cola[0] if cola else 300
        rf.busy = sum(1 for k in perdidos if k < sig)

    rf = RingFalso()
    rf.generar = generar
    rf, ring, lec = _medidor(rf)
    t_fin = time.time() + 5
    while time.time() < t_fin and lec.medida['eventos'] < 300 - len(perdidos):
        lec.medir('verificar', _plazo(2), disparos=d)
    m = lec.medida
    assert m['eventos'] == 300 - len(perdidos) and _errores(m) == {}
    assert m['k_saltos'] + (300 - 1 - m['k_ultimo']) == len(perdidos)
    assert m['descartados'] == len(perdidos)
    assert m['ocupacion_max'] <= N_SLOTS
    ring.close()


def test_medir_aleatorio_detecta_marcas_demasiado_juntas():
    rf, ring, lec = _medidor()
    d = G.disparos(aleatorio=True, tasa=1e6, dt_min=50, n=0, semilla=3)
    gen_slot(rf, 0, 60)
    gen_slot(rf, 2, 60 + 99)                            # 2 k en 99 ciclos: faltan 100
    gen_slot(rf, 3, 60 + 99 + 50)                       # justo dt_min: vale
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert _errores(m) == {'err_ts': 1} and m['primer_error_seq'] == 1
    ring.close()


def test_medir_sin_el_generador_solo_mira_que_avancen():
    rf, ring, lec = _medidor()
    for k, ts in ((0, 50), (1, 49), (3, 900)):           # ts para atrás
        gen_slot(rf, k, ts)
    m = lec.medir('verificar', _plazo(5))
    assert _errores(m) == {'err_ts': 1} and m['k_saltos'] == 1
    gen_slot(rf, 3, 1000)                                # k repetido
    gen_slot(rf, 4, 1100)
    m = lec.medir('verificar', _plazo(5))
    assert _errores(m) == {'err_ts': 1, 'err_k': 1} and m['k_ultimo'] == 4
    ring.close()


def test_medir_k_pasa_la_vuelta_de_16_bits():
    rf, ring, lec = _medidor()
    d = G.disparos(periodo=3, n=0)
    ks = [65533, 65535, 65536, 65537, 65540]
    for k in ks:
        gen_slot(rf, k, ts_per(k, 3))
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert _errores(m) == {} and m['k_ultimo'] == 65540
    assert m['k_saltos'] == 65533 + 1 + 2
    # Sin el motor, del snapshot solo: lo mismo mientras no falten 65 536 seguidos.
    rf, ring2, lec = _medidor()
    for k in ks:
        gen_slot(rf, k, ts_per(k, 3))
    m = lec.medir('verificar', _plazo(5))
    assert _errores(m) == {} and m['k_ultimo'] == 65540
    # 65 536 descartados justos: el mismo k16. El periódico lo resuelve por la marca.
    rf, ring3, lec = _medidor()
    for k in (5, 5 + 65536, 5 + 65537):
        gen_slot(rf, k, ts_per(k, 3))
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert _errores(m) == {} and m['k_ultimo'] == 5 + 65537
    assert m['k_saltos'] == 5 + 65535
    ring.close()
    ring2.close()
    ring3.close()


def test_medir_n_es_el_tope_de_k():
    rf, ring, lec = _medidor()
    d = G.disparos(periodo=100, n=3)
    for k in range(4):
        gen_slot(rf, k, ts_per(k, 100))
    m = lec.medir('verificar', _plazo(5), disparos=d)
    assert _errores(m) == {'err_k': 1} and m['primer_error_seq'] == 3
    ring.close()


def test_medir_no_mira_las_muestras_de_antes_del_arranque():
    """Lo que se vio en la placa: un disparo en ts = 2 con pre = 8 trae 6 muestras de
    la corrida anterior."""
    rf, ring, lec = _medidor()
    _, off = gen_slot(rf, 0, 2)
    viejo = np.arange(6138, 6144, dtype='<i2')
    for j in range(PRE - 2):
        rf.ddr[off + 32 + 4 * j:off + 36 + 4 * j] = np.frombuffer(
            struct.pack('<hh', viejo[j], ~viejo[j]), np.uint8)
    m = lec.medir('verificar', _plazo(5), disparos=G.disparos(aleatorio=True, tasa=3e6,
                                                               dt_min=5, n=10, semilla=7))
    assert _errores(m) == {}
    rf2, ring2, lec2 = _medidor()                       # la primera de después: sí
    _, off2 = gen_slot(rf2, 0, 2)
    rf2.ddr[off2 + 32 + 4 * (PRE - 2)] ^= 1
    assert _errores(lec2.medir('verificar', _plazo(5))) == dict(err_patron=1,
                                                               muestras_malas=1)
    ring.close()
    ring2.close()


def test_medir_el_patron_de_c_es_el_de_python():
    """Marcas al azar (también cruzando 2^14 y grandes), cada una con su patrón de
    `patron_gen`: C no encuentra errores; con una muestra cambiada en algunos slots,
    encuentra exactamente ésos."""
    rng = np.random.default_rng(5)
    ts = np.concatenate([[(1 << 14) - 3, (1 << 14) + 9],         # cruzan 2^14
                         (1 << 33) + np.cumsum(rng.integers(40, 30_000, 12))])
    malos = {2, 7, 11}
    rf, ring, lec = _medidor()
    for i, t in enumerate(ts):
        _, off = gen_slot(rf, i, int(t))
        if i in malos:
            j, ch = rng.integers(0, S), rng.integers(0, 2)
            rf.ddr[off + 32 + 4 * j + 2 * ch] ^= 1 << int(rng.integers(0, 8))
    m = lec.medir('verificar', _plazo(5))
    assert (m['err_patron'], m['muestras_malas'], m['primer_error_seq']) == (3, 3, 2)
    assert m['err_k'] == m['err_ts'] == 0
    ring.close()


def test_medir_modos_y_estado_invalidos():
    rf = RingFalso()
    lec = LectorRing(rf.handle(), PRE, POST, 2, [IDENTIDAD] * 2, slot_shift=SLOT_SHIFT)
    with pytest.raises(ValueError, match='no est'):
        lec.medir('creditos', _plazo(1))
    lec.configurar()
    with pytest.raises(ValueError, match='modo'):
        lec.medir('rapido', _plazo(1))
    with pytest.raises(ValueError, match='modo=3'):
        lec.medir(3, _plazo(1))
    with pytest.raises(ValueError, match='periodo = 1'):
        lec.medir('verificar', _plazo(1), disparos=G.disparos(periodo=1))


def test_medir_configurar_pone_la_medida_en_cero():
    rf, ring, lec = _medidor()
    gen_slot(rf, 0, 5, snap=0)
    assert lec.medir('verificar', _plazo(5))['err_marca'] == 1
    ring.parar()
    lec.configurar()
    m = lec.medida
    assert m['eventos'] == m['errores'] == 0
    assert m['k_ultimo'] == -1 and m['primer_error_seq'] is None
    ring.close()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
