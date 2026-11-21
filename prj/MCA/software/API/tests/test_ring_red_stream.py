"""El ring por red, sin placa: `EmisionRing` (osciloscope_ring_enviar) contra el ring
simulado con el generador (`API/ring_falso.py`), y del otro lado `API.ring_red`:
`RecepcionRing` guarda el stream y `convertir` lo pasa a los archivos de la sesión.

Lo que tiene que valer (docs/event_ring/salida_por_red.md):

- cada slot llega, en orden, con el patrón del generador muestra por muestra;
- las cuentas cierran: lo que contó el ring (EV_CNT) llegó, y los descartados que
  viajan en las cabeceras son DROP_BUSY + DROP_FULL;
- los archivos convertidos son los de la sesión: la misma verificación de la etapa C
  (`run_etapas_ring.verificar_archivos`) y el mismo invariante de `gap`;
- si la PC no se conecta o se va, la emisión termina sola y `parar()` igual para el
  ring.
"""
import json
import os
import socket
import sys
import threading
import time

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.join(_RAIZ, 'campanas'))

import API.generadores as G                                          # noqa: E402
import API.osciloscope_ring as OR                                    # noqa: E402
import API.ring_red as RR                                            # noqa: E402
import run_etapas_ring as R                                          # noqa: E402
from API.osciloscope import osciloscope_calibrar                     # noqa: E402
from API.osciloscope_store import archivos_de_corrida, load_chunk   # noqa: E402
from API.ring_falso import RingFalsoGen                              # noqa: E402

IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}
CALIB = [IDENTIDAD] * OR.N_CH_HW


class RemotoLocal:
    """Lo que `RecepcionRing` le pide al servidor (`ring.iniciar/estado/parar`), sin
    servidor: la `EmisionRing` en este proceso, sobre un ring simulado."""

    def __init__(self, rf=None, **kw_emision):
        self.rf = rf or RingFalsoGen()
        self.kw = kw_emision
        self.em = None

    def ring_iniciar(self, destino='red', **kw):
        assert destino == 'red'
        self.em = OR.EmisionRing(self.rf.handle(), host='127.0.0.1',
                                 **(kw | self.kw))
        return self.em.iniciar()

    def ring_estado(self):
        return self.em.estado()

    def ring_parar(self):
        return self.em.parar()


def _hasta_el_fin(estado, plazo_s=30.0):
    """Hasta que el motor terminó y salió todo lo que el ring escribió."""
    t_fin, fin_visto = time.monotonic() + plazo_s, False
    while time.monotonic() < t_fin:
        time.sleep(0.02)
        e = estado()
        assert e['motivo'] is None, e
        if e['hw'] is None:
            continue
        if fin_visto and e['stats']['n_read'] >= e['hw']['hw_ev_cnt']:
            return e
        fin_visto = e['hw']['hw_gen_terminado']
    raise TimeoutError('la emisión no terminó')


class Crudo:
    """Del otro lado del socket, sin `RecepcionRing`: todo el stream a un buffer."""

    def __init__(self, puerto):
        self.s = socket.create_connection(('127.0.0.1', puerto))
        self.datos = bytearray()
        self.hilo = threading.Thread(target=self._leer, daemon=True)
        self.hilo.start()

    def _leer(self):
        while True:
            b = self.s.recv(1 << 20)
            if not b:
                break
            self.datos.extend(b)

    def bloques(self):
        self.hilo.join(10)
        out, i = [], 0
        while i < len(self.datos):
            cab = RR.leer_cabecera(self.datos, i)
            i += OR.BLOQUE.size
            out.append((cab, bytes(self.datos[i:i + cab['bytes']])))
            i += cab['bytes']
        return out


def _emitir(rf=None, n=3000, tasa=1e5, **kw):
    rf = rf or RingFalsoGen()
    em = OR.EmisionRing(rf.handle(), pre=8, post=24, calib=CALIB, host='127.0.0.1',
                        generador=G.disparos(tasa=tasa, n=n), **kw)
    return em, rf


# -----------------------------------------------------------------------------
# El stream
# -----------------------------------------------------------------------------

