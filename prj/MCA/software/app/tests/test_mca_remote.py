#!/usr/bin/env python3
"""El handle remoto (`API/mca_remote.py`) contra el servidor en modo --fake.

Ésta es la prueba que sostiene el diseño: si la superficie `mca_*` ENTERA pasa
por socket sin que las funciones sepan que hay una red en el medio, entonces la
abstracción del handle es correcta y la GUI puede escribirse contra `API.mca` y
no contra un protocolo.

Levanta `app/mca_server.py --fake` en un puerto libre de loopback. No necesita
placa ni permisos.

    python app/tests/test_mca_remote.py
    python -m pytest app/tests/test_mca_remote.py -q
"""

import os
import socket
import threading
import subprocess
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
_SOFTWARE = _RAIZ
sys.path.insert(0, _SOFTWARE)

import API.mca as A                                                # noqa: E402
from API.mca_net import RemoteError                                # noqa: E402
from API.mca_remote import MCARemote                               # noqa: E402


# =============================================================================
# Servidor de prueba
# =============================================================================

def _puerto_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServidorDePrueba:
    """`mca_server.py --fake` en un subproceso.

    La espera al arranque se hace leyendo la línea "escuchando" de su stdout,
    NO abriendo un socket de sondeo: el servidor acepta un cliente a la vez, y
    el sondeo se gastaría el cupo justo antes de la prueba.

    `h_aw` elige la geometría del MCA simulado: 14 son los 16384 canales del
    bitstream viejo y 13 los 8192 del nuevo. El cliente lee la geometría del
    registro WIDTHS y no debería notar la diferencia — que es exactamente lo
    que hay que poder comprobar.
    """

    def __init__(self, h_aw=14, rsz=14):
        self.h_aw = h_aw
        self.rsz = rsz

    def __enter__(self):
        self.port = _puerto_libre()
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(_SOFTWARE, 'app', 'mca_server.py'),
             '--fake', '--host', '127.0.0.1', '--port', str(self.port),
             '--fake-h-aw', str(self.h_aw), '--fake-rsz', str(self.rsz)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.salida = []
        self._listo = threading.Event()
        threading.Thread(target=self._drenar, daemon=True).start()
        if not self._listo.wait(10.0):
            raise TimeoutError('el servidor no llegó a escuchar:\n' +
                               ''.join(self.salida))
        return self

    def _drenar(self):
        # Hay que vaciar la tubería igual: si se llena, el servidor se bloquea
        # en el print de la conexión siguiente.
        for linea in self.proc.stdout:
            self.salida.append(linea)
            if 'escuchando' in linea:
                self._listo.set()
        self._listo.set()

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def conectar(self):
        return MCARemote.connect('127.0.0.1', self.port, timeout=10.0)


# =============================================================================
# Pruebas
# =============================================================================

def test_identify_trae_la_geometria_del_hardware():
    """El cliente no hardcodea 16384: lo deriva de WIDTHS, como en la placa."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        info = A.mca_identify(h, verbose=False)
        assert info['magic'] == A.MAGIC
        assert (h.h_aw, h.h2_aw, h.psd_aw) == (14, 7, 6)
        assert info['n_channels'] == 16384
        assert info['map2d_shape'] == (128, 64)
        assert h._has_2d is True
        h.close()


def test_accesores_por_campo_por_red():
    """Los mca_get_/mca_set_ de API/mca.py, sin tocarlos, sobre el proxy."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        for setter, getter, valor in (
                (A.mca_set_n_acc,      A.mca_get_n_acc,        3),
                (A.mca_set_pre_dly,    A.mca_get_pre_dly,     42),
                (A.mca_set_trap_k,     A.mca_get_trap_k,      32),
                (A.mca_set_trap_mq,    A.mca_get_trap_mq,   3885),
                (A.mca_set_amp_min,    A.mca_get_amp_min,    100),
                (A.mca_set_amp_max,    A.mca_get_amp_max,  16300),
                (A.mca_set_q_shift,    A.mca_get_q_shift,      5),
                (A.mca_set_gate_long,  A.mca_get_gate_long,  400),
                (A.mca_set_channel,    A.mca_get_channel,      1),
        ):
            setter(h, valor)
            leido = getter(h)
            assert leido == valor, f'{getter.__name__}: puse {valor}, leí {leido}'
        h.close()


