"""El ring por red, del lado de la PC: recibir los slots de la placa y pasarlos a archivos.

La placa (`EmisionRing`, con `ring.iniciar(destino='red')`) manda los slots del
event_ring tal como están en la DDR, por un socket, desde un lazo de C y sin Python por
lote: es lo que saca a la sesión de Python del camino de los datos en la placa, donde
limitaba la tasa (docs/event_ring/salida_por_red.md). Acá hay dos pasos, a propósito:

1. **Recibir** (`RecepcionRing`): el stream va al disco tal cual llega, en
   `ring_NNNNNN.bin`. Por bloque, el hilo sólo lee la cabecera para contar y ver que
   los `seq` sigan; no toca los eventos. Así la PC no puede limitar la adquisición: si
   se atrasara, TCP frena a la placa, el ring se llena y el hardware descarta y cuenta
   (`DROP_FULL`); nunca hay una pérdida sin contar.
2. **Convertir** (`convertir`): después, o en otro proceso, los `.bin` pasan a los
   mismos `chunk_*.npz` (o `.lh5`) que escribe la sesión en la placa, con el mismo
   esquema (`t_ns`, `wp`, `snap`, `gap`, `ts_hw`, `seq`) y `run_summary.json`. El
   análisis no cambia. La calibración se hace acá, con la misma función de C que usa
   el lazo de la placa (`osciloscope_calibrar`): la onda sale igual, cuenta por cuenta.

    from API.mca_remote import MCARemote
    from API.ring_red import RecepcionRing, convertir

    h = MCARemote.connect('10.73.28.30', 1001)
    with RecepcionRing(h, '~/datos/corrida_01', pre=8, post=24,
                       generador=disparos(tasa=1e5)) as r:
        r.esperar(segundos=30)
    convertir('~/datos/corrida_01')

o desde la línea de comandos: `python3 -m API.ring_red recibir|convertir --help`.

El formato del stream (y de los `.bin`) es el de `osciloscope_ring_enviar`
(libmca/include/osciloscope_ring.h): por bloque, `BLOQUE` (40 B) y `bytes` de carga,
que son n slots de `carga` bytes (la cabecera del slot, 32 B, y las muestras crudas de
los dos canales del RTL, intercaladas). El último bloque es el FIN: n = 0 y los
contadores del ring.
"""

import argparse
import json
import os
import queue
import socket
import sys
import threading
import time

import numpy as np

if __package__ in (None, ''):                       # python3 API/ring_red.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from API.osciloscope import osciloscope_calibrar                     # noqa: E402
from API.osciloscope_ring import (BLOQUE, BLOQUE_CAMPOS, BLOQUE_FIN,  # noqa: E402
                                  BLOQUE_MAGIC, BLOQUE_VERSION, CONTADORES,
                                  CONTADORES_CAMPOS, HDR_BYTES, RING_FIELDS)
from API.osciloscope_store.events import BASE_FIELDS, make_pool      # noqa: E402
from API.osciloscope_store.storage import ChunkWriter                # noqa: E402

CRUDO = 'ring_{:06d}.bin'
META = 'ring_meta.json'
RECEPCION = 'recepcion.json'
RESUMEN = 'run_summary.json'


class StreamError(RuntimeError):
    """El stream de la placa no es lo que dice el formato: cortado, o una cabecera
    que no es de un bloque."""


def leer_cabecera(buf, offset=0):
    """La cabecera de un bloque como dict (`BLOQUE_CAMPOS`). StreamError si no es."""
    cab = dict(zip(BLOQUE_CAMPOS, BLOQUE.unpack_from(buf, offset)))
    if cab['magic'] != BLOQUE_MAGIC:
        raise StreamError(f'magic 0x{cab["magic"]:08X}: no es un bloque del ring '
                          f'(se esperaba 0x{BLOQUE_MAGIC:08X}, "RBLK")')
    if cab['version'] != BLOQUE_VERSION:
        raise StreamError(f'versión {cab["version"]} del bloque: este lector entiende '
                          f'la {BLOQUE_VERSION}')
    return cab


def _escribir_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(obj, fh, indent=2, default=str)
    os.replace(tmp, path)


