#!/usr/bin/env python3
"""Multitrigger: máscaras OR, trigger_shield y snapshot de fuentes.

Es el bloque que el proyecto AÑADIÓ al scope original de RedPitaya. Vive en su
región propia, el slot 3 (0x4030_0000), y `mt_cfg.sv` es su esclavo. El
osciloscopio clásico (umbral, decimación, delay, histéresis, filtros, calibración,
BRAM) vive en el slot 1 y en `API/osciloscope.py`.

    from API.osciloscope import Osciloscope
    from API.multitrigger import MultiTrigger, multitrigger_arm, BIT_ADC_P0

    osc = Osciloscope.open()
    mt  = MultiTrigger.open()
    multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, thr=0.5)

`multitrigger_arm()` recibe LOS DOS handles a propósito: la secuencia de armado
cruza registros de ambos módulos y su orden es load-bearing (ver el docstring
de la función). Con la firma explícita la dependencia se ve; escondida dentro
de una clase sería accidental.

**La lógica está en C** (`libmca/include/multitrigger.h`). `MultiTrigger` y
`MtRegion` son dos fachadas de Python sobre el mismo tipo de handle: difieren en la
firma (`set_or_mask(m0, m1)` contra `set_or_mask(ch, m)`), no en los registros.
`open(..., impl='py')` abre la referencia (`API/ref_py/multitrigger2.py`), y si
libmca no carga se cae a ella avisando.

Acá quedan las constantes, las recetas puras (`decode_snap`, `pz_ganancia`,
`slope_pico`) y las secuencias que cruzan con el osciloscopio (`multitrigger_arm`,
`multitrigger_armar_mca`, ...), como composición.

Todo el acceso pasa por C, también el del lazo por evento: `BramSource` re-arma las
máscaras y lee el snapshot desde `osciloscope_leer_lote`, que recibe este handle.
"""

import ctypes
import math
import operator
import os
import sys

from API import _libmca
from API._despacho import api as _api, elegir_impl as _elegir_impl
from API.ref_py import multitrigger2 as _ref

SCOPE_PHYS = 0x4010_0000        # el osciloscopio; acá sólo para compatibilidad
SCOPE_SIZE = 0x30000

# La región propia del multitrigger. En el top del MCA está en el slot 3; en
# red_pitaya_top en el 7: `Integration.base('mtrg')` da la del bitstream cargado.
MTRG_PHYS  = 0x4030_0000
MTRG_SIZE  = 0x1000
MTRG_MAGIC = 0x4D54_5247        # "MTRG"

# ---------- bits de la OR_MASK (matchean trg_src_bits de mt_trig_src.sv) ----------

OR_MASK_ALL = 0xFFFF_FFFF

BIT_SW       = 1 << 0
BIT_ADC_P0   = 1 << 1
BIT_ADC_N0   = 1 << 2
BIT_ADC_P1   = 1 << 3
BIT_ADC_N1   = 1 << 4
BIT_ADC_P2   = 1 << 5
BIT_ADC_N2   = 1 << 6
BIT_ADC_P3   = 1 << 7
BIT_ADC_N3   = 1 << 8
BIT_EXT_P    = 1 << 9
BIT_EXT_N    = 1 << 10
BIT_ASG_P    = 1 << 11
BIT_ASG_N    = 1 << 12
BIT_TRIG_CH0 = 1 << 13
BIT_TRIG_CH1 = 1 << 14
BIT_TRIG_CH2 = 1 << 15
BIT_TRIG_CH3 = 1 << 16
# Disparo por PENDIENTE (mt_slope_trig): p = flanco de subida, n = de bajada.
# Se configuran en el slot 3 (ver MtRegion.set_slope), no en el slot 1.
BIT_SLOPE_P0 = 1 << 17
BIT_SLOPE_P1 = 1 << 18
BIT_SLOPE_P2 = 1 << 19
BIT_SLOPE_P3 = 1 << 20
BIT_SLOPE_N0 = 1 << 21
BIT_SLOPE_N1 = 1 << 22
BIT_SLOPE_N2 = 1 << 23
BIT_SLOPE_N3 = 1 << 24
# Disparo con POLO-CERO (mt_pz_trig): un trapecio corto con polo-cero y un
# Schmitt, solo positivo. Es el disparo del banco de trapecios del MCA: separa
# pares desde 7-8 muestras y no queda ciego en la cola de un pulso grande
# (docs/mca/pruebas_banco_trapecios.md). Se configura en el slot 3 (ver
# MtRegion.set_pz).
BIT_PZ_P0    = 1 << 25
BIT_PZ_P1    = 1 << 26
BIT_PZ_P2    = 1 << 27
BIT_PZ_P3    = 1 << 28


# ---------- decoder del snapshot (R_TRIG_SNAP) ----------

_SNAP_NAMES = [
    'sw_any',
    'adc_p0', 'adc_p1', 'adc_p2', 'adc_p3',
    'adc_n0', 'adc_n1', 'adc_n2', 'adc_n3',
    'ext_p', 'ext_n', 'asg_p', 'asg_n',
    'trig_ch0', 'trig_ch1', 'trig_ch2', 'trig_ch3',
    # bits 17..24: mismo lugar que en la OR_MASK. El event ring guarda 17 bits.
    'slope_p0', 'slope_p1', 'slope_p2', 'slope_p3',
    'slope_n0', 'slope_n1', 'slope_n2', 'slope_n3',
    # bits 25..28: el polo-cero
    'pz_p0', 'pz_p1', 'pz_p2', 'pz_p3',
]


def decode_snap(s):
    """Lista de nombres de fuentes activas en un snapshot (R_TRIG_SNAP)."""
    return [n for i, n in enumerate(_SNAP_NAMES) if s & (1 << i)]


# =============================================================================
# Registros del bloque multitrigger
# =============================================================================
#
# El fichero original no tenía constantes de offset: cada dirección era un
# literal hex inline (`self.w32(0x240, mask)`). Nombrarlas es lo que permite
# que API/tests/test_compat_api.py verifique los valores contra el baseline.

