#!/usr/bin/env python3
"""Protocolo de red del MCA: una línea JSON de control, un bloque binario de datos.

El servidor (`app/mca_server.py`) corre en la Pitaya y es el único proceso que
toca /dev/mem; el cliente (`app/mcamon.py`) corre en la PC. Entre los dos va
esto.

Cada mensaje es UNA línea JSON UTF-8 terminada en '\\n', seguida opcionalmente
de `nbytes` crudos::

    ->  {"op": "read.spectrum", "args": {}}
    <-  {"ok": true, "result": {}, "nbytes": 65536, "dtype": "uint32",
         "shape": [16384]}
        <65536 bytes>
    <-  {"ok": false, "error": "MCANotPresent", "msg": "...", "hint": "..."}

Por qué mixto y no todo JSON: un espectro de 16384 canales son 64 KB en binario
y ~10x más en JSON, y del otro lado se arma con un `np.frombuffer` en vez de
parsear 16384 enteros. Por qué no todo binario: los comandos son pocos y raros,
y que se puedan leer con `nc` vale más que los bytes que ahorraría un formato
empaquetado.

El framing lo hace `Channel`. Hace falta un lector CON BUFFER porque se mezclan
líneas y bloques: un `sock.recv()` suelto se queda corto con 64 KB y se come el
principio de la cabecera siguiente.
"""

import json
import socket

import numpy as np

PORT_DEFAULT = 1001
PROTOCOL_VERSION = 1

# Una cabecera es una línea de JSON con un puñado de claves. Si llegan 64 KB
# sin un '\n', del otro lado no hay un cliente de este protocolo.
MAX_HEADER_BYTES = 1 << 16


# =============================================================================
# Operaciones
# =============================================================================
#
# `r32`/`w32` son las que sostienen todo lo demás: con esas dos, la subclase
# MCARemote hereda de `class MCA` el resto de la API sin reimplementarla. Las
# otras existen sólo para ahorrar idas y vueltas (config.get son 19 registros)
# o para que una secuencia sea atómica del lado de la placa (ctrl.clear poléa
# clear_busy cada 1 ms: por red serían decenas de vueltas).

OPS = (
    'identify',             # -> caps, widths, n_channels, map2d_shape, fpga_state
    'r32',                  # off            -> val
    'w32',                  # off, val
    'config.get',           # -> todos los campos de _CAMPOS
    'config.set',           # fields         -> config releída
    'ctrl.start',           # seconds=None, clear_first=False
    'ctrl.stop',
    'ctrl.clear',           # timeout_s
    'status',               # -> counters, running, tasas, exposición
    'read.spectrum',        # -> uint32[2**h_aw]        (binario)
    'read.map2d',           # -> uint32[2**h2_aw, 2**psd_aw] (binario)
    'read.metadata',        # -> mca_get_metadata()
    'read.last_event',
    'fpga.state',
    'fpga.load_bitstream',  # path
    # --- slot 6, opcional: un bitstream viejo no lo trae y el MCA anda igual ---
    'integracion.get',          # -> modules, slots, caps, routes, status, run
    'integracion.set_route',    # consumidor, tap, enable  -> el get de vuelta
    'integracion.reset_routes',
    'integracion.ctrl',         # que: run_on|run_off|clear|srst
)


class ProtocolError(RuntimeError):
    """La trama no se entiende, o la conexión se cortó a la mitad."""


class RemoteError(RuntimeError):
    """El otro lado contestó ok=false.

    Conserva el tipo de excepción original en `.error` para que el cliente
    pueda distinguir, por ejemplo, un MCANotPresent (hay que cargar el
    bitstream) de un TimeoutError (el barrido de borrado no terminó).
    """

    def __init__(self, error, msg, hint=None):
        super().__init__(f'{error}: {msg}' + (f' — {hint}' if hint else ''))
        self.error = error
        self.msg = msg
        self.hint = hint


# =============================================================================
# Framing
# =============================================================================

class Channel:
    """Un socket con framing de cabecera JSON + payload binario opcional.

    Se usan dos ficheros separados (`rb` y `wb`) en vez de un `makefile('rwb')`
    porque el par de lectura/escritura hereda el `readline()` genérico, que va
    byte a byte; el `BufferedReader` de 'rb' trae el suyo.
    """

    def __init__(self, sock):
        self.sock = sock
        self._r = sock.makefile('rb')
        self._w = sock.makefile('wb')

    @classmethod
    def connect(cls, host, port=PORT_DEFAULT, timeout=10.0):
        return cls(socket.create_connection((host, port), timeout=timeout))

    # ---------- envío ----------

    def send(self, obj, payload=None):
        cab = dict(obj)
        if payload is not None:
            cab['nbytes'] = len(payload)
        linea = json.dumps(cab, ensure_ascii=False).encode('utf-8')
        # json.dumps escapa los saltos de línea, así que esto no debería pasar
        # nunca; si pasa, es mejor romper acá que desincronizar el stream.
        if b'\n' in linea:
            raise ProtocolError('la cabecera JSON no puede llevar saltos de línea')
        self._w.write(linea + b'\n')
        if payload:
            self._w.write(payload)
        self._w.flush()

    def send_error(self, exc, hint=None):
        self.send({'ok': False, 'error': type(exc).__name__,
                   'msg': str(exc), 'hint': hint})

    def send_result(self, result=None, array=None):
        cab = {'ok': True, 'result': result if result is not None else {}}
        payload = None
        if array is not None:
            a = np.ascontiguousarray(array)
            cab['dtype'] = a.dtype.name
            cab['shape'] = list(a.shape)
            payload = a.tobytes()
        self.send(cab, payload)

    # ---------- recepción ----------

    def recv(self):
        """-> (cabecera, payload|None). Levanta ProtocolError si se cortó."""
        linea = self._r.readline(MAX_HEADER_BYTES)
        if not linea:
            raise ProtocolError('la conexión se cerró')
        if not linea.endswith(b'\n'):
            raise ProtocolError(
                f'cabecera de más de {MAX_HEADER_BYTES} B sin terminar')
        try:
            obj = json.loads(linea.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as e:
            raise ProtocolError(f'cabecera ilegible: {e}') from e
        if not isinstance(obj, dict):
            raise ProtocolError(f'la cabecera no es un objeto: {obj!r}')

        n = int(obj.get('nbytes') or 0)
        return obj, (self._read_exact(n) if n else None)

    def _read_exact(self, n):
        buf = self._r.read(n)
        if buf is None or len(buf) != n:
            got = 0 if buf is None else len(buf)
            raise ProtocolError(f'payload truncado: {got} de {n} B')
        return buf

    # ---------- cierre ----------

    def close(self):
        for f in (self._r, self._w):
            try:
                f.close()
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass


# =============================================================================
# Helpers
# =============================================================================

def array_desde(obj, payload):
    """Reconstruye el array de una respuesta con payload binario.

    Se copia a propósito: `np.frombuffer` sobre bytes devuelve un array de sólo
    lectura, y del otro lado hay una GUI que rebinea y recorta sobre él.
    """
    if payload is None:
        raise ProtocolError('se esperaba un payload binario y no vino')
    if 'dtype' not in obj or 'shape' not in obj:
        raise ProtocolError('el payload no declara dtype/shape')
    a = np.frombuffer(payload, dtype=np.dtype(obj['dtype']))
    return a.reshape(obj['shape']).copy()