def test_read_modify_write_sobrevive_a_la_red():
    """`bl_k` y `bl_holdoff` comparten registro: el RMW son dos idas y vueltas
    y tiene que seguir siendo correcto."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_set_bl_holdoff(h, 0xBEEF)
        A.mca_set_bl_k(h, 13)
        A.mca_set_bl_auto(h, True)
        cfg = A.mca_get_config(h)
        assert (cfg['bl_holdoff'], cfg['bl_k'], cfg['bl_auto']) == (0xBEEF, 13, 1)

        A.mca_set_gate_short(h, 0x5678)
        A.mca_set_gate_long(h, 0x1234)
        cfg = A.mca_get_config(h)
        assert (cfg['gate_short'], cfg['gate_long']) == (0x5678, 0x1234)
        h.close()


def test_configure_en_bloque():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, n_acc=4, pre_dly=20, gate_long=300,
                        amp_src=1, q_shift=6, dec=1)
        cfg = A.mca_get_config(h)
        assert cfg['n_acc'] == 4 and cfg['amp_src'] == 1
        assert cfg['q_shift'] == 6 and cfg['pre_dly'] == 20
        h.close()


def test_configure_valida_del_lado_de_la_placa():
    """n_acc fuera de rango lo rechaza `mca_configure`, que corre en el
    servidor: el error tiene que volver con su tipo, no como un fallo de
    socket."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            A.mca_configure(h, n_acc=9)
        except RemoteError as e:
            assert e.error == 'ValueError'
            assert 'n_acc' in e.msg
        else:
            raise AssertionError('n_acc=9 pasó')
        h.close()


def test_adquisicion_y_espectro():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, n_acc=2)
        A.mca_clear(h)
        A.mca_start(h)
        assert A.mca_get_running(h) is True
        time.sleep(0.6)
        A.mca_stop(h)
        assert A.mca_get_running(h) is False

        hist = A.mca_read_histogram(h)
        assert hist.dtype == np.uint32 and hist.size == 16384
        assert hist.sum() > 0

        cnt = A.mca_read_counters(h)
        assert cnt['accepted'] == int(hist.sum())
        # MCA2: las ventanas con solape (`pileup`) se marcan y se histogramean
        # igual; el corte lo hace el discriminador.
        assert cnt['total'] == cnt['accepted'] + cnt['rej_amp']
        assert cnt['pileup'] <= cnt['total']
        assert cnt['livetime_s'] > 0
        assert abs(cnt['realtime_s'] - cnt['livetime_s'] - cnt['deadtime_s']) < 1e-6
        h.close()


def test_clear_borra_todo():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_start(h)
        time.sleep(0.3)
        A.mca_stop(h)
        assert A.mca_read_histogram(h).sum() > 0
        A.mca_clear(h)
        assert A.mca_read_histogram(h).sum() == 0
        assert A.mca_read_counters(h)['total'] == 0
        h.close()


