#!/usr/bin/env python3
"""Osciloscopio clásico del Red Pitaya: configuración, captura y lectura.

Slot 1 del bus de sistema (0x4010_0000). Cubre lo que ya existía en el diseño
original — umbral, decimación, delay, histéresis, filtros, calibración,
punteros de escritura y las aperturas de BRAM — mientras que las máscaras OR,
el trigger_shield y el snapshot que AÑADIÓ este proyecto viven en
`API/multitrigger.py`. Son dos APIs sobre el mismo bloque físico.

    from API.osciloscope import Osciloscope, osciloscope_set_decim
    from API.multitrigger import MultiTrigger, multitrigger_arm

    osc = Osciloscope.open()
    mt  = MultiTrigger.open(osc=osc)
    osciloscope_set_decim(osc, 8)
    multitrigger_arm(osc, mt, thr=0.5)
    eventos, dur = osciloscope_read_events(osc, n=50)

El bring-up de la PL (bitstream, puentes AXI) está en `API/fpga.py`: no es del
osciloscopio, aunque viviera en el mismo fichero por accidente histórico.

**La lógica está en C** (`libmca/include/osciloscope.h`): `Osciloscope` es un binding
fino sobre un `osciloscope_h*`. `open(..., impl='py')` abre la referencia
(`API/ref_py/osciloscope2.py`), y si libmca no carga se cae a ella avisando.

Acá quedan las constantes, `geometria_scope`, lo que se compone sobre `r32`
(`verify_bitstream`, `debug_*`, `acq_capture_sw`) y comprobar que la PL esté programada
antes de abrir, que es sysfs.

**La captura también está en C** desde la Parte 6: el lazo por evento
(`osciloscope_leer_lote`, que usan `BramSource` y `capture_n_events`) y las ventanas
calibradas (`osciloscope_read_cal`, que usan `read_buffers` y `capture_window_np`). La
calibración es la de librp, con los números de la EEPROM (`calibracion_adc`): `rp` ya no
hace falta para leer.
"""

import ctypes          # el binding, y _fb_to_np: envuelve el fBuffer de rp sin copiarlo
import importlib
import mmap            # noqa: F401  (se reexporta: multitrigger_utils hace import *)
import operator
import os              # noqa: F401
import struct
import sys
import time

import numpy as np

from API import _libmca
from API._despacho import api as _api, elegir_impl as _elegir_impl
from API.fpga import (                                              # noqa: F401
    BITSTREAM_DEFAULT, FPGA_STATE, FPGA_BRIDGE_DIR,
    fpgautil_bin, fpga_state, fpga_bridges, set_fpga_bridges,
    pl_probe, pl_bus_ready, load_bitstream,
)
from API.ref_py import osciloscope2 as _ref


class _RpPerezoso:
    """Proxy que importa `rp` en el primer uso, no al importar el módulo.

    La librería de RedPitaya sólo existe en la Pitaya. Con `import rp` arriba,
    este fichero entero era inimportable desde la PC — y con él la
    configuración, los registros y cualquier test offline. Así los cuerpos que
    llaman `rp.rp_AcqGetDataPosV(...)` quedan igual que estaban y el error, si
    falta, sale donde se usa y no donde se importa.
    """

    def __getattr__(self, nombre):
        import rp as _real
        globals()['rp'] = _real          # se auto-reemplaza: sin coste después
        return getattr(_real, nombre)


rp = _RpPerezoso()



SCOPE_PHYS = 0x4010_0000

# =============================================================================
# Geometría del scope: de dónde sale y por qué no puede ser una constante
# =============================================================================
#
# Dos parámetros de síntesis la fijan, y los dos varían entre bitstreams:
#
#   RSZ    profundidad del buffer por canal, en potencias de 2. `N_BUF = 2^RSZ`.
#   N_CH   canales construidos (2 en las Z10/Z20 actuales, 4 en la z20_125_4ch).
#
# El stride de las aperturas de BRAM NO depende de RSZ: lo decide el decodificador
# de direcciones, que mira `sys_addr[19:16]` (osc_cfg.sv:432). O sea que el canal
# `i` vive siempre en 0x10000*(i+1), y con RSZ<14 la mitad alta de su apertura es
# un ALIAS de la baja — no un error de bus, un espejo silencioso.
#
# **Ese alias es la razón de que esto importe.** Como 2^14 = 2 * 2^13, pedir
# 16384 muestras a un bitstream de RSZ=13 no falla: devuelve el anillo DOS VECES,
# sin código de error y sin que nada se queje. Un `% 16384` sobre punteros de 13
# bits tampoco se rompe, porque el alias deshace exactamente el módulo de más.
# Lo único que se pierde —en silencio— es la mitad de la ventana. Por eso los
# límites tienen que salir del hardware y no de un literal: no hay excepción que
# avise.

RSZ_DEFECTO  = 14                 # los tops de hoy; `geometria()` lee el real
N_CH_DEFECTO = 2

APERTURA_BRAM_0     = 0x10000     # apertura del canal 0
APERTURA_BRAM_PASO  = 0x10000     # stride fijo, lo fija sys_addr[19:16]
APERTURAS_DECODIFICADAS = 4       # el casez decodifica 4 aunque N_CH sea menor


def geometria_scope(rsz=RSZ_DEFECTO, n_ch=N_CH_DEFECTO):
    """Profundidad, aperturas y tamaño de mapeo para un (rsz, n_ch) dados.

    Es la ÚNICA cuenta que traduce parámetros de síntesis a direcciones. Las
    constantes de abajo son su resultado para el bitstream por defecto, no una
    segunda fuente de verdad.

    `size` llega hasta el final de la apertura del último canal construido: con
    2 canales y RSZ=14 da los 0x30000 de siempre; con 4 canales y RSZ=14 hacen
    falta 0x50000, que es lo que el valor fijo no cubría.
    """
    if not 1 <= n_ch <= APERTURAS_DECODIFICADAS:
        raise ValueError(f'n_ch={n_ch} fuera de 1..{APERTURAS_DECODIFICADAS}')
    if not 1 <= rsz <= 24:
        raise ValueError(f'rsz={rsz} no es una profundidad plausible')
    n_buf     = 1 << rsz
    aperturas = tuple(APERTURA_BRAM_0 + i * APERTURA_BRAM_PASO
                      for i in range(n_ch))
    return {'rsz': rsz, 'n_ch': n_ch, 'n_buf': n_buf, 'aperturas': aperturas,
            'size': aperturas[-1] + 4 * n_buf}   # 1 palabra de 32 b por muestra


_GEO_DEFECTO = geometria_scope()

SCOPE_SIZE = _GEO_DEFECTO['size']    # 0x30000 con 2 canales y RSZ=14
N_BUF      = _GEO_DEFECTO['n_buf']   # 16384
FS         = 125e6                # Hz, sampling rate con decim=1

ADC_CNT_PER_V = 8192              # escala LV (±1 V): cuentas por volt
DEC_LEGAL     = (1, 8, 64, 1024, 8192, 65536)

# struct precompilado para los accesos al mmap: `unpack_from`/`pack_into` no
# alocan el slice intermedio ni re-parsean el formato en cada llamada, que es
# lo que domina el costo del loop de polling de capture_n_events.
_U32 = struct.Struct('<I')

# valores de reset usados como sanity check del bus (existen también en el
# scope stock — necesarios pero NO suficientes para identificar el diseño)
RESET_SET_DEC    = 1
RESET_CALIB_GAIN = 0x8000


# =============================================================================
# Registros del osciloscopio
# =============================================================================
#
# El fichero original no tenía constantes de offset: cada dirección era un
# literal hex inline. Nombrarlas es lo que permite que test_compat_api.py
# verifique los valores contra el baseline en vez de confiar en la vista.
# Sufijo _CH1 = el mismo registro para el canal 1 (offset +0x100 salvo excepciones).

R_CMD          = 0x000      # W: arm[0] rst[1] we_keep[3] indep[5] | R: adc_state
R_SW_TRIG      = 0x004      # W: [3:0]==1 dispara | R: trg_state
R_THR_CH0      = 0x008
R_THR_CH1      = 0x00C
R_DLY_CH0      = 0x010
R_DLY_CH1      = 0x110
R_DEC_CH0      = 0x014
R_DEC_CH1      = 0x114
R_WP_CUR_CH0   = 0x018
R_WP_CUR_CH1   = 0x118
R_WP_TRIG_CH0  = 0x01C
R_WP_TRIG_CH1  = 0x11C
R_HYST_CH0     = 0x020
R_HYST_CH1     = 0x024
R_AVG_EN       = 0x028
R_WE_CNT_CH0   = 0x02C
R_WE_CNT_CH1   = 0x12C
R_DEB_LEN      = 0x090
R_TRIG_DIS_CLR = 0x094
R_FILT_BYPASS  = 0x098
R_CALIB_OFF_CH0 = 0x200
R_CALIB_GAIN_CH0 = 0x204
R_CALIB_OFF_CH1 = 0x208
R_CALIB_GAIN_CH1 = 0x20C

# Las cuatro que el casez decodifica, existan o no los canales. Las del
# bitstream cargado son `Osciloscope.geometria()['aperturas']`, que se queda con
# las `n_ch` primeras.
APERTURE_BRAM = tuple(APERTURA_BRAM_0 + i * APERTURA_BRAM_PASO
                      for i in range(APERTURAS_DECODIFICADAS))

