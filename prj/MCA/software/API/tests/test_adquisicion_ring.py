"""`AdquisicionRing` (API/osciloscope_ring.py): una adquisición del ring con su sesión,
la que corre el servidor con las ops `ring.*`, contra el ring simulado con el generador
(`API/ring_falso.py`). Y lo que la sostiene: `AcquisitionSession.motivo()`,
`destrabar` desde `RingSource.close()` y `sistema_de_archivos`.
"""
import os
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
from API.osciloscope_store import (AcquisitionSession, FakeSource,  # noqa: E402
                                   archivos_de_corrida, load_chunk)
from API.osciloscope_store.storage import sistema_de_archivos       # noqa: E402
from API.ring_falso import RingFalsoGen                              # noqa: E402

IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}
CALIB = [IDENTIDAD] * OR.N_CH_HW


def _hasta(adq, plazo_s=30.0):
    """Sondea como la campaña: hasta que el motor terminó y se leyó todo lo escrito."""
    t_fin, fin_visto = time.monotonic() + plazo_s, False
    while time.monotonic() < t_fin:
        time.sleep(0.02)
        e = adq.estado()
        assert e['corriendo'] and e['motivo'] is None, e
        if fin_visto and e['stats']['n_read'] >= e['hw']['hw_ev_cnt']:
            return e
        fin_visto = e['hw']['hw_gen_terminado']
    raise TimeoutError('la adquisición no terminó')


def _adq(tmp_path, rf=None, **kw):
    rf = rf or RingFalsoGen()
    kw = dict(pre=8, post=24, generador=G.disparos(tasa=1e5, n=2000), calib=CALIB,
              capacity=256) | kw
    return OR.AdquisicionRing(rf.handle(), str(tmp_path / 'corrida'), **kw), rf


# -----------------------------------------------------------------------------
# AdquisicionRing
# -----------------------------------------------------------------------------

def test_inicia_informa_y_para(tmp_path):
    adq, rf = _adq(tmp_path)
    assert adq.estado() == dict(corriendo=False, motivo=None, stats=None, hw=None,
                                error=None)
    info = adq.iniciar()
    assert info['run_dir'] == str(tmp_path / 'corrida')
    assert info['fs'] == sistema_de_archivos(tmp_path)
    assert info['n_slots'] == rf.n_slots and 'batches' in info['pool']
    _hasta(adq)
    fin = adq.parar()
    hw = fin['hw_final']
    assert fin['error'] is None and fin['motivo'] is None
    # la cuenta del generador cierra con el ring parado
    assert hw['hw_gen_cnt'] == 2000 and hw['hw_gen_terminado']
    assert hw['hw_ev_cnt'] + hw['hw_drop_busy'] + hw['hw_drop_full'] == 2000
    assert fin['stats']['n_read'] == fin['stats']['n_written'] == hw['hw_ev_cnt']
    assert hw['hw_destrabe'] is None
    assert fin['stats']['vaciado'] and not hw['hw_gen_cortado']
    # los archivos: el patrón del generador, con fs en el meta
    arch = archivos_de_corrida(fin['run_dir'])
    assert arch
    datos, meta = load_chunk(arch[0])
    assert meta['fs'] == info['fs'] and meta['source']['generador']['n'] == 2000
    ts = datos['ts_hw'][0]
    np.testing.assert_array_equal(datos['wave'][0], OR.patron_gen(ts, 8, 32))
    # idempotente, y el estado de después es el final
    assert adq.parar() is fin
    assert adq.estado() == dict(fin, corriendo=False)
    assert not adq.corriendo


def test_parar_vacia_el_ring_antes_de_pararlo(tmp_path):
    """Sin fin y con el ring lleno: `parar` corta el generador (N ← 1) con el ring
    corriendo, el lector se lleva lo que quedó, y recién ahí para el ring. Antes el
    lector paraba primero: lo de los últimos sondeos quedaba en la DDR, y el ring
    lleno no paraba sin destrabarlo."""
    rf = RingFalsoGen(ddr_bytes=16 * 256, trabado=True)
    adq, _ = _adq(tmp_path, rf, generador=G.disparos(tasa=1e6, n=0))
    adq.iniciar()
    time.sleep(0.3)
    fin = adq.parar()
    hw, st = fin['hw_final'], fin['stats']
    assert fin['error'] is None and st['vaciado']
    assert hw['hw_destrabe'] is None and hw['hw_no_leidos'] == 0
    assert hw['hw_drop_full'] > 0, 'el ring se llenó'
    assert st['n_read'] == st['n_written'] == hw['hw_ev_cnt']
    assert hw['hw_ev_cnt'] + hw['hw_drop_busy'] + hw['hw_drop_full'] == hw['hw_gen_cnt']
    assert hw['hw_gen_cortado'] and not hw['hw_gen_terminado']
    assert rf.gst == 0