def test_ventana_de_amplitud_recorta_el_pico():
    """El simulador respeta amp_min/amp_max, así que mover la ventana desde la
    GUI tiene que verse en el espectro y en rej_amp."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, amp_min=0, amp_max=0xFFFF)
        A.mca_clear(h)
        A.mca_start(h)
        time.sleep(0.4)
        A.mca_stop(h)
        assert A.mca_read_counters(h)['rej_amp'] == 0

        # La ventana es sobre la feature de 16 b, no sobre el canal: el pico
        # está en el canal ~8000 y el corte va en el 12000.
        A.mca_set_amp_min(h, A.mca_amplitud_de_canal(12000, h.h_aw))
        A.mca_clear(h)
        A.mca_start(h)
        time.sleep(0.4)
        A.mca_stop(h)
        cnt = A.mca_read_counters(h)
        assert cnt['rej_amp'] > 0
        assert cnt['accepted'] == 0
        h.close()


def test_mapa_2d():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_clear(h)
        A.mca_start(h)
        time.sleep(0.4)
        A.mca_stop(h)
        m = A.mca_read_map2d(h)
        assert m.shape == (128, 64) and m.dtype == np.uint32
        assert m.sum() > 0
        h.close()


def test_metadata_completa_y_guardado():
    """La metadata que viaja por red tiene que servir para escribir el MISMO
    fichero que se escribe en la placa, y `mca_load_file` releerlo."""
    import tempfile
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, n_acc=3, gate_long=400)
        A.mca_start(h)
        time.sleep(0.3)
        A.mca_stop(h)

        hist = A.mca_read_histogram(h)
        meta = A.mca_get_metadata(h)
        assert meta['n_acc'] == 3 and meta['n_channels'] == 16384
        assert meta['mapa'] == 'MCA2' and len(meta['t_ocup_s']) == 5
        assert meta['schema_version'] == A.SCHEMA_VERSION_MCA
        assert 'livetime_s' in meta and 'fs_hz' in meta

        with tempfile.TemporaryDirectory() as d:
            for nombre, guardar in (('e.csv',  A.mca_write_file_histogram),
                                    ('e.npz',  A.mca_save_file_binary),
                                    ('e.json', A.mca_save_file_json),
                                    ('e.n42',  A.mca_save_file_n42)):
                ruta = os.path.join(d, nombre)
                guardar(hist, ruta, meta=meta)
                h2, m2 = A.mca_load_file(ruta)
                assert np.array_equal(h2, hist), nombre
                assert m2['n_acc'] == 3, nombre
        h.close()


def test_acquire_heredado():
    """`MCA.acquire` no se redefine: se hereda y funciona sobre el proxy."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        spec, m2d, cnt = A.mca_read_acquire(h, seconds=0.4)
        assert spec.sum() > 0
        assert m2d is not None and m2d.shape == (128, 64)
        assert cnt['accepted'] > 0
        h.close()


def test_status_trae_tasas_y_exposicion():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_clear(h)
        h._pedir('ctrl.start', seconds=0.5)
        time.sleep(0.25)
        est = h.status()
        assert est['running'] is True
        assert est['exposure']['target_s'] is not None
        assert est['exposure']['left_s'] > 0
        time.sleep(0.6)
        est = h.status()
        assert est['running'] is False
        assert est['exposure']['done'] is True
        assert est['rate_avg_hz'] > 0
        h.close()


def test_la_tasa_de_entrada_descuenta_veto_y_rearmado():
    """λ̂ = (cross − lost_veto) / (real − veto − t_rearm), con números a mano.

    Los perdidos sin ranura y esperando al publicador SÍ cuentan como arribos:
    llegaron, aunque no se midieran.
    """
    from app.mca_server import arribos_y_tiempo
    cnt = {'cross': 1200, 'open': 900, 'lost_active': 150, 'lost_veto': 100,
           'realtime_s': 2.0, 'vetotime_s': 0.4, 't_rearm_s': 0.5,
           'accepted': 850, 'livetime_s': 0.9}
    arribos, seg = arribos_y_tiempo(cnt)
    assert arribos == 1100
    assert abs(seg - 1.1) < 1e-12
    # Un bitstream que no publica estos campos da cero, no una excepción.
    assert arribos_y_tiempo({}) == (0, 0.0)


def test_status_trae_la_tasa_de_entrada():
    """El MCA falso dispara a 1000/s sin veto ni re-armado: λ̂ tiene que dar eso.
    Con ~1 s de corrida son ~1000 arribos, σ ≈ 3 %."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_clear(h)
        h._pedir('ctrl.start', seconds=None)
        h.status()                          # la referencia de la instantánea
        time.sleep(1.0)
        est = h.status()
        h._pedir('ctrl.stop')
        assert abs(est['tasa_entrada_hz'] / 1000.0 - 1) < 0.2, est['tasa_entrada_hz']
        assert abs(est['tasa_entrada_inst_hz'] / 1000.0 - 1) < 0.2, \
            est['tasa_entrada_inst_hz']
        h.close()


def test_un_cliente_a_la_vez():
    """Dos procesos sobre /dev/mem es SIGBUS: el segundo cliente se rechaza."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            s.conectar()
        except RemoteError as e:
            assert e.error == 'Ocupado'
        else:
            raise AssertionError('el servidor aceptó un segundo cliente')
        h.close()