# --- mapa canónico de osc_cfg (0x01000): la geometría contada por el módulo ---
#
# `integration_cfg` publica una SEGUNDA copia de rsz/dw/n_ch en su CAPS_0, y esa
# copia ya demostró que se desincroniza: cada top pasa el literal dos veces, y
# con `h_aw` se olvidaron de una (ver el docstring de `Integration.caps`). Ésta
# es la buena, porque el mismo parámetro que la imprime es el que dimensiona la
# BRAM que hay detrás.
R_CANON_MAGIC = 0x01000
R_CANON_CAPS  = 0x01004           # {RSZ[21:16], DW[13:8], N_CH[3:0]}
MAGIC_OSC     = 0x4F53_4331       # "OSC1"; los bitstreams pre-refactor no lo tienen

# `decode_snap` decodifica el snapshot, que es un registro del
# multitrigger: la definición única vive allá. Acá se importa porque los dos
# volcados de diagnóstico (`debug_trigger`, `debug_dump`) imprimen registros de
# los dos bloques. No hay ciclo: API.multitrigger no importa este módulo.
from API.multitrigger import (                                      # noqa: E402,F401
    BIT_SW, MultiTrigger, R_FLAGS, R_OR_MASK_CH0, R_OR_MASK_CH1, R_SHIELD_CFG,
    R_SHIELD_RUN, R_TRIG_SNAP, _dict, _i64, _u32, decode_snap)


# =============================================================================
# libmca: carga, firmas y tipos
# =============================================================================
#
# Los structs replican los de include/osciloscope.h campo por campo. `_cargar()`
# compara su tamaño con el que informa C: con un campo agregado de un solo lado,
# ctypes leería corrido sin ningún error.

_I32, _I64, _U, _D = ctypes.c_int32, ctypes.c_int64, ctypes.c_uint32, ctypes.c_double
_P, _PU, _PD = ctypes.c_void_p, ctypes.POINTER(_U), ctypes.POINTER(_D)
_PI, _PL = ctypes.POINTER(_I32), ctypes.POINTER(_I64)
_PP = ctypes.POINTER(ctypes.c_void_p)
_PS = ctypes.POINTER(ctypes.c_int16)

_AMBOS = -2 ** 63               # OSCILOSCOPE_AMBOS


class _Geometria(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('rsz', 'n_ch', 'dw', 'n_buf', 'size')] + [
        ('descubierta', _I32), ('aperturas', _U * APERTURAS_DECODIFICADAS)]


class _Calib(ctypes.Structure):
    _fields_ = [('offset', _U), ('gain', _U)]


class _Status(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('adc_state', 'trg_state', 'wp_cur_ch0', 'wp_cur_ch1',
                                  'wp_trig_ch0', 'wp_trig_ch1', 'we_cnt_ch0', 'we_cnt_ch1')]


class _AdcCal(ctypes.Structure):
    _fields_ = [('gain', _U), ('base', _U), ('offset', _I32)]


class _LoteCfg(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('pre', 'post', 'n_ch', 'mascara', 'wp_off')] + [
        (k, _I32) for k in ('single_shot', 'rearmar', 'leer_snap')] + [
        ('cal', _AdcCal * APERTURAS_DECODIFICADAS)]


class _LoteEstado(ctypes.Structure):
    _fields_ = [('pendientes', ctypes.c_uint64), ('wp_prev', _U), ('reservado', _U)]


class _Lote(ctypes.Structure):
    _fields_ = [('wave', _PS), ('t_ns', _PL), ('wp', _PI), ('snap', _PU),
                ('gap', ctypes.POINTER(ctypes.c_uint8)), ('dead_ns', _PL)]


