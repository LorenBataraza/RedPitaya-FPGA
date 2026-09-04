#!/usr/bin/env python3
"""Framing del protocolo de red del MCA (`API/mca_net.py`).

Lo que se prueba es lo que rompe en producción y no en una demo: que un payload
de 64 KB no se lea con un `recv` corto, que la cabecera siguiente no se coma el
final del bloque anterior, y que una conexión cortada a la mitad dé
ProtocolError en vez de un array de basura.

Corre en la PC, sin placa ni sockets de red: usa `socket.socketpair()`.

    python API/tests/test_mca_net.py
    python -m pytest API/tests/test_mca_net.py -q
"""

import os
import socket
import sys
import threading

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.mca_net import (Channel, ProtocolError,                   # noqa: E402
                         array_desde)


def _par():
    a, b = socket.socketpair()
    return Channel(a), Channel(b)


def test_ida_y_vuelta_sin_payload():
    ca, cb = _par()
    ca.send({'op': 'identify', 'args': {}})
    obj, payload = cb.recv()
    assert obj == {'op': 'identify', 'args': {}}
    assert payload is None
    ca.close()
    cb.close()


def test_payload_grande_llega_entero():
    """64 KB es más que el buffer de un recv suelto: si el lector no insiste,
    acá se ve."""
    ca, cb = _par()
    espectro = np.arange(16384, dtype=np.uint32) * 7

    hilo = threading.Thread(target=ca.send_result,
                            kwargs={'result': {}, 'array': espectro})
    hilo.start()
    obj, payload = cb.recv()
    hilo.join()

    assert obj['ok'] is True
    assert obj['nbytes'] == 65536
    vuelto = array_desde(obj, payload)
    assert vuelto.dtype == np.uint32
    assert np.array_equal(vuelto, espectro)
    ca.close()
    cb.close()


def test_dos_mensajes_seguidos_no_se_pisan():
    """El caso que rompe un lector sin buffer: el segundo `recv` tiene que
    empezar justo después del payload del primero, no en medio."""
    ca, cb = _par()
    m2d = np.arange(128 * 64, dtype=np.uint32).reshape(128, 64)

    def emisor():
        ca.send_result({'a': 1}, m2d)
        ca.send_result({'b': 2})
        ca.send_result({'c': 3}, np.zeros(4, dtype=np.uint32))
    hilo = threading.Thread(target=emisor)
    hilo.start()

    o1, p1 = cb.recv()
    o2, p2 = cb.recv()
    o3, p3 = cb.recv()
    hilo.join()

    assert np.array_equal(array_desde(o1, p1), m2d)
    assert o1['shape'] == [128, 64]
    assert o2['result'] == {'b': 2} and p2 is None
    assert o3['result'] == {'c': 3} and len(p3) == 16
    ca.close()
    cb.close()


def test_array_es_escribible():
    """np.frombuffer sobre bytes da un array de sólo lectura, y del otro lado
    hay una GUI que rebinea sobre él."""
    ca, cb = _par()
    hilo = threading.Thread(target=ca.send_result,
                            kwargs={'array': np.ones(8, dtype=np.uint32)})
    hilo.start()
    obj, payload = cb.recv()
    hilo.join()
    a = array_desde(obj, payload)
    a[0] = 5                      # no debe levantar ValueError
    assert a[0] == 5
    ca.close()
    cb.close()


def test_conexion_cerrada():
    ca, cb = _par()
    ca.close()
    try:
        cb.recv()
    except ProtocolError as e:
        assert 'cerr' in str(e)
    else:
        raise AssertionError('recv() sobre una conexión cerrada no avisó')
    cb.close()


def test_payload_truncado():
    """El emisor anuncia 1024 B y manda 10: tiene que dar ProtocolError, no un
    array corto que después se interprete como un espectro vacío."""
    ca, cb = _par()

    def emisor():
        ca.send({'ok': True, 'nbytes': 1024, 'dtype': 'uint32',
                 'shape': [256]})
        ca._w.write(b'0123456789')
        ca._w.flush()
        ca.close()
    hilo = threading.Thread(target=emisor)
    hilo.start()
    try:
        cb.recv()
    except ProtocolError as e:
        assert 'truncado' in str(e)
    else:
        raise AssertionError('un payload corto pasó como bueno')
    finally:
        hilo.join()
        cb.close()


def test_cabecera_ilegible():
    ca, cb = _par()

    def emisor():
        ca._w.write(b'esto no es json\n')
        ca._w.flush()
    hilo = threading.Thread(target=emisor)
    hilo.start()
    try:
        cb.recv()
    except ProtocolError as e:
        assert 'ilegible' in str(e)
    else:
        raise AssertionError('una cabecera basura pasó como buena')
    finally:
        hilo.join()
        ca.close()
        cb.close()


def test_error_lleva_tipo_y_pista():
    ca, cb = _par()
    hilo = threading.Thread(
        target=ca.send_error,
        args=(RuntimeError('no hay MCA'),),
        kwargs={'hint': 'cargá mca_red_pitaya.bit.bin'})
    hilo.start()
    obj, _ = cb.recv()
    hilo.join()
    assert obj['ok'] is False
    assert obj['error'] == 'RuntimeError'
    assert obj['hint'].endswith('.bit.bin')
    ca.close()
    cb.close()


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
