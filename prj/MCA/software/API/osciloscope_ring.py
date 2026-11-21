"""El event_ring en DDR (slot 2, 0x4020_0000): el handle de libmca y la fuente de eventos.

    from API.osciloscope_ring import OsciloscopeRing, RingSource

    src = RingSource(MultiTriggerScope.open(), pre=8, post=24)   # abre el ring solo
    AcquisitionSession(src, run_dir, ...).start()

**La lógica está en C** (`libmca/include/osciloscope_ring.h`), como el lazo de la
BRAM: el ring se configura, corre y se lee desde C, y el lazo por lote corre sin el
GIL. Acá quedan los tipos de ctypes, la detección de la región de DDR y `RingSource`,
que es la interfaz `EventSource` de `osciloscope_store/sources.py`.

Lo que hace el ring, y por qué se lee así (docs/event_ring/diseno_y_register_map.md):

- **Se re-arma solo.** El PS no está en el camino del disparo: la captura copia cada
  ventana a un slot de DDR y sigue. Lo que el PS no consume a tiempo lo descarta el
  hardware y lo cuenta (`DROP_FULL`); lo que dispara mientras se drena la anterior,
  también (`DROP_BUSY`). Esos contadores son el `gap`.
- **Se lee por bloque.** `WR_SLOT` (una lectura del bus) dice cuántos slots cerró el
  writer, y el footer `{~seq, seq}` de cada uno, en la DDR, confirma que llegó. El
  crédito (`RD_SLOT`) se devuelve una vez por bloque, no por evento: publicarlo por
  evento devolvería el bus al camino crítico. Medido desde Python en la placa, leer
  un slot suelto costaba 27 µs y en bloques de 64 KB, 2.3 µs por slot.

Lo que cambió con la Parte 7 del plan de libmca, respecto del `RingSource` de Python:

- `read_batch` por lote, en C, en vez de `wait_event`/`snapshot`/`read_into`/`rearm`;
- `snap` es el del MISMO slot. El lector por evento pedía `snapshot()` antes de
  `read_into()`, y el de aquella fuente salía del slot leído antes: el anterior;
- columnas `ts_hw` (la marca de la cabecera, ciclos de 8 ns desde que arrancó el ring,
  que antes se descartaba) y `seq`, que antes caía en `wp`. `wp` es -1: el ring no
  tiene `wp_trig`;
- `wave` en cuentas calibradas (int16), las mismas de la BRAM: antes, volts sin
  calibrar;
- el footer se valida ANTES de leer los datos, y los footers de la corrida anterior se
  borran al configurar (ver la cabecera de `libmca/src/osciloscope_ring.c`).

**Por red** (libmca 0.12.0): `EmisionRing` manda los slots por un socket desde C
(`osciloscope_ring_enviar`), sin sesión ni archivos en la placa, y la PC los recibe con
`API.ring_red`. Ver docs/event_ring/salida_por_red.md, «El ring por red».

**En la placa** (bitstreams del ring del 2026-11-09): `make verificar-placa-ring`, con
disparos por software (`test_ring_source_placa.py` usa esta API; `hw_ring_swtrig.py`
no, a propósito). El generador de eventos (`gen_*`, desde libmca 0.9.0) se prueba con
`make verificar-placa-generadores`, que pasó en la placa el 2026-11-09.
"""

import ctypes
import operator
import os
import socket
import struct
import threading
import time

import numpy as np

from API import _libmca
from API import generadores as _gen
from API._libmca import Bus, Mem
from API.osciloscope import (APERTURAS_DECODIFICADAS, _AdcCal, _LoteRes, _cal_dict,
                             _cargar_cal, calibracion_adc)
from API.osciloscope_store.events import BASE_FIELDS

# --- registros del event_ring (slot 2) --------------------------------------
RING_PHYS = 0x4020_0000
RING_SIZE = 0x1000

R_CTRL, R_STATUS = 0x00, 0x04
R_SLOT_BASE, R_RING_SZ, R_SLOT_SHIFT = 0x08, 0x0C, 0x10
R_PRE, R_POST = 0x14, 0x18
R_WR_SLOT, R_RD_SLOT, R_SEQ, R_N_SLOTS = 0x20, 0x24, 0x28, 0x2C
R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_LVL = 0x30, 0x34, 0x38, 0x3C
R_TS_LO, R_TS_HI, R_AXI_ADDR, R_MAGIC = 0x40, 0x44, 0x48, 0x50

MAGIC = 0x45564E54  # "EVNT"

# --- el generador de eventos (gen_eventos.sv, EN_GEN = 1; leen 0 sin él) -----
R_GEN_CTRL, R_GEN_PERIODO, R_GEN_UMBRAL = 0x100, 0x104, 0x108
R_GEN_DT_MIN, R_GEN_N, R_GEN_SEMILLA = 0x10C, 0x110, 0x114
R_GEN_CNT, R_GEN_ESTADO, R_GEN_MAGIC = 0x118, 0x11C, 0x120

GEN_MAGIC = 0x47454E31      # "GEN1"
GEN_CTRL_EN, GEN_CTRL_ALEATORIO, GEN_CTRL_PATRON = 1 << 0, 1 << 1, 1 << 2
GEN_LAT_TS = 2              # de la decisión a la marca del slot: el `lat` de predecir
GEN_SNAP_MARCA = 1 << 16    # el snapshot de un evento generado: {1, k[15:0]}

# Los modos de `LectorRing.medir` (osciloscope_ring_medir): las etapas de
# docs/event_ring/generador.md §6.
MEDIR_CREDITOS = 0          # etapa A: RD_SLOT <- WR_SLOT, sin tocar la DDR
MEDIR_COPIA = 1             # el footer y la copia de cada slot, sin mirarla
MEDIR_VERIFICAR = 2         # etapa B: la copia, y el slot del generador verificado en C
MODOS_MEDIR = {'creditos': MEDIR_CREDITOS, 'copia': MEDIR_COPIA,
               'verificar': MEDIR_VERIFICAR}

CTRL_RUN, CTRL_CLR = 1 << 0, 1 << 1
ST_ESTADO = 0x3                 # 0 parado, 1 corriendo, 2 drenando
ST_SIN_CREDITO, ST_ERR_CFG, ST_ERR_SLOT, ST_ERR_FIFO = 1 << 4, 1 << 5, 1 << 6, 1 << 7

ADC_CNT_PER_V = 8192        # escala LV (+-1 V), la misma que BramSource
DT_NS = 8.0                 # el ring toma la muestra antes de la decimación: 125 MS/s
HDR_BYTES = 32              # 4 palabras de 64 b
FOOTER_BYTES = 8

# 64 KB fue el óptimo medido en placa, desde Python (ver el docstring del módulo).
MAX_BATCH_BYTES = 64 * 1024

# El ring por red (`osciloscope_ring_enviar`, docs/event_ring/salida_por_red.md): cada
# bloque es esta cabecera de 40 B y `bytes` de carga, n slots compactados de `carga`
# bytes (la cabecera del slot y las muestras crudas de los N_CH_HW canales). El FIN
# trae n = 0 y, como carga, los contadores del ring (CONTADORES, en el orden de
# osciloscope_ring_contadores_t).
BLOQUE = struct.Struct('<IHHIIIIQq')
BLOQUE_CAMPOS = ('magic', 'version', 'flags', 'seq0', 'n', 'carga', 'bytes',
                 'descartados', 't_ns')
BLOQUE_MAGIC = 0x4B4C4252   # "RBLK"
BLOQUE_VERSION = 1
BLOQUE_FIN = 1 << 0
CONTADORES = struct.Struct('<10IQ')
CONTADORES_CAMPOS = ('status', 'ev_cnt', 'drop_busy', 'drop_full', 'wr_slot', 'rd_slot',
                     'seq', 'n_slots', 'lvl', 'axi_addr', 'ts')