def test_el_stream_trae_cada_slot_y_el_fin():
    em, _rf = _emitir()
    info = em.iniciar()
    assert info['carga'] == OR.carga_slot(8, 24) == 160
    assert info['calib'] == CALIB and info['bloque_version'] == OR.BLOQUE_VERSION
    rx = Crudo(info['puerto_datos'])
    _hasta_el_fin(em.estado)
    fin = em.parar()
    assert fin['error'] is None and fin['fin_enviado'] and fin['motivo'] is None
    hw = fin['hw_final']
    assert hw['hw_gen_cnt'] == 3000 and hw['hw_destrabe'] is None

    bloques = rx.bloques()
    cab_fin, contadores = bloques[-1]
    assert cab_fin['flags'] & OR.BLOQUE_FIN and cab_fin['n'] == 0
    k = dict(zip(OR.CONTADORES_CAMPOS, OR.CONTADORES.unpack(contadores)))
    datos = [(c, d) for c, d in bloques[:-1]]
    assert all(not c['flags'] & OR.BLOQUE_FIN for c, _ in datos)

    dt = RR._dtype_slot(info['carga'])
    slots = np.concatenate([np.frombuffer(d, dt) for _, d in datos])
    n = slots.size
    assert n == k['ev_cnt'] == hw['hw_ev_cnt'] == fin['stats']['eventos']
    # en orden, sin huecos, y cada bloque dice dónde empieza
    np.testing.assert_array_equal(slots['w1'] & 0xFFFFFFFF, np.arange(n))
    assert [c['seq0'] for c, _ in datos] == list(
        np.cumsum([0] + [c['n'] for c, _ in datos[:-1]]))
    # el patrón del generador, crudo (sin calibrar)
    ts = slots['ts']
    w = slots['m'][:, :64].reshape(n, 32, 2).transpose(0, 2, 1)
    antes = (ts[:, None] - 8 + np.arange(32)) < 0
    assert ((w == OR.patron_gen(ts, 8, 32)) | antes[:, None, :]).all()
    # los descartados que viajaron son los del hardware
    viajaron = sum(c['descartados'] for c, _ in bloques)
    assert viajaron == k['drop_busy'] + k['drop_full'] == fin['stats']['descartados']
    assert fin['stats']['asignados'] == viajaron
    assert hw['hw_ev_cnt'] + hw['hw_drop_busy'] + hw['hw_drop_full'] == 3000


def test_con_descartes_las_cuentas_viajan():
    """A más tasa de la que acepta la captura (2·S + 3 ciclos entre marcas) el ring
    descarta por ocupado: esos descartes viajan en las cabeceras y cierran."""
    em, _rf = _emitir(n=4000, tasa=5e6)
    info = em.iniciar()
    rx = Crudo(info['puerto_datos'])
    _hasta_el_fin(em.estado)
    fin = em.parar()
    hw = fin['hw_final']
    assert hw['hw_drop_busy'] > 0
    bloques = rx.bloques()
    viajaron = sum(c['descartados'] for c, _ in bloques)
    assert viajaron == hw['hw_drop_busy'] + hw['hw_drop_full']
    assert sum(c['n'] for c, _ in bloques) == hw['hw_ev_cnt']
    assert hw['hw_ev_cnt'] + viajaron == 4000


def test_sin_conexion_termina_sola_y_para_el_ring():
    em, rf = _emitir()
    em.aceptar_s = 0.3
    em.iniciar()
    t_fin = time.monotonic() + 5
    while em.estado()['motivo'] is None and time.monotonic() < t_fin:
        time.sleep(0.02)
    e = em.estado()
    assert e['motivo'] == 'sin_conexion' and 'nadie se conectó' in e['error']
    fin = em.parar()
    assert fin['motivo'] == 'sin_conexion' and not fin['fin_enviado']
    assert fin['stats']['eventos'] == 0
    assert rf.gst == 0                      # el ring quedó parado
    assert em.parar() is fin


def test_solo_acepta_al_que_la_pidio():
    em, _rf = _emitir(desde='10.0.0.1')
    em.aceptar_s = 0.5
    info = em.iniciar()
    s = socket.create_connection(('127.0.0.1', info['puerto_datos']))
    s.settimeout(2.0)
    assert s.recv(1) == b''                 # la cerró: no es de 10.0.0.1
    s.close()
    fin = em.parar()
    assert fin['stats']['eventos'] == 0


def test_si_la_pc_se_va_el_motivo_es_la_red():
    em, rf = _emitir(n=0, tasa=2e5)         # sin fin: sigue hasta que lo paren
    info = em.iniciar()
    s = socket.create_connection(('127.0.0.1', info['puerto_datos']))
    t_fin = time.monotonic() + 10
    while em.estado()['stats']['eventos'] < 500 and time.monotonic() < t_fin:
        s.recv(1 << 16)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b'\x01\x00\x00\x00\x00\x00\x00\x00')
    s.close()                               # RST: el próximo send falla
    while em.estado()['motivo'] is None and time.monotonic() < t_fin:
        time.sleep(0.02)
    e = em.estado()
    assert e['motivo'] == 'red', e
    fin = em.parar()
    assert fin['motivo'] == 'red' and not fin['fin_enviado']
    assert rf.gst == 0


def test_valida_antes_de_tocar_nada():
    rf = RingFalsoGen()
    with pytest.raises(ValueError, match='el estímulo es uno'):
        OR.EmisionRing(rf.handle(), calib=CALIB)
    with pytest.raises(ValueError, match='PRE y POST'):
        OR.EmisionRing(rf.handle(), pre=4000, generador=G.disparos(tasa=1e5),
                       calib=CALIB)
    em, _ = _emitir()
    with pytest.raises(RuntimeError, match='no se inició'):
        em.parar()