def test_si_no_se_vacia_lo_dice(tmp_path, monkeypatch):
    import API.osciloscope_store.session as S

    monkeypatch.setattr(S, 'VACIAR_S', 0.05)
    adq, _ = _adq(tmp_path, generador=G.disparos(tasa=1e5, n=0))
    adq.iniciar()
    time.sleep(0.1)
    adq._src.vaciado = lambda: False
    fin = adq.parar()
    assert fin['stats']['vaciado'] is False
    assert 'al parar quedaron' in fin['error']


def _sin_lector(adq):
    """El lector se cae (un error, el disco): nadie vacía el ring."""
    adq._ses.reader.stop()
    adq._ses.reader.join(5)


def test_parar_con_el_ring_lleno_destraba(tmp_path):
    """El lector se cayó con el ring lleno: no hay vaciado, `parar` vence, se destraba
    devolviendo los créditos, y lo dice."""
    rf = RingFalsoGen(ddr_bytes=16 * 256, trabado=True)
    adq, _ = _adq(tmp_path, rf, generador=G.disparos(tasa=1e5, n=200_000))
    adq.iniciar()
    time.sleep(0.3)
    _sin_lector(adq)
    fin = adq.parar()
    assert fin['hw_final']['hw_destrabe'] == 'creditos'
    assert 'parar no terminó: el ring estaba lleno (creditos)' in fin['error']
    assert rf.gst == 0                       # quedó parado
    assert fin['hw_final']['hw_gen_cnt'] > 0  # los contadores de después de parar


def test_con_clr_quedan_los_contadores_de_antes_de_parar(tmp_path):
    """Si ni devolviendo los créditos para, `CTRL ← 0x2` borra los contadores: los de
    después de parar serían ceros, y `hw_final` tiene que quedarse con los de antes."""
    from API._libmca import LibMCAError

    rf = RingFalsoGen(ddr_bytes=16 * 256, trabado=True)
    adq, _ = _adq(tmp_path, rf, generador=G.disparos(tasa=1e5, n=200_000))
    adq.iniciar()
    time.sleep(0.3)

    def no_devuelve(*a, **k):
        raise LibMCAError('el lector no puede devolver', -1)

    adq._src._lector.medir = no_devuelve
    _sin_lector(adq)
    fin = adq.parar()
    hw = fin['hw_final']
    assert hw['hw_destrabe'] == 'clr' and rf.gst == 0
    assert 'parar no terminó: el ring estaba lleno (clr)' in fin['error']
    assert hw['hw_ev_cnt'] > 0 and hw['hw_gen_cnt'] > 0     # no los ceros del clr
    assert rf.ev == 0                                        # el clr sí los borró


def test_destrabar_dice_como(tmp_path):
    rf = RingFalsoGen(trabado=True)
    ring = rf.handle()
    assert OR.destrabar(ring, None) == 'parado'
    ring.w32(OR.R_CTRL, 1)                   # corriendo, sin nada sin leer: para
    assert OR.destrabar(ring, None) == 'creditos'
    ring.w32(OR.R_CTRL, 1)
    rf.wr = 1                                # un slot sin leer y nadie que lo devuelva
    assert OR.destrabar(ring, None) == 'clr'
    assert rf.gst == 0 and ('ring', OR.R_CTRL, 0x2) in rf.log