def carga_slot(pre, post):
    """Los bytes de un slot en el cable: la cabecera y las muestras de los N_CH_HW
    canales, redondeadas a 8 (sin el relleno hasta 2^slot_shift ni el footer)."""
    return HDR_BYTES + (((pre + post) * N_CH_HW * 2 + 7) & ~7)

# Lo que construye event_ring_red_pitaya_top. El RTL escribe siempre N_CH_HW canales.
N_CH_HW = 2
PRE_BUF_WORDS = 1 << 11     # pre-buffer de la captura, palabras de N_CH muestras
STAGE_SAMPLES = 1 << 12     # cola de muestras del stage

# Las columnas que el ring agrega a BASE_FIELDS.
RING_FIELDS = (('ts_hw', np.int64), ('seq', np.uint32))

# La región reservada del device tree. Este RP OS (2.00) trae dos, sin tocar nada:
#   buffer@1000000  0x0100_0000   2 MB   (deep memory del ADC, rp_AcqAxi)
#   labuf@a000000   0x0A00_0000  32 MB   (buffer del analizador lógico)
# Se usa labuf por tamaño. Es prestada: si corre la app del analizador lógico al
# mismo tiempo, se pisan. Para producción conviene un nodo propio.
DT_RESERVED = '/sys/firmware/devicetree/base/reserved-memory'
PREFER_REGIONS = ('labuf@a000000', 'buffer@1000000')


class RingNotPresent(RuntimeError):
    """El bitstream cargado no tiene el event_ring en el slot 2."""


def region_ddr():
    """`(phys, size)` de la región de DDR donde escribe el ring.

    `$RING_DDR` ("0xADDR:SIZE") si está; si no, la primera de PREFER_REGIONS que
    exista en el device tree. FileNotFoundError si no hay ninguna (en la PC, siempre).
    """
    env = os.environ.get('RING_DDR')
    if env:
        a, s = env.split(':')
        return int(a, 0), int(s, 0)
    for nombre in PREFER_REGIONS:
        reg = os.path.join(DT_RESERVED, nombre, 'reg')
        if os.path.isfile(reg):
            with open(reg, 'rb') as fh:
                return struct.unpack('>II', fh.read(8))
    raise FileNotFoundError(
        'no hay ninguna región reservada en el device tree '
        f'({", ".join(PREFER_REGIONS)}): forzarla con RING_DDR=0xADDR:SIZE')


# =============================================================================
# Los tipos de C
# =============================================================================

_U, _I32, _I64 = ctypes.c_uint32, ctypes.c_int32, ctypes.c_int64
_P, _PP = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
_PU = ctypes.POINTER(_U)


class _Cfg(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('pre', 'post', 'n_ch', 'dw', 'slot_shift',
                                  'ring_bytes', 'lote_bytes', 'reservado')] + [
        ('cal', _AdcCal * APERTURAS_DECODIFICADAS)]


class _Geo(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('muestras', 'slot_shift', 'slot_bytes', 'n_slots',
                                  'ring_bytes', 'lote_slots')]


class _Estado(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('next', 'publicado', 'slot_shift', 'n_slots',
                                  'drop_prev', 'reservado')] + [
        ('pendientes', ctypes.c_uint64)]


_PS, _PL, _PI = (ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_int64),
                 ctypes.POINTER(ctypes.c_int32))

# Las columnas que llena `osciloscope_ring_leer_lote`, con su tipo en C, en el orden
# del struct.
_COLUMNAS = (('wave', np.int16, _PS), ('t_ns', np.int64, _PL), ('wp', np.int32, _PI),
             ('snap', np.uint32, _PU), ('gap', np.uint8, ctypes.POINTER(ctypes.c_uint8)),
             ('dead_ns', np.int64, _PL), ('ts_hw', np.int64, _PL), ('seq', np.uint32, _PU))


class _Lote(ctypes.Structure):
    _fields_ = [(nombre, ptr) for nombre, _, ptr in _COLUMNAS]


class _Cont(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('status', 'ev_cnt', 'drop_busy', 'drop_full',
                                  'wr_slot', 'rd_slot', 'seq', 'n_slots', 'lvl',
                                  'axi_addr')] + [('ts', ctypes.c_uint64)]


class _Medida(ctypes.Structure):
    _fields_ = ([(k, ctypes.c_uint64) for k in ('eventos', 'bytes', 'sondeos', 'bloques',
                                                'descartados')]
                + [(k, _I64) for k in ('t0_ns', 't1_ns', 'trabajo_ns')]
                + [('ocupacion_max', _U), ('primer_error_seq', _U)]
                + [(k, ctypes.c_uint64) for k in ('err_cabecera', 'err_marca', 'err_k',
                                                  'err_ts', 'err_patron', 'muestras_malas',
                                                  'k_saltos')]
                + [('k_ultimo', _I64), ('ts_ultimo', _I64)])


class _Envio(ctypes.Structure):
    _fields_ = ([(k, ctypes.c_uint64) for k in ('eventos', 'bytes', 'sondeos', 'bloques',
                                                'descartados', 'asignados')]
                + [(k, _I64) for k in ('t0_ns', 't1_ns', 'copia_ns', 'envio_ns')]
                + [('ocupacion_max', _U), ('reservado', _U)])


class _Reg(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U)]


_lib = None