class _LoteRes(ctypes.Structure):
    _fields_ = [('n', _U), ('reservado', _U), ('descartados', ctypes.c_uint64),
                ('asignados', ctypes.c_uint64)]


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
    # suelta, y el servidor lo tomaría por "este bitstream no trae el osciloscopio".
    if not hasattr(lib, 'osciloscope_open') or not hasattr(lib, 'osciloscope_leer_lote'):
        raise OSError('libmca no tiene osciloscope_*: el .so es de otra versión. '
                      'Recompilarla: `make -C libmca arm` en la PC y volver a '
                      'copiarla a la placa, o `make -C libmca placa-lib`.')

    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)

    c = ctypes.c_int
    pg = ctypes.POINTER(_Geometria)
    f('osciloscope_open', c, _PP, _U, _U)
    f('osciloscope_open_file', c, _PP, ctypes.c_char_p, _U, _U)
    f('osciloscope_open_bus', c, _PP, _P, c)
    f('osciloscope_close', None, _P)
    f('osciloscope_last_error', ctypes.c_char_p, _P)
    f('osciloscope_reg_count', _I32)
    f('osciloscope_reg_info', ctypes.POINTER(_Reg), _I32)
    f('osciloscope_field_count', _I32)
    f('osciloscope_field_info', ctypes.POINTER(_Field), _I32)
    f('osciloscope_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    f('osciloscope_r32', c, _P, _U, _PU)
    f('osciloscope_w32', c, _P, _U, _U)
    f('osciloscope_geometria_de', c, _I64, _I64, pg)
    f('osciloscope_get_geometria', c, _P, pg)
    f('osciloscope_get_thr', c, _P, _I64, _PD)
    f('osciloscope_set_thr', c, _P, _D, _I64)
    f('osciloscope_get_decim', c, _P, _I64, _PU)
    f('osciloscope_set_decim', c, _P, _I64, _I64)
    f('osciloscope_get_delay', c, _P, _I64, _PU)
    f('osciloscope_set_delay', c, _P, _U, _I64)
    f('osciloscope_get_hysteresis', c, _P, _I64, _PD)
    f('osciloscope_set_hysteresis', c, _P, _D, _I64)
    f('osciloscope_get_calibration', c, _P, _I64, ctypes.POINTER(_Calib))
    f('osciloscope_set_calib_offset', c, _P, _I64, _U)
    f('osciloscope_set_calib_gain', c, _P, _I64, _U)
    f('osciloscope_get_avg', c, _P, _PI)
    f('osciloscope_set_avg', c, _P, _I32)
    f('osciloscope_get_deb_len', c, _P, _PU)
    f('osciloscope_set_deb_len', c, _P, _U)
    f('osciloscope_get_filter_bypass', c, _P, _PU)
    f('osciloscope_set_filter_bypass', c, _P, _U)
    f('osciloscope_get_config', c, _P, _PL, _I32)
    f('osciloscope_configure', c, _P, _PI, _PU, _I32)
    f('osciloscope_get_adc_state', c, _P, _PU)
    f('osciloscope_get_trg_state', c, _P, _PU)
    f('osciloscope_get_wp_cur', c, _P, _I64, _PU)
    f('osciloscope_get_wp_trig', c, _P, _I64, _PU)
    f('osciloscope_get_we_cnt', c, _P, _I64, _PU)
    f('osciloscope_get_status', c, _P, ctypes.POINTER(_Status))
    f('osciloscope_reset', c, _P)
    f('osciloscope_sw_trigger', c, _P)
    f('osciloscope_acq_base', c, _P, _D, _U, _I64)
    f('osciloscope_read_bram', c, _P, _I64, _I64, _I64, _PS)
    pc = ctypes.POINTER(_AdcCal)
    f('osciloscope_calibrar', c, pc, _I64, _PU, _PS, _I64)
    f('osciloscope_read_cal', c, _P, _I64, _I64, _I64, pc, _PS)
    f('osciloscope_lote_iniciar', c, _P, ctypes.POINTER(_LoteCfg),
      ctypes.POINTER(_LoteEstado))
    f('osciloscope_leer_lote', c, _P, _P, ctypes.POINTER(_LoteCfg),
      ctypes.POINTER(_LoteEstado), ctypes.POINTER(_Lote), _U, _I64,
      ctypes.POINTER(_LoteRes))
    f('osciloscope_ahora_ns', _I64)

    if lib.osciloscope_field_count() != len(_CAMPOS):
        raise OSError(f'libmca tiene {lib.osciloscope_field_count()} campos del '
                      f'osciloscopio y API/osciloscope.py {len(_CAMPOS)}: el .so es de '
                      'otra versión. Recompilarla: `make -C libmca arm`.')
    for tipo, py in (('osciloscope_geometria_t', _Geometria), ('osciloscope_calib_t', _Calib),
                     ('osciloscope_status_t', _Status), ('osciloscope_adc_cal_t', _AdcCal),
                     ('osciloscope_lote_cfg_t', _LoteCfg),
                     ('osciloscope_lote_estado_t', _LoteEstado),
                     ('osciloscope_lote_t', _Lote),
                     ('osciloscope_lote_resultado_t', _LoteRes)):
        if lib.osciloscope_sizeof(tipo.encode()) != ctypes.sizeof(py):
            raise OSError(f'libmca y API/osciloscope.py no coinciden en {tipo}: '
                          f'{lib.osciloscope_sizeof(tipo.encode())} contra '
                          f'{ctypes.sizeof(py)} bytes. Recompilar libmca o '
                          'actualizar el struct del binding.')
    _lib = lib
    return lib


def _ok(h, rc, que=''):
    """rc de libmca -> nada, o la excepción con el detalle que dejó C. Si el handle
    corre sobre callbacks, primero se relanza la excepción que haya tirado un
    callback: es la causa real."""
    if rc == 0:
        return
    det = _cargar().osciloscope_last_error(h._c).decode('utf-8', 'replace') or None
    if h._bus is not None:
        h._bus.check(rc, que, None, det)
    _libmca.check(rc, que, None, det)


def _volts(v):
    """Un número de Python al double de C. Multiplicar es lo que hacía la cuenta en
    Python, y rechaza lo mismo: `float()` aceptaría el string '0.5'."""
    return float(v * 1.0)


def _cual(ch):
    """El canal de un set: None son los dos."""
    return _AMBOS if ch is None else _i64(ch)


def _decim(v):
    """Lo que no es entero tampoco es legal. C valida el resto, con este mismo mensaje."""
    try:
        return _i64(v)
    except TypeError:
        raise ValueError(f'decim {v} no legal; usar {DEC_LEGAL}') from None


def _u32_de(h, fn, *args, que=''):
    v = _U()
    rc = fn(h._c, *args, ctypes.byref(v))
    if rc:
        _ok(h, rc, que)
    return v.value


def _fb_to_np(fb, n):
    """Convierte un rp.fBuffer (array SWIG de floats) a np.ndarray(float32).

    Usa np.frombuffer sobre el puntero del buffer (fb.cast()) en vez del loop
    `np.fromiter((fb[i] for i in range(n)))`: ~800x más rápido (medido en
    API/bench/bench_read_vs_length.py; 105 ms -> 0.12 ms para 16384 samples), porque
    evita n accesos SWIG desde Python. `.copy()` es obligatorio: la memoria del
    fBuffer se reusa/libera.
    """
    addr = int(fb.cast().__int__())
    return np.frombuffer((ctypes.c_float * n).from_address(addr),
                         dtype=np.float32).copy()

class Osciloscope:
    """Wrapper del cfg del osciloscopio + helpers de diagnóstico,
    arm y captura.

    No abre por sí solo: usar :py:meth:`open` o pasar (mmap, fd) si ya los
    tenés mapeados.
    """

    impl = 'c'
    _via = 'c'
    _CLASE_REF = _ref.Osciloscope   # la de esta clase en la referencia

    def __init__(self, scope_mmap, fd):
        """Un handle sobre un buffer ya mapeado, o sobre el `r32`/`w32` de una
        subclase con `scope_mmap=None`, sin leer nada. Ver `_libmca.Bus.de_handle`."""
        self._mmap = scope_mmap
        self._fd   = fd
        self._propio = fd is not None and fd >= 0   # con fd = -1 el mmap es prestado
        self._c    = None
        self._bus  = None
        self._geo  = None
        self._mt   = None           # lo abre `mt`, recién si hace falta
        self._region  = None        # (phys, size), si abrió /dev/mem
        self._cal     = {}          # canal -> calibración del ADC, ver calibracion()
        lib = _cargar()
        self._bus = _libmca.Bus.de_handle(self, Osciloscope, scope_mmap, tarde=True)
        p = ctypes.c_void_p()
        _libmca.check(lib.osciloscope_open_bus(ctypes.byref(p), self._bus.ptr, 0),
                      'osciloscope_open_bus')
        self._c = p

    @property
    def mt(self):
        """El multitrigger, para lo de acá que lo cruza (snapshot, máscara de la
        captura por software, diagnóstico). Vive en otra región, así que tiene su
        mapeo, y se abre la primera vez: quien no lo usa no lo necesita presente."""
        if self._mt is None:
            self._mt = MultiTrigger.open(impl=self.impl)
        return self._mt

    @classmethod
    def open(cls, phys=SCOPE_PHYS, size=SCOPE_SIZE, check_pl=True, impl=None):
        """Abrir /dev/mem y mapear la región del scope.

        `size=None` la descubre: mapea una página, lee la geometría del mapa
        canónico y re-mapea con el tamaño que hace falta. Es lo que hay que usar
        cuando el bitstream puede no ser el de siempre — con 4 canales el valor
        por defecto se queda corto y las aperturas de los canales 3 y 4 no entran
        en el mapeo.

        `check_pl` mira el FPGA manager antes de mapear: si la PL no está
        'operating' no hay quién conteste en el bus y la PRIMERA lectura del
        scope mata el proceso con SIGBUS (external abort), sin traceback. Es
        barato chequearlo acá en vez de perder el kernel.

        `impl` es 'c' o 'py'; sin decirlo, `$MCA_IMPL` o 'c' si libmca carga.
        """
        impl, aviso = _elegir_impl(impl)
        if aviso:
            print(f'warn: {aviso}', file=sys.stderr)
        if impl == 'py':
            h = cls._CLASE_REF.open(phys, size, check_pl)
            h._via = 'py'
            h.impl = 'py'
            return h
        if check_pl:
            st = fpga_state()
            # st is None -> el sysfs no existe y no se puede saber: no bloquear.
            if st is not None and st != 'operating':
                raise RuntimeError(
                    f'la PL no está programada (fpga0/state={st!r}). Cargá el '
                    'bitstream ANTES de abrir el scope: load_bitstream(). '
                    'Mapear y leer ahora daría SIGBUS.')
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.osciloscope_open(ctypes.byref(p), phys, 0 if size is None else size)
        if rc:
            det = lib.osciloscope_last_error(None).decode('utf-8', 'replace') or None
            _libmca.check(rc, f'/dev/mem @ {phys:#x}', None, det)
        h = cls._envolver(p, None)
        h._region = (phys, h.geometria()['size'] if size is None else size)
        return h

    @classmethod
    def _sobre_bus(cls, bus):
        """Un handle sobre un `_libmca.Bus` ya abierto, que pasa a ser suyo: lo
        cierra `close()`. Lo usan los tests y `bench_impl.py --shm`, con el backend
        devmem apuntando a un fichero."""
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.osciloscope_open_bus(ctypes.byref(p), bus.ptr, 0)
        if rc:
            bus.check(rc, 'osciloscope_open_bus')
        return cls._envolver(p, bus)

    @classmethod
    def _de_fichero(cls, ruta, phys=0, size=None):
        """Como `open`, con un fichero común en vez de /dev/mem: prueba la sonda de
        geometría y el mapeo sin la placa."""
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.osciloscope_open_file(ctypes.byref(p), os.fsencode(ruta), phys,
                                       0 if size is None else size)
        if rc:
            det = lib.osciloscope_last_error(None).decode('utf-8', 'replace') or None
            _libmca.check(rc, str(ruta), None, det)
        return cls._envolver(p, None)

    @classmethod
    def _envolver(cls, p, bus):
        h = cls.__new__(cls)
        h._mmap, h._fd, h._propio, h._bus, h._c = None, -1, False, bus, p
        h._geo, h._mt, h._region, h._cal = None, None, None, {}
        return h

    # ---------- geometría ----------

    def geometria(self):
        """Profundidad y canales del bitstream CARGADO, no los de por defecto.

        Sale del mapa canónico de `osc_cfg` (0x01004), que imprime los mismos
        parámetros `RSZ`/`N_CH` con los que se dimensionó la BRAM de al lado.

        Un bitstream anterior al refactor de registros no tiene ese mapa: ahí
        0x01000 no trae el magic y se devuelve la geometría por defecto, con
        `descubierta=False` para que quien necesite saberlo pueda distinguir un
        dato leído de una suposición. Falla ABIERTA por lo mismo que la guarda
        de variante: negarse a operar contra un bitstream viejo sería peor que
        operar con los valores que ese bitstream justamente tiene.
        """
        if self._geo is None:
            g = _Geometria()
            _ok(self, _cargar().osciloscope_get_geometria(self._c, ctypes.byref(g)),
                'geometria')
            self._geo = {'rsz': g.rsz, 'n_ch': g.n_ch, 'n_buf': g.n_buf,
                         'aperturas': tuple(g.aperturas[:g.n_ch]), 'size': g.size,
                         'dw': g.dw, 'descubierta': bool(g.descubierta)}
        return self._geo

    @property
    def n_buf(self):
        """Muestras por canal del bitstream cargado. Ver `geometria`."""
        return self.geometria()['n_buf']

    @classmethod
    def reload_bitstream(cls, path=BITSTREAM_DEFAULT, scope=None,
                         phys=SCOPE_PHYS, size=SCOPE_SIZE, release_rp=True,
                         verbose=True):
        """Recarga la PL a mitad de sesión con el orden menos riesgoso.

        Reprogramar con los mapeos abiertos es lo que produce el
        `external abort ... *pte=40100743` de dmesg (ver `load_bitstream`).
        Acá el orden es:

            cerrar el mmap  ->  rp_Release  ->  fpgautil (con los puentes AXI
            bajos)  ->  rp_Init  ->  reabrir

        **Aun así, reconfigurar en caliente NO es seguro del todo en esta
        placa.** El bus de registros del scope está en el dominio `adc_clk` y
        en reset por `adc_rstn = frstn[0] & ~rst_after_locked`
        (red_pitaya_top.sv:227 y :289): mientras la PL se reconfigura no hay
        esclavo que conteste, y si el puerto GP0 llega a abortar una vez queda
        trabado — todo acceso posterior a 0x4010_0000 aborta aunque la PL ya
        esté bien. **De ese estado sólo se sale reiniciando la Pitaya.**

        Si venís de un kernel muerto por SIGBUS: reiniciá la placa y cargá el
        bitstream UNA vez, antes de mapear nada (primera celda del notebook).

        `scope` es la instancia actual (se cierra); devuelve la NUEVA, así que
        en el notebook hay que reasignar:  ``sc = MultiTriggerScope.reload_bitstream(scope=sc)``
        La vieja queda inutilizable.
        """
        if scope is not None:
            try:
                scope.close()
            except Exception as e:
                print('warn: cerrando el scope viejo:', e)
        if release_rp:
            try:
                rp.rp_Release()
            except Exception as e:
                print('warn: rp_Release:', e)
        info = load_bitstream(path)
        if release_rp:
            rp.rp_Init()
        new = cls.open(phys, size, impl=getattr(scope, 'impl', None))
        if verbose:
            print(f'bitstream recargado: {info["path"]}  state={info["state"]}')
            print(f'  cfg sanity: OR_MASK ch0 = {new.mt.r32(R_OR_MASK_CH0):#010x} '
                  f'(esperado tras reset: 0)')
        return new

    def close(self):
        mt, self._mt = getattr(self, '_mt', None), None
        if mt is not None:
            mt.close()
        c, self._c = getattr(self, '_c', None), None
        if c:
            _cargar().osciloscope_close(c)
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

    # ---------- acceso al bus ----------

    def w32(self, off, v):
        # En C: un store de 32 b alineado, validado antes de llegar al bus.
        rc = _cargar().osciloscope_w32(self._c, off, _u32(v))
        if rc:
            _ok(self, rc, f'w32 {off:#x}')

    def r32(self, off):
        v = _U()
        rc = _cargar().osciloscope_r32(self._c, off, ctypes.byref(v))
        if rc:
            _ok(self, rc, f'r32 {off:#x}')
        return v.value

    # ---------- la calibración del ADC ----------

    def calibracion(self, ch):
        """La de librp para el canal `ch`: `{'gain', 'base', 'offset'}`. Se lee de la
        EEPROM la primera vez (`calibracion_adc`) y queda guardada en el handle."""
        ch = operator.index(ch)
        if ch not in self._cal:
            self._cal[ch] = calibracion_adc([ch])[0]
        return dict(self._cal[ch])

    def set_calibracion(self, cal):
        """Fija la calibración en vez de leerla: `{canal: {'gain', 'base', 'offset'}}`,
        o una lista desde el canal 0. Para los tests, los simuladores y para repetir
        una corrida con la calibración de otra."""
        items = cal.items() if isinstance(cal, dict) else enumerate(cal)
        nueva = {operator.index(k): _cal_dict(v) for k, v in items}
        dw = self.geometria()['dw']
        for v in nueva.values():        # valida acá, en C, y no en la primera lectura
            osciloscope_calibrar(v, np.zeros(1, np.uint32), dw)
        self._cal.update(nueva)

    def read_cal(self, ch, start, n):
        """`osciloscope_read_cal` con la calibración de este handle."""
        return osciloscope_read_cal(self, ch, start, n, self.calibracion(ch))

    # ---------- diagnóstico ----------

    def debug_trigger(self):
        """Dump completo de regs del scope (write-side + run-time)."""
        print('--- write-side (config) ---')
        print(f'  set_tresh ch0/ch1 @0x08/0x0C = {self.r32(0x08):#010x} / {self.r32(0x0C):#010x}')
        print(f'  set_hyst  ch0/ch1 @0x20/0x24 = {self.r32(0x20):#010x} / {self.r32(0x24):#010x}')
        print(f'  set_deb_len       @0x90     = {self.r32(0x90):#010x}')
        mt = self.mt
        print(f'  OR_MASK ch0/ch1 (mtrg) = {mt.r32(R_OR_MASK_CH0):#010x} / {mt.r32(R_OR_MASK_CH1):#010x}')
        print(f'  shield_cfg      (mtrg) = {mt.r32(R_SHIELD_CFG):#010x}')
        print('--- run-time (status / debug) ---')
        print(f'  adc_state         @0x00 = {self.r32(0x00):#010x}  (config + trigger_status por canal)')
        print(f'  trg_state         @0x04 = {self.r32(0x04):#010x}  (set_trig_src[7:0] activo por canal en bytes)')
        print(f'  shield runtime  (mtrg) = {mt.r32(R_SHIELD_RUN):#010x}  ({{active, cnt[15:0]}})')
        snap = mt.r32(R_TRIG_SNAP)
        print(f'  snapshot        (mtrg) = {snap:#010x}  -> {decode_snap(snap)}')
        dis_we = mt.r32(R_FLAGS)
        print(f'  dis+we_keep     (mtrg) = {dis_we:#010x}  dis_act={dis_we & 0xF:#x} we_keep={(dis_we>>4) & 0xF:#x}')
        print(f'  wp_trig ch0/ch1   @0x1C/0x11C = {self.r32(0x1C):#010x} / {self.r32(0x11C):#010x}')
        print(f'  wp_cur  ch0/ch1   @0x18/0x118 = {self.r32(0x18):#010x} / {self.r32(0x118):#010x}')

    def debug_dump(self):
        """Versión corta — solo lo más relevante por captura."""
        mt = self.mt
        snap = mt.r32(R_TRIG_SNAP)
        print(f'  snapshot = {snap:#010x}  -> {decode_snap(snap)}')
        print(f'  dis_act  = {mt.r32(R_FLAGS):#010x}')
        print(f'  mask act ch0/ch1 = {mt.r32(R_OR_MASK_CH0):#010x} / {mt.r32(R_OR_MASK_CH1):#010x}')
        print(f'  wp_trig ch0/ch1 = {self.r32(0x1C):#010x} / {self.r32(0x11C):#010x}')
        print(f'  shield   = {mt.r32(R_SHIELD_RUN):#010x}')

    # ---------- verificación del bitstream ----------

    def _probe_rw(self, off, patterns, mask=0xFFFFFFFF, dev=None):
        """Escribe cada patrón en `off` y lo lee de vuelta (comparando solo los
        bits de `mask`, para registros con nibbles no almacenados). Restaura
        siempre el valor original. Devuelve (ok, orig).

        Es la prueba fuerte de que un registro R/W EXISTE: una dirección
        read-only o no decodificada no retiene lo escrito. `dev` es el bloque a
        probar, si no es el osciloscopio.
        """
        dev = self if dev is None else dev
        orig = dev.r32(off)
        ok = True
        try:
            for p in patterns:
                dev.w32(off, p)
                got = dev.r32(off) & mask
                if got != (p & mask):
                    ok = False
                    break
        finally:
            dev.w32(off, orig)           # restaurar sí o sí
        return ok, orig

    def verify_bitstream(self, verbose=True, raise_on_fail=False):
        """Comprueba que el bitstream cargado sea realmente el diseño
        multitrigger (y no el scope stock ni una región sin decodificar).

        Estrategia (ver docs/osc/register_map_mt_rp_scope_cfg.md):

        1. **Sanity** (necesario, no suficiente): registros comunes al scope
           stock leen su valor de reset. Detecta "no hay bitstream / región
           equivocada / bus muerto", pero NO distingue este diseño del stock.
        2. **Fingerprint** (decisivo): readback R/W sobre los registros que el
           scope original NO tiene — OR_MASK y trigger_shield, en la región del
           multitrigger. Si retienen patrones escritos, el multitrigger está
           cargado. No destructivo: restaura los valores originales.

        Correr ANTES de armar (los probes tocan la máscara y el shield, que
        set_or_mask / arm reescriben igual). Devuelve dict con 'ok', 'sanity_ok',
        'fingerprint_ok' y 'checks' (lista de (nombre, esperado, obtenido, ok)).
        """
        checks = []   # (nombre, esperado_str, obtenido, ok, tipo)

        # 1) sanity: comunes al scope stock
        for name, off, exp in (
            ('set_dec_ch0 @0x014', 0x014, RESET_SET_DEC),
            ('set_dec_ch1 @0x114', 0x114, RESET_SET_DEC),
            ('calib_gain0 @0x204', 0x204, RESET_CALIB_GAIN),
        ):
            got = self.r32(off)
            checks.append((name, f'{exp:#010x}', got, got == exp, 'sanity'))

        # 2) fingerprint: R/W readback en registros multitrigger-only.
        #    patrones = dos valores distintos + limpieza a 0.
        #    El shield tiene nibbles [15:12] y [7:4] no almacenados -> mask 0xFFFF0F0F.
        #    Un bitstream sin la región falla acá, sin levantar la excepción.
        dis_we = 0
        try:
            mt = self.mt
        except RuntimeError as e:
            mt = None
            checks.append(('región multitrigger', 'MAGIC MTRG', 0, False, 'fingerprint'))
            if verbose:
                print(f'  {e}')
        if mt is not None:
            for name, off, pats, mask in (
                ('OR_MASK ch0', R_OR_MASK_CH0, (0xA5A5_5A5A, 0x0000_FFFF, 0x0), 0xFFFF_FFFF),
                ('OR_MASK ch1', R_OR_MASK_CH1, (0x5A5A_A5A5, 0xFFFF_0000, 0x0), 0xFFFF_FFFF),
                ('shield_cfg',  R_SHIELD_CFG,  (0x1234_050A, 0x0),              0xFFFF_0F0F),
            ):
                ok, _orig = self._probe_rw(off, pats, mask, dev=mt)
                checks.append((name, 'R/W latch', mt.r32(off), ok, 'fingerprint'))
            # info suave (dependiente de estado, no afecta el veredicto)
            dis_we = mt.r32(R_FLAGS)

        sanity_ok = all(ok for _, _, _, ok, t in checks if t == 'sanity')
        fp_ok     = all(ok for _, _, _, ok, t in checks if t == 'fingerprint')
        ok        = sanity_ok and fp_ok

        if verbose:
            print('=== verify_bitstream ===')
            for name, exp, got, cok, t in checks:
                flag = 'OK ' if cok else 'FAIL'
                print(f'  [{flag}] {name:22s} esperado={exp:12s} leido={got:#010x}  ({t})')
            print(f'  info: dis+we_keep = {dis_we:#010x} '
                  f'(dis={dis_we & 0xF:#x} we_keep={(dis_we >> 4) & 0xF:#x}; '
                  f'0 esperado recién cargado)')
            if ok:
                print('  -> VERDICTO: PASS — diseño multitrigger cargado y verificado')
            elif sanity_ok and not fp_ok:
                print('  -> VERDICTO: FAIL — hay un scope mapeado pero NO es el '
                      'multitrigger (¿bitstream stock? ¿versión vieja?)')
            else:
                print('  -> VERDICTO: FAIL — no se lee un scope válido en '
                      f'{SCOPE_PHYS:#010x} (¿bitstream sin cargar? ¿fpgautil falló?)')

        if raise_on_fail and not ok:
            raise RuntimeError('verify_bitstream: el bitstream cargado no es el '
                               'diseño multitrigger esperado')

        return {'ok': ok, 'sanity_ok': sanity_ok, 'fingerprint_ok': fp_ok,
                'checks': checks}

    # ---------- configuración acq ----------

    def acq_base(self, thr=0.5, delay=0, decim=1):
        """Reset + decim/threshold/delay por escritura directa de registros.

        Reemplaza la rp API (rp_AcqReset / SetDecimation / SetTriggerLevel /
        SetTriggerDelay) por writes a /dev/mem ya verificados en
        multitrigger_test_cfg.ipynb (tabla TESTS).

        NOTA: thr se convierte a cuentas con escala fija ADC_CNT_PER_V
        (8192 cuentas/V, rango LV ±1 V). A diferencia de
        rp_AcqSetTriggerLevel, NO aplica la calibración de EEPROM; para
        triggering por flanco la diferencia es despreciable.

        Limpia adc_trg_dis (0x94): tras un trigger single-shot el HW deja el
        trigger BLOQUEADO (adc_trg_dis latcheado) y la máscara efectiva queda
        en 0. rp_AcqReset lo reseteaba implícitamente; el reset directo
        (adc_rst_do) NO, así que lo desbloqueamos explícitamente acá para que
        cada re-config pueda volver a disparar.
        """
        d = _decim(decim)
        rc = _cargar().osciloscope_acq_base(self._c, _volts(thr), _u32(delay), d)
        if rc:
            _ok(self, rc, 'acq_base')

    def set_raw_delay(self, delay=1):
        """Bypasea el offset que mete rp_AcqSetTriggerDelay. Escribe set_dly
        directamente al cfg (0x10 ch0, 0x110 ch1). Sin esto, llamar a
        rp_AcqSetTriggerDelay(0) en realidad escribe ~8192 samples = 65 µs
        de post-trigger delay, que impone un floor de dead-time de 65 µs.

        Default delay=1 (= 8 ns) en lugar de 0 porque el rp_bram_sm tiene un
        caso degenerado con set_dly=0: la FSM trata el contador en 0 como
        'delay completo' antes de ver el trigger, se salta el estado de
        espera-trigger y termina ignorando los triggers que llegan.
        delay=1 es efectivamente 0 (8 ns es << que cualquier flanco real)
        pero evita ese caso degenerado.
        """
        _ok(self, _cargar().osciloscope_set_delay(self._c, _u32(delay), _AMBOS),
            'set_raw_delay')

    # ---------- waits ----------
    #
    # Eran `rp_AcqGetTriggerState` y `rp_AcqGetBufferFillState`, que leen los bits 2
    # (adc_trg_rd) y 4 (adc_dly_end) de 0x000 del canal 0 (rp-api 2.00,
    # oscilloscope.c). Se leen acá, por C, con la misma pausa de 1 ms.

    def _esperar_bit(self, bit, timeout_ms):
        for _ in range(timeout_ms):
            if osciloscope_get_adc_state(self) & bit:
                return True
            time.sleep(0.001)
        return False

    def wait_triggered(self, timeout_ms=2000):
        """Hasta que el canal 0 haya disparado. CUIDADO: en we_keep=1 es STICKY."""
        return self._esperar_bit(0x04, timeout_ms)

    def wait_fill(self, timeout_ms=2000):
        """Hasta que la FSM del canal 0 complete el post-trigger."""
        return self._esperar_bit(0x10, timeout_ms)

    def read_buffers(self, n_buf=None):
        """Los dos buffers enteros, del más viejo al más nuevo, en volts (float32).

        Es lo que daba `rp_AcqGetOldestDataV`: desde `wp_cur + 1` del canal 0, con la
        calibración de librp (`calibracion`). En LV, cuenta / 8192 es exactamente el
        float de librp. `n_buf=None` es el anillo del bitstream cargado.
        """
        n = self.n_buf if n_buf is None else n_buf
        start = osciloscope_get_wp_cur(self, 0) + 1
        return tuple(self.read_cal(ch, start, n).astype(np.float32) / ADC_CNT_PER_V
                     for ch in (0, 1))

    def capture_window_np(self, channels=None, pre=0, post=None, at_trigger=True,
                          n_buf=None):
        """Una ventana de `pre+post` muestras alrededor del trigger, por canal, en volts.

        Ventana = posiciones [ref-pre, ref+post-1], con `ref` = wp_trig del canal 0
        si `at_trigger` (la muestra del disparo) y wp_cur si no: lo mismo que
        `rp_AcqGetWritePointerAtTrig` y `rp_AcqGetWritePointer`. Da la vuelta al
        anillo sin cortar la ventana. La calibración es la de librp (`calibracion`):
        cuenta / 8192 es el float que devolvía `rp_AcqGetDataPosV`.

        `n_buf` y `post` son, sin decirlos, el anillo del bitstream cargado. Pedir
        más muestras que el anillo es un ValueError, y no el buffer repetido.
        Devuelve (data, ref) con data = {canal: np.ndarray(float32)}; los canales son
        0 y 1, como `rp.RP_CH_1` y `rp.RP_CH_2`.
        """
        if n_buf is None:
            n_buf = self.n_buf
        if post is None:
            post = n_buf
        if pre + post > n_buf:
            raise ValueError(
                f'ventana de {pre + post} muestras sobre un anillo de {n_buf}: '
                f'el hardware devolvería el buffer repetido sin avisar')
        if channels is None:
            channels = (0, 1)
        ref = (osciloscope_get_wp_trig(self, 0) if at_trigger
               else osciloscope_get_wp_cur(self, 0))
        n = pre + post
        data = {ch: self.read_cal(ch, ref - pre, n).astype(np.float32) / ADC_CNT_PER_V
                for ch in channels}
        return data, ref

    # ---------- captura ----------

    def acq_capture_sw(self, thr=0.5, delay=None, timeout_ms=500):
        """Captura single-shot forzada con SW trigger (mask=BIT_SW + pulso a 0x04).
        Devuelve (d1, d2, snapshot). Sirve para confirmar que el bram_sm
        captura el buffer correctamente, independiente del trigger ADC.
        """
        if delay is None:
            delay = self.n_buf // 2       # el del bitstream, no el de por defecto
        self.acq_base(thr=thr, delay=delay)
        # Limpiar adc_trg_dis si quedó pegado de una corrida anterior. Sin esto,
        # src_mask = set_trig_src & {!adc_trg_dis} = 0 y el SW pulse no firma.
        self.w32(0x94, 0x0000_0101)
        self.mt.set_or_mask(BIT_SW, BIT_SW)
        self.w32(0x00, 0x0000_0101)     # arm ch0+ch1 (single-shot, sin we_keep)
        time.sleep(0.01)
        self.w32(0x04, 0x0000_0101)     # pulso adc_trig_sw[0] y [1]
        self.wait_fill(timeout_ms=timeout_ms)
        d1, d2 = self.read_buffers(self.n_buf)
        return d1, d2, self.mt.r32(R_TRIG_SNAP)

    def capture_n_events(self, n=100, timeout_ms=2000, wp_addr=0x1C,
                          clear_both=True, read_snap=False, deadline_every=256):
        """Captura n triggers consecutivos detectando cambios en wp_trig.
        Requiere `arm_for_adc_trigger` previo.

        Con `arm_for_adc_trigger(auto_rearm=True)` (default) el trigger_shield
        del FPGA limpia adc_trg_dis automáticamente cada disparo, así que el
        loop NO necesita pulsar 0x94. Solo polea cambios de wp_trig.

        Si se llama con `auto_rearm=False`, el pulso inicial al 0x94 cubre
        el caso del trigger durante el arm. El loop sigue sin pulsar (mejor
        usar `auto_rearm=True` para alta tasa).

        **El costo de una vuelta del loop ES el dead-time del método**: los
        eventos separados por menos que eso se pierden (el HW re-arma en ~24 ns,
        cuatro órdenes de magnitud más rápido). Por eso el loop es el de libmca
        (`osciloscope_leer_lote` en modo continuo, sin ventana ni re-armado), con
        el GIL suelto. `deadline_every` queda por compatibilidad y no se usa: C mira
        el reloj cada 16 lecturas. `read_snap=False` (default) ahorra la lectura
        del snapshot por evento, que queda en 0: ponerlo en True sólo si el
        análisis necesita saber QUÉ fuente disparó cada evento. `t_ns` es relativo
        al comienzo, en el reloj de `time.perf_counter_ns`.

        Devuelve (events, duration_s) donde events es lista de dicts con
        't_ns' (timestamp SW), 'wp' (write pointer al trigger) y 'snap'
        (snapshot del momento, 0 si `read_snap=False`)."""
        clear_mask = 0x0000_0101 if clear_both else 0x0000_0001
        # Pulso inicial defensivo: si el primer trigger firmó durante el arm
        # y el shield no está activo, esto destraba el dis.
        self.w32(0x94, clear_mask)

        # El lazo es el de libmca, en modo continuo: sin ventana y sin re-armar.
        lector = Lector(self, self.mt if read_snap else None, pre=0, post=0, n_ch=0,
                        mascara=0, wp_off=wp_addr, single_shot=False, rearmar=False,
                        leer_snap=read_snap)
        lector.iniciar()
        n = max(0, operator.index(n))
        cols = {'t_ns': np.zeros(n, np.int64), 'wp': np.zeros(n, np.int32),
                'snap': np.zeros(n, np.uint32)}
        pc = time.perf_counter_ns
        t0 = pc()
        fin = t0 + timeout_ms * 1_000_000
        count = 0
        # De a tramos de 50 ms: C no ve un Ctrl-C, y así se lo atiende entre tramos.
        while count < n:
            ahora = pc()
            if ahora > fin:
                break
            k, _, _ = lector.leer(cols, count, n - count, min(fin, ahora + 50_000_000))
            count += k
        dur_s = (pc() - t0) / 1e9

        events = [{'t_ns': int(cols['t_ns'][i]) - t0, 'wp': int(cols['wp'][i]) & 0xFFFFFFFF,
                   'snap': int(cols['snap'][i])}
                  for i in range(count)]
        return events, dur_s

# =============================================================================
# API de configuración y estatus
# =============================================================================

def osciloscope_open(phys=SCOPE_PHYS, size=None, check_pl=True, impl=None):
    """Abre el scope MIDIENDO el mapeo, en vez de suponerlo.

    Es la diferencia con `Osciloscope.open()`, que conserva el default histórico
    de 0x30000 por compatibilidad: acá `size=None` pregunta cuántos canales
    construyó el bitstream. Con cuatro hacen falta 0x50000 y el valor viejo deja
    las dos últimas aperturas fuera del mapeo.
    """
    return Osciloscope.open(phys, size, check_pl, impl)


def osciloscope_close(osc):
    osc.close()


@_api()
def osciloscope_get_thr(osc, ch=0):
    """Umbral en volts (escala fija ADC_CNT_PER_V, sin calibración de EEPROM)."""
    v = _D()
    _ok(osc, _cargar().osciloscope_get_thr(osc._c, _i64(ch), ctypes.byref(v)), 'get_thr')
    return v.value


@_api()
def osciloscope_set_thr(osc, v, ch=None):
    _ok(osc, _cargar().osciloscope_set_thr(osc._c, _volts(v), _cual(ch)), 'set_thr')


@_api()
def osciloscope_get_decim(osc, ch=0):
    return _u32_de(osc, _cargar().osciloscope_get_decim, _i64(ch), que='get_decim')


@_api()
def osciloscope_set_decim(osc, v, ch=None):
    _ok(osc, _cargar().osciloscope_set_decim(osc._c, _decim(v), _cual(ch)), 'set_decim')


@_api()
def osciloscope_get_delay(osc, ch=0):
    return _u32_de(osc, _cargar().osciloscope_get_delay, _i64(ch), que='get_delay')


@_api()
def osciloscope_set_delay(osc, v, ch=None):
    """Delay post-trigger EN CRUDO. Es dead-time real: mientras corre,
    adc_dly_do bloquea la actualización de adc_wp_trig (rp_bram_sm.v:91)."""
    _ok(osc, _cargar().osciloscope_set_delay(osc._c, _u32(v), _cual(ch)), 'set_delay')


@_api()
def osciloscope_get_hysteresis(osc, ch=0):
    v = _D()
    _ok(osc, _cargar().osciloscope_get_hysteresis(osc._c, _i64(ch), ctypes.byref(v)),
        'get_hysteresis')
    return v.value


@_api()
def osciloscope_set_hysteresis(osc, v, ch=None):
    _ok(osc, _cargar().osciloscope_set_hysteresis(osc._c, _volts(v), _cual(ch)),
        'set_hysteresis')


@_api()
def osciloscope_get_avg(osc):
    v = _I32()
    _ok(osc, _cargar().osciloscope_get_avg(osc._c, ctypes.byref(v)), 'get_avg')
    return v.value


@_api()
def osciloscope_set_avg(osc, v):
    _ok(osc, _cargar().osciloscope_set_avg(osc._c, 1 if v else 0), 'set_avg')


@_api()
def osciloscope_get_deb_len(osc):
    return _u32_de(osc, _cargar().osciloscope_get_deb_len, que='get_deb_len')


@_api()
def osciloscope_set_deb_len(osc, v):
    _ok(osc, _cargar().osciloscope_set_deb_len(osc._c, _u32(v)), 'set_deb_len')


@_api()
def osciloscope_get_filter_bypass(osc):
    return _u32_de(osc, _cargar().osciloscope_get_filter_bypass, que='get_filter_bypass')


@_api()
def osciloscope_set_filter_bypass(osc, v):
    _ok(osc, _cargar().osciloscope_set_filter_bypass(osc._c, _u32(v)), 'set_filter_bypass')


@_api()
def osciloscope_get_calibration(osc, ch=0):
    c = _Calib()
    _ok(osc, _cargar().osciloscope_get_calibration(osc._c, _i64(ch), ctypes.byref(c)),
        'get_calibration')
    return _dict(c)


@_api()
def osciloscope_set_calibration(osc, offset=None, gain=None, ch=0):
    lib = _cargar()
    if offset is not None:
        _ok(osc, lib.osciloscope_set_calib_offset(osc._c, _i64(ch), _u32(offset)),
            'set_calibration')
    if gain is not None:
        _ok(osc, lib.osciloscope_set_calib_gain(osc._c, _i64(ch), _u32(gain)),
            'set_calibration')


# ---------- estatus (sólo lectura) ----------

@_api()
def osciloscope_get_adc_state(osc):
    return _u32_de(osc, _cargar().osciloscope_get_adc_state, que='get_adc_state')


@_api()
def osciloscope_get_trg_state(osc):
    return _u32_de(osc, _cargar().osciloscope_get_trg_state, que='get_trg_state')


@_api()
def osciloscope_get_wp_cur(osc, ch=0):
    return _u32_de(osc, _cargar().osciloscope_get_wp_cur, _i64(ch), que='get_wp_cur')


@_api()
def osciloscope_get_wp_trig(osc, ch=0):
    return _u32_de(osc, _cargar().osciloscope_get_wp_trig, _i64(ch), que='get_wp_trig')


@_api()
def osciloscope_get_we_cnt(osc, ch=0):
    return _u32_de(osc, _cargar().osciloscope_get_we_cnt, _i64(ch), que='get_we_cnt')


# ---------- configuración en bloque ----------
#
# Misma forma que `_CAMPOS` de `API/mca.py`: campo -> (offset, shift, máscara).
# Existe por la misma razón que allá — que se pueda **releer lo que se escribe**
# en una sola operación, sin una función por registro y sin que el cliente
# tenga que saber en qué bit vive cada cosa.
#
# Las máscaras salen de `modulos/osc/rtl/osc_cfg.sv`, no de suponer 32 bits:
# `set_tresh`/`set_hyst` son DW=14, `set_dec` es 17, `set_dly` 32, `set_deb_len`
# 20 y `set_filt_byp` 4. Escribir de más no rompe —el RTL trunca— pero leer de
# más devuelve bits que no existen y el readback deja de coincidir con lo
# escrito, que es justo lo que el anti-eco de la GUI usa para no reescribir.

_CAMPOS = {
    'thr_ch0':        (R_THR_CH0,        0, 0x3FFF),
    'thr_ch1':        (R_THR_CH1,        0, 0x3FFF),
    'hyst_ch0':       (R_HYST_CH0,       0, 0x3FFF),
    'hyst_ch1':       (R_HYST_CH1,       0, 0x3FFF),
    'dec_ch0':        (R_DEC_CH0,        0, 0x1FFFF),
    'dec_ch1':        (R_DEC_CH1,        0, 0x1FFFF),
    'dly_ch0':        (R_DLY_CH0,        0, 0xFFFFFFFF),
    'dly_ch1':        (R_DLY_CH1,        0, 0xFFFFFFFF),
    # avg_en NO es un bit por canal contiguo: el RTL lo lee y lo devuelve como
    # un BYTE por canal (`set_avg_en[c] <= sys_dats_all[c*8]`, y el readback
    # arma {7'h0, avg[3], 7'h0, avg[2], ...}). `osciloscope_set_avg()` escribe
    # la palabra entera con un 1 y por lo tanto toca sólo el canal 0.
    'avg_en_ch0':     (R_AVG_EN,         0, 0x1),
    'avg_en_ch1':     (R_AVG_EN,         8, 0x1),
    'deb_len':        (R_DEB_LEN,        0, 0xFFFFF),
    'filt_bypass':    (R_FILT_BYPASS,    0, 0xF),
    'calib_off_ch0':  (R_CALIB_OFF_CH0,  0, 0x3FFF),
    'calib_gain_ch0': (R_CALIB_GAIN_CH0, 0, 0xFFFF),
    'calib_off_ch1':  (R_CALIB_OFF_CH1,  0, 0x3FFF),
    'calib_gain_ch1': (R_CALIB_GAIN_CH1, 0, 0xFFFF),
}

# Los que el RTL guarda en complemento a dos sobre DW bits. Sin extender el
# signo, un umbral de -0.5 V se lee como +15792 cuentas y el control de la GUI
# salta al tope en vez de mostrar el valor que tiene puesto.
_CON_SIGNO = frozenset(('thr_ch0', 'thr_ch1',
                        'calib_off_ch0', 'calib_off_ch1'))


@_api()
def osciloscope_get_config(osc):
    """Todos los campos de `_CAMPOS`, en crudo (cuentas, no volts).

    En cuentas a propósito: es lo que está escrito en el registro. La conversión
    a volts depende de la escala del jumper (LV/HV) y de la calibración, así que
    hacerla acá metería una suposición en el dato en vez de en la vista.
    """
    n = len(_CAMPOS)
    v = (_I64 * n)()
    _ok(osc, _cargar().osciloscope_get_config(osc._c, v, n), 'get_config')
    return dict(zip(_CAMPOS, v))


@_api()
def osciloscope_configure(osc, **campos):
    """Escribe campos por nombre. Los que comparten registro se agrupan.

    Read-modify-write por registro y no por campo: `avg_en_ch0` y `avg_en_ch1`
    viven en la misma palabra, así que escribirlos de a uno haría que el segundo
    leyera un valor que el primero acaba de cambiar. Agrupando, la palabra se
    lee una vez y se escribe una vez.
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
    _ok(osc, _cargar().osciloscope_configure(osc._c, indices, valores, n), 'configure')


@_api()
def osciloscope_get_status(osc):
    """Lo que se refresca en pantalla: estado de las FSM y punteros.

    Sólo lectura y sin efectos: se puede poléar con una captura corriendo.
    """
    s = _Status()
    _ok(osc, _cargar().osciloscope_get_status(osc._c, ctypes.byref(s)), 'get_status')
    return _dict(s)


# ---------- comandos ----------

@_api()
def osciloscope_reset(osc):
    """Reset del FSM de ambos canales + desbloqueo de adc_trg_dis."""
    _ok(osc, _cargar().osciloscope_reset(osc._c), 'reset')


@_api()
def osciloscope_sw_trigger(osc):
    _ok(osc, _cargar().osciloscope_sw_trigger(osc._c), 'sw_trigger')


def osciloscope_wait_triggered(osc, timeout_ms=2000):
    return osc.wait_triggered(timeout_ms)


def osciloscope_wait_fill(osc, timeout_ms=2000):
    return osc.wait_fill(timeout_ms)


# =============================================================================
# API de lectura
# =============================================================================

@_api()
def osciloscope_read_bram(osc, ch, start, n):
    """`n` muestras del canal `ch` desde la posición `start`, en un `np.int16`.

    Son cuentas con el signo extendido y SIN calibrar: lo que hay en la BRAM. Se lee
    de a una palabra, y una ventana que pasa el final del anillo da la vuelta, así que
    `wp - pre` se puede pasar tal cual. El anillo es el del bitstream cargado: pedir
    más muestras que eso es un ValueError, y no el buffer repetido.

    Sólo existe en C. En single-shot tiene sentido con el buffer ya congelado.
    """
    n = _i64(n)
    dst = np.empty(min(max(n, 0), osc.n_buf), dtype=np.int16)
    rc = _cargar().osciloscope_read_bram(osc._c, _i64(ch), _i64(start), n,
                                         dst.ctypes.data_as(_PS))
    if rc:
        _ok(osc, rc, 'read_bram')
    return dst


@_api()
def osciloscope_read_cal(osc, ch, start, n, cal):
    """`osciloscope_read_bram`, calibrada: cuentas como las de librp, en un `np.int16`.

    `cal` es `{'gain', 'base', 'offset'}` (ver `calibracion_adc`). En LV, la cuenta
    sobre 8192 es exactamente el volt que devolvía `rp_AcqGetDataPosV`. Sólo existe
    en C.
    """
    n = _i64(n)
    dst = np.empty(min(max(n, 0), osc.n_buf), dtype=np.int16)
    c = _cargar_cal(cal)
    rc = _cargar().osciloscope_read_cal(osc._c, _i64(ch), _i64(start), n,
                                        ctypes.byref(c), dst.ctypes.data_as(_PS))
    if rc:
        _ok(osc, rc, 'read_cal')
    return dst


def osciloscope_calibrar(cal, crudo, dw=14):
    """Palabras crudas de la BRAM (se usan los `dw` bits bajos) a cuentas calibradas,
    con la cuenta de librp. No toca el hardware: es la función de C sola."""
    crudo = np.ascontiguousarray(crudo, dtype=np.uint32)
    dst = np.empty(crudo.shape, dtype=np.int16)
    lib = _cargar()
    rc = lib.osciloscope_calibrar(ctypes.byref(_cargar_cal(cal)), _i64(dw),
                                  crudo.ctypes.data_as(_PU), dst.ctypes.data_as(_PS),
                                  crudo.size)
    if rc:
        det = lib.osciloscope_last_error(None).decode('utf-8', 'replace') or None
        _libmca.check(rc, 'calibrar', None, det)
    return dst


# =============================================================================
# La calibración del ADC
# =============================================================================
#
# La de librp (cmn_CalibCntsSigned, rp-api 2.00): m = gain * (s - offset) / base,
# truncando hacia cero y recortando a ±8192. Ver libmca/include/osciloscope_lote.h.

_RP_PYTHON = '/opt/redpitaya/lib/python'


def _redpitaya(nombre):
    """Un módulo de la librería de Red Pitaya.

    Viven en /opt/redpitaya/lib/python, que entra al `sys.path` sólo desde un shell
    de login (`/etc/profile.d/redpitaya.sh`): un proceso lanzado por `ssh` sin login,
    como el servidor de `make app-servidor-remoto`, no los ve. Si no están en el
    camino y el directorio existe, se lo agrega.
    """
    try:
        return importlib.import_module(nombre)
    except ImportError:
        if not os.path.isdir(_RP_PYTHON) or _RP_PYTHON in sys.path:
            raise
        sys.path.append(_RP_PYTHON)
        return importlib.import_module(nombre)


def _cal_dict(c):
    """{'gain', 'base', 'offset'} de un dict, de una tupla (gain, base, offset) o de un
    objeto con esos atributos (el `uint_gain_calib_t` de rp_hw_calib)."""
    if isinstance(c, dict):
        g, b, o = c['gain'], c['base'], c['offset']
    elif isinstance(c, (tuple, list)):
        g, b, o = c
    else:
        g, b, o = c.gain, c.base, c.offset
    return {'gain': operator.index(g), 'base': operator.index(b),
            'offset': operator.index(o)}


def _cargar_cal(c):
    """El `osciloscope_adc_cal_t` de C. Lo fuera de rango de los tipos es ValueError;
    lo que C rechaza (base 0, un desborde) sale de C con su mensaje."""
    d = _cal_dict(c)
    for k, (lo, hi) in (('gain', (0, 2**32 - 1)), ('base', (0, 2**32 - 1)),
                        ('offset', (-2**31, 2**31 - 1))):
        if not lo <= d[k] <= hi:
            raise ValueError(f'{k}={d[k]} de la calibración: fuera de {lo}..{hi}')
    return _AdcCal(d['gain'], d['base'], d['offset'])


def calibracion_adc(canales=(0, 1)):
    """La calibración que usa librp en LV para cada canal: `[{'gain', 'base',
    'offset'}, ...]`, leída de la EEPROM por `rp_hw_calib` (DC, ganancia 1:1).

    **Si no se puede leer, error**: sin ella las cuentas no serían las de librp, y
    nunca se guarda crudo sin avisar. En la PC no hay EEPROM: pasar la calibración a
    mano (`BramSource(calib=...)`, `Osciloscope.set_calibracion`).
    """
    canales = [operator.index(c) for c in canales]
    try:
        hc = _redpitaya('rp_hw_calib')
    except ImportError as e:
        raise RuntimeError(
            'no se puede leer la calibración del ADC: falta el módulo rp_hw_calib de '
            f'Red Pitaya ({_RP_PYTHON}). Sin ella las cuentas no son las de librp. '
            'Fuera de la placa, pasarla a mano.') from e
    rc = hc.rp_CalibInit()
    if rc != 0:
        raise RuntimeError(f'rp_CalibInit devolvió {rc}: no se leyó la EEPROM')
    out = []
    for ch in canales:
        c = hc.uint_gain_calib_t()
        rc = hc.rp_CalibGetFastADCCalibValueI(ch, hc.RP_DC_CALIB, c)
        if rc != 0:
            raise RuntimeError(f'rp_CalibGetFastADCCalibValueI(canal {ch}) devolvió {rc}')
        out.append(_cal_dict(c))
    _exigir_lv(canales)
    return out


def _exigir_lv(canales):
    """Sólo LV. Con HV librp multiplica por 20 y V·8192 no entra en un int16: el camino
    de antes ya desbordaba. El jumper no se ve desde el software; lo que sí se ve es
    que alguien haya pedido HV a librp en este proceso (`rp_AcqSetGain`)."""
    rp_mod = sys.modules.get('rp')
    if rp_mod is None or not hasattr(rp_mod, 'rp_AcqGetGain'):
        return
    for ch in canales:
        try:
            rc, g = rp_mod.rp_AcqGetGain(ch)
        except Exception:                                      # noqa: BLE001
            return
        if rc == 0 and g == getattr(rp_mod, 'RP_HIGH', object()):
            raise ValueError(
                f'el canal {ch} está en HV para librp: el proyecto mide sólo en LV '
                '(con HV, V·8192 no entra en las cuentas de 16 bits)')


def ahora_ns():
    """El reloj del lazo de C: el mismo de `time.perf_counter_ns` en Linux."""
    return _cargar().osciloscope_ahora_ns()


# =============================================================================
# El lazo por evento
# =============================================================================

# Las columnas que llena `osciloscope_leer_lote`, con su tipo en C.
_COLUMNAS = (('wave', np.int16, _PS), ('t_ns', np.int64, _PL), ('wp', np.int32, _PI),
             ('snap', np.uint32, _PU), ('gap', np.uint8, ctypes.POINTER(ctypes.c_uint8)),
             ('dead_ns', np.int64, _PL))


class Lector:
    """El lazo por evento de libmca (`osciloscope_leer_lote`) sobre un osciloscopio y
    su multitrigger. Lo usan `BramSource.read_batch` y `capture_n_events`.

    Por evento: espera (single-shot: el buffer congelado; continuo: un cambio de
    wp_trig), anota `t_ns`, `wp`, `snap` y los descartados desde el anterior (`gap`),
    lee la ventana calibrada de cada canal, re-arma (0x000 primero, las máscaras
    después) y anota `dead_ns`. Durante la llamada el GIL está suelto.

    Sólo existe en C: con un handle de la referencia (`impl='py'`), TypeError.
    """

    def __init__(self, osc, mt, pre, post, n_ch, mascara, cal=(), wp_off=R_WP_TRIG_CH0,
                 single_shot=True, rearmar=True, leer_snap=True):
        for h in (osc, mt):
            if h is not None and getattr(h, '_via', 'c') != 'c':
                raise TypeError(
                    f'el lazo por evento existe sólo en libmca, y {type(h).__name__} '
                    f'es impl={getattr(h, "impl", "?")!r}: abrir con impl="c"')
        cal = list(cal)
        if len(cal) > APERTURAS_DECODIFICADAS:
            raise ValueError(f'{len(cal)} calibraciones: hay {APERTURAS_DECODIFICADAS} '
                             'canales como mucho')
        c = _LoteCfg()
        c.pre, c.post, c.n_ch = _u32(pre), _u32(post), _u32(n_ch)
        c.mascara, c.wp_off = _u32(mascara), _u32(wp_off)
        c.single_shot, c.rearmar, c.leer_snap = (int(bool(x)) for x in
                                                 (single_shot, rearmar, leer_snap))
        for k, v in enumerate(cal):
            c.cal[k] = _cargar_cal(v)
        self.osc, self.mt = osc, mt
        self.n_ch, self.samples = operator.index(n_ch), operator.index(pre) + operator.index(post)
        self._cfg, self._st = c, _LoteEstado()
        self._lote, self._res = _Lote(), _LoteRes()

    def iniciar(self):
        """Valida la configuración y deja el estado en cero, con el wp_trig de
        ahora. Va después de armar."""
        rc = _cargar().osciloscope_lote_iniciar(self.osc._c, ctypes.byref(self._cfg),
                                                ctypes.byref(self._st))
        if rc:
            _ok(self.osc, rc, 'lote_iniciar')

    @property
    def pendientes(self):
        """Descartados desde el último evento guardado: los que van al próximo `gap`,
        o los del final de la corrida."""
        return int(self._st.pendientes)

    def _apuntar(self, cols, i0, n_max):
        lote = self._lote
        for nombre, tipo, ptr in _COLUMNAS:
            a = cols.get(nombre) if cols is not None else None
            if a is None:
                setattr(lote, nombre, ptr())
                continue
            if a.dtype != tipo or not a.flags.c_contiguous:
                raise TypeError(f'{nombre}: hace falta un arreglo contiguo de {np.dtype(tipo)}, '
                                f'y es {a.dtype}')
            if a.shape[0] < i0 + n_max:
                raise ValueError(f'{nombre}: {a.shape[0]} filas, y se escribirían '
                                 f'hasta la {i0 + n_max}')
            if nombre == 'wave' and a.shape[1:] != (self.n_ch, self.samples):
                raise ValueError(f'wave: cada fila es {a.shape[1:]}, y el lector lee '
                                 f'{(self.n_ch, self.samples)}')
            setattr(lote, nombre, a[i0:].ctypes.data_as(ptr))
        return lote

    def leer(self, cols, i0, n_max, plazo_ns):
        """Hasta `n_max` eventos desde la fila `i0` de las columnas `cols` (un dict de
        arreglos, o algo con `.wave` y `.scalars`), o hasta `plazo_ns`.

        Con `cols=None` no hay dónde guardar: cuenta y re-arma sin leer. Devuelve
        `(guardados, descartados, asignados)`: los descartados vistos en esta llamada
        y los que fueron a parar al `gap` de los guardados.
        """
        if cols is not None and not isinstance(cols, dict):
            cols = dict(cols.scalars, wave=cols.wave)
        lote = self._apuntar(cols, i0, n_max) if cols is not None else None
        mt = self.mt._c if self.mt is not None else None
        rc = _cargar().osciloscope_leer_lote(
            self.osc._c, mt, ctypes.byref(self._cfg), ctypes.byref(self._st),
            ctypes.byref(lote) if lote is not None else None, _u32(n_max),
            _i64(plazo_ns), ctypes.byref(self._res))
        if rc:
            # Un callback del multitrigger que falló deja su excepción en su bus.
            bus = getattr(self.mt, '_bus', None)
            if bus is not None and getattr(bus, '_pendiente', None) is not None:
                bus.check(rc, 'leer_lote')
            _ok(self.osc, rc, 'leer_lote')
        r = self._res
        return int(r.n), int(r.descartados), int(r.asignados)


def osciloscope_read_buffers(osc, n_buf=None):
    """Los dos buffers enteros. `n_buf=None` = el del bitstream cargado."""
    return osc.read_buffers(osc.n_buf if n_buf is None else n_buf)


def osciloscope_read_window(osc, channels=None, pre=0, post=None,
                            at_trigger=True):
    """Ventana alrededor del trigger, por canal. Ver capture_window_np.

    Toman el largo del anillo del `osc`, que lo leyó del bitstream: son las
    versiones que NO se quedan con el 16384 de por defecto cuando el bitstream
    trae menos.
    """
    return osc.capture_window_np(channels=channels, pre=pre,
                                 post=osc.n_buf if post is None else post,
                                 at_trigger=at_trigger, n_buf=osc.n_buf)


def osciloscope_read_events(osc, n=100, timeout_ms=2000, wp_addr=R_WP_TRIG_CH0,
                            **kw):
    return osc.capture_n_events(n=n, timeout_ms=timeout_ms, wp_addr=wp_addr, **kw)


def osciloscope_read_capture_sw(osc, thr=0.5, delay=None, timeout_ms=500):
    """Captura forzada por SW trigger: no depende de que haya señal."""
    return osc.acq_capture_sw(thr=thr, delay=delay, timeout_ms=timeout_ms)


# =============================================================================
# Análisis offline de buffers capturados (no tocan hardware)
# =============================================================================

def events_to_intervals(events):
    """Intervalos SW entre triggers consecutivos en µs."""
    if len(events) < 2:
        return np.array([])
    ts = np.array([e['t_ns'] for e in events])
    return np.diff(ts) / 1000.0


def efficiency(observed_n, target_freq_hz, duration_s):
    """Cuántos triggers debería haber visto vs cuántos vio."""
    expected = target_freq_hz * duration_s
    return observed_n / max(expected, 1)


def pulses_from_buffer(d, threshold=0.0, hyst=0.05):
    """Detecta cruces ascendentes en un buffer con histéresis.
    Devuelve índices (samples) de cada cruce ascendente."""
    above = d > (threshold + hyst)
    below = d < (threshold - hyst)
    state = np.zeros(len(d), dtype=bool)
    s = False
    for i in range(len(d)):
        if   above[i]: s = True
        elif below[i]: s = False
        state[i] = s
    return np.where(np.diff(state.astype(np.int8)) > 0)[0]