def test_operacion_desconocida():
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            h._pedir('borrar.todo')
        except RemoteError as e:
            assert e.error == 'ValueError' and 'desconocida' in e.msg
        else:
            raise AssertionError('el servidor aceptó una operación inventada')
        # y el canal sigue usable después del error
        assert A.mca_get_n_acc(h) >= 1
        h.close()


def test_load_bitstream_rechazado_en_fake():
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            h.load_bitstream()
        except RemoteError as e:
            assert e.error == 'RuntimeError'
        else:
            raise AssertionError('--fake aceptó cargar un bitstream')
        h.close()


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f'  ok    {fn.__name__}')
        except Exception as e:
            fallos += 1
            print(f'  FALLO {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(pruebas) - fallos}/{len(pruebas)} pruebas OK')
    return 1 if fallos else 0


if __name__ == '__main__':
    raise SystemExit(main())

def test_ops_documentadas_y_despacho_coinciden():
    """La tupla `OPS` de mca_net.py es documentacion y no se importa en ningun
    lado, asi que podia desincronizarse del despacho real sin que nada lo
    detectara. `docs/APP/pruebas.md` la listaba como "la prueba mas barata de
    las que faltan"; esta es.
    """
    from API.mca_net import OPS
    from app.mca_server import ServidorMCA

    documentadas = set(OPS)
    despachadas = set(ServidorMCA._OPS)
    assert documentadas == despachadas, (
        f'sólo en OPS (documentadas y no implementadas): '
        f'{sorted(documentadas - despachadas)}\n'
        f'sólo en _OPS (implementadas y no documentadas): '
        f'{sorted(despachadas - documentadas)}')


# =============================================================================
# Descubrimiento de bases por el registro SLOTS
# =============================================================================
#
# El multitrigger está en el slot 3 del top del MCA y en el 7 del
# `red_pitaya_top` clásico, así que una base hardcodeada hace que el mismo
# software mienta contra el otro bitstream. `Integration.slots()` publica el
# mapa real; lo que se prueba acá es que el servidor lo OBEDEZCA y lo diga.

class _IntegracionFalsa:
    """Sólo lo que `_base_de` usa: `base(modulo)`."""

    def __init__(self, bases=None, romper=False):
        self._bases = bases or {}
        self._romper = romper

    def base(self, modulo):
        if self._romper:
            raise RuntimeError('el bus no contesta')
        return self._bases[modulo]

    def close(self):
        pass


def _servidor_sin_arrancar():
    """Un `ServidorMCA` sin `__init__`: acá se prueba un método, no el ciclo de
    vida, y arrancarlo de verdad abriría hilos y sockets que no hacen falta."""
    from app.mca_server import ServidorMCA
    return ServidorMCA.__new__(ServidorMCA)


def test_el_impl_del_servidor_llega_a_todos_los_bloques_en_c():
    """`--impl py` compara las dos implementaciones de la API en la placa: si sólo
    llegara al MCA, la columna `py` mediría una mezcla sin decirlo."""
    import API.integration as I
    import API.multitrigger as MT
    import API.osciloscope as O
    pedidos = []

    def registrar(nombre):
        def abrir(*a, **k):
            pedidos.append((nombre, k.get('impl', 'falta')))
            return _IntegracionFalsa()
        return abrir

    originales = (I.integration_open, MT.MtRegion.__dict__['open'],
                  MT.MultiTrigger.__dict__['open'], O.osciloscope_open)
    I.integration_open = registrar('top')
    O.osciloscope_open = registrar('osc')
    MT.MtRegion.open = registrar('mtr')
    MT.MultiTrigger.open = registrar('mt')
    try:
        for impl in ('c', 'py', None):
            del pedidos[:]
            s = _servidor_sin_arrancar()
            s.fake, s.impl, s.notas_bases, s.bases = False, impl, [], {}
            s._abrir_integracion()
            s.ig = None
            s._abrir_osc()
            assert pedidos == [('top', impl), ('osc', impl), ('mtr', impl), ('mt', impl)], pedidos
    finally:
        (I.integration_open, MT.MtRegion.open, MT.MultiTrigger.open,
         O.osciloscope_open) = originales


