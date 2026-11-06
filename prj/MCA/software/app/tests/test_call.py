#!/usr/bin/env python3
"""La op `call`: cada función de la API da lo mismo por red que en la placa.

Corre la MISMA secuencia de operaciones sobre un `FakeMCA` local y sobre un
`MCARemote` conectado a `mca_server.py --fake` (que tiene otro `FakeMCA`, con
los mismos parámetros). Mientras no se adquiere, los dos modelos son
deterministas, así que cada paso tiene que dar:

  - el mismo resultado, con los mismos tipos (una tupla vuelve tupla, un bool
    vuelve bool) y los floats exactos;
  - la misma excepción: del lado remoto, una subclase de RemoteError Y del tipo
    original, con el mismo mensaje.

Y cubre TODAS las funciones que `@_api` registró con `remoto=True`: si se
agrega una y no se la ejercita acá, el test lo dice.

    python -m pytest app/tests/test_call.py -q
"""

import os
import sys

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

from test_mca_remote import ServidorDePrueba                       # noqa: E402

import API.mca as A                                                # noqa: E402
from API._despacho import API_REGISTRADA, NoRemota                 # noqa: E402
from API.mca_net import RemoteError                                # noqa: E402
from API.mca_remote import FakeMCA                                 # noqa: E402

REMOTAS = sorted(n for n, e in API_REGISTRADA.items()
                 if e.modulo == 'API.mca' and e.remoto)

# (función, args) en orden: setters válidos e inválidos, configure, control y
# lecturas. Los getters van todos, al final de cada bloque.
SETTERS = [
    ('mca_set_n_acc', (3,)), ('mca_set_n_acc', (9,)), ('mca_set_n_acc', (0,)),
    ('mca_set_pre_dly', (42,)), ('mca_set_pre_dly', (128,)),
    ('mca_set_trap_k', (32,)), ('mca_set_trap_k', (0,)),
    ('mca_set_trap_m', (16,)), ('mca_set_trap_mq', (3885,)),
    ('mca_set_trap_mq', (1 << 20,)), ('mca_set_trap_off', (40,)),
    ('mca_set_trap_lw', (3,)), ('mca_set_trap_sh', (9,)),
    ('mca_set_dec', (4,)), ('mca_set_dec', (0,)),
    ('mca_set_bl_k', (13,)), ('mca_set_bl_holdoff', (0xBEEF,)),
    ('mca_set_bl_auto', (True,)), ('mca_set_baseline', (123,)),
    ('mca_set_amp_min', (11,)), ('mca_set_amp_max', (0xABCD,)),
    ('mca_set_amp_src', (1,)), ('mca_set_q_shift', (5,)),
    ('mca_set_gate_short', (48,)), ('mca_set_gate_long', (400,)),
    ('mca_set_channel', (1,)),
    ('mca_set_sel_1d', ('integral',)), ('mca_set_sel_1d', (12,)),
    ('mca_set_sel_1d', ('trapecio',)),             # sin CAPS bit 2: error
    ('mca_set_sel_2dx', ('dt_anterior',)), ('mca_set_sel_2dy', ('solape',)),
    ('mca_set_zoom_1d_z', (30,)), ('mca_set_zoom_1d_k', (1,)),
    ('mca_set_zoom_2dx_z', (2,)), ('mca_set_zoom_2dx_k', (3,)),
    ('mca_set_zoom_2dy_z', (1,)), ('mca_set_zoom_2dy_k', (0,)),
    ('mca_set_discr_en', (True,)), ('mca_set_discr_ext', (False,)),
    ('mca_set_discr_sel', ('psd',)), ('mca_set_discr_min', (10,)),
    ('mca_set_discr_max', (900,)), ('mca_set_keep_if_full', (False,)),
    ('mca_set_sel_1d', ('forma',)),                # sin CAPS bit 2: error, como trapecio
]
# El banco de trapecios: cada campo con un valor que cabe y uno que no
SETTERS += [(f'mca_set_{n}', (v,)) for n in A._CAMPOS_BANCO for v in (5, 0x1FFFF)]
CONFIGURES = [
    {},
    dict(n_acc=4, pre_dly=20, gate_long=300, amp_src=1, q_shift=6,
         zoom_1d=(2, 1), discr=('psd', 10, 900), keep_if_full=False),
    dict(sel_2dy='dt_siguiente', discr=('pico', 500, 100, True)),
    dict(n_acc=5),                                  # error: N_ACC = 4
    dict(discr=('pico', 500, 100)),                 # error: intervalo vacío
    dict(trap_k=1000, trap_m=100),                  # error: k + m > 1023
]
CONTROL = [('mca_stop', ()), ('mca_clear', ()), ('mca_start', ()),
           ('mca_stop', ()), ('mca_clear', (0.5,))]
LECTURAS = [('mca_read_histogram', ()), ('mca_read_map2d', ()),
            ('mca_read_counters', ()), ('mca_read_last_event', ()),
            ('mca_identify', (False,))]


def _correr(fn):
    try:
        return ('ok', fn())
    except Exception as e:                                     # noqa: BLE001
        return ('exc', e)