# -----------------------------------------------------------------------------
# La PC: recibir y convertir
# -----------------------------------------------------------------------------

def _recibir(tmp_path, n=3000, tasa=1e5, calib=CALIB, nombre='corrida', **kw):
    remoto = RemotoLocal()
    d = G.disparos(tasa=tasa, n=n)
    rec = RR.RecepcionRing(remoto, tmp_path / nombre, host='127.0.0.1', pre=8,
                           post=24, generador=d, calib=calib, **kw)
    rec.iniciar()
    _hasta_el_fin(remoto.ring_estado)
    return rec, rec.parar(), d


def test_recibir_guarda_el_stream_y_las_cuentas_cierran(tmp_path):
    rec, res, _ = _recibir(tmp_path, rotar_mb=0.1)
    assert res['error'] is None and res['cuentas']['ok'], res
    assert res['recibido']['eventos'] == res['fin_hw']['ev_cnt'] == 3000
    crudos = RR.archivos_crudos(rec.run_dir)
    assert len(crudos) > 1                  # rotó, y ningún .tmp quedó
    assert not [n for n in os.listdir(rec.run_dir) if n.endswith('.tmp')]
    with open(os.path.join(rec.run_dir, RR.RECEPCION)) as fh:
        assert json.load(fh)['cuentas']['ok']
    with open(os.path.join(rec.run_dir, RR.META)) as fh:
        meta = json.load(fh)
    assert meta['carga'] == 160 and meta['calib'] == CALIB


def test_convertir_da_los_archivos_de_la_sesion(tmp_path):
    rec, _res, d = _recibir(tmp_path, n=5000)
    res = RR.convertir(rec.run_dir, capacity=1024)
    assert res['n_read'] == res['n_written'] == 5000 and res['chunks'] == 5
    assert res['cuentas'] == dict(eventos_cierran=True, descartados_cierran=True)
    # la verificación de la etapa C, sin cambios
    v = R.verificar_archivos(rec.run_dir, d, 8, 24)
    assert v['errores'] == 0 and v['eventos'] == 5000
    # el esquema de la sesión
    datos, meta = load_chunk(archivos_de_corrida(rec.run_dir)[0])
    assert set(meta['fields']) == {'t_ns', 'wp', 'snap', 'gap', 'ts_hw', 'seq'}
    assert meta['source']['kind'] == 'ring_red' and (datos['wp'] == -1).all()
    assert datos['wave'].dtype == np.int16 and datos['wave'].shape == (1024, 2, 32)


def test_convertir_con_descartes_cierra_el_invariante_del_gap(tmp_path):
    rec, _res, _ = _recibir(tmp_path, n=4000, tasa=5e6)
    res = RR.convertir(rec.run_dir, capacity=512)
    assert res['n_dropped'] > 0 and res['cuentas']['descartados_cierran']
    total = 0
    for p in archivos_de_corrida(rec.run_dir):
        _, meta = load_chunk(p)
        total += meta['chunk_dropped']
    assert total + res['trailing_dropped'] == res['n_dropped']


def test_convertir_calibra_como_la_placa(tmp_path):
    """La calibración en la PC es la función de C de la placa: con una que no es la
    identidad, la onda es la del patrón calibrado, cuenta por cuenta."""
    cal = [{'gain': 30000, 'base': 32768, 'offset': 5},
           {'gain': 36000, 'base': 32768, 'offset': -7}]
    rec, _res, _ = _recibir(tmp_path, n=1000, calib=cal)
    RR.convertir(rec.run_dir, capacity=1000)
    datos, meta = load_chunk(archivos_de_corrida(rec.run_dir)[0])
    assert meta['source']['calib'] == cal
    pat = OR.patron_gen(datos['ts_hw'], 8, 32)
    for c in range(2):
        np.testing.assert_array_equal(datos['wave'][:, c, :],
                                      osciloscope_calibrar(cal[c], pat[:, c, :]))


def test_recibir_sin_guardar_no_escribe(tmp_path):
    rec, res, _ = _recibir(tmp_path, guardar=False)
    assert res['cuentas']['ok'] and res['recibido']['eventos'] == 3000
    assert not os.path.exists(rec.run_dir)


def test_una_carpeta_por_corrida(tmp_path):
    rec, _res, _ = _recibir(tmp_path)
    otra = RR.RecepcionRing(RemotoLocal(), rec.run_dir, host='127.0.0.1',
                            generador=G.disparos(tasa=1e5, n=10), calib=CALIB)
    with pytest.raises(FileExistsError, match='una carpeta por corrida'):
        otra.iniciar()


def test_lh5(tmp_path):
    pytest.importorskip('h5py')
    rec, _res, d = _recibir(tmp_path, n=2000)
    res = RR.convertir(rec.run_dir, formato='lh5', capacity=1000)
    assert res['n_written'] == 2000
    v = R.verificar_archivos(rec.run_dir, d, 8, 24)
    assert v['errores'] == 0 and v['eventos'] == 2000