def test_sin_slot_6_se_usa_la_base_por_defecto():
    from API.osciloscope import SCOPE_PHYS
    s = _servidor_sin_arrancar()
    s.ig = None
    base, nota = s._base_de('osc', SCOPE_PHYS)
    assert base == SCOPE_PHYS
    assert 'sin slot 6' in nota


def test_una_base_descubierta_distinta_gana_y_se_avisa():
    """El caso que motiva todo: otro top, otro slot. Se obedece lo descubierto
    y la discrepancia queda dicha — verla es cómo se diagnostica."""
    from API.osciloscope import SCOPE_PHYS
    otra = 0x4070_0000
    s = _servidor_sin_arrancar()
    s.ig = _IntegracionFalsa({'osc': otra})
    base, nota = s._base_de('osc', SCOPE_PHYS)
    assert base == otra, 'no se obedeció la base descubierta'
    assert 'DESCUBIERTA' in nota
    assert f'{otra:#x}' in nota and f'{SCOPE_PHYS:#x}' in nota


def test_una_base_descubierta_igual_no_alarma():
    from API.osciloscope import SCOPE_PHYS
    s = _servidor_sin_arrancar()
    s.ig = _IntegracionFalsa({'osc': SCOPE_PHYS})
    base, nota = s._base_de('osc', SCOPE_PHYS)
    assert base == SCOPE_PHYS
    assert 'coincide' in nota


def test_un_slots_ilegible_cae_a_la_constante_en_vez_de_romper():
    """Que el descubrimiento falle no puede dejar al servidor sin osciloscopio:
    la constante sigue siendo correcta para el bitstream de siempre."""
    from API.osciloscope import SCOPE_PHYS
    s = _servidor_sin_arrancar()
    s.ig = _IntegracionFalsa(romper=True)
    base, nota = s._base_de('osc', SCOPE_PHYS)
    assert base == SCOPE_PHYS
    assert 'ilegible' in nota


def test_identify_publica_los_bloques_y_sus_bases():
    """El cliente arma la interfaz con esto, nunca suponiendo."""
    with ServidorDePrueba() as s:
        h = MCARemote.connect('127.0.0.1', s.port)
        try:
            info = h.info
            assert info['has_osc'] is True
            assert info['has_mtrg'] is True
            assert info['has_integracion'] is False   # el fake no simula slot 6
            assert 'osc' in info['bases']
            assert info['bases_notas']
        finally:
            h.close()


def test_la_captura_viaja_como_binario():
    """Es la tercera operación con payload, después del espectro y el mapa 2D."""
    with ServidorDePrueba() as s:
        h = MCARemote.connect('127.0.0.1', s.port)
        try:
            meta, datos = h.capturar_osc(pre=64, post=192)
            assert meta['pre'] == 64 and meta['post'] == 192
            assert datos.shape == (2, 256)
            assert datos.dtype.name == 'float32'
            assert 't_captura' in meta, 'sin el instante no se puede marcar la tasa'
        finally:
            h.close()


def test_una_ventana_mas_grande_que_el_buffer_se_rechaza():
    """Del lado del SERVIDOR, no sólo en la GUI: pedirla por `nc` también falla."""
    from API.osciloscope import N_BUF
    with ServidorDePrueba() as s:
        h = MCARemote.connect('127.0.0.1', s.port)
        try:
            try:
                h.capturar_osc(pre=N_BUF, post=N_BUF)
            except RemoteError as e:
                assert 'no entra en el buffer' in str(e)
            else:
                raise AssertionError('aceptó una ventana que no entra')
        finally:
            h.close()