def archivos_crudos(run_dir):
    """Los `ring_*.bin` completos de una corrida, en orden (nunca un `.tmp`)."""
    run_dir = os.fspath(run_dir)
    return sorted(os.path.join(run_dir, n) for n in os.listdir(run_dir)
                  if n.startswith('ring_') and n.endswith('.bin'))


# =============================================================================
# Recibir
# =============================================================================

class RecepcionRing:
    """Pide la emisión a la placa por el control (`remoto`, un `MCARemote`), se conecta
    al puerto de datos y guarda el stream en `run_dir`.

    - `run_dir` es de esta máquina; se crea, y no puede tener ya una corrida.
    - `host`: la IP de la placa (por defecto, la del control).
    - `guardar=False` recibe y descarta: el techo de la placa y la red, sin el disco
      (la etapa D0 de `campanas/run_etapas_ring.py`).
    - `rotar_mb`: cada cuánto se empieza otro `.bin` (siempre en un borde de bloque).
    - El resto (`pre`, `post`, `generador` o `disparo`, `calib`, `slot_shift`,
      `meta`) va a `ring.iniciar`.

    `iniciar()`, `estado()`, `esperar()` y `parar()`; o como context manager.
    """

    def __init__(self, remoto, run_dir, host=None, guardar=True, rotar_mb=256,
                 conectar_s=10.0, **args_ring):
        self.remoto = remoto
        self.run_dir = os.path.abspath(os.path.expanduser(os.fspath(run_dir)))
        self.host = host or remoto._canal.sock.getpeername()[0]
        self.guardar = guardar
        self.rotar = int(rotar_mb * 2 ** 20)
        self.conectar_s = conectar_s
        self.args = dict(args_ring)
        self.info = None
        self.fin_hw = None              # los contadores del FIN
        self.fin_placa = None           # lo que devolvió ring.parar
        self.error = None
        self.stats = dict(eventos=0, bloques=0, bytes=0, descartados=0, errores_seq=0,
                          archivos=0, fin=False, t0=None, t1=None)
        self._sock = self._hilo = self._fh = None
        self._tmp = None
        self._en_archivo = 0

    # -- ciclo de vida ------------------------------------------------------

    def iniciar(self):
        if self.info is not None:
            raise RuntimeError('esta recepción ya se inició')
        if self.guardar:
            os.makedirs(self.run_dir, exist_ok=True)
            hay = [n for n in os.listdir(self.run_dir)
                   if n.startswith(('ring_', 'chunk_', 'evt_')) or n == META]
            if hay:
                raise FileExistsError(f'{self.run_dir} ya tiene una corrida ({hay[0]}): '
                                      'una carpeta por corrida')
        info = self.remoto.ring_iniciar(destino='red', **self.args)
        self.info = info
        try:
            if self.guardar:
                _escribir_json(os.path.join(self.run_dir, META),
                               dict(info, host=self.host, args=self.args,
                                    t_wall=time.time(), guardar=self.guardar))
            s = socket.create_connection((self.host, info['puerto_datos']),
                                         timeout=self.conectar_s)
            s.settimeout(None)
        except BaseException:
            try:
                self.remoto.ring_parar()
            except Exception:           # noqa: BLE001 — el error que importa es el de arriba
                pass
            raise
        self._sock = s
        self._hilo = threading.Thread(target=self._recibir, name='ring-rx', daemon=True)
        self._hilo.start()
        return info

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, *exc):
        self.parar()
        return False

    # -- el hilo que recibe -------------------------------------------------

    def _leer(self, vista):
        """Llena `vista` entera. False si la placa cerró antes del primer byte;
        StreamError si cerró en el medio."""
        n, total = 0, len(vista)
        while n < total:
            r = self._sock.recv_into(vista[n:])
            if r == 0:
                if n == 0:
                    return False
                raise StreamError(f'la placa cerró a mitad de un bloque ({n} de {total} B)')
            n += r
        return True

    def _archivo(self):
        """El `.bin` donde va el próximo bloque: abre otro al pasar `rotar`."""
        if self._fh is not None and self._en_archivo >= self.rotar:
            self._cerrar_archivo()
        if self._fh is None:
            final = os.path.join(self.run_dir, CRUDO.format(self.stats['archivos']))
            self._tmp = final + '.tmp'
            self._fh = open(self._tmp, 'wb')
            self._en_archivo = 0
        return self._fh

    def _cerrar_archivo(self):
        if self._fh is None:
            return
        self._fh.close()
        os.replace(self._tmp, self._tmp[:-len('.tmp')])
        self._fh = None
        self.stats['archivos'] += 1

    def _recibir(self):
        try:
            self._lazo()
        except BaseException as exc:            # que no se muera en silencio
            self.error = exc
        finally:
            try:
                self._cerrar_archivo()
            finally:
                self._sock.close()

    def _lazo(self):
        st = self.stats
        cab_buf = bytearray(BLOQUE.size)
        cv = memoryview(cab_buf)
        datos = bytearray(1 << 20)
        dv = memoryview(datos)
        esperado = 0
        while True:
            if not self._leer(cv):
                raise StreamError('la placa cerró el stream sin el bloque FIN')
            cab = leer_cabecera(cab_buf)
            n_bytes = cab['bytes']
            if n_bytes > len(datos):
                datos = bytearray(n_bytes)
                dv = memoryview(datos)
            if n_bytes and not self._leer(dv[:n_bytes]):
                raise StreamError('la placa cerró después de una cabecera')
            if self.guardar:
                fh = self._archivo()
                fh.write(cv)
                fh.write(dv[:n_bytes])
                self._en_archivo += BLOQUE.size + n_bytes
            st['descartados'] += cab['descartados']
            if cab['flags'] & BLOQUE_FIN:
                self.fin_hw = dict(zip(CONTADORES_CAMPOS, CONTADORES.unpack_from(datos)))
                st['fin'] = True
                return
            if cab['n'] * cab['carga'] != n_bytes:
                raise StreamError(f'bloque de {cab["n"]} slots de {cab["carga"]} B con '
                                  f'{n_bytes} B de carga')
            if cab['seq0'] != esperado:
                st['errores_seq'] += 1
            esperado = (cab['seq0'] + cab['n']) & 0xFFFFFFFF
            ahora = time.perf_counter()
            if st['t0'] is None:
                st['t0'] = ahora
            st['t1'] = ahora
            st['eventos'] += cab['n']
            st['bloques'] += 1
            st['bytes'] += n_bytes

    # -- estado -------------------------------------------------------------

    def recibido(self):
        """Lo que llegó, con la tasa: `eventos`, `bloques`, `bytes`, `descartados`,
        `errores_seq`, `archivos`, `fin`, `tasa_ev_s` y `MB_s`."""
        st = dict(self.stats)
        t0, t1 = st.pop('t0'), st.pop('t1')
        dur = (t1 - t0) if t0 is not None and t1 is not None else 0.0
        st['tasa_ev_s'] = st['eventos'] / dur if dur > 0 else 0.0
        st['MB_s'] = st['bytes'] / dur / 1e6 if dur > 0 else 0.0
        return st

    def recibiendo(self):
        return self._hilo is not None and self._hilo.is_alive()

    def estado(self):
        """`recibido` (de este lado), `placa` (`ring.estado`) y `error`."""
        return dict(recibido=self.recibido(), placa=self.remoto.ring_estado(),
                    error=None if self.error is None else repr(self.error))

    def esperar(self, segundos=None, eventos=None, sondeo_s=0.2, on_tick=None):
        """Hasta `segundos`, `eventos` recibidos, o que algo falle. Devuelve el motivo:
        'duration' | 'events' | 'error' (de este lado) | 'placa' (la emisión terminó
        sola: sin conexión o la red cortada)."""
        t0 = time.monotonic()
        while True:
            if self.error is not None or not self.recibiendo():
                return 'error'
            if segundos is not None and time.monotonic() - t0 >= segundos:
                return 'duration'
            if eventos is not None and self.stats['eventos'] >= eventos:
                return 'events'
            e = self.remoto.ring_estado()
            if e.get('motivo') is not None:
                return 'placa'
            if on_tick:
                on_tick(self.recibido(), e)
            time.sleep(sondeo_s)

    def cuentas(self):
        """Lo que tiene que cerrar, con el FIN: todo lo que contó el ring llegó, y los
        descartados que llegaron son los del hardware. None lo que no se puede ver."""
        r, hw = self.stats, self.fin_hw
        out = dict(fin=r['fin'], seq_continuo=r['errores_seq'] == 0,
                   eventos_cierran=None, descartados_cierran=None)
        if hw is not None:
            out['eventos_cierran'] = hw['ev_cnt'] == r['eventos']
            out['descartados_cierran'] = (hw['drop_busy'] + hw['drop_full']
                                          == r['descartados'])
        out['ok'] = all(v is not False for v in out.values()) and r['fin']
        return out

    def parar(self):
        """Para la emisión en la placa (que corta el estímulo, manda lo que quedó y el
        FIN), espera el fin del stream y escribe `recepcion.json`. Devuelve ese dict."""
        if self.info is None:
            raise RuntimeError('esta recepción no se inició')
        fin = None
        try:
            fin = self.remoto.ring_parar()
        finally:
            if self._hilo is not None:
                self._hilo.join(timeout=30)
                if self._hilo.is_alive():
                    # La placa no cerró: se corta de este lado.
                    try:
                        self._sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self._hilo.join(timeout=5)
        self.fin_placa = fin
        resumen = dict(recibido=self.recibido(), fin_hw=self.fin_hw, placa=fin,
                       cuentas=self.cuentas(), host=self.host,
                       error=None if self.error is None else repr(self.error))
        if self.guardar:
            _escribir_json(os.path.join(self.run_dir, RECEPCION), resumen)
        return resumen