@pytest.mark.parametrize('kw, error', [
    (dict(run_dir='relativo/corrida'), 'absoluto'),
    (dict(run_dir='/no/existe/este/corrida'), 'no existe'),
    (dict(generador=None), 'el estímulo es uno'),
    (dict(disparo={'thr': 0.5}), 'el estímulo es uno'),
    (dict(generador=None, disparo={'thr': 0.5}), 'osciloscopio y el multitrigger'),
    (dict(generador=None, disparo={'umbral': 0.5}, osc=object(), mt=object()),
     r"no se conoce \['umbral'\]"),
])
def test_valida_antes_de_tocar_nada(tmp_path, kw, error):
    rf = RingFalsoGen()
    base = dict(pre=8, post=24, generador=G.disparos(tasa=1e5, n=10), calib=CALIB)
    run_dir = kw.pop('run_dir', str(tmp_path / 'c'))
    with pytest.raises((ValueError, FileNotFoundError), match=error):
        OR.AdquisicionRing(rf.handle(), run_dir, **(base | kw))
    assert rf.log == []                      # no escribió un registro


def test_iniciar_dos_veces_y_parar_sin_iniciar(tmp_path):
    adq, _ = _adq(tmp_path)
    with pytest.raises(RuntimeError, match='no se inició'):
        adq.parar()
    adq.iniciar()
    with pytest.raises(RuntimeError, match='ya se inició'):
        adq.iniciar()
    adq.parar()


def test_el_escritor_que_falla_es_el_motivo(tmp_path):
    adq, _ = _adq(tmp_path, generador=G.disparos(tasa=1e5, n=200_000), capacity=64)
    adq.iniciar()
    adq._ses.writer.error = RuntimeError('el NFS se fue')
    e = adq.estado()
    assert e['motivo'] == 'error' and 'el NFS se fue' in e['error']
    fin = adq.parar()
    assert fin['motivo'] == 'error' and 'el NFS se fue' in fin['error']


def test_un_disparo_que_no_arma_deja_el_ring_parado(tmp_path):
    class Roto:
        def arm_for_adc_trigger(self, **kw):
            raise OSError('sin multitrigger')

        def disarm(self):
            pass

    rf = RingFalsoGen()
    adq = OR.AdquisicionRing(rf.handle(), str(tmp_path / 'c'), generador=None,
                             disparo={'thr': 0.5}, osc=object(), mt=object(), calib=CALIB)
    OR._Disparo, viejo = (lambda osc, mt: Roto()), OR._Disparo
    try:
        with pytest.raises(OSError, match='sin multitrigger'):
            adq.iniciar()
    finally:
        OR._Disparo = viejo
    assert rf.gst == 0 and not adq.corriendo


# -----------------------------------------------------------------------------
# AcquisitionSession.motivo
# -----------------------------------------------------------------------------

def test_motivo_de_la_sesion(tmp_path):
    src = FakeSource(rate_hz=2000, pre=4, post=12, n_events=50)
    ses = AcquisitionSession(src, tmp_path / 's', capacity=16, verbose=False)
    ses.start()
    try:
        assert ses.motivo() is None
        assert ses.wait(n_events=50, poll_s=0.01) == 'events'
        t_fin = time.monotonic() + 5
        while ses.motivo() is None and time.monotonic() < t_fin:
            time.sleep(0.01)
        assert ses.motivo() == 'source'           # el lector terminó solo
        assert ses.wait(n_events=50) == 'events'  # pero wait prefiere 'events'
        ses.writer.disk_full.set()
        assert ses.motivo() == 'disk'
        ses.reader.error = RuntimeError('x')
        assert ses.motivo() == 'error'
    finally:
        ses.writer.disk_full.clear()
        ses.reader.error = None
        ses.stop()


# -----------------------------------------------------------------------------
# sistema_de_archivos
# -----------------------------------------------------------------------------

def test_sistema_de_archivos_toma_el_montaje_mas_largo(tmp_path):
    m = tmp_path / 'mounts'
    # la raíz al final: gana el montaje más largo, no el último que coincide
    m.write_text('tmpfs /dev/shm tmpfs rw 0 0\n'
                 '10.73.28.32:/home/x/pitaya_red /mnt/pc nfs rw,vers=3 0 0\n'
                 'host:/raro /mnt/con\\040espacio nfs rw 0 0\n'
                 '/dev/root / ext4 rw 0 0\n')
    assert sistema_de_archivos('/mnt/pc/etapas/c_8_24', m) == 'nfs'
    assert sistema_de_archivos('/mnt/pcx', m) == 'ext4'      # no es /mnt/pc
    assert sistema_de_archivos('/dev/shm/a', m) == 'tmpfs'
    assert sistema_de_archivos('/mnt/con espacio/a', m) == 'nfs'
    assert sistema_de_archivos('/root', tmp_path / 'no_hay') is None