def test_el_limite_de_la_ventana_sigue_al_bitstream():
    """Con un anillo de 8192, una ventana de 16384 tiene que fallar.

    Es el caso que el `N_BUF` del módulo no podía cubrir, y el que el hardware
    NO reporta: las aperturas de BRAM están decodificadas por `sys_addr[19:16]`,
    o sea que su tamaño no cambia con `RSZ`; con RSZ=13 la mitad alta es un
    alias de la baja y pedir 16384 muestras devuelve el anillo DOS VECES, sin
    error. Si el límite se queda en la constante, la GUI ofrece ventanas que no
    existen y lo que dibuja es el buffer repetido.
    """
    with ServidorDePrueba(rsz=13) as s:
        h = MCARemote.connect('127.0.0.1', s.port)
        try:
            obj, _ = h._pedir('osc.get')
            assert obj['result']['n_buf'] == 8192, (
                'el servidor publica la constante en vez de la del scope')
            try:
                h.capturar_osc(pre=8192, post=8192)
            except RemoteError as e:
                assert 'de 8192 muestras' in str(e), str(e)
            else:
                raise AssertionError('aceptó 16384 sobre un anillo de 8192')
            meta, datos = h.capturar_osc(pre=64, post=192)   # y la que entra, entra
            assert datos.shape == (2, 256)
        finally:
            h.close()


# =============================================================================
# El generador de pulsos (slot 2) y el lazo digital
# =============================================================================

def test_el_generador_se_configura_y_relee_por_red():
    """`gen.configurar` con dos líneas arma la tabla sorteada, y `gen.get` la
    reconstruye: cada amplitud con la fracción de la tabla que ocupa."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        assert h.info['has_pulsos'] is True
        r = h.pedir('gen.configurar', cfg={
            'aleatorio': True, 'tasa': 20e3, 'dt_min': 3, 'tau_us': 2.0,
            'lineas': [[1500, 3], [4000, 1]], 'ruido': 1, 'ruido_sh': 6})
        (a1, p1), (a2, p2) = r['lineas']
        assert (a1, a2) == (1500, 4000)
        assert abs(p1 - 0.75) < 2e-3 and abs(p2 - 0.25) < 2e-3
        assert r['config']['amp_aleat'] == 1 and r['config']['aleatorio'] == 1
        assert abs(r['tasa_hz'] / 20e3 - 1) < 1e-3
        assert abs(r['tau_us'] - 2.0) < 0.01
        assert r['mq'] > 0 and r['estado']['generando'] is False

        # Una sola amplitud es fija: sin sorteo, una entrada.
        r = h.pedir('gen.configurar', cfg={'tasa': 1e3, 'lineas': [[-300, 1]]})
        assert r['lineas'] == [[-300, 1.0]]
        assert r['config']['amp_aleat'] == 0
        h.close()


def test_una_amplitud_fuera_de_rango_no_toca_el_generador():
    """La tabla se arma ANTES de escribir: un error deja la configuración de antes."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        antes = h.pedir('gen.configurar', cfg={'tasa': 5e3, 'lineas': [[1000, 1]]})
        try:
            h.pedir('gen.configurar', cfg={'tasa': 9e3,
                                            'lineas': [[1000, 1], [20000, 1]]})
        except RemoteError as e:
            assert e.error == 'ValueError', e
        else:
            raise AssertionError('aceptó una amplitud de 20000')
        assert h.pedir('gen.get')['config'] == antes['config']
        h.close()


def test_con_el_lazo_el_mca_ve_la_tasa_del_generador():
    """De punta a punta en el simulador: lazo + generador a 5000/s → λ̂ ≈ 5000;
    generador parado con el lazo → 0, porque el ADC queda desconectado. El status
    trae el estado del generador y el lazo."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_clear(h)
        h.pedir('gen.configurar', cfg={'aleatorio': True, 'tasa': 5000.0,
                                        'lineas': [[2000, 1]]})
        h.pedir('gen.lazo', on=True)
        h.pedir('gen.ctrl', que='arrancar')
        h._pedir('ctrl.start', seconds=None)
        h.status()
        time.sleep(1.0)
        est = h.status()
        assert est['gen']['lazo'] is True and est['gen']['generando'] is True
        assert abs(est['tasa_entrada_inst_hz'] / 5000.0 - 1) < 0.15, est

        h.pedir('gen.ctrl', que='parar')
        h.status()
        time.sleep(0.4)
        assert h.status()['tasa_entrada_inst_hz'] == 0.0
        h.pedir('gen.lazo', on=False)
        h._pedir('ctrl.stop')
        assert h.status()['gen']['lazo'] is False
        h.close()