def _cargar():
    """libmca con las firmas del ring declaradas. OSError si no está o es vieja."""
    global _lib
    if _lib is not None:
        return _lib
    lib = _libmca.cargar()
    if not hasattr(lib, 'osciloscope_ring_leer_lote'):
        raise OSError('libmca no tiene osciloscope_ring_*: el .so es de otra versión. '
                      'Recompilarla: `make -C libmca`.')

    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)

    c = ctypes.c_int
    pcfg, pst = ctypes.POINTER(_Cfg), ctypes.POINTER(_Estado)
    f('osciloscope_ring_open', c, _PP, _U, _U, _U, _U, c)
    f('osciloscope_ring_open_bus', c, _PP, _P, c, _P, c, c)
    f('osciloscope_ring_close', None, _P)
    f('osciloscope_ring_last_error', ctypes.c_char_p, _P)
    f('osciloscope_ring_reg_count', _I32)
    f('osciloscope_ring_reg_info', ctypes.POINTER(_Reg), _I32)
    f('osciloscope_ring_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    f('osciloscope_ring_r32', c, _P, _U, _PU)
    f('osciloscope_ring_w32', c, _P, _U, _U)
    f('osciloscope_ring_ddr', c, _P, _PU, _PU)
    f('osciloscope_ring_geometria', c, pcfg, _U, ctypes.POINTER(_Geo))
    f('osciloscope_ring_configurar', c, _P, pcfg, pst)
    f('osciloscope_ring_correr', c, _P)
    f('osciloscope_ring_parar', c, _P, _I64)
    f('osciloscope_ring_contadores', c, _P, ctypes.POINTER(_Cont))
    f('osciloscope_ring_leer_lote', c, _P, pcfg, pst, ctypes.POINTER(_Lote), _U, _I64,
      ctypes.POINTER(_LoteRes))
    if not hasattr(lib, 'osciloscope_ring_gen_configurar'):
        raise OSError('libmca no tiene osciloscope_ring_gen_*: el .so es de otra versión. '
                      'Recompilarla: `make -C libmca`.')
    _gen._cargar()                      # los structs del motor, ya comprobados
    f('osciloscope_ring_gen_presente', c, _P, ctypes.POINTER(_I32))
    f('osciloscope_ring_gen_configurar', c, _P, ctypes.POINTER(_gen._Disparos), _I32)
    f('osciloscope_ring_gen_apagar', c, _P)
    f('osciloscope_ring_gen_estado', c, _P, ctypes.POINTER(_gen._Estado))
    if not hasattr(lib, 'osciloscope_ring_medir'):
        raise OSError('libmca no tiene osciloscope_ring_medir: el .so es de antes de '
                      '0.10.0. Recompilarla: `make -C libmca`.')
    f('osciloscope_ring_medir', c, _P, pcfg, pst, _U, ctypes.POINTER(_gen._Disparos), _U,
      _I64, ctypes.POINTER(_Medida))
    f('osciloscope_ring_medida_cero', None, ctypes.POINTER(_Medida))
    if not hasattr(lib, 'osciloscope_ring_enviar'):
        raise OSError('libmca no tiene osciloscope_ring_enviar: el .so es de antes de '
                      '0.12.0. Recompilarla: `make -C libmca`.')
    f('osciloscope_ring_enviar', c, _P, pcfg, pst, c, _U, _I64, ctypes.POINTER(_Envio))
    f('osciloscope_ring_enviar_fin', c, _P, pst, c, ctypes.POINTER(_Envio))
    for tipo, py in (('osciloscope_ring_cfg_t', _Cfg),
                     ('osciloscope_ring_geometria_t', _Geo),
                     ('osciloscope_ring_estado_t', _Estado),
                     ('osciloscope_ring_lote_t', _Lote),
                     ('osciloscope_ring_contadores_t', _Cont),
                     ('osciloscope_ring_medida_t', _Medida),
                     ('osciloscope_ring_envio_t', _Envio),
                     ('osciloscope_ring_bloque_t', BLOQUE.size),
                     ('osciloscope_ring_contadores_t', CONTADORES.size)):
        tam = py if isinstance(py, int) else ctypes.sizeof(py)
        if lib.osciloscope_ring_sizeof(tipo.encode()) != tam:
            raise OSError(f'libmca y API/osciloscope_ring.py no coinciden en {tipo}: '
                          f'{lib.osciloscope_ring_sizeof(tipo.encode())} contra '
                          f'{tam} bytes. Recompilar libmca o '
                          'actualizar el struct del binding.')
    _lib = lib
    return lib


def _detalle(c=None):
    return _cargar().osciloscope_ring_last_error(c).decode('utf-8', 'replace') or None


_EXCEPCIONES = {_libmca.MCA_ENOTPRESENT: RingNotPresent}


def registros():
    """{nombre: offset} del mapa de registros, como lo exporta libmca."""
    lib = _cargar()
    out = {}
    for i in range(lib.osciloscope_ring_reg_count()):
        r = lib.osciloscope_ring_reg_info(i).contents
        out[r.nombre.decode()] = r.offset
    return out


def _u32(v):
    v = operator.index(v)
    if not 0 <= v < 2 ** 32:
        raise ValueError(f'{v}: fuera de 0..2^32 - 1')
    return v


def _cfg(pre, post, n_ch, cal=(), slot_shift=None, ring_bytes=None, lote_bytes=None,
         dw=14):
    c = _Cfg()
    c.pre, c.post, c.n_ch, c.dw = _u32(pre), _u32(post), _u32(n_ch), _u32(dw)
    c.slot_shift = _u32(slot_shift or 0)
    c.ring_bytes = _u32(ring_bytes or 0)
    c.lote_bytes = _u32(lote_bytes or 0)
    cal = list(cal)
    if len(cal) > APERTURAS_DECODIFICADAS:
        raise ValueError(f'{len(cal)} calibraciones: hay {APERTURAS_DECODIFICADAS} '
                         'canales como mucho')
    for k, v in enumerate(cal):
        c.cal[k] = _cargar_cal(v)
    return c


def geometria(pre, post, n_ch=N_CH_HW, slot_shift=None, ring_bytes=None,
              lote_bytes=None, ddr_size=0):
    """La geometría que sale de una ventana, sin tocar el hardware: dict con
    `muestras`, `slot_shift`, `slot_bytes`, `n_slots`, `ring_bytes`, `lote_slots` (los
    tres del ring en 0 sin `ddr_size`). ValueError con el motivo si el RTL no la
    acepta."""
    c = _cfg(pre, post, n_ch, (), slot_shift, ring_bytes, lote_bytes)
    g = _Geo()
    rc = _cargar().osciloscope_ring_geometria(ctypes.byref(c), _u32(ddr_size),
                                              ctypes.byref(g))
    if rc:
        _libmca.check(rc, 'geometría del ring', None, _detalle())
    return {k: getattr(g, k) for k, _ in _Geo._fields_}


def patron_gen(ts, pre, muestras, n_ch=N_CH_HW, dw=14):
    """Lo que el generador de eventos pone en la ventana de un slot con marca `ts`,
    como lo guarda el slot (int16, con el signo de 14 bits): el canal par es
    (ts - pre + j) mod 2^dw y el impar su complemento. Es `patron` del modelo
    (gen_eventos_model.py) muestra por muestra. Con `ts` escalar, de forma
    (n_ch, muestras); con un arreglo de n marcas, (n, n_ch, muestras).

    Las muestras de antes del arranque (ts - pre + j < 0, sólo si ts < pre) no son
    esto: son lo que quedó en el buffer de pre-trigger de la corrida anterior
    (docs/event_ring/logica_de_captura_y_axi.md §2.3)."""
    m = (1 << dw) - 1
    t = np.asarray(ts, np.int64)
    j = np.arange(muestras, dtype=np.int64)
    par = (t[..., None] - int(pre) + j) & m                     # (..., muestras)
    out = np.empty(t.shape + (n_ch, muestras), np.int64)
    out[..., 0::2, :] = par[..., None, :]
    out[..., 1::2, :] = (~par & m)[..., None, :]
    return np.where(out >= 1 << (dw - 1), out - (1 << dw), out).astype(np.int16)


# =============================================================================
# El handle
# =============================================================================

class OsciloscopeRing:
    """El event_ring de libmca: los registros del slot 2 y la región de DDR.

        r = OsciloscopeRing.open()                    # la región del device tree
        r = OsciloscopeRing.open(ddr=(0x0A00_0000, 32 << 20))
        r = OsciloscopeRing.sobre(Bus.callbacks(...), Mem.sobre(arreglo))   # tests
    """

    def __init__(self, c, bus=None, mem=None):
        self._c = c
        self._bus = bus          # los de Python, si se abrió sobre ellos: viven con él
        self._mem = mem

    @classmethod
    def open(cls, phys=RING_PHYS, size=RING_SIZE, ddr=None, check_magic=True):
        """Mapea los registros y la región de DDR (`ddr=(phys, size)`; None la busca
        con `region_ddr()`). RingNotPresent si el slot 2 no tiene el ring."""
        dp, ds = region_ddr() if ddr is None else ddr
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.osciloscope_ring_open(ctypes.byref(p), _u32(phys), _u32(size), _u32(dp),
                                       _u32(ds), int(bool(check_magic)))
        if rc:
            _libmca.check(rc, 'osciloscope_ring_open', _EXCEPCIONES, _detalle())
        return cls(p)

    @classmethod
    def sobre(cls, bus, mem, check_magic=True):
        """Sobre un `Bus` y una `Mem` de `API._libmca`, que quedan a cargo de este
        handle (los cierra `close`)."""
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.osciloscope_ring_open_bus(ctypes.byref(p), bus.ptr, 0, mem.ptr, 0,
                                           int(bool(check_magic)))
        if rc:
            bus.check(rc, 'osciloscope_ring_open_bus', _EXCEPCIONES, _detalle())
        return cls(p, bus, mem)

    def _ok(self, rc, que=''):
        if rc == 0:
            return
        det = _detalle(self._c)
        for r in (self._bus, self._mem):
            if r is not None and r._pendiente is not None:
                r.check(rc, que, None, det)
        _libmca.check(rc, que, _EXCEPCIONES, det)

    @property
    def c(self):
        if self._c is None:
            raise ValueError('ring cerrado')
        return self._c

    def r32(self, off):
        v = _U()
        self._ok(_cargar().osciloscope_ring_r32(self.c, _u32(off), ctypes.byref(v)),
                 f'r32 {off:#x}')
        return v.value

    def w32(self, off, val):
        self._ok(_cargar().osciloscope_ring_w32(self.c, _u32(off),
                                                int(val) & 0xFFFFFFFF), f'w32 {off:#x}')

    @property
    def ddr(self):
        """`(phys, size)` de la región de DDR."""
        p, s = _U(), _U()
        self._ok(_cargar().osciloscope_ring_ddr(self.c, ctypes.byref(p), ctypes.byref(s)))
        return p.value, s.value

    def correr(self):
        self._ok(_cargar().osciloscope_ring_correr(self.c), 'correr')

    def parar(self, timeout_s=0.5):
        """CTRL = 0 y espera que termine la ventana en vuelo. TimeoutError si no."""
        plazo = time.perf_counter_ns() + int(timeout_s * 1e9)
        self._ok(_cargar().osciloscope_ring_parar(self.c, plazo), 'parar')

    def contadores(self):
        """Los contadores y el estado del hardware: dict con `status`, `ev_cnt`,
        `drop_busy`, `drop_full`, `wr_slot`, `rd_slot`, `seq`, `n_slots`, `lvl`,
        `axi_addr` y `ts`."""
        k = _Cont()
        self._ok(_cargar().osciloscope_ring_contadores(self.c, ctypes.byref(k)),
                 'contadores')
        return {n: getattr(k, n) for n, _ in _Cont._fields_}

    # -- el generador de eventos --

    def gen_presente(self):
        """¿El ring de este bitstream tiene el generador (GEN_MAGIC "GEN1")?"""
        v = _I32()
        self._ok(_cargar().osciloscope_ring_gen_presente(self.c, ctypes.byref(v)),
                 'gen_presente')
        return bool(v.value)

    def gen_configurar(self, disparos=None, patron=False):
        """Con el ring parado: los disparos del motor (un dict de
        `API.generadores.disparos`, o None para seguir con los del multitrigger) y el
        patrón en lugar del dato. Lo deja prendido: corre cuando corra el ring.
        LibMCAError (MCA_ENOSYS) si el bitstream no lo tiene; ValueError si el ring
        está corriendo."""
        d = None
        if disparos is not None:
            d = _gen._struct_disparos(_gen.disparos() | dict(disparos))
        self._ok(_cargar().osciloscope_ring_gen_configurar(
            self.c, ctypes.byref(d) if d is not None else None, int(bool(patron))),
            'gen_configurar')

    def gen_apagar(self):
        """El ring vuelve a los disparos y al dato de la cadena del scope."""
        self._ok(_cargar().osciloscope_ring_gen_apagar(self.c), 'gen_apagar')

    def gen_estado(self):
        """`gen_cnt`, `estado`, `generando` y `terminado`. Después de parar el ring,
        `ev_cnt + drop_busy + drop_full == gen_cnt`."""
        e = _gen._Estado()
        self._ok(_cargar().osciloscope_ring_gen_estado(self.c, ctypes.byref(e)),
                 'gen_estado')
        return _gen._estado_dict(e)

    def close(self):
        if self._c is not None:
            _cargar().osciloscope_ring_close(self._c)
            self._c = None
        for r in (self._bus, self._mem):
            if r is not None:
                r.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LectorRing:
    """El lazo por lote de libmca (`osciloscope_ring_leer_lote`) sobre un ring. Lo usa
    `RingSource`; es la contraparte del `Lector` de la BRAM. Durante la llamada el GIL
    está suelto."""

    def __init__(self, ring, pre, post, n_ch, cal, slot_shift=None, ring_bytes=None,
                 lote_bytes=None):
        self.ring = ring
        self.n_ch = operator.index(n_ch)
        self.samples = operator.index(pre) + operator.index(post)
        self._cfg = _cfg(pre, post, n_ch, cal, slot_shift, ring_bytes, lote_bytes)
        self._st, self._lote, self._res = _Estado(), _Lote(), _LoteRes()
        self._med, self._env = _Medida(), _Envio()
        _cargar().osciloscope_ring_medida_cero(ctypes.byref(self._med))

    def configurar(self):
        """Con el ring parado: geometría, contadores, footers. Deja el estado en
        cero. No lo arranca."""
        self.ring._ok(_cargar().osciloscope_ring_configurar(
            self.ring.c, ctypes.byref(self._cfg), ctypes.byref(self._st)), 'configurar')
        _cargar().osciloscope_ring_medida_cero(ctypes.byref(self._med))
        self._env = _Envio()

    @property
    def pendientes(self):
        """Descartados desde el último evento guardado: los del próximo `gap`, o los
        del final de la corrida."""
        return int(self._st.pendientes)

    @property
    def estado(self):
        return {k: getattr(self._st, k) for k, _ in _Estado._fields_}

    def _apuntar(self, cols, i0, n_max):
        lote = self._lote
        for nombre, tipo, ptr in _COLUMNAS:
            a = cols.get(nombre)
            if a is None:
                setattr(lote, nombre, ptr())
                continue
            if a.dtype != tipo or not a.flags.c_contiguous:
                raise TypeError(f'{nombre}: hace falta un arreglo contiguo de '
                                f'{np.dtype(tipo)}, y es {a.dtype}')
            if a.shape[0] < i0 + n_max:
                raise ValueError(f'{nombre}: {a.shape[0]} filas, y se escribirían '
                                 f'hasta la {i0 + n_max}')
            if nombre == 'wave' and a.shape[1:] != (self.n_ch, self.samples):
                raise ValueError(f'wave: cada fila es {a.shape[1:]}, y el lector lee '
                                 f'{(self.n_ch, self.samples)}')
            setattr(lote, nombre, a[i0:].ctypes.data_as(ptr))
        return lote

    def leer(self, cols, i0, n_max, plazo_ns):
        """Hasta `n_max` eventos desde la fila `i0` de `cols` (un dict de arreglos, o
        algo con `.wave` y `.scalars`), o hasta `plazo_ns`. Con `cols=None` no consume:
        espera al plazo y cuenta los descartes del hardware. Devuelve
        `(guardados, descartados, asignados)`."""
        if cols is not None and not isinstance(cols, dict):
            cols = dict(cols.scalars, wave=cols.wave)
        lote = self._apuntar(cols, i0, n_max) if cols is not None else None
        rc = _cargar().osciloscope_ring_leer_lote(
            self.ring.c, ctypes.byref(self._cfg), ctypes.byref(self._st),
            ctypes.byref(lote) if lote is not None else None, _u32(n_max),
            _I64(plazo_ns), ctypes.byref(self._res))
        if rc:
            self.ring._ok(rc, 'leer_lote')
        r = self._res
        return int(r.n), int(r.descartados), int(r.asignados)

    def medir(self, modo, plazo_ns, n_max=2 ** 32 - 1, disparos=None):
        """Consume sin entregar, hasta `plazo_ns` o `n_max` eventos, en uno de los modos
        de `osciloscope_ring_medir`: `'creditos'` (etapa A), `'copia'` o `'verificar'`
        (etapa B), o su MEDIR_*. Con `disparos` (el dict de `API.generadores.disparos`
        con que se configuró el generador) 'verificar' compara además cada marca con el
        motor. Acumula de una llamada a la otra hasta `configurar`, y devuelve lo
        acumulado (`medida`)."""
        if isinstance(modo, str):
            if modo not in MODOS_MEDIR:
                raise ValueError(f'modo {modo!r}: es uno de {sorted(MODOS_MEDIR)}')
            modo = MODOS_MEDIR[modo]
        d = None
        if disparos is not None:
            d = _gen._struct_disparos(_gen.disparos() | dict(disparos))
        rc = _cargar().osciloscope_ring_medir(
            self.ring.c, ctypes.byref(self._cfg), ctypes.byref(self._st), _u32(modo),
            ctypes.byref(d) if d is not None else None, _u32(n_max), _I64(plazo_ns),
            ctypes.byref(self._med))
        if rc:
            self.ring._ok(rc, 'medir')
        return self.medida

    def enviar(self, fd, plazo_ns, n_max=2 ** 32 - 1):
        """Manda por `fd` (un socket conectado) lo que haya, bloque por bloque, hasta
        `plazo_ns` o `n_max` eventos: `osciloscope_ring_enviar`. Sin el GIL. Devuelve lo
        acumulado desde `configurar` (`envio`). Si la red se corta, ConnectionError; si
        no avanza en 10 s, TimeoutError: en los dos casos el stream quedó cortado."""
        rc = _cargar().osciloscope_ring_enviar(
            self.ring.c, ctypes.byref(self._cfg), ctypes.byref(self._st), int(fd),
            _u32(n_max), _I64(plazo_ns), ctypes.byref(self._env))
        if rc:
            self.ring._ok(rc, 'enviar')
        return self.envio

    def enviar_fin(self, fd):
        """El bloque FIN: los descartados que falten y los contadores del ring. Una vez,
        después del último `enviar`."""
        rc = _cargar().osciloscope_ring_enviar_fin(
            self.ring.c, ctypes.byref(self._st), int(fd), ctypes.byref(self._env))
        if rc:
            self.ring._ok(rc, 'enviar_fin')
        return self.envio

    @property
    def envio(self):
        """Lo acumulado por `enviar` desde `configurar`: los campos de
        osciloscope_ring_envio_t (sin `reservado`)."""
        return {k: int(getattr(self._env, k)) for k, _ in _Envio._fields_
                if k != 'reservado'}

    @property
    def medida(self):
        """Lo acumulado por `medir` desde `configurar`: los campos de
        osciloscope_ring_medida_t, más `errores` (los slots con algún error, contados
        por tipo), y `primer_error_seq` en None si no hubo."""
        m = {k: int(getattr(self._med, k)) for k, _ in _Medida._fields_}
        m['errores'] = sum(m[k] for k in ('err_cabecera', 'err_marca', 'err_k', 'err_ts',
                                          'err_patron'))
        if m['primer_error_seq'] == 2 ** 32 - 1:
            m['primer_error_seq'] = None
        return m


def destrabar(ring, lector):
    """Para un ring que `parar` no pudo parar: lleno, la ventana en vuelo espera un
    crédito que nadie devuelve (STATUS = drenando + no_credit). Pasa cuando el lector
    dejó de leer con el ring lleno: un punto cortado, el disco lleno, una sesión que se
    paró con el estímulo corriendo.

    Devuelve cómo se destrabó:

    - `'creditos'`: se devolvieron los créditos (`lector.medir('creditos')`) y paró. Lo
      devuelto no llega a nadie: queda en `EV_CNT` y no en lo leído.
    - `'parado'`: ya había parado. En la placa (2026-11-12) el ring terminó de parar
      entre el `parar` vencido y esto, y al parar WR_SLOT vuelve a 0: `medir` lo toma
      como un ring con 2^32 slots llenos.
    - `'clr'`: no alcanzó, y `CTRL ← 0x2` lo paró. **Borra los contadores**: los de la
      corrida hay que haberlos leído antes."""
    if not ring.contadores()['status'] & ST_ESTADO:
        return 'parado'
    como = 'creditos'
    if lector is not None:
        try:
            lector.medir('creditos', time.perf_counter_ns() + 100_000_000)
        except _libmca.LibMCAError:
            pass                     # paró mientras tanto: WR_SLOT ya es 0
    try:
        ring.parar()
    except TimeoutError:
        ring.w32(R_CTRL, 0x2)
        ring.parar()
        como = 'clr'
    return como


# =============================================================================
# La fuente de eventos
# =============================================================================

class RingSource:
    """Eventos del event_ring: la interfaz `EventSource` por lote.

    `scope` (un MultiTriggerScope) se usa sólo para armar el disparo (umbral,
    histéresis, máscara); la captura y la lectura no lo tocan. `ring` es un
    `OsciloscopeRing`; sin él, `arm()` abre el de la placa (`region_ddr()`) y `close()`
    lo cierra.

    `wave` son cuentas calibradas (int16), como en `BramSource`: la calibración de
    librp con los números de la EEPROM (`calib=None` los lee al armar).

    `n_ch` son los canales que se entregan; el RTL escribe siempre `N_CH_HW`, y con
    ellos se cuentan el slot y los límites de la ventana.

    `generador` (un dict de `API.generadores.disparos`, con su `n`) cambia el estímulo:
    los disparos salen del motor del generador del ring y cada slot trae el patrón en
    vez del dato (docs/event_ring/generador.md). Entonces el scope no se arma y puede
    ser None. Es la etapa C de `campanas/run_etapas_ring.py`.
    """

    scalar_fields = BASE_FIELDS + RING_FIELDS
    wave_dtype = np.int16

    def __init__(self, scope, ring=None, pre=8, post=24, n_ch=2, thr=0.5, hyst=0.02,
                 mask=None, slot_shift=None, ring_bytes=None, calib=None, generador=None):
        # Lo que el RTL no acepta sale acá, antes de abrir nada.
        g = geometria(pre, post, n_ch, slot_shift)
        if scope is None and generador is None:
            raise ValueError('sin scope no hay disparo: hace falta el generador '
                             '(generador=) o un MultiTriggerScope')
        self.generador = None if generador is None else _gen.disparos() | dict(generador)
        self.sc = scope
        self.ring = ring
        self._ring_propio = ring is None
        self.pre = pre
        self.post = post
        self.samples = pre + post
        self.n_ch = n_ch
        self.thr = thr
        self.hyst = hyst
        self.mask = mask
        self.slot_shift = g['slot_shift']
        self.slot_sz = g['slot_bytes']
        self.ring_bytes = ring_bytes
        self.calib = None if calib is None else [_cal_dict(c) for c in calib]
        self.n_slots = None
        self._lector = None
        self._final = None
        self.destrabe = None             # cómo se destrabó al cerrar (ver close)
        self._cortado = False            # `detener` ya cortó el estímulo

    # -- ciclo de vida ------------------------------------------------------

    def arm(self):
        from API.multitrigger import BIT_ADC_P0

        if self.calib is None:
            self.calib = calibracion_adc(range(self.n_ch))
        if len(self.calib) < self.n_ch:
            raise ValueError(f'{len(self.calib)} calibraciones para {self.n_ch} canales')
        if self.ring is None:
            self.ring = OsciloscopeRing.open()
        lector = LectorRing(self.ring, self.pre, self.post, self.n_ch,
                            self.calib[:self.n_ch], self.slot_shift, self.ring_bytes)
        lector.configurar()              # parado: geometría, contadores, footers
        self.n_slots = lector.estado['n_slots']

        if self.generador is not None:
            # Parado: el motor y el patrón quedan prendidos y arrancan con el ring.
            self.ring.gen_configurar(self.generador, patron=True)
        else:
            # El disparo: el mismo camino que BramSource. we_keep para que la máscara
            # no se auto-limpie, y el shield para el re-armado por hardware.
            mask = BIT_ADC_P0 if self.mask is None else self.mask
            self.sc.arm_for_adc_trigger(
                mask_ch0=mask, mask_ch1=mask, thr=self.thr, hyst=self.hyst,
                delay=1, we_keep_both=True, auto_rearm=True)
        self._lector = lector
        self._final = None
        self._cortado = False
        self.ring.correr()

    def detener(self):
        """Corta el estímulo con el ring corriendo, para que el lector se lleve lo que
        quedó antes de parar (`AcquisitionSession.stop`, que después espera
        `vaciado()`). Hace falta porque con el ring parado WR_SLOT vuelve a 0, y lo que
        quedaba en la DDR ya no se lee: en la placa, unos 40 ms de disparos.

        - Con el generador, N ← 1: el motor ya pasó de N y no dispara más (con
          GEN_CNT = 0 sale uno más). `GEN_CTRL.EN ← 0` no sirve: devuelve el disparo
          del ring al multitrigger. `hw_gen_terminado` sigue siendo respecto del N de
          la corrida.
        - Con el disparo del ADC, la máscara OR en 0: el armado al revés. El resto del
          desarme (la FSM del scope) queda para `close`, con el ring parado."""
        if self.ring is None or self._lector is None or self._cortado:
            return
        self._cortado = True
        if self.generador is not None:
            self.ring.w32(R_GEN_N, 1)
        elif hasattr(self.sc, 'set_or_mask'):
            self.sc.set_or_mask(0, 0)
        else:
            self.sc.disarm()

    def vaciado(self):
        """¿Quedó algo por leer? Después de `detener`: True si no hay ninguna ventana
        en vuelo (WR_SLOT = EV_CNT: EV_CNT sube cuando la ventana empieza a salir de la
        captura, WR_SLOT cuando terminó de escribirse) y el lector está al día
        (WR_SLOT = el próximo que lee). Entre que termina una ventana y empieza la
        siguiente puede dar True un instante: hay que verlo dos veces seguidas."""
        k = self.ring.contadores()
        return k['wr_slot'] == k['ev_cnt'] == self._lector.estado['next']

    def _gen_estado(self):
        """`gen_estado()`, con `terminado` respecto del N de la corrida: después de
        `detener` (N ← 1) el motor dice terminado aunque lo hayan cortado antes."""
        e = self.ring.gen_estado()
        if self._cortado:
            n = self.generador['n']
            e['terminado'] = bool(n) and e['gen_cnt'] >= n
        return e

    def close(self):
        """Para el ring (la ventana en vuelo termina), desarma el disparo y guarda los
        contadores finales del hardware para `meta()`. Con el generador, los de
        después de parar (la cuenta con GEN_CNT cierra recién ahí) y lo apaga.

        Si el ring no para (lleno y sin créditos: el lector ya se fue), lo destraba
        con `destrabar` y deja cómo en `self.destrabe` y en `hw_destrabe`. Con `'clr'`
        los contadores se borraron, y quedan los de antes de parar."""
        if self.ring is None:
            return
        try:
            try:
                self._final = self.hw_counters()
            finally:
                try:
                    self.ring.parar()
                    self.destrabe = None
                except TimeoutError:
                    self.destrabe = destrabar(self.ring, self._lector)
                if self.generador is not None:
                    k, e = self.ring.contadores(), self._gen_estado()
                    self.ring.gen_apagar()
                    if self._final is not None and self.destrabe != 'clr':
                        self._final.update({f'hw_{n}': k[n] for n in
                                            ('ev_cnt', 'drop_busy', 'drop_full')},
                                           hw_gen_cnt=e['gen_cnt'],
                                           hw_gen_terminado=e['terminado'])
                    if self._final is not None:
                        # Lo cortó `detener` antes de llegar a N (o era sin fin).
                        self._final['hw_gen_cortado'] = (
                            self._cortado and not self._final['hw_gen_terminado'])
                if self._final is not None:
                    self._final['hw_destrabe'] = self.destrabe
        finally:
            if self.generador is None:
                self.sc.disarm()
            if self._ring_propio:
                self.ring.close()
                self.ring = None

    # -- lazo caliente ------------------------------------------------------

    def read_batch(self, batch, deadline_ns):
        """Llena `batch` desde `batch.n`, en C: ver `osciloscope_ring_leer_lote`.

        `t_ns` es cuando se leyó el bloque; `ts_hw`, cuando disparó. `gap` lleva los
        descartes que contó el hardware, en el primer evento leído después.
        """
        if batch is None:
            return self._lector.leer(None, 0, 0, deadline_ns)
        return self._lector.leer(batch, batch.n, batch.capacity - batch.n, deadline_ns)

    @property
    def pending(self):
        return self._lector.pendientes if self._lector is not None else 0

    # -- diagnóstico y metadatos --------------------------------------------

    def hw_counters(self):
        """Los contadores del hardware, para el resumen de la corrida. `hw_drop_full`
        y `hw_drop_busy` son la pérdida que con la BRAM era invisible. `hw_no_leidos`:
        los que quedaron en la DDR sin leer. Con el generador, `hw_gen_cnt` y
        `hw_gen_terminado`."""
        k = self.ring.contadores()
        out = {f'hw_{n}': v for n, v in k.items()}
        if self._lector is not None:
            out['hw_no_leidos'] = (k['wr_slot'] - self._lector.estado['next']) & 0xFFFFFFFF
        out['hw_slot_sz'] = self.slot_sz
        if self.generador is not None:
            e = self._gen_estado()
            out['hw_gen_cnt'], out['hw_gen_terminado'] = e['gen_cnt'], e['terminado']
        return out

    def meta(self):
        dp, ds = self.ring.ddr if self.ring is not None else (None, None)
        return dict(kind='ring', pre=self.pre, post=self.post, samples=self.samples,
                    n_ch=self.n_ch, thr_V=self.thr, hyst_V=self.hyst,
                    mask=None if self.mask is None else int(self.mask),
                    slot_shift=self.slot_shift, slot_sz=self.slot_sz,
                    n_slots=self.n_slots, ddr_phys=dp, ddr_size=ds,
                    adc_cnt_per_V=ADC_CNT_PER_V, dt_ns=DT_NS,
                    wave='cuentas calibradas: las de librp (cmn_CalibCntsSigned)',
                    calib=None if self.calib is None else
                    [dict(c) for c in self.calib[:self.n_ch]],
                    ts_hw='ciclos de 8 ns desde que arrancó el ring',
                    gap='descartes del hardware (DROP_BUSY + DROP_FULL), por bloque',
                    lector='libmca', hw_final=self._final,
                    generador=None if self.generador is None else dict(self.generador))



# =============================================================================
# Una adquisición entera: la fuente y la sesión
# =============================================================================

class _Disparo:
    """El disparo real de `RingSource` sobre un `Osciloscope` y un `MultiTrigger`
    separados: el mismo par que compone `MultiTriggerScope` (multitrigger_utils.py),
    sin la clase de compatibilidad."""

    def __init__(self, osc, mt):
        self.osc, self.mt = osc, mt

    def arm_for_adc_trigger(self, **kw):
        from API.multitrigger import multitrigger_arm
        return multitrigger_arm(self.osc, self.mt, **kw)

    def set_or_mask(self, mask_ch0, mask_ch1=None):
        return self.mt.set_or_mask(mask_ch0, mask_ch1)

    def disarm(self):
        from API.multitrigger import multitrigger_disarm
        return multitrigger_disarm(self.osc, self.mt)


def _validar_estimulo(generador, disparo, osc, mt):
    """El estímulo es uno: `generador` (el motor del ring) o `disparo` (el real, con el
    osciloscopio y el multitrigger). Lo comparten `AdquisicionRing` y `EmisionRing`."""
    if (generador is None) == (disparo is None):
        raise ValueError('el estímulo es uno: generador= o disparo=')
    if disparo is not None and (osc is None or mt is None):
        raise ValueError('el disparo real necesita el osciloscopio y el multitrigger')
    if disparo is not None:
        sobra = set(disparo) - {'thr', 'hyst', 'mask'}
        if sobra:
            raise ValueError(f'disparo: no se conoce {sorted(sobra)} '
                             '(son thr, hyst y mask)')


def _fuente(ring, pre, post, n_ch, slot_shift, generador, disparo, osc, mt, calib):
    """La `RingSource` de una adquisición o de una emisión, sin armar."""
    d = disparo or {}
    return RingSource(None if disparo is None else _Disparo(osc, mt), ring, pre, post,
                      n_ch, thr=d.get('thr', 0.5), hyst=d.get('hyst', 0.02),
                      mask=d.get('mask'), slot_shift=slot_shift, calib=calib,
                      generador=generador)


class AdquisicionRing:
    """Una adquisición del ring con su sesión: `RingSource` + `AcquisitionSession`,
    con argumentos que viajan en JSON. Es lo que corre el servidor con las ops
    `ring.*` y la etapa C de `campanas/run_etapas_ring.py`.

    - El estímulo es uno de dos: `generador` (un dict de `API.generadores.disparos`)
      o `disparo` (`{thr, hyst, mask}`, el disparo real, con `osc` y `mt`).
    - `calib`: None lee la EEPROM al armar; si no, una calibración por canal
      (`{gain, base, offset}`).
    - `run_dir` tiene que ser absoluto y su padre tiene que existir: se crea el
      directorio de la corrida, no el punto de montaje.
    - `margen_mb`: lo que el escritor deja libre en el disco (None: el de la sesión).

    `iniciar()` arma y arranca; `estado()` no bloquea; `parar()` para la sesión y el
    ring (destrabándolo si hace falta) y devuelve lo final. `parar()` es idempotente.
    """

    def __init__(self, ring, run_dir, pre=8, post=24, n_ch=N_CH_HW, slot_shift=None,
                 generador=None, disparo=None, osc=None, mt=None, calib=None,
                 formato='npz', capacity=4096, ram_mb=64.0, margen_mb=None, meta=None):
        run_dir = os.fspath(run_dir)
        if not os.path.isabs(run_dir):
            raise ValueError(f'run_dir={run_dir!r}: tiene que ser absoluto (es un '
                             'camino de la máquina donde corre la sesión)')
        padre = os.path.dirname(os.path.normpath(run_dir))
        if not os.path.isdir(padre):
            raise FileNotFoundError(f'{padre} no existe: el directorio de la corrida se '
                                    'crea, el punto de montaje no')
        _validar_estimulo(generador, disparo, osc, mt)
        self.ring = ring
        self.run_dir = os.path.normpath(run_dir)
        self.pre, self.post, self.n_ch, self.slot_shift = pre, post, n_ch, slot_shift
        self.generador = None if generador is None else dict(generador)
        self.disparo = None if disparo is None else dict(disparo)
        self.osc, self.mt = osc, mt
        self.calib = calib
        self.formato, self.capacity, self.ram_mb = formato, capacity, ram_mb
        self.margen_mb = margen_mb
        self.meta = dict(meta or {})
        self.fs = None
        self._src = self._ses = self._fin = None

    @property
    def corriendo(self):
        return self._ses is not None and self._fin is None

    def iniciar(self):
        from API.osciloscope_store.session import AcquisitionSession
        from API.osciloscope_store.storage import sistema_de_archivos

        if self._ses is not None:
            raise RuntimeError('esta adquisición ya se inició')
        src = _fuente(self.ring, self.pre, self.post, self.n_ch, self.slot_shift,
                      self.generador, self.disparo, self.osc, self.mt, self.calib)
        self.fs = sistema_de_archivos(os.path.dirname(self.run_dir))
        ses = AcquisitionSession(src, self.run_dir, capacity=self.capacity,
                                 ram_budget_mb=self.ram_mb, verbose=False,
                                 formato=self.formato, meta=self.meta | {'fs': self.fs})
        if self.margen_mb is not None:
            ses.writer.min_free_mb = self.margen_mb
        try:
            ses.start()
        except BaseException:
            try:
                src.close()
            except Exception:        # noqa: BLE001 — el error que importa es el de arriba
                pass
            raise
        self._src, self._ses = src, ses
        return dict(run_dir=self.run_dir, fs=self.fs, n_slots=src.n_slots,
                    pool=ses.describe())

    def _errores(self):
        ses = self._ses
        out = []
        if ses.reader.error is not None:
            out.append(f'lector: {ses.reader.error!r}')
        if ses.writer.error is not None:
            out.append(f'escritor: {ses.writer.error!r}')
        if ses.writer.disk_full.is_set():
            out.append('disco lleno')
        return '; '.join(out) or None

    def estado(self):
        """Sin bloquear: `corriendo`, `motivo` (el de `AcquisitionSession.motivo`),
        `stats` de la sesión, `hw` (los contadores del ring) y `error`. Parada, lo de
        `parar()` con `corriendo=False`."""
        if self._ses is None:
            return dict(corriendo=False, motivo=None, stats=None, hw=None, error=None)
        if self._fin is not None:
            return dict(self._fin, corriendo=False)
        return dict(corriendo=True, motivo=self._ses.motivo(),
                    stats=dict(self._ses.stats), hw=self._src.hw_counters(),
                    error=self._errores(), run_dir=self.run_dir, fs=self.fs)

    def parar(self):
        """Para la sesión y el ring, y devuelve `stats`, `hw_final` (los contadores con
        el ring parado), `n_slots`, `motivo` y `error`. La segunda vez devuelve lo
        mismo."""
        if self._fin is not None:
            return self._fin
        if self._ses is None:
            raise RuntimeError('esta adquisición no se inició')
        ses, src = self._ses, self._src
        motivo, error = ses.motivo(), self._errores()
        ses.stop()
        notas = []
        if ses.stats.get('vaciado') is False:
            sin_leer = (src.meta()['hw_final'] or {}).get('hw_no_leidos')
            notas.append(f'al parar quedaron {sin_leer} eventos sin leer en el ring')
        if src.destrabe is not None:
            notas.append(f'parar no terminó: el ring estaba lleno ({src.destrabe})')
        error = '; '.join(([error] if error else []) + notas) or None
        self._fin = dict(corriendo=False, motivo=motivo, stats=dict(ses.stats),
                         hw_final=src.meta()['hw_final'], n_slots=src.n_slots,
                         error=error, run_dir=self.run_dir, fs=self.fs)
        return self._fin


# =============================================================================
# El ring por red: los slots a un socket, sin sesión en la placa
# =============================================================================

class EmisionRing:
    """El ring por red: los slots salen por un socket hacia la PC, sin sesión ni
    archivos en la placa (docs/event_ring/salida_por_red.md). Es lo que corre el
    servidor con `ring.iniciar(destino='red')`; la PC recibe con `API.ring_red`.

    Tiene la interfaz de `AdquisicionRing` (`iniciar`, `estado`, `parar`,
    `corriendo`) y reusa `RingSource` para todo lo que no es leer: la geometría, el
    estímulo, `detener`, `vaciado` y `close`.

    1. `iniciar()` abre el puerto de datos y devuelve lo que la PC necesita para leer
       el stream: la geometría, `carga` y la calibración (las muestras van crudas).
    2. Un hilo (`ring-tx`) acepta UNA conexión y recién entonces arma el ring, así no
       se pierde el principio. Después llama a `osciloscope_ring_enviar` en lazo, de a
       `PLAZO_NS`, sin el GIL.
    3. `parar()` corta el estímulo, espera que salga lo que quedó, manda el FIN y
       cierra.

    Con `desde` (una IP) sólo se acepta la conexión que venga de ahí: el servidor pasa
    la del cliente que pidió la emisión. Si la conexión no llega en `aceptar_s`, o la
    red se corta, la emisión termina sola, con el motivo (`'sin_conexion'`, `'red'`) y
    el error; `parar()` igual para el ring.
    """

    PLAZO_NS = 50_000_000
    run_dir = None                  # no escribe nada en la placa

    def __init__(self, ring, pre=8, post=24, n_ch=N_CH_HW, slot_shift=None,
                 generador=None, disparo=None, osc=None, mt=None, calib=None,
                 host='0.0.0.0', puerto=0, desde=None, aceptar_s=10.0, meta=None):
        _validar_estimulo(generador, disparo, osc, mt)
        geometria(pre, post, n_ch, slot_shift)          # lo que el RTL no acepta, ya
        self.ring = ring
        self.pre, self.post, self.n_ch, self.slot_shift = pre, post, n_ch, slot_shift
        self.generador = None if generador is None else dict(generador)
        self.disparo = None if disparo is None else dict(disparo)
        self.osc, self.mt = osc, mt
        self.calib = calib
        self.host, self.puerto_pedido, self.desde = host, puerto, desde
        self.aceptar_s = aceptar_s
        self.meta = dict(meta or {})
        self.puerto = None
        self.cliente = None
        self.error = None
        self._motivo = None
        self._fase = 'nueva'            # esperando -> enviando -> terminada
        self._src = self._lsock = self._conn = self._hilo = self._fin = None
        self._armado = False
        self._fin_enviado = False
        self._cortar = threading.Event()
        self._vaciado = None

    @property
    def corriendo(self):
        return self._src is not None and self._fin is None

    def iniciar(self):
        if self._src is not None:
            raise RuntimeError('esta emisión ya se inició')
        src = _fuente(self.ring, self.pre, self.post, self.n_ch, self.slot_shift,
                      self.generador, self.disparo, self.osc, self.mt, self.calib)
        if src.calib is None:
            # La PC calibra: la necesita antes de que llegue el primer bloque.
            src.calib = calibracion_adc(range(self.n_ch))
        g = geometria(self.pre, self.post, N_CH_HW, src.slot_shift,
                      ddr_size=self.ring.ddr[1])
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ls.bind((self.host, self.puerto_pedido))
            ls.listen(1)
            ls.settimeout(0.1)              # para poder cortar la espera
        except BaseException:
            ls.close()
            raise
        self._src, self._lsock = src, ls
        self.puerto = ls.getsockname()[1]
        self._fase = 'esperando'
        self._hilo = threading.Thread(target=self._correr, name='ring-tx', daemon=True)
        self._hilo.start()
        return dict(destino='red', puerto_datos=self.puerto, pre=self.pre,
                    post=self.post, n_ch=self.n_ch, n_ch_hw=N_CH_HW,
                    carga=carga_slot(self.pre, self.post),
                    slot_shift=g['slot_shift'], slot_bytes=g['slot_bytes'],
                    n_slots=g['n_slots'],
                    calib=[dict(c) for c in src.calib[:self.n_ch]],
                    adc_cnt_per_V=ADC_CNT_PER_V, dt_ns=DT_NS,
                    generador=self.generador, disparo=self.disparo,
                    bloque_magic=BLOQUE_MAGIC, bloque_version=BLOQUE_VERSION,
                    meta=self.meta)

    # -- el hilo que manda --------------------------------------------------

    def _aceptar(self):
        """La conexión de la PC, o None si no llegó a tiempo o se canceló."""
        t_fin = time.monotonic() + self.aceptar_s
        while not self._cortar.is_set():
            if time.monotonic() > t_fin:
                self._motivo = 'sin_conexion'
                self.error = TimeoutError(f'nadie se conectó al puerto {self.puerto} en '
                                          f'{self.aceptar_s:g} s')
                return None
            try:
                c, addr = self._lsock.accept()
            except socket.timeout:
                continue
            if self.desde is not None and addr[0] != self.desde:
                c.close()               # no es el cliente que la pidió
                continue
            c.settimeout(None)
            self.cliente = f'{addr[0]}:{addr[1]}'
            return c
        return None

    def _correr(self):
        try:
            conn = self._aceptar()
            self._lsock.close()
            if conn is None:
                return
            self._conn = conn
            self._src.arm()                 # configura, el estímulo, y corre
            self._armado = True
            self._fase = 'enviando'
            lector, fd = self._src._lector, conn.fileno()
            while not self._cortar.is_set():
                lector.enviar(fd, time.perf_counter_ns() + self.PLAZO_NS)
            # lo que llegó entre el último plazo y el corte, y el FIN
            lector.enviar(fd, time.perf_counter_ns() + self.PLAZO_NS)
            lector.enviar_fin(fd)
            self._fin_enviado = True
        except BaseException as exc:            # que no se muera en silencio
            self.error = exc
            self._motivo = 'red' if isinstance(exc, OSError) else 'error'
        finally:
            self._fase = 'terminada'
            if self._conn is not None:
                try:
                    self._conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._conn.close()

    def _vaciar(self):
        """Lo de `AcquisitionSession._vaciar`: corta el estímulo con el ring andando y
        espera que el hilo mande lo que quedó (dos veces seguidas vacío)."""
        from API.osciloscope_store.session import VACIAR_S, VACIAR_SONDEO_S

        self._src.detener()
        plazo = time.perf_counter() + VACIAR_S
        seguidas = 0
        while seguidas < 2:
            time.sleep(VACIAR_SONDEO_S)
            if not self._hilo.is_alive() or time.perf_counter() > plazo:
                self._vaciado = False
                return
            seguidas = seguidas + 1 if self._src.vaciado() else 0
        self._vaciado = True

    # -- estado -------------------------------------------------------------

    def motivo(self):
        """None mientras manda; `'sin_conexion'` si la PC no se conectó a tiempo,
        `'red'` si la conexión se cortó, `'error'` por otra cosa."""
        return self._motivo

    def _stats(self):
        lector = None if self._src is None else self._src._lector
        e = lector.envio if lector is not None else {
            k: 0 for k, _ in _Envio._fields_ if k != 'reservado'}
        e['n_read'] = e['eventos']              # el nombre de la sesión, para los sondeos
        dur = (e['t1_ns'] - e['t0_ns']) / 1e9
        e['tasa_ev_s'] = e['eventos'] / dur if e['eventos'] and dur > 0 else 0.0
        e['MB_s'] = e['bytes'] / dur / 1e6 if e['eventos'] and dur > 0 else 0.0
        if self._vaciado is not None:
            e['vaciado'] = self._vaciado
        return e

    def _error_txt(self):
        return None if self.error is None else repr(self.error)

    def estado(self):
        """Sin bloquear: `corriendo`, `fase`, `motivo`, `stats` (lo enviado), `hw` (los
        contadores del ring, ya armado) y `error`. Parada, lo de `parar()`."""
        if self._src is None:
            return dict(corriendo=False, motivo=None, stats=None, hw=None, error=None)
        if self._fin is not None:
            return dict(self._fin, corriendo=False)
        return dict(corriendo=True, fase=self._fase, motivo=self._motivo,
                    stats=self._stats(),
                    hw=self._src.hw_counters() if self._armado else None,
                    error=self._error_txt(), puerto_datos=self.puerto,
                    cliente=self.cliente, destino='red')

    def parar(self):
        """Corta el estímulo, espera que salga lo que quedó, manda el FIN, para el ring
        y devuelve lo final: `stats`, `hw_final`, `n_slots`, `motivo`, `error` y
        `fin_enviado`. La segunda vez devuelve lo mismo."""
        if self._fin is not None:
            return self._fin
        if self._src is None:
            raise RuntimeError('esta emisión no se inició')
        if self._armado and self._hilo.is_alive():
            self._vaciar()
        self._cortar.set()
        self._hilo.join(timeout=30)
        notas = []
        if self._hilo.is_alive():
            notas.append('el hilo que manda no terminó')
        src = self._src
        try:
            src.close()
        finally:
            if self._vaciado is False:
                sin_leer = (src.meta()['hw_final'] or {}).get('hw_no_leidos')
                notas.append(f'al parar quedaron {sin_leer} eventos sin mandar en el ring')
            if src.destrabe is not None:
                notas.append(f'parar no terminó: el ring estaba lleno ({src.destrabe})')
            error = '; '.join(([self._error_txt()] if self.error else []) + notas) or None
            self._fin = dict(corriendo=False, motivo=self._motivo, stats=self._stats(),
                             hw_final=src.meta()['hw_final'], n_slots=src.n_slots,
                             error=error, fin_enviado=self._fin_enviado,
                             puerto_datos=self.puerto, cliente=self.cliente,
                             destino='red')
        return self._fin