# Son de la región propia. Antes vivían en 0x210-0x24C del slot 1, 0x200 más
# arriba: ese espejo ya no existe (osc_cfg.sv sólo sigue decodificando 0x004 y
# 0x094), y lo que se escribía ahí se perdía sin ningún error.

R_CMD         = 0x000           # del SCOPE, no de esta región: arm / rst / we_keep
R_TRIG_DIS_CLR = 0x094          # del SCOPE: desbloquea adc_trg_dis
R_SHIELD_CFG  = 0x010           # {dur[31:16], dst[12:8], src[6:0]}
R_SHIELD_RUN  = 0x014           # {trig_arm[18], mca_veto[17], active[16], cnt[15:0]} (R)
R_TRIG_SNAP   = 0x018           # snapshot de 29 b, sticky (R)
R_FLAGS       = 0x01C           # dis_act / we_keep (R)
R_OR_MASK_CH0 = 0x040
R_OR_MASK_CH1 = 0x044
R_OR_MASK_CH2 = 0x048
R_OR_MASK_CH3 = 0x04C


# =============================================================================
# libmca: carga, firmas y tipos
# =============================================================================
#
# Los structs replican los de include/multitrigger.h campo por campo. `_cargar()`
# compara su tamaño con el que informa C: con un campo agregado de un solo lado,
# ctypes leería corrido sin ningún error.

_I32, _I64, _U = ctypes.c_int32, ctypes.c_int64, ctypes.c_uint32
_P, _PU, _PI = ctypes.c_void_p, ctypes.POINTER(_U), ctypes.POINTER(_I32)
_PP = ctypes.POINTER(ctypes.c_void_p)


class _Shield(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('dur', 'dst', 'src', 'runtime')]


class _Slope(ctypes.Structure):
    _fields_ = [('en', _I32)] + [(k, _U) for k in ('L', 'G', 'thr', 'hyst')]


class _Pz(ctypes.Structure):
    _fields_ = [('en', _I32)] + [(k, _U) for k in ('k', 'm', 'sh', 'mq', 'thr', 'hyst')]


class _Status(ctypes.Structure):
    _fields_ = [('snapshot', _U), ('flags', _U), ('shield_runtime', _U),
                ('shield_active', _I32), ('mca_veto', _I32), ('trig_arm', _I32)]


class _Reg(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U)]


class _Field(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U), ('shift', _U),
                ('mascara', _U), ('bandera', _I32)]


_lib = None