def _iguales(a, b):
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return (isinstance(a, np.ndarray) and isinstance(b, np.ndarray)
                and a.dtype == b.dtype and a.shape == b.shape
                and np.array_equal(a, b))
    if isinstance(a, dict):
        return (isinstance(b, dict) and list(a) == list(b)
                and all(_iguales(a[k], b[k]) for k in a))
    if isinstance(a, (tuple, list)):
        return (type(a) is type(b) and len(a) == len(b)
                and all(_iguales(x, y) for x, y in zip(a, b)))
    return type(a) is type(b) and a == b


def _comparar(nombre, local, remoto, args):
    fn = getattr(A, nombre)
    rl = _correr(lambda: fn(local, *args))
    rr = _correr(lambda: fn(remoto, *args))
    caso = f'{nombre}{args!r}'
    assert rl[0] == rr[0], f'{caso}: local {rl}, remoto {rr}'
    if rl[0] == 'ok':
        assert _iguales(rl[1], rr[1]), f'{caso}:\n  local  {rl[1]!r}\n  remoto {rr[1]!r}'
    else:
        el, er = rl[1], rr[1]
        assert isinstance(er, RemoteError) and isinstance(er, type(el)), (
            f'{caso}: local {type(el).__name__}, remoto {type(er).__mro__}')
        assert er.msg == str(el), f'{caso}:\n  local  {el}\n  remoto {er.msg}'


@pytest.fixture(scope='module')
def par():
    with ServidorDePrueba() as s:
        remoto = s.conectar()
        local = FakeMCA()
        yield local, remoto
        remoto.close()
        local.close()


def test_cada_funcion_da_lo_mismo_por_red(par):
    local, remoto = par
    hechas = set()
    getters = [n for n in REMOTAS if n.startswith('mca_get_')]

    def todos_los_getters():
        for g in getters:
            _comparar(g, local, remoto, ())
            hechas.add(g)

    todos_los_getters()
    for nombre, args in SETTERS:
        _comparar(nombre, local, remoto, args)
        hechas.add(nombre)
    todos_los_getters()
    for kw in CONFIGURES:
        _comparar_configure(local, remoto, kw)
        hechas.add('mca_configure')
    todos_los_getters()
    for nombre, args in CONTROL + LECTURAS:
        _comparar(nombre, local, remoto, args)
        hechas.add(nombre)

    faltan = set(REMOTAS) - hechas
    assert not faltan, f'funciones remotas sin ejercitar: {sorted(faltan)}'


def _comparar_configure(local, remoto, kw):
    rl = _correr(lambda: A.mca_configure(local, **kw))
    rr = _correr(lambda: A.mca_configure(remoto, **kw))
    assert rl[0] == rr[0], f'configure {kw}: local {rl}, remoto {rr}'
    if rl[0] == 'exc':
        assert isinstance(rr[1], type(rl[1])) and rr[1].msg == str(rl[1])
    assert A.mca_get_config(local) == A.mca_get_config(remoto), kw


def test_lo_que_espera_no_viaja_por_call(par):
    _, remoto = par
    with pytest.raises(NoRemota):
        remoto.call('mca_read_acquire', 0)
    # ...pero la función anda: el proxy la arma del lado del cliente.
    spec, m2d, cnt = A.mca_read_acquire(remoto, 0.2)
    assert spec.size == 1 << remoto.h_aw and cnt['realtime_s'] > 0


def test_call_sólo_acepta_funciones_de_hardware_del_mca(par):
    _, remoto = par
    for fn in ('mca_write_file_histogram', 'mca_open', 'os.system',
               'mca_get_metadata'):
        with pytest.raises(ValueError, match='no es una función de hardware'):
            remoto.call(fn)


def test_un_timeout_remoto_no_parece_una_caida_del_transporte(par):
    """La GUI corta la conexión con un OSError: un TimeoutError del servidor
    tiene que volver como RemoteError, no como OSError."""
    from API.mca_remote import excepcion_remota
    e = excepcion_remota('TimeoutError', 'el barrido de borrado no terminó')
    assert isinstance(e, RemoteError) and not isinstance(e, OSError)
    e = excepcion_remota('ValueError', 'x')
    assert isinstance(e, RemoteError) and isinstance(e, ValueError)


def test_el_proxy_no_carga_libmca():
    """El cliente remoto no corre la biblioteca: en una PC sin el .so, conectar
    y usar la API por red tiene que andar."""
    import subprocess
    codigo = (
        'import sys; sys.path.insert(0, %r)\n'
        'import API._libmca as L\n'
        'L.cargar = lambda: (_ for _ in ()).throw(OSError("sin libmca"))\n'
        'from API.mca_remote import MCARemote\n'
        'import API.mca as A\n'
        'h = MCARemote.connect("127.0.0.1", %d)\n'
        'A.mca_set_n_acc(h, 2); assert A.mca_get_n_acc(h) == 2\n'
        'assert A.mca_read_histogram(h).size == 1 << h.h_aw\n'
        'h.close(); print("ok")\n')
    software = os.path.dirname(os.path.dirname(_AQUI))
    with ServidorDePrueba() as s:
        r = subprocess.run([sys.executable, '-c', codigo % (software, s.port)],
                           capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == 'ok', r.stdout + r.stderr


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