# =============================================================================
# Convertir
# =============================================================================

def bloques(path):
    """Los bloques de un `.bin`: `(cabecera, carga)`, la carga como memoryview."""
    with open(path, 'rb') as fh:
        datos = fh.read()
    vista = memoryview(datos)
    i = 0
    while i < len(datos):
        if i + BLOQUE.size > len(datos):
            raise StreamError(f'{path}: termina en el medio de una cabecera')
        cab = leer_cabecera(datos, i)
        i += BLOQUE.size
        if i + cab['bytes'] > len(datos):
            raise StreamError(f'{path}: termina en el medio de un bloque')
        yield cab, vista[i:i + cab['bytes']]
        i += cab['bytes']


def _dtype_slot(carga):
    """Un slot compactado como registro de numpy: la cabecera en cuatro palabras de 64
    b y las muestras intercaladas."""
    return np.dtype([('ts', '<i8'), ('w1', '<u8'), ('w2', '<u8'), ('w3', '<u8'),
                     ('m', '<i2', ((carga - HDR_BYTES) // 2,))])


def convertir(run_dir, formato='npz', capacity=4096, borrar_crudos=False):
    """Los `ring_*.bin` de `run_dir` a `chunk_*.npz` (o `evt_*.lh5`) y `run_summary.json`,
    con el esquema de la sesión de la placa: `wave` en cuentas calibradas, `t_ns` (el
    CLOCK_MONOTONIC de la placa al leer el bloque), `wp` = -1, `snap`, `gap` (los
    descartados del bloque, en su primer evento), `ts_hw` y `seq`. Los archivos los
    escribe `ChunkWriter`, el mismo de la sesión. Devuelve el resumen."""
    run_dir = os.path.abspath(os.path.expanduser(os.fspath(run_dir)))
    with open(os.path.join(run_dir, META)) as fh:
        meta = json.load(fh)
    crudos = archivos_crudos(run_dir)
    if not crudos:
        raise FileNotFoundError(f'{run_dir}: no hay ring_*.bin')
    pre, post, n_ch = meta['pre'], meta['post'], meta['n_ch']
    S, N, carga = pre + post, meta['n_ch_hw'], meta['carga']
    cal = meta['calib']
    dt = _dtype_slot(carga)
    fields = BASE_FIELDS + RING_FIELDS

    free_q, full_q = queue.Queue(), queue.Queue()
    for b in make_pool(3, capacity, n_ch, S, fields, np.int16):
        free_q.put(b)
    stats = dict(n_read=0, n_dropped=0, n_timeouts=0, n_written=0, chunks=0)
    fuente = dict(kind='ring_red', pre=pre, post=post, samples=S, n_ch=n_ch,
                  slot_shift=meta['slot_shift'], n_slots=meta['n_slots'],
                  adc_cnt_per_V=meta['adc_cnt_per_V'], dt_ns=meta['dt_ns'], calib=cal,
                  generador=meta.get('generador'), disparo=meta.get('disparo'),
                  wave='cuentas calibradas en la PC, con la cuenta de librp '
                       '(osciloscope_calibrar, la de la placa)',
                  t_ns='CLOCK_MONOTONIC de la placa al leer el bloque',
                  ts_hw='ciclos de 8 ns desde que arrancó el ring',
                  gap='descartes del hardware (DROP_BUSY + DROP_FULL), por bloque',
                  lector='libmca, por red (osciloscope_ring_enviar)', host=meta['host'])
    writer = ChunkWriter(run_dir, free_q, full_q, stats,
                         meta_base=dict(source=fuente, channels=list(range(1, n_ch + 1)),
                                        annotators=[], capacity=capacity, origen='red'),
                         wave_dtype=np.int16, wave_scale=meta['adc_cnt_per_V'],
                         formato=formato)
    writer.start()

    batch, trailing, fin_hw, errores_seq, esperado = None, 0, None, 0, 0
    try:
        for path in crudos:
            for cab, datos in bloques(path):
                stats['n_dropped'] += cab['descartados']
                if cab['flags'] & BLOQUE_FIN:
                    trailing = cab['descartados']
                    fin_hw = dict(zip(CONTADORES_CAMPOS, CONTADORES.unpack(datos)))
                    continue
                if cab['seq0'] != esperado:
                    errores_seq += 1
                esperado = (cab['seq0'] + cab['n']) & 0xFFFFFFFF
                slots = np.frombuffer(datos, dt)
                # muestras intercaladas: la j-ésima del canal k está en j·N + k
                m = slots['m'][:, :S * N].reshape(-1, S, N)
                pend, i, n = cab['descartados'], 0, len(slots)
                while i < n:
                    if batch is None:
                        batch = free_q.get()
                        batch.reset()
                    j0 = batch.n
                    k = min(n - i, capacity - j0)
                    j1 = j0 + k
                    sl = slots[i:i + k]
                    batch.ts_hw[j0:j1] = sl['ts']
                    batch.seq[j0:j1] = sl['w1'] & 0xFFFFFFFF
                    batch.snap[j0:j1] = sl['w2'] & 0x1FFFF
                    batch.t_ns[j0:j1] = cab['t_ns']
                    batch.wp[j0:j1] = -1
                    batch.gap[j0:j1] = 0
                    if pend:
                        batch.gap[j0] = min(pend, 255)
                        batch.dropped += pend
                        pend = 0
                    for c in range(n_ch):
                        batch.wave[j0:j1, c, :] = osciloscope_calibrar(cal[c],
                                                                       m[i:i + k, :, c])
                    batch.n = j1
                    stats['n_read'] += k
                    i += k
                    if batch.n == capacity:
                        full_q.put(batch)
                        batch = None
        if batch is not None:
            (full_q if batch.n else free_q).put(batch)
            batch = None
    finally:
        full_q.put(None)                 # centinela: cierra al escritor
        writer.join()
    if writer.error is not None:
        raise writer.error

    recepcion = None
    p = os.path.join(run_dir, RECEPCION)
    if os.path.isfile(p):
        with open(p) as fh:
            recepcion = json.load(fh)
    resumen = dict(stats, trailing_dropped=int(trailing), run_dir=run_dir,
                   source=fuente, formato=formato, capacity=capacity,
                   errores_seq=errores_seq, fin_hw=fin_hw, recepcion=recepcion,
                   crudos=[os.path.basename(c) for c in crudos])
    if fin_hw is not None:
        resumen['cuentas'] = dict(
            eventos_cierran=fin_hw['ev_cnt'] == stats['n_read'],
            descartados_cierran=fin_hw['drop_busy'] + fin_hw['drop_full']
            == stats['n_dropped'])
    _escribir_json(os.path.join(run_dir, RESUMEN), resumen)
    if borrar_crudos:
        for c in crudos:
            os.unlink(c)
    return resumen


# =============================================================================
# Línea de comandos
# =============================================================================

def _args_ring(a):
    from API.generadores import disparos

    out = dict(pre=a.pre, post=a.post)
    if a.generador is not None:
        out['generador'] = disparos(tasa=a.generador, aleatorio=a.aleatorio, n=a.n)
    else:
        out['disparo'] = dict(thr=a.thr, hyst=a.hyst)
    if a.slot_shift:
        out['slot_shift'] = a.slot_shift
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='modo', required=True)

    r = sub.add_parser('recibir', help='pide la emisión a la placa y guarda el stream')
    r.add_argument('--host', required=True, help='la IP de la placa')
    r.add_argument('--puerto', type=int, default=1001, help='el del servidor')
    r.add_argument('--dir', required=True, help='la carpeta de la corrida, en esta PC')
    r.add_argument('--segundos', type=float, default=10.0)
    r.add_argument('--pre', type=int, default=8)
    r.add_argument('--post', type=int, default=24)
    r.add_argument('--slot-shift', type=int, default=0)
    g = r.add_argument_group('estímulo (uno)')
    g.add_argument('--generador', type=float, default=None, metavar='TASA',
                   help='el generador de eventos del ring, a TASA disparos/s')
    g.add_argument('--aleatorio', action='store_true', help='con el generador: Poisson')
    g.add_argument('--n', type=int, default=0, help='con el generador: cuántos (0 = sin fin)')
    g.add_argument('--thr', type=float, default=0.05, help='el disparo real: umbral (V)')
    g.add_argument('--hyst', type=float, default=0.01)
    r.add_argument('--descartar', action='store_true',
                   help='recibir sin guardar: el techo de la placa y la red')
    r.add_argument('--convertir', action='store_true', help='y después a chunk_*.npz')
    r.add_argument('--formato', default='npz', choices=('npz', 'lh5'))

    c = sub.add_parser('convertir', help='ring_*.bin -> chunk_*.npz y run_summary.json')
    c.add_argument('dir')
    c.add_argument('--formato', default='npz', choices=('npz', 'lh5'))
    c.add_argument('--capacity', type=int, default=4096)
    c.add_argument('--borrar-crudos', action='store_true')

    a = p.parse_args(argv)
    if a.modo == 'convertir':
        res = convertir(a.dir, a.formato, a.capacity, a.borrar_crudos)
        print(json.dumps({k: res[k] for k in ('n_read', 'n_written', 'chunks',
                                               'n_dropped', 'trailing_dropped')}
                         | {'cuentas': res.get('cuentas')}, indent=2))
        return 0

    from API.mca_remote import MCARemote
    h = MCARemote.connect(a.host, a.puerto)
    try:
        rec = RecepcionRing(h, a.dir, host=a.host, guardar=not a.descartar,
                            **_args_ring(a))
        info = rec.iniciar()
        print(f"recibiendo de {a.host}:{info['puerto_datos']}, "
              f"{info['pre']}+{info['post']}, {info['carga']} B por slot")

        def tic(rx, _placa):
            print(f"  {rx['eventos']:>12} eventos  {rx['tasa_ev_s'] / 1e3:8.1f} k/s  "
                  f"{rx['MB_s']:6.1f} MB/s  descartados {rx['descartados']}",
                  flush=True)

        motivo = rec.esperar(segundos=a.segundos, on_tick=tic, sondeo_s=1.0)
        res = rec.parar()
    finally:
        h.close()
    print(json.dumps(dict(motivo=motivo, recibido=res['recibido'], cuentas=res['cuentas'],
                          error=res['error']), indent=2))
    if a.convertir and not a.descartar:
        conv = convertir(a.dir, a.formato)
        print(f"convertido: {conv['n_written']} eventos en {conv['chunks']} archivos")
    return 0 if res['cuentas']['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