def _cargar():
    """libmca con las firmas de este bloque declaradas. OSError si no está."""
    global _lib
    if _lib is not None:
        return _lib
    lib = _libmca.cargar()
    # Un .so anterior a este bloque daría un AttributeError sobre una función
    # suelta, y el servidor lo tomaría por "este bitstream no trae el multitrigger".
    if not hasattr(lib, 'multitrigger_open'):
        raise OSError('libmca no tiene multitrigger_*: el .so es de otra versión. '
                      'Recompilarla: `make -C libmca arm` en la PC y volver a '
                      'copiarla a la placa, o `make -C libmca placa-lib`.')

    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)

    c = ctypes.c_int
    f('multitrigger_open', c, _PP, _U, _U, c)
    f('multitrigger_open_bus', c, _PP, _P, c, c)
    f('multitrigger_close', None, _P)
    f('multitrigger_last_error', ctypes.c_char_p, _P)
    f('multitrigger_reg_count', _I32)
    f('multitrigger_reg_info', ctypes.POINTER(_Reg), _I32)
    f('multitrigger_field_count', _I32)
    f('multitrigger_field_info', ctypes.POINTER(_Field), _I32)
    f('multitrigger_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    f('multitrigger_r32', c, _P, _U, _PU)
    f('multitrigger_w32', c, _P, _U, _U)
    f('multitrigger_get_caps', c, _P, _PU)
    f('multitrigger_has_slope', c, _P, _PI)
    f('multitrigger_has_pz', c, _P, _PI)
    f('multitrigger_set_or_mask', c, _P, _I64, _U)
    f('multitrigger_get_or_mask', c, _P, _I64, _PU)
    f('multitrigger_set_or_masks', c, _P, _I64, _I64)
    f('multitrigger_set_shield', c, _P, _U, _U, _U)
    f('multitrigger_get_shield', c, _P, ctypes.POINTER(_Shield))
    f('multitrigger_shield_autorearm', c, _P, _U, _U)
    f('multitrigger_disable_shield', c, _P)
    f('multitrigger_get_snapshot', c, _P, _PU)
    f('multitrigger_get_flags', c, _P, _PU)
    f('multitrigger_set_slope', c, _P, _I64, _I64, _I64, _I64, _I64, _I32)
    f('multitrigger_get_slope', c, _P, _I64, ctypes.POINTER(_Slope))
    f('multitrigger_disable_slope', c, _P, _I64)
    f('multitrigger_set_pz', c, _P, _I64, _I64, _I64, _I64, _I64, _I64, _I64, _I32)
    f('multitrigger_get_pz', c, _P, _I64, ctypes.POINTER(_Pz))
    f('multitrigger_disable_pz', c, _P, _I64)
    f('multitrigger_get_config', c, _P, _PU, _I32)
    f('multitrigger_configure', c, _P, _PI, _PU, _I32)
    f('multitrigger_get_status', c, _P, ctypes.POINTER(_Status))

    if lib.multitrigger_field_count() != len(_CAMPOS):
        raise OSError(f'libmca tiene {lib.multitrigger_field_count()} campos del '
                      f'multitrigger y API/multitrigger.py {len(_CAMPOS)}: el .so es '
                      'de otra versión. Recompilarla: `make -C libmca arm`.')
    for tipo, py in (('multitrigger_shield_t', _Shield), ('multitrigger_slope_t', _Slope),
                     ('multitrigger_pz_t', _Pz), ('multitrigger_status_t', _Status)):
        if lib.multitrigger_sizeof(tipo.encode()) != ctypes.sizeof(py):
            raise OSError(f'libmca y API/multitrigger.py no coinciden en {tipo}: '
                          f'{lib.multitrigger_sizeof(tipo.encode())} contra '
                          f'{ctypes.sizeof(py)} bytes. Recompilar libmca o '
                          'actualizar el struct del binding.')
    _lib = lib
    return lib


def _ok(h, rc, que='', excepciones=None):
    """rc de libmca -> nada, o la excepción con el detalle que dejó C.

    Un MCA_ENOTPRESENT y un MCA_EVERIFY salen como LibMCAError, que es un
    RuntimeError, como en Python. Si el handle corre sobre callbacks, primero se
    relanza la excepción que haya tirado un callback: es la causa real.
    """
    if rc == 0:
        return
    det = _cargar().multitrigger_last_error(h._c).decode('utf-8', 'replace') or None
    if h._bus is not None:
        h._bus.check(rc, que, excepciones, det)
    _libmca.check(rc, que, excepciones, det)


def _i64(v):
    """Un entero de Python al int64 de lo que C valida. `operator.index` rechaza lo
    que `v & 0xFFFFFFFF` también rechazaba (un float, None) con el mismo TypeError,
    y saturar evita que un número enorme cambie de signo al cruzar."""
    return max(-2 ** 63, min(2 ** 63 - 1, operator.index(v)))


def _u32(v):
    return operator.index(v) & 0xFFFFFFFF


def _dict(s, conv=lambda v: v):
    """Un struct a dict, en el orden de sus campos."""
    return {k: conv(getattr(s, k)) for k, _ in s._fields_}


def _sin_en(s):
    d = _dict(s)
    d['en'] = bool(d['en'])
    return d


# =============================================================================
# Los dos handles
# =============================================================================

class _Region:
    """Lo común a `MultiTrigger` y `MtRegion`: un `multitrigger_h*` sobre la región.

    `open` comprueba el MAGIC: un bitstream sin esta región falla acá, en vez de que
    las máscaras se escriban al vacío.
    """

    impl = 'c'
    _via = 'c'
    _CLASE_REF = None           # la clase de esta fachada en la referencia

    def __init__(self, mem, fd):
        """Un handle sobre un buffer ya mapeado, o sobre el `r32`/`w32` de una
        subclase con `mem=None`, sin leer nada. Ver `_libmca.Bus.de_handle`."""
        self._mmap = mem
        self._fd   = fd
        self._propio = fd >= 0          # con fd = -1 el mmap es prestado
        self._c    = None
        self._bus  = None
        self._geo  = None               # (phys, size), si abrió /dev/mem
        lib = _cargar()
        self._bus = _libmca.Bus.de_handle(self, _Region, mem, tarde=True)
        p = ctypes.c_void_p()
        _libmca.check(lib.multitrigger_open_bus(ctypes.byref(p), self._bus.ptr, 0, 0),
                      'multitrigger_open_bus')
        self._c = p

    @classmethod
    def _abrir(cls, phys, size, check_magic, impl):
        impl, aviso = _elegir_impl(impl)
        if aviso:
            print(f'warn: {aviso}', file=sys.stderr)
        if impl == 'py':
            h = getattr(_ref, cls._CLASE_REF).open(phys=phys, size=size,
                                                   check_magic=check_magic)
            h._via = 'py'
            h.impl = 'py'
            return h
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.multitrigger_open(ctypes.byref(p), phys, size, 1 if check_magic else 0)
        if rc:
            det = lib.multitrigger_last_error(None).decode('utf-8', 'replace') or None
            _libmca.check(rc, f'/dev/mem @ {phys:#x}', None, det)
        h = cls._envolver(p, None)
        h._geo = (phys, size)
        return h

    @classmethod
    def _sobre_bus(cls, bus, check_magic=True):
        """Un handle sobre un `_libmca.Bus` ya abierto, que pasa a ser suyo: lo
        cierra `close()`. Lo usan los tests y `bench_impl.py --shm`, con el backend
        devmem apuntando a un fichero."""
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.multitrigger_open_bus(ctypes.byref(p), bus.ptr, 0,
                                       1 if check_magic else 0)
        if rc:
            det = lib.multitrigger_last_error(None).decode('utf-8', 'replace') or None
            bus.check(rc, 'multitrigger_open_bus', None, det)
        return cls._envolver(p, bus)

    @classmethod
    def _envolver(cls, p, bus):
        h = cls.__new__(cls)
        h._mmap, h._fd, h._propio, h._bus, h._c = None, -1, False, bus, p
        h._geo = None
        return h

    def close(self):
        c, self._c = getattr(self, '_c', None), None
        if c:
            _cargar().multitrigger_close(c)
        bus, self._bus = getattr(self, '_bus', None), None
        if bus is not None:
            bus.close()
        # Lo que el constructor recibió ya abierto se cierra sólo si era suyo.
        mem, self._mmap = getattr(self, '_mmap', None), None
        fd, self._fd = getattr(self, '_fd', -1), -1
        if getattr(self, '_propio', False):
            self._propio = False
            if mem is not None and hasattr(mem, 'close'):
                mem.close()
            if fd is not None and fd >= 0:
                os.close(fd)

    def __del__(self):
        # Un handle olvidado no deja /dev/mem mapeado: reprogramar la PL con un
        # mapeo abierto traba el puerto GP0 (API/fpga.py).
        try:
            self.close()
        except Exception:                                      # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def w32(self, off, v):
        # En C: un store de 32 b alineado, validado antes de llegar al bus.
        rc = _cargar().multitrigger_w32(self._c, off, _u32(v))
        if rc:
            _ok(self, rc, f'w32 {off:#x}')

    def r32(self, off):
        v = ctypes.c_uint32()
        rc = _cargar().multitrigger_r32(self._c, off, ctypes.byref(v))
        if rc:
            _ok(self, rc, f'r32 {off:#x}')
        return v.value

    # ---------- lo que las dos fachadas leen igual ----------

    def _flags(self):
        v = ctypes.c_uint32()
        _ok(self, _cargar().multitrigger_get_flags(self._c, ctypes.byref(v)), 'get_flags')
        return v.value

    def _snapshot(self):
        v = ctypes.c_uint32()
        _ok(self, _cargar().multitrigger_get_snapshot(self._c, ctypes.byref(v)),
            'get_snapshot')
        return v.value

    def _shield(self):
        s = _Shield()
        _ok(self, _cargar().multitrigger_get_shield(self._c, ctypes.byref(s)), 'get_shield')
        return _dict(s)

    def _or_mask(self, ch):
        v = ctypes.c_uint32()
        _ok(self, _cargar().multitrigger_get_or_mask(self._c, _i64(ch), ctypes.byref(v)),
            'get_or_mask')
        return v.value

    def read_snapshot(self):
        """Fuentes que dispararon, decodificadas. El registro es STICKY: con la
        región propia son los 29 bits, con las fuentes de pendiente y de polo-cero."""
        return decode_snap(self._snapshot())


class MultiTrigger(_Region):
    """Máscaras OR, shield y snapshot, en la región propia.

    El disparo por pendiente y el polo-cero están en `MtRegion`, sobre los mismos
    registros.
    """

    _CLASE_REF = 'MultiTrigger'

    @classmethod
    def open(cls, osc=None, phys=MTRG_PHYS, size=MTRG_SIZE, check_magic=True, impl=None):
        """`osc` se acepta y no se usa: antes compartían mapeo, y ya no."""
        return cls._abrir(phys, size, check_magic, impl)

    def set_or_mask(self, mask_ch0=OR_MASK_ALL, mask_ch1=None):
        """Escribe la máscara de los dos canales, con assert de readback.

        A diferencia de un `assert`, la relectura de C no desaparece con `python -O`.
        """
        if mask_ch1 is None:
            mask_ch1 = mask_ch0
        _ok(self, _cargar().multitrigger_set_or_masks(self._c, _i64(mask_ch0), _i64(mask_ch1)),
            'set_or_mask', {_libmca.MCA_EVERIFY: AssertionError})

    def configure_shield_autorearm(self, channels=0x3, dur=0):
        """Configura el trigger_shield para clear automático del adc_trg_dis.
        Con dur=0 el clear se emite en el MISMO ciclo del trigger (ver
        trigger_shield.sv:44-48), lo que reemplaza el pulso manual a 0x94
        después de cada disparo y permite re-triggering a velocidad de HW.

        channels: bits de los canales a auto-rearmar (0x3 = ch0+ch1).
        dur:      ciclos de ADC de holdoff antes del clear (0 = inmediato).
        Layout: {dur[31:16], 4'h0, dst[11:8], 4'h0, src[3:0]}.
        """
        _ok(self, _cargar().multitrigger_shield_autorearm(self._c, _u32(channels), _u32(dur)),
            'shield_autorearm')

    def disable_shield(self):
        """Apaga el shield (vuelve al modo SW-clear manual de 0x94)."""
        _ok(self, _cargar().multitrigger_disable_shield(self._c), 'disable_shield')

    # ---------- estatus ----------

    def get_or_mask(self, ch=0):
        return self._or_mask(ch)

    def get_shield(self):
        return self._shield()

    def read_snapshot_raw(self):
        return self._snapshot()

    def get_flags(self):
        return self._flags()


# =============================================================================
# Región propia del multitrigger (slot 3): disparo por pendiente
# =============================================================================
#
# La misma región que MultiTrigger, con el disparo por pendiente y el polo-cero.

R3_CAPS       = 0x004           # {HAS_PZ[17], HAS_SLOPE[16], SHIELD_N[15:12], SRC_W[11:4], N_CH[3:0]}
R3_SHIELD     = R_SHIELD_CFG    # {dur[31:16], dst[12:8], src[6:0]}
R3_SNAPSHOT   = 0x018           # 29 b, sticky
R3_FLAGS      = 0x01C           # {we_keep[7:4], dis_act[3:0]}
R3_OR_MASK    = 0x040           # +4·ch: la máscara con los 29 bits (pendiente y polo-cero)
R3_SLOPE_CFG  = 0x060           # +4·ch: {en[31], G[12:8], L[4:0]}
R3_SLOPE_THR  = 0x070           # +4·ch: umbral sobre |s|
R3_SLOPE_HYST = 0x080           # +4·ch: histéresis
R3_PZ_CFG     = 0x090           # +4·ch: {en[31], sh[29:24], m[12:8], k[4:0]}
R3_PZ_MQ      = 0x0A0           # +4·ch: constante polo-cero, M·16
R3_PZ_THR     = 0x0B0           # +4·ch: umbral sobre la salida del trapecio
R3_PZ_HYST    = 0x0C0           # +4·ch: histéresis

CAPS_HAS_SLOPE = 1 << 16
CAPS_HAS_PZ    = 1 << 17

# Rangos de mt_slope_trig con los parámetros del top (LMAX=16, GMAX=31, DW=14).
SLOPE_LMAX = 16
SLOPE_GMAX = 31
SLOPE_TMAX = (1 << 18) - 1

# Rangos de mt_pz_trig con los parámetros del top (DAW=5, KW=5, MW=20, TW=18):
# las líneas de retardo tienen 32 muestras, así que k + m <= 31.
PZ_LMAX = 31
PZ_MQMAX = (1 << 20) - 1
PZ_TMAX = (1 << 18) - 1


def pz_ganancia(k=2, m=1, mq=3992, sh=10, tr10=1.2):
    """Altura de la salida de mt_pz_trig por cuenta de amplitud del pulso, para
    poner el umbral en cuentas: el valor en el medio de la meseta de un pulso
    con subida 10-90 % de `tr10` muestras, la cola que cancela `mq` y el pie en
    una muestra entera. Es la ganancia del modelo con el que se validó el
    disparo (pruebas_banco.ganancia): con k = 2 y m = 1 la meseta es de una
    muestra y la subida no llega entera, así que sale ~10 % debajo de la ideal
    16·k·(1 + M) / 2^sh (7.07 contra 7.83 con el Mq nominal de 3992)."""
    M = mq / 16.0
    tau = 1.0 / math.log(1.0 + 1.0 / M) if M > 0 else float('inf')
    tr = tr10 / 2.197
    n = 2 * (k + m) + 8
    x = [0.0] + [(1.0 - math.exp(-t / tr)) * math.exp(-t / tau) for t in range(1, n)]

    def v(i):
        return x[i] if i >= 0 else 0.0

    p = s = 0.0
    out = []
    for i in range(n):
        d = v(i) - v(i - k) - v(i - k - m) + v(i - 2 * k - m)
        p += d
        s += 16.0 * p + mq * d
        out.append(s / 2.0 ** sh)
    return out[k + m // 2]


def slope_pico(L, G, escalon=None, pendiente=None):
    """Valor de s que produce un escalón o una rampa, para elegir el umbral.

    Escalón de alto A (más rápido que L+G muestras): s llega a L·A.
    Rampa de m cuentas/muestra: s = L·(L+G)·m.
    El ruido blanco σ da σ_s = σ·√(2L).
    """
    if (escalon is None) == (pendiente is None):
        raise ValueError('pasar escalon o pendiente, uno solo')
    if escalon is not None:
        return L * escalon
    return L * (L + G) * pendiente


class MtRegion(_Region):
    """La región propia del multitrigger (mt_cfg.sv), con los disparos propios."""

    _CLASE_REF = 'MtRegion'

    @classmethod
    def open(cls, phys=MTRG_PHYS, size=MTRG_SIZE, check_magic=True, impl=None):
        return cls._abrir(phys, size, check_magic, impl)

    def _tiene(self, fn):
        v = _I32()
        _ok(self, fn(self._c, ctypes.byref(v)), 'caps')
        return bool(v.value)

    # ---------- disparo por pendiente ----------

    def has_slope(self):
        return self._tiene(_cargar().multitrigger_has_slope)

    def set_slope(self, ch, L, G, thr, hyst, en=True):
        """Configura el trapezoidal rápido del canal `ch`.

        L: muestras de cada suma (1..16). G: separación entre sumas (0..31).
        thr, hyst: en unidades de s (ver `slope_pico`); hyst < thr o el
        Schmitt no re-arma en s=0. Para dispararlo hay que poner además
        BIT_SLOPE_P<ch> / BIT_SLOPE_N<ch> en la OR_MASK.
        """
        _ok(self, _cargar().multitrigger_set_slope(
            self._c, _i64(ch), _i64(L), _i64(G), _i64(thr), _i64(hyst), 1 if en else 0),
            'set_slope')

    def get_slope(self, ch):
        s = _Slope()
        _ok(self, _cargar().multitrigger_get_slope(self._c, _i64(ch), ctypes.byref(s)),
            'get_slope')
        return _sin_en(s)

    def disable_slope(self, ch):
        _ok(self, _cargar().multitrigger_disable_slope(self._c, _i64(ch)), 'disable_slope')

    # ---------- disparo con polo-cero ----------

    def has_pz(self):
        return self._tiene(_cargar().multitrigger_has_pz)

    def set_pz(self, ch, k, m, mq, sh, thr, hyst, en=True):
        """Configura el disparo con polo-cero del canal `ch`.

        k, m: subida y meseta del trapecio (k >= 1, k + m <= 31). mq: la
        constante polo-cero M·16 (la misma que el MCA, que sale de ajustar la
        cola en la placa). sh: corrimiento de la salida. thr, hyst: en unidades
        de la salida (ver `pz_ganancia`); hyst < thr o el Schmitt no re-arma.
        Para dispararlo hay que poner además BIT_PZ_P<ch> en la OR_MASK.
        """
        _ok(self, _cargar().multitrigger_set_pz(
            self._c, _i64(ch), _i64(k), _i64(m), _i64(mq), _i64(sh), _i64(thr), _i64(hyst),
            1 if en else 0), 'set_pz')

    def get_pz(self, ch):
        p = _Pz()
        _ok(self, _cargar().multitrigger_get_pz(self._c, _i64(ch), ctypes.byref(p)), 'get_pz')
        return _sin_en(p)

    def disable_pz(self, ch):
        _ok(self, _cargar().multitrigger_disable_pz(self._c, _i64(ch)), 'disable_pz')

    # ---------- máscara, shield y flags de la región propia ----------

    def set_or_mask(self, ch, mascara):
        _ok(self, _cargar().multitrigger_set_or_mask(self._c, _i64(ch), _u32(mascara)),
            'set_or_mask')

    def get_or_mask(self, ch):
        return self._or_mask(ch)

    def set_shield(self, src, dst, dur=0):
        """`src`/`dst` son máscaras (SRC_*/DST_*); `dur` el holdoff en ciclos."""
        _ok(self, _cargar().multitrigger_set_shield(self._c, _u32(src), _u32(dst), _u32(dur)),
            'set_shield')

    def get_shield(self):
        d = self._shield()
        del d['runtime']
        return d

    def get_flags(self):
        """{'dis_act': [4 bool], 'we_keep': [4 bool]} por canal."""
        w = self._flags()
        return {'dis_act': [bool((w >> c) & 1) for c in range(4)],
                'we_keep': [bool((w >> (4 + c)) & 1) for c in range(4)]}


# =============================================================================
# Configuración en bloque
# =============================================================================
#
# Misma forma que `_CAMPOS` de `API/mca.py` y de `API/osciloscope.py`:
# campo -> (offset, shift, máscara). Es lo que permite releer en una operación
# lo que se escribió, que es de lo que depende el anti-eco de la GUI.

_CAMPOS = {
    'or_mask_ch0': (R_OR_MASK_CH0, 0, 0xFFFFFFFF),
    'or_mask_ch1': (R_OR_MASK_CH1, 0, 0xFFFFFFFF),
    # Layout: {dur[31:16], 3'h0, dst[12:8], 1'b0, src[6:0]}. `src` y `dst` son
    # máscaras, no índices: los 4 bits bajos de cada una son los canales del
    # scope (0x3 = ch0+ch1); arriba, `src` tiene la entrada externa cruda
    # (flancos y NIVEL) y `dst` tiene al MCA, como VETO. Ver BITS_SHIELD_*.
    'shield_src':  (R_SHIELD_CFG,  0, 0x7F),
    'shield_dst':  (R_SHIELD_CFG,  8, 0x1F),
    'shield_dur':  (R_SHIELD_CFG, 16, 0xFFFF),
}

# ---------- bits de shield_src / shield_dst (trigger_shield.sv) ----------
#
# Con SRC_EXT_LVL y dur=0 el veto ES el nivel de DIO0_P (sincronizado); con
# dur>0 se extiende dur ciclos despues de que baje la linea. Con SRC_EXT_P es
# una ventana de dur ciclos tras el flanco. En los dos casos hace falta
# DST_MCA para que llegue al analizador; sin el, el escudo corre pero no veta.
SRC_CH0, SRC_CH1, SRC_CH2, SRC_CH3 = 1 << 0, 1 << 1, 1 << 2, 1 << 3
SRC_EXT_P   = 1 << 4
SRC_EXT_N   = 1 << 5
SRC_EXT_LVL = 1 << 6
DST_CH0, DST_CH1, DST_CH2, DST_CH3 = 1 << 0, 1 << 1, 1 << 2, 1 << 3
DST_MCA     = 1 << 4

BITS_SHIELD_SRC = (
    ('ch0',     SRC_CH0,     'disparo del canal 0 del scope'),
    ('ch1',     SRC_CH1,     'disparo del canal 1'),
    ('ch2',     SRC_CH2,     'disparo del canal 2'),
    ('ch3',     SRC_CH3,     'disparo del canal 3'),
    ('ext_p',   SRC_EXT_P,   'entrada externa (DIO0_P), flanco positivo: ventana de `dur`'),
    ('ext_n',   SRC_EXT_N,   'entrada externa, flanco negativo'),
    ('ext_lvl', SRC_EXT_LVL, 'entrada externa, NIVEL: veto mientras esté alta, más `dur`'),
)
BITS_SHIELD_DST = (
    ('ch0', DST_CH0, 'escudar el canal 0 del scope (holdoff del re-arme)'),
    ('ch1', DST_CH1, 'escudar el canal 1'),
    ('ch2', DST_CH2, 'escudar el canal 2'),
    ('ch3', DST_CH3, 'escudar el canal 3'),
    ('mca', DST_MCA, 'VETO al MCA: no abre pulsos y para el reloj de tiempo vivo'),
)

# Los bits de la OR_MASK, en orden, para que la GUI dibuje casillas con nombre
# en vez de pedir un hexadecimal. El orden es el de `trg_src_bits` del RTL y el
# mismo de `_SNAP_NAMES`, así que una casilla y su fuente en el snapshot se
# corresponden posicionalmente.
BITS_OR_MASK = (
    ('sw',       BIT_SW,       'disparo por software (registro 0x004)'),
    ('adc_p0',   BIT_ADC_P0,   'flanco positivo del ADC, canal 0'),
    ('adc_n0',   BIT_ADC_N0,   'flanco negativo del ADC, canal 0'),
    ('adc_p1',   BIT_ADC_P1,   'flanco positivo del ADC, canal 1'),
    ('adc_n1',   BIT_ADC_N1,   'flanco negativo del ADC, canal 1'),
    ('adc_p2',   BIT_ADC_P2,   'flanco positivo del ADC, canal 2'),
    ('adc_n2',   BIT_ADC_N2,   'flanco negativo del ADC, canal 2'),
    ('adc_p3',   BIT_ADC_P3,   'flanco positivo del ADC, canal 3'),
    ('adc_n3',   BIT_ADC_N3,   'flanco negativo del ADC, canal 3'),
    ('ext_p',    BIT_EXT_P,    'entrada externa, flanco positivo'),
    ('ext_n',    BIT_EXT_N,    'entrada externa, flanco negativo'),
    ('asg_p',    BIT_ASG_P,    'generador interno, flanco positivo'),
    ('asg_n',    BIT_ASG_N,    'generador interno, flanco negativo'),
    ('trig_ch0', BIT_TRIG_CH0, 'trigger del canal 0'),
    ('trig_ch1', BIT_TRIG_CH1, 'trigger del canal 1'),
    ('trig_ch2', BIT_TRIG_CH2, 'trigger del canal 2'),
    ('trig_ch3', BIT_TRIG_CH3, 'trigger del canal 3'),
    ('slope_p0', BIT_SLOPE_P0, 'pendiente positiva, canal 0 (MtRegion.set_slope)'),
    ('slope_p1', BIT_SLOPE_P1, 'pendiente positiva, canal 1'),
    ('slope_p2', BIT_SLOPE_P2, 'pendiente positiva, canal 2'),
    ('slope_p3', BIT_SLOPE_P3, 'pendiente positiva, canal 3'),
    ('slope_n0', BIT_SLOPE_N0, 'pendiente negativa, canal 0'),
    ('slope_n1', BIT_SLOPE_N1, 'pendiente negativa, canal 1'),
    ('slope_n2', BIT_SLOPE_N2, 'pendiente negativa, canal 2'),
    ('slope_n3', BIT_SLOPE_N3, 'pendiente negativa, canal 3'),
    ('pz_p0',    BIT_PZ_P0,    'polo-cero, canal 0'),
    ('pz_p1',    BIT_PZ_P1,    'polo-cero, canal 1'),
    ('pz_p2',    BIT_PZ_P2,    'polo-cero, canal 2'),
    ('pz_p3',    BIT_PZ_P3,    'polo-cero, canal 3'),
)


@_api()
def multitrigger_get_config(mt):
    """Todos los campos de `_CAMPOS`."""
    n = len(_CAMPOS)
    v = (_U * n)()
    _ok(mt, _cargar().multitrigger_get_config(mt._c, v, n), 'get_config')
    return dict(zip(_CAMPOS, v))


@_api()
def multitrigger_configure(mt, **campos):
    """Escribe campos por nombre, agrupando los que comparten registro.

    Los tres campos del shield viven en la misma palabra, así que escribirlos
    de a uno haría que el segundo leyera lo que el primero acaba de cambiar.
    La relectura es de verdad, no un `assert`: una máscara que no latchea es
    exactamente el fallo que deja el scope sin disparar, sin ningún síntoma más
    que "no llegan eventos".
    """
    desconocidos = set(campos) - set(_CAMPOS)
    if desconocidos:
        raise ValueError(f'campos desconocidos: {sorted(desconocidos)}; '
                         f'hay: {sorted(_CAMPOS)}')
    nombres = list(_CAMPOS)
    n = len(campos)
    # `int()` antes de cruzar, como antes: un valor que no convierte no deja nada
    # escrito.
    valores = (_U * n)(*(int(v) & 0xFFFFFFFF for v in campos.values()))
    indices = (_I32 * n)(*(nombres.index(c) for c in campos))
    _ok(mt, _cargar().multitrigger_configure(mt._c, indices, valores, n), 'configure')


@_api()
def multitrigger_get_status(mt):
    """Snapshot, flags y runtime del shield. Sólo lectura.

    `mca_veto` es el nivel que el shield le está mandando al MCA ahora mismo:
    con `shield_dst` sin DST_MCA es siempre False aunque el escudo corra.
    `trig_arm`: algún canal puede disparar ya. En False, el MCA suma a t_rearm.
    """
    s = _Status()
    _ok(mt, _cargar().multitrigger_get_status(mt._c, ctypes.byref(s)), 'get_status')
    return {'snapshot': s.snapshot,
            'fuentes': decode_snap(s.snapshot),
            'flags': s.flags,
            'shield_runtime': s.shield_runtime,
            'shield_active': bool(s.shield_active),
            'mca_veto': bool(s.mca_veto),
            'trig_arm': bool(s.trig_arm)}


# =============================================================================
# Secuencias que cruzan los dos módulos
# =============================================================================

def multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                     thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                     auto_rearm=True):
    """Arma el scope para trigger por flanco del ADC.

    Recibe LOS DOS handles porque la secuencia los cruza: histéresis y arm son
    registros del osciloscopio (0x20/0x24, 0x00), shield y máscara OR son del
    multitrigger (R_SHIELD_CFG, R_OR_MASK_CH*).

    ORDEN CRÍTICO (arm ANTES de la máscara): se arma la bram_sm (0x00) y RECIÉN
    DESPUÉS se habilita la OR-mask. Es la misma convención que la
    API de RedPitaya (rp_AcqStart antes de rp_AcqSetTriggerSrc). Si se hiciera
    al revés, con una señal viva un flanco de ADC puede disparar en la ventana
    pre-arm: engancha adc_trg_dis y (en single-shot) auto-limpia set_trig_src
    ANTES de que la bram_sm esté armada, dejándola esperando un trigger
    imposible (wp_trig=0 permanente). El SW trigger es inmune porque adc_trig_sw
    es pasivo hasta el pulso 0x04. Ver docs/osc/orden_arm_trigger_captura.md.

    auto_rearm=True (default): activa el trigger_shield para clear automático
        de adc_trg_dis (dur=0, inmediato) Y sobreescribe set_dly raw para
        eliminar los 65 us de offset que mete rp_AcqSetTriggerDelay. Baja el
        dead-time del sistema de ~65 us a ~us.
    auto_rearm=False: comportamiento legacy, el SW pulsa 0x94 entre triggers.

    `delay` se respeta en los dos modos; delay=0 se traduce a 1 sample, que es
    el mínimo que no cae en el caso degenerado del bram_sm (con set_dly=0 la
    FSM se saltea la espera de trigger y los ignora). OJO: el post-trigger
    delay ES dead-time real.
    """
    osc.acq_base(thr=thr, delay=delay)
    hyst_cnt = max(1, int(abs(hyst) * 8192))        # 14 b signed, escala 8192
    osc.w32(0x20, hyst_cnt)
    osc.w32(0x24, hyst_cnt)
    if auto_rearm:
        mt.configure_shield_autorearm(channels=0x3, dur=0)
        osc.set_raw_delay(delay or 1)
    else:
        mt.disable_shield()
    # arm (bit0) + we_keep (bit3) en una sola escritura, ch0 byte0 + ch1 byte1.
    # PRIMERO armar...
    b = 0x09 if we_keep_both else 0x01
    osc.w32(0x00, (b << 8) | b)
    # ...y DESPUES habilitar la mascara (arm-antes-de-fuente, ver docstring).
    mt.set_or_mask(mask_ch0, mask_ch1)


def multitrigger_disarm(osc, mt):
    """Apaga we_keep, limpia el shield y adc_trg_dis, resetea el FSM."""
    osc.w32(0x00, 0x0000_0000)
    mt.disable_shield()
    osc.w32(0x94, 0x0000_0101)
    osc.w32(0x00, 0x0000_0202)


# =============================================================================
# El disparo del MCA2
# =============================================================================
#
# En el MCA2 la ventana la abre SÓLO el disparo del multitrigger (`trig_i`): sin
# esto el MCA no mide nada. Lo que necesita es un disparo por pulso sin que el
# software intervenga entre uno y otro (docs/mca/register_map_mca.md, "Cómo
# configurar el multitrigger para el MCA"):
#
#   1. modo continuo: `we_keep` (bit 3 de 0x000 del scope) hace que la máscara
#      sobreviva al disparo;
#   2. re-armado por el shield: fuente y destino en el canal, dur = 0;
#   3. disparo por pendiente (`mt_slope_trig`) y su bit en la máscara de la
#      región propia: su Schmitt es el que re-arma, también con un pulso montado
#      sobre la cola de otro.
#
# La secuencia es la de `test_mca2_placa.py` (`Pendiente.armar`), validada en la
# placa, y `test_disparo_mca.py` exige que sea la misma escritura por escritura.

# El disparo con polo-cero que se validó para el banco: k = 2, m = 1, umbral
# en 50 cuentas de amplitud y re-armado en 25 (pruebas_banco_trapecios.md §4).
PZ_DEFAULT = dict(k=2, m=1, sh=10, thr_cuentas=50.0, hyst_cuentas=25.0)


def multitrigger_armar_mca(osc, mtr, ch=0, L=8, G=4, thr=600, hyst=300,
                           fuente='pendiente', mq=3992, k=2, m=1, sh=10,
                           thr_cuentas=50.0, hyst_cuentas=25.0):
    """Arma el disparo del canal `ch` en modo continuo, para el MCA.

    `osc` es el handle del slot 1 (el scope: arm y `we_keep`) y `mtr` la región
    propia del multitrigger (`MtRegion`, slot 3 en el top del MCA).

    fuente='pendiente' (el de siempre): `thr` y `hyst` están en unidades de la
    pendiente s (ver `slope_pico`): para un escalón de alto A, s = L·A. Los
    defaults son los de la campaña, medidos en la placa con el pulso de 2 us
    del Rigol.

    fuente='pz': el disparo con polo-cero, el del banco de trapecios. `mq` es
    la constante polo-cero, la MISMA que el MCA (la del ajuste de la cola en la
    placa); `k`, `m` y `sh` la forma (k = 2, m = 1 para el Rigol); el umbral y
    el re-armado van en cuentas de amplitud y se convierten con `pz_ganancia`.

    No veta al MCA (el shield no lleva DST_MCA). RuntimeError si `we_keep` no
    quedó puesto: sin él el disparo se apaga después del primer pulso.
    """
    if not 0 <= ch <= 3:
        raise ValueError(f'canal {ch} fuera de 0..3')
    if fuente not in ('pendiente', 'pz'):
        raise ValueError(f"fuente {fuente!r}: 'pendiente' o 'pz'")
    mtr.set_or_mask(ch, 0)
    if fuente == 'pendiente':
        mtr.disable_slope(ch)
        mtr.set_slope(ch, L, G, thr, hyst)
        bit = BIT_SLOPE_P0 << ch
    else:
        g = pz_ganancia(k, m, mq, sh)
        mtr.disable_pz(ch)
        mtr.set_pz(ch, k, m, mq, sh, int(round(thr_cuentas * g)), int(round(hyst_cuentas * g)))
        bit = BIT_PZ_P0 << ch
    mtr.set_shield(src=1 << ch, dst=1 << ch, dur=0)
    osc.w32(0x094, 0x0000_0101)                 # limpia adc_trg_dis
    # arm + we_keep en los dos canales, y DESPUÉS la máscara (arm antes que la
    # fuente: docs/osc/orden_arm_trigger_captura.md).
    osc.w32(0x000, 0x0000_0909)
    mtr.set_or_mask(ch, bit)
    if not mtr.get_flags()['we_keep'][ch]:
        raise RuntimeError(f'we_keep no quedó puesto en el canal {ch}: el '
                           f'disparo se apagaría después del primer pulso '
                           f'(flags {mtr.r32(R3_FLAGS):#x})')


def multitrigger_desarmar_mca(osc, mtr, ch=0):
    """Apaga el disparo del MCA: máscara, las fuentes, shield y `we_keep`.

    Apaga las dos fuentes, no la que diga la máscara: con la máscara ya en cero
    (un `armar` que falló a mitad de camino, otro `desarmar`) no se podría saber
    cuál quedó encendida.
    """
    mtr.set_or_mask(ch, 0)
    mtr.disable_slope(ch)
    if mtr.has_pz():
        mtr.disable_pz(ch)
    mtr.w32(R3_SHIELD, 0)
    osc.w32(0x000, 0)
    osc.w32(0x094, 0x0000_0101)
    osc.w32(0x000, 0x0000_0202)


def multitrigger_armar_banco(h, osc, mtr, mq, ch=0, pre_dly=16, formas=None,
                             n_acc=None, k=2, m=1, sh=10, thr_cuentas=50.0,
                             hyst_cuentas=25.0, **config):
    """El banco de trapecios y su disparo con polo-cero, con el MISMO `mq`.

    `mq` (M*16) está dos veces en el hardware, en el MCA y en el disparo, y tiene
    que ser la misma: la del ajuste de la cola en la placa. No tiene default a
    propósito. El resto de `config` va a `mca_configure` (por ejemplo
    `sel_1d='trapecio'`); deja el MCA parado, y el disparo armado. `n_acc=None`
    usa todas las ranuras del bitstream (4 hasta el 2026-11-09, 3 desde entonces).
    """
    from API.mca import BANCO_PZ, mca_banco_config, mca_configure, mca_get_n_acc_max
    if n_acc is None:
        n_acc = mca_get_n_acc_max(h)
    mca_configure(h, n_acc=n_acc,
                  **mca_banco_config(mq, pre_dly=pre_dly,
                                     formas=BANCO_PZ if formas is None else formas),
                  **config)
    multitrigger_armar_mca(osc, mtr, ch=ch, fuente='pz', mq=mq, k=k, m=m, sh=sh,
                           thr_cuentas=thr_cuentas, hyst_cuentas=hyst_cuentas)


def multitrigger_disparo_mca(mtr, ch=0):
    """El estado del disparo del MCA en el canal `ch`, para mostrarlo."""
    mascara = mtr.get_or_mask(ch)
    fuente = ('pz' if mascara & (BIT_PZ_P0 << ch)
              else 'pendiente' if mascara & (BIT_SLOPE_P0 << ch) else None)
    return {'pendiente': mtr.get_slope(ch),
            'polo_cero': mtr.get_pz(ch) if mtr.has_pz() else None,
            'fuente': fuente,
            'or_mask': mascara,
            'armado': fuente is not None,
            'we_keep': mtr.get_flags()['we_keep'][ch],
            'shield': mtr.get_shield()}
