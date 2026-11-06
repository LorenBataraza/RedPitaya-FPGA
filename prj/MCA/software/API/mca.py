#!/usr/bin/env python3
"""Analizador Multicanal con ranuras ("MCA2") en la PL: registros, lectura y guardado.

El MCA vive en el slot 7 del bus de sistema (base 0x4070_0000) del bitstream
`mca_red_pitaya.bit`. Acumula en hardware:

  - un espectro 1D de la feature elegida (8192 canales en el build por defecto), y
  - un mapa 2D con el par de features que elige `sel_2dx`/`sel_2dy`.

La ventana la abre el disparo del multitrigger (`trig_i`) y la cierra la
compuerta larga; hasta `N_ACC` ranuras miden a la vez. **Sin el disparo armado
no abre ninguna ventana**: ver `API.multitrigger.multitrigger_armar_mca`. El
mapa es `docs/mca/register_map_mca.md`.

Nomenclatura (ver API/README.md)::

    h = mca_open()
    mca_set_n_acc(h, 4)              # config y estatus: mca_get_* / mca_set_*
    mca_start(h)
    hist = mca_read_histogram(h)     # lectura:  mca_read_*
    mca_write_file_histogram(hist, 'esp.csv', meta=mca_get_metadata(h))

**La lógica está en C.** Cada función de hardware de este módulo es una llamada
a la función del mismo nombre de `libmca` (`software/libmca/`, ver
`include/mca.h`), por ctypes. Este módulo no hace más que traducir: kwargs a
structs, structs a dicts, buffers a arreglos de numpy y códigos de error a las
excepciones de siempre. Lo que no toca hardware —el guardado en disco y la
conversión amplitud <-> canal— sigue en Python.

Cada función lleva el decorador `@_api` (`API/_despacho.py`), que mira el
handle y decide a dónde va la llamada:

    mca_open()            -> handle de C (libmca)        h._via == 'c'
    mca_open(impl='py')   -> la implementación Python    h._via == 'py'
                             de referencia (API/ref_py/mca2.py): es la base
                             de los benchmarks y de la comparación py contra c

**El MCA1** (el bitstream anterior, con Schmitt interno, histéresis y
re-armado) ya no lo habla libmca: `mca_open()` lo rechaza diciéndolo, y
`mca_open(impl='py')` lo abre con la referencia congelada `API/ref_py/mca.py`.

`class MCA` es el handle que devuelve `mca_open()`; sus métodos llaman a las
funciones de este módulo. Su constructor `MCA(mem, fd, caps, h_aw, h2_aw,
psd_aw)` sigue andando sobre un buffer ya mapeado (o sobre el `r32`/`w32` de
una subclase, como `FakeMCA`): la lógica de C corre igual, a través del backend
por callbacks de libmca.

Los helpers de análisis viven en `API/analisis.py`: son puros, no tocan
hardware, y así se prueban contra .npz guardados sin la placa.
"""

# ctypes, mmap y struct quedan importados aunque el binding use sólo parte:
# `mca_utils` los reexporta con `import *` y son parte de la superficie que
# congela API/tests/test_compat_api.py.
import ctypes
import json
import math
import mmap                                                     # noqa: F401
import os
import struct
import sys
import time

import numpy as np

from API import _libmca
from API._despacho import api as _api, elegir_impl as _elegir_impl
from API.ref_py import mca as _ref_mca1
from API.ref_py import mca2 as _ref

# =============================================================================
# Mapa de memoria: "MCA2" (docs/mca/register_map_mca.md)
# =============================================================================

MCA_PHYS = 0x4070_0000          # slot 7 del sys bus
MCA_SIZE = 0x30000              # registros + las dos aperturas

MAGIC      = 0x4D434132         # "MCA2"
MAGIC_MCA1 = 0x4D434131         # el mapa anterior: lo abre sólo la referencia

# --- identificación ---
R_MAGIC        = 0x000
R_CAPS         = 0x004          # bit0 1D, bit1 2D, bit2 trapecio
R_WIDTHS       = 0x008          # {psd_aw[23:16], h2_aw[15:8], h_aw[7:0]}
# --- control y estado ---
R_CTRL         = 0x00C          # bit0 run, bit1 clear (autolimpiante), bit8 chan
R_STATUS       = 0x010          # bit0 clear_busy, bit1 busy, bit2 bl_stale,
                                # bit3 vetoed, bit5 puede_abrir, [10:8] n_ocup
# --- configuración ---
R_BASELINE     = 0x01C
R_BL_CTRL      = 0x020          # {holdoff[31:16], k[7:4], auto[0]}
R_BASELINE_NOW = 0x024
R_AMP_MIN      = 0x030
R_AMP_MAX      = 0x034
R_AMP_SRC      = 0x038          # {q_shift[12:8], amp_src[0]}; mueve sel_1d/2dx
R_H_SHIFT      = 0x03C          # DEPRECADO: sin efecto, lo subsume el zoom
R_H2_SHIFT     = 0x040          # DEPRECADO: sin efecto, lo subsume el zoom
R_DEC          = 0x044
R_GATE_LEN     = 0x04C          # {larga[31:16], corta[15:0]}, desde el disparo

# --- selector de feature por eje, zoom y discriminador ---
R_HIST_SEL     = 0x090          # {sel_2dy[11:8], sel_2dx[7:4], sel_1d[3:0]}
R_ZOOM_1D      = 0x094          # {k[15:8], z[3:0]}
R_ZOOM_2DX     = 0x0B8
R_ZOOM_2DY     = 0x0BC
R_DISCR_CTRL   = 0x098          # {sel[7:4], externo[1], enable[0]}
R_DISCR_MIN    = 0x09C
R_DISCR_MAX    = 0x0A0

# --- histograma lleno ---
R_HIST_CTRL     = 0x0A4         # bit0 keep_counter_if_full
R_HIST_STATUS   = 0x0A8         # bit0 full_1d, bit1 full_2d (pegajosos)
R_CNT_REJ_DISCR = 0x0AC
R_CNT_FULL_SUPP = 0x0B0

# Índices del bus de features: un solo espacio de numeración compartido por los
# tres ejes del histograma y por el discriminador.
F_PEAK, F_INT, F_PSD, F_INVW, F_LEN, F_TRISE = 0, 1, 2, 3, 4, 5
F_DTPREV, F_DTNEXT, F_SOLAPE, F_TRAP = 6, 7, 8, 9
F_FORMA = 10

FEATURES = {
    'pico':         F_PEAK,     # amplitud de pico, alineada a la izquierda
    'integral':     F_INT,      # Q_total >> q_shift
    'psd':          F_PSD,      # Q_cola/Q_total -- DONDE está la carga
    'ancho_inv':    F_INVW,     # pico/Q_total -- rechaza apilamiento
    'largo':        F_LEN,      # muestras de la ventana
    't_subida':     F_TRISE,    # muestras del disparo al pico
    'dt_anterior':  F_DTPREV,   # muestras desde el disparo anterior
    'dt_siguiente': F_DTNEXT,   # muestras hasta el siguiente, dentro de la ventana
    'solape':       F_SOLAPE,   # {perdido[5], adentro[4], otras[3:0]}
    'trapecio':     F_TRAP,     # meseta del trapecio (CAPS bit 2)
    'forma':        F_FORMA,    # la forma del banco que se publico, 0xFFFF = marcado
}
# --- contadores de eventos ---
R_CNT_TOTAL    = 0x050          # ventanas cerradas
R_CNT_ACCEPTED = 0x054
R_CNT_REJ_AMP  = 0x058
R_CNT_REJ_PSD  = 0x05C
R_CNT_PILEUP   = 0x060          # ventanas cerradas CON marca de solape
R_CNT_DROPPED  = 0x064          # lost_busy + colisiones + borrado
# --- relojes (64 b; leer la palabra BAJA congela la ALTA) ---
# realtime == vetotime + t_win + t_div + livetime, exacto en todo ciclo (una
# assertion del RTL). El tiempo muerto es "no hay ranura libre": t_win + t_div.
R_REALTIME_LO  = 0x068
R_REALTIME_HI  = 0x06C
R_LIVETIME_LO  = 0x070          # alguna ranura libre
R_LIVETIME_HI  = 0x074
R_DEADTIME_LO  = 0x078          # OCUPACIÓN: alguna ranura ocupada
R_DEADTIME_HI  = 0x07C
R_VETOTIME_LO  = 0x0C0          # bajo veto externo (trigger_shield, dst=mca)
R_VETOTIME_HI  = 0x0C4
R_T_WIN_LO     = 0x0C8          # sin ranura libre, todas midiendo
R_T_WIN_HI     = 0x0CC
R_T_DIV_LO     = 0x0D0          # sin ranura libre, alguna esperando publicar
R_T_DIV_HI     = 0x0D4
R_T_CLEAR_LO   = 0x0FC          # barrido de borrado (aparte del teselado)
R_T_CLEAR_HI   = 0x100
R_T_OCUP       = 0x140          # + 8*j: ciclos con exactamente j ranuras ocupadas
# --- distribución del período muerto ---
R_DEAD_PERIODS = 0x0E0
R_DEAD_LEN_MAX = 0x0E4
R_DEAD_EXT     = 0x0E8
# --- atribución de arribos ---
# cnt_cross == cnt_open + lost_active + lost_busy + lost_veto
R_CNT_CROSS    = 0x0EC          # disparos con run
R_CNT_OPEN     = 0x0B4          # ...que abrieron una ranura
R_LOST_ACTIVE  = 0x0F4          # ...sin ranura libre, todas midiendo
R_LOST_VETO    = 0x0F8          # ...bajo veto
R_CNT_WIN      = 0x110          # ventanas abiertas
R_CNT_TRIG     = 0x118          # flancos crudos de trig_i
# --- las ranuras ---
R_PUB_STATE    = 0x10C          # {last_win_id[31:16], occ_max[15:8], occ[7:0]}
R_N_ACC_MAX    = 0x11C          # ranuras con que se sintetizó (R)
R_N_ACC        = 0x120          # ranuras habilitadas, 1..N_ACC
R_PRE_DLY      = 0x124          # retardo de la muestra respecto de trig_i
# --- el conformado trapezoidal ---
R_TRAP_KM      = 0x128          # {m[25:16], k[9:0]}; escribirlo reinicia el estado
R_TRAP_MQ      = 0x12C          # M*16; escribirlo reinicia el estado
R_TRAP_MED     = 0x130          # {ok[31] (R), sh[29:24], lw[18:16], off[15:0]}
# --- el banco de trapecios (N_FORMAS formas; la 0 es la de TRAP_KM/TRAP_MED) ---
R_N_FORMAS     = 0x134          # {umbr_ok[31] (R), N_FORMAS[10:8] (R), n_formas[2:0]}
R_TRAP_UMBR    = 0x188          # forma 0: {despues[31:16], antes[15:0]}
R_FORMA1_KM    = 0x190          # forma 1: como TRAP_KM
R_FORMA1_MED   = 0x194          # forma 1: como TRAP_MED
R_FORMA1_UMBR  = 0x198          # forma 1: como TRAP_UMBR
R_FORMA2_KM    = 0x1A0          # forma 2: como TRAP_KM
R_FORMA2_MED   = 0x1A4          # forma 2: como TRAP_MED
R_FORMA2_UMBR  = 0x1A8          # forma 2: como TRAP_UMBR
R_FORMA3_KM    = 0x1B0          # forma 3: como TRAP_KM
R_FORMA3_MED   = 0x1B4          # forma 3: como TRAP_MED
R_FORMA3_UMBR  = 0x1B8          # forma 3: como TRAP_UMBR
# --- último evento (depuración) ---
R_LAST_AMP     = 0x080
R_LAST_PSD     = 0x084
R_LAST_QTOT    = 0x088
R_LAST_QTAIL   = 0x08C
# --- aperturas de histograma ---
APERTURE_H     = 0x10000        # espectro 1D
APERTURE_2D    = 0x20000        # el par de features del mapa 2D

CAP_HIST_H     = 1 << 0
CAP_HIST_H_PSD = 1 << 1
CAP_TRAP       = 1 << 2

FS_HZ          = 125e6          # muestreo del ADC
ADC_CNT_PER_V  = 8192           # cuentas por volt (mismo que multitrigger_utils)

# Ancho del bus de features
AMP_W          = 16

# Topes de los campos que el RTL satura o envuelve (los valida C).
N_ACC_TOPE     = 7              # cfg_n_acc es de 3 bits
PRE_DLY_MAX    = 127
TRAP_KL_MAX    = 1023
TRAP_MQ_MAX    = (1 << 20) - 1
TRAP_LAT       = 8              # la latencia de mca_trap: entra en trap_ok
N_FORMAS_TOPE  = 4              # el banco: el mapa tiene cuatro bloques

_U32 = struct.Struct('<I')


class MCANotPresent(RuntimeError):
    """El bitstream cargado no tiene el MCA2 en el slot 7."""

# Las referencias lanzan su propia MCANotPresent: se la reemplaza por ésta, así
# un `except MCANotPresent` atrapa el error venga de C o de la implementación
# Python. Es un alias en memoria; los ficheros de referencia no se tocan.
_ref.MCANotPresent = MCANotPresent
_ref_mca1.MCANotPresent = MCANotPresent


# =============================================================================
# libmca: carga, firmas y tipos
# =============================================================================
#
# Los structs replican los de include/mca.h campo por campo. `_cargar()`
# compara su tamaño con el que informa C: si alguien agrega un campo de un lado
# y no del otro, ctypes leería corrido sin ningún error, y eso es justo lo que
# no puede pasar con los contadores de una medición.

_I32, _I64, _U = ctypes.c_int32, ctypes.c_int64, ctypes.c_uint32
_D, _P, _PU = ctypes.c_double, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)
_PP = ctypes.POINTER(ctypes.c_void_p)


class _Config(ctypes.Structure):
    _fields_ = [
        ('baseline', _I64), ('bl_auto', _I32), ('bl_k', _I64),
        ('bl_holdoff', _I64), ('amp_min', _I64), ('amp_max', _I64),
        ('amp_src', _I32), ('q_shift', _I64), ('dec', _I64),
        ('channel', _I32), ('gate_short', _I64), ('gate_long', _I64),
        ('n_acc', _I64), ('pre_dly', _I64), ('trap_k', _I64), ('trap_m', _I64),
        ('trap_mq', _I64), ('trap_off', _I64), ('trap_lw', _I64),
        ('trap_sh', _I64), ('verify', _I32), ('sel_1d', _I32),
        ('sel_2dx', _I32), ('sel_2dy', _I32), ('zoom_1d_z', _I64),
        ('zoom_1d_k', _I64), ('zoom_2dx_z', _I64), ('zoom_2dx_k', _I64),
        ('zoom_2dy_z', _I64), ('zoom_2dy_k', _I64), ('discr_en', _I32),
        ('discr_sel', _I32), ('discr_min', _I64), ('discr_max', _I64),
        ('discr_ext', _I32), ('keep_if_full', _I32),
        ('n_formas', _I64), ('trap_antes', _I64), ('trap_despues', _I64),
    ] + [(f'forma{f}_{c}', _I64) for f in range(1, N_FORMAS_TOPE)
         for c in ('k', 'm', 'off', 'lw', 'sh', 'antes', 'despues')]


# Las claves del dict de counters(), en su orden, con su tipo de Python. El
# struct de C tiene los mismos campos en el mismo orden; después vienen
# `t_ocup_s` (un arreglo, que va al final del dict como lista de N_ACC + 1),
# su largo, y los relojes crudos.
_CLAVES_CONTADORES = (
    ('total', int), ('accepted', int), ('rej_amp', int), ('rej_psd', int),
    ('pileup', int), ('dropped', int), ('rej_discr', int), ('full_supp', int),
    ('realtime_s', float), ('livetime_s', float), ('deadtime_s', float),
    ('vetotime_s', float), ('t_win_s', float), ('t_div_s', float),
    ('t_clear_s', float), ('deadtime_real_s', float),
    ('dead_periods', int), ('dead_len_max_s', float),
    ('dead_len_mean_s', float), ('dead_ext', int), ('dead_ext_frac', float),
    ('cross', int), ('open', int), ('lost_active', int), ('lost_veto', int),
    ('windows', int), ('trig_edges', int),
    ('pub_occ', int), ('pub_occ_max', int), ('last_win_id', int),
    ('n_acc', int), ('n_acc_max', int), ('pub_saturada', bool),
    ('clear_busy', bool), ('busy', bool), ('baseline_stale', bool),
    ('vetoed', bool), ('puede_abrir', bool), ('n_ocup', int),
    ('full_1d', bool), ('full_2d', bool), ('trap_ok', bool),
)
_CTYPE = {int: _U, float: _D, bool: _I32}


class _Counters(ctypes.Structure):
    _fields_ = ([(k, _CTYPE[t]) for k, t in _CLAVES_CONTADORES]
                + [('t_ocup_s', _D * (N_ACC_TOPE + 1)), ('n_t_ocup', _I32)]
                + [(k, ctypes.c_uint64) for k in (
                    'realtime', 'livetime', 'deadtime', 'vetotime', 't_win',
                    't_div', 't_clear')]
                + [('t_ocup', ctypes.c_uint64 * (N_ACC_TOPE + 1))])


class _Info(ctypes.Structure):
    _fields_ = [('magic', _U), ('hist_h', _I32), ('hist_h_psd', _I32),
                ('h_aw', _U), ('h2_aw', _U), ('psd_aw', _U),
                ('n_channels', _U), ('map2d_rows', _U), ('map2d_cols', _U),
                ('trap', _I32), ('n_acc_max', _U), ('features', _I32),
                ('n_formas_max', _U)]


class _LastEvent(ctypes.Structure):
    _fields_ = [('amp', _U), ('psd', _U), ('q_tot', _U), ('q_tail', _U),
                ('baseline', _I32)]


class _Field(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U), ('shift', _U),
                ('mascara', _U), ('bandera', _I32)]


class _Reg(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U)]


_CHUNK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int32)

# Los selectores de feature especiales de mca.h: fuera de todo índice válido.
_F_DEFAULT = -2 ** 31
_F_DESCONOCIDA = -2 ** 31 + 1

# Los setters de mca_regs.h escritos a mano en C (validan o saturan) y su tipo.
_SET_ESPECIALES = {
    'dec': _I64, 'n_acc': _I64, 'pre_dly': _I64, 'trap_k': _I64,
    'trap_mq': _I64, 'n_formas': _I64,
    'forma1_k': _I64, 'forma2_k': _I64, 'forma3_k': _I64,
    'zoom_1d_z': _I64, 'zoom_2dx_z': _I64, 'zoom_2dy_z': _I64,
    'sel_1d': _I32, 'sel_2dx': _I32, 'sel_2dy': _I32, 'discr_sel': _I32,
}

_lib = None


class _Funciones:
    """Las funciones de libmca para llamar desde el binding, cargadas al primer
    uso. Después de `_cargar()` cada una es un atributo común, sin indirección."""

    def __getattr__(self, nombre):
        _cargar()
        try:
            return self.__dict__[nombre]
        except KeyError:
            raise AttributeError(nombre) from None


_C = _Funciones()
_FIRMAS = []            # las declaradas en _cargar(), en orden
_GET = {}               # campo -> mca_get_<campo>
_SET = {}               # campo -> mca_set_<campo>


def _exigir_misma_tabla(n_lib):
    if n_lib != len(_CAMPOS):
        raise OSError(f'libmca tiene {n_lib} campos de configuración y API/mca.py '
                      f'{len(_CAMPOS)}: el .so es de otra versión. Recompilarla: '
                      '`make -C libmca arm` en la PC y volver a copiarla a la placa, '
                      'o `make -C libmca placa-lib`.')


def _cargar():
    """libmca con las firmas del MCA declaradas. OSError si no está compilada."""
    global _lib
    if _lib is not None:
        return _lib
    lib = _libmca.cargar()
    # Antes de pedirle ningún símbolo: un .so viejo daría un AttributeError sobre
    # una función suelta, o un EINVAL más adelante en mca_get_config.
    lib.mca_field_count.restype = _I32
    lib.mca_field_count.argtypes = []
    _exigir_misma_tabla(lib.mca_field_count())

    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)
        _FIRMAS.append(nombre)

    _FIRMAS.clear()
    c = ctypes.c_int
    f('mca_open', c, _PP, _U, _U, c)
    f('mca_open_bus', c, _PP, _P, c, c)
    f('mca_wrap', c, _PP, _P, c, _U, _U, _U, _U)
    f('mca_close', None, _P)
    f('mca_last_error', ctypes.c_char_p, _P)
    f('mca_get_geometry', c, _P, _PU, _PU, _PU, _PU)
    f('mca_r32', c, _P, _U, _PU)
    f('mca_w32', c, _P, _U, _U)
    f('mca_read_words', c, _P, _U, _U, _PU)
    f('mca_r64', c, _P, _U, _U, ctypes.POINTER(ctypes.c_uint64))
    f('mca_identify', c, _P, ctypes.POINTER(_Info))
    f('mca_tiene_features', c, _P, ctypes.POINTER(_I32))
    f('mca_exigir_features', c, _P)
    f('mca_start', c, _P)
    f('mca_stop', c, _P)
    f('mca_clear', c, _P, _D)
    f('mca_get_formas_ok', c, _P, _PU, _PU)
    f('mca_field_count', _I32)
    f('mca_field_info', ctypes.POINTER(_Field), _I32)
    f('mca_reg_count', _I32)
    f('mca_reg_info', ctypes.POINTER(_Reg), _I32)
    f('mca_get_field', c, _P, _I32, _PU)
    f('mca_set_field', c, _P, _I32, _U)
    f('mca_get_config', c, _P, _PU, _I32)
    for n in ('status', 'running', 'clear_busy', 'busy', 'baseline_stale',
              'vetoed', 'puede_abrir', 'n_ocup', 'n_acc_max', 'trap_ok', 'caps',
              'n_formas_max', 'umbr_ok'):
        f(f'mca_get_{n}', c, _P, _PU)
    f('mca_get_baseline_now', c, _P, ctypes.POINTER(_I32))
    f('mca_get_widths', c, _P, _PU, _PU, _PU)
    f('mca_config_default', None, ctypes.POINTER(_Config))
    f('mca_configure', c, _P, ctypes.POINTER(_Config))
    f('mca_read_counters', c, _P, ctypes.POINTER(_Counters))
    f('mca_read_histogram', c, _P, _PU, _U)
    f('mca_read_map2d', c, _P, _PU, _U)
    f('mca_read_last_event', c, _P, ctypes.POINTER(_LastEvent))
    f('mca_read_acquire', c, _P, _D, c, _PU, _U, _PU, _U,
      ctypes.POINTER(_Counters))
    f('mca_read_acquire_chunks', c, _P, _D, _D, _CHUNK, _P, _PU, _U, _PU, _U,
      ctypes.POINTER(_Counters))
    f('mca_autoscale_q_shift', c, _P, _D, _D, ctypes.POINTER(_I32))
    f('mca_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    f('mca_feature_from_name', c, ctypes.c_char_p, ctypes.POINTER(_I32))
    f('mca_feature_name', ctypes.c_char_p, _I32)

    # Un get/set por campo de la tabla de C (ya comprobado que es la misma).
    for i in range(lib.mca_field_count()):
        nombre = lib.mca_field_info(i).contents.nombre.decode()
        f(f'mca_get_{nombre}', c, _P, _PU)
        f(f'mca_set_{nombre}', c, _P, _SET_ESPECIALES.get(nombre, _U))

    for tipo, py in (('mca_config_t', _Config), ('mca_counters_t', _Counters),
                     ('mca_info_t', _Info), ('mca_last_event_t', _LastEvent),
                     ('mca_field_t', _Field), ('mca_reg_t', _Reg)):
        if lib.mca_sizeof(tipo.encode()) != ctypes.sizeof(py):
            raise OSError(f'libmca y API/mca.py no coinciden en {tipo}: '
                          f'{lib.mca_sizeof(tipo.encode())} contra '
                          f'{ctypes.sizeof(py)} bytes. Recompilar libmca o '
                          'actualizar el struct del binding.')

    # Lo que llama el binding es, cuando es seguro, una copia de cada función
    # SIN argtypes: en la placa, convertir los argumentos costaba más que la
    # llamada (ver `_libmca.version_rapida`). Por eso h._c, que es un c_void_p,
    # es lo único que se pasa como puntero de handle.
    for nombre in list(_FIRMAS):
        fn = _libmca.version_rapida(lib, nombre)
        _C.__dict__[nombre] = fn
        if nombre.startswith('mca_get_'):
            _GET[nombre[8:]] = fn
        elif nombre.startswith('mca_set_'):
            _SET[nombre[8:]] = fn
    _lib = lib
    return lib


# =============================================================================
# Traducción
# =============================================================================

_EXCEPCIONES = {_libmca.MCA_ENOTPRESENT: MCANotPresent}


def _ok(h, rc, que=''):
    """rc de libmca -> nada, o la excepción con el detalle que dejó C.

    Si el handle corre sobre callbacks (FakeMCA, un buffer de test), primero se
    relanza la excepción que haya tirado un callback: es la causa real.
    """
    if rc == 0:
        return
    det = _C.mca_last_error(h._c).decode('utf-8', 'replace') or None
    if h._bus is not None:
        h._bus.check(rc, que, _EXCEPCIONES, det)
    _libmca.check(rc, que, _EXCEPCIONES, det)


# Los caminos calientes no llaman a _ok cuando rc == 0, ni arman el texto del
# contexto: en la placa cada llamada de Python cuesta ~1 µs.

def _u32(h, fn, *args):
    v = ctypes.c_uint32()
    rc = fn(h._c, *args, ctypes.byref(v))
    if rc:
        _ok(h, rc, fn.__name__)
    return v.value


def _get(h, nombre):
    v = ctypes.c_uint32()
    rc = _GET[nombre](h._c, ctypes.byref(v))
    if rc:
        _ok(h, rc, f'mca_get_{nombre}')
    return v.value


def _set(h, nombre, v):
    rc = _SET[nombre](h._c, int(v) & 0xFFFFFFFF)
    if rc:
        _ok(h, rc, f'mca_set_{nombre}')


def _set_bandera(h, nombre, v):
    # El `1 if v else 0` de antes: la verdad de Python, no el bit 0 de v.
    _set(h, nombre, 1 if v else 0)


def _i64(v):
    """Un entero de Python al int64 de los setters que validan. Satura en vez
    de dar la vuelta, así un número enorme no cambia de signo al cruzar."""
    v = int(v)
    return max(-2 ** 63, min(2 ** 63 - 1, v))


def _set_i64(h, nombre, v):
    rc = _SET[nombre](h._c, _i64(v))
    if rc:
        _ok(h, rc, f'mca_set_{nombre}')


def _feat(f):
    """Selector de feature -> el int32 de C: None, un nombre o un índice.

    No valida: eso lo hace C, en el mismo punto en que lo hacía Python. Un
    nombre que no existe viaja como _F_DESCONOCIDA para que C lo rechace ahí,
    y no acá antes de escribir nada.
    """
    if f is None:
        return _F_DEFAULT
    if isinstance(f, str):
        return FEATURES.get(f, _F_DESCONOCIDA)
    f = int(f)
    return f if _F_DESCONOCIDA < f < 2 ** 31 else 99        # 99: inválido


# Convertir un struct campo por campo cuesta un getattr de ctypes por campo:
# 132 µs los contadores en la placa. Con un struct.Struct del mismo layout es un
# solo unpack. `_layout` arma el formato desde los _fields_ y `_mismo_layout`
# lo comprueba contra ctypes al importar, con un valor distinto por campo.
_FMT_CTYPES = {ctypes.c_uint32: 'I', ctypes.c_int32: 'i', ctypes.c_int64: 'q',
               ctypes.c_uint64: 'Q', ctypes.c_double: 'd'}


def _fmt(t):
    """El formato de `struct` de un tipo de ctypes; un arreglo, repetido."""
    if issubclass(t, ctypes.Array):
        return f'{t._length_}{_FMT_CTYPES[t._type_]}'
    return _FMT_CTYPES[t]


def _layout(tipo):
    # El '0' + el tipo más alineado agrega el relleno del final, que C (y
    # ctypes) cuentan en el tamaño del struct y `struct` no.
    tipos = [t for _, t in tipo._fields_]
    final = max(tipos, key=ctypes.alignment)
    final = final._type_ if issubclass(final, ctypes.Array) else final
    return struct.Struct('@' + ''.join(_fmt(t) for t in tipos)
                         + '0' + _FMT_CTYPES[final])


def _mismo_layout(tipo, st):
    """Un valor distinto en cada posición, escrito por ctypes y leído por struct."""
    if st.size != ctypes.sizeof(tipo):
        return False
    c, vals, i = tipo(), [], 0
    for nombre, t in tipo._fields_:
        base = t._type_ if issubclass(t, ctypes.Array) else t
        n = t._length_ if issubclass(t, ctypes.Array) else 1
        v = [float(i + j) + 0.5 if base is ctypes.c_double else i + j + 1
             for j in range(n)]
        setattr(c, nombre, t(*v) if issubclass(t, ctypes.Array) else v[0])
        vals += v
        i += n
    return list(st.unpack_from(c)) == vals


_ST_CONTADORES = _layout(_Counters)
_CLAVES_C = tuple(k for k, _ in _CLAVES_CONTADORES)
_BOOLS_C = tuple(k for k, t in _CLAVES_CONTADORES if t is bool)
_N_C = len(_CLAVES_C)               # después: t_ocup_s[N_ACC_TOPE + 1], n_t_ocup
_ST_CONFIG = _layout(_Config)
_ENTEROS_CONFIG = tuple(i for i, (_, t) in enumerate(_Config._fields_)
                        if t is ctypes.c_int64)
assert _mismo_layout(_Counters, _ST_CONTADORES)
assert _mismo_layout(_Config, _ST_CONFIG)


def _contadores(c):
    # zip corta en las claves: el arreglo y los relojes crudos van aparte.
    vals = _ST_CONTADORES.unpack_from(c)
    d = dict(zip(_CLAVES_C, vals))
    for k in _BOOLS_C:
        d[k] = bool(d[k])
    n = vals[_N_C + N_ACC_TOPE + 1]                 # n_t_ocup
    d['t_ocup_s'] = list(vals[_N_C:_N_C + n])
    return d


def _evento(ev):
    return {'amp': ev.amp, 'psd': ev.psd, 'q_tot': ev.q_tot,
            'q_tail': ev.q_tail, 'baseline': ev.baseline}


def _ptr(a):
    return a.ctypes.data_as(_PU)


# =============================================================================
# Driver
# =============================================================================

class MCA:
    """Handle del MCA sobre libmca.

    Uso típico::

        mca = MCA.open()
        mca.identify()
        mca.configure(gate_long=384, n_acc=4)
        # el disparo: multitrigger_armar_mca(osc, mtr)
        spec, m2d, cnt = mca.acquire(10.0)

    Los métodos son la API de siempre y cada uno es una llamada a la función
    `mca_*` del mismo nombre. La geometría (`caps`, `h_aw`, `h2_aw`, `psd_aw`)
    se lee al abrir y queda como atributo, igual que antes.
    """

    # La implementación que hay abajo; va a la metadata (`api_impl`).
    impl = 'c'
    _via = 'c'

    def __init__(self, mem, fd, caps, h_aw, h2_aw, psd_aw):
        """Un handle sobre un buffer ya mapeado, sin leer nada.

        `mem` es lo que antes se le pasaba al mmap: un `mmap.mmap` o, en los
        tests, un `bytearray` que graba las escrituras. Con `mem=None`, los
        accesos son el `r32`/`w32` de la subclase (así se enchufa `FakeMCA`).
        En los dos casos la lógica es la de libmca, que llega al buffer por el
        backend de callbacks.
        """
        self._mmap = mem
        self._fd = fd
        self._c = None
        self._bus = None
        self.caps = caps
        self.h_aw = h_aw
        self.h2_aw = h2_aw
        self.psd_aw = psd_aw
        self._has_2d = bool(caps & CAP_HIST_H_PSD)
        lib = _cargar()
        self._bus = self._bus_de_python(mem)
        p = ctypes.c_void_p()
        _libmca.check(lib.mca_wrap(ctypes.byref(p), self._bus.ptr, 0, caps,
                                   h_aw, h2_aw, psd_aw), 'mca_wrap')
        self._c = p
        self.libmca_version = _libmca.version()

    def _bus_de_python(self, mem):
        if mem is not None:
            def r32(off):
                return _U32.unpack_from(mem, off)[0]

            def w32(off, v):
                # Asignación por slice, NO struct.pack_into: ver la nota de
                # `w32` más abajo.
                mem[off:off + 4] = _U32.pack(v & 0xFFFFFFFF)

            # En memoria común un bloque se puede copiar de una vez. Sobre un
            # mmap de /dev/mem NO (§7.3 del doc del bus: reinicia la placa):
            # ahí C hace n lecturas de 32 b, una por callback.
            bloque = None
            if isinstance(mem, (bytes, bytearray)):
                def bloque(off, n):
                    return np.frombuffer(mem, dtype='<u4', count=n, offset=off)
            return _libmca.Bus.callbacks(r32, w32, bloque, size=len(mem))
        if type(self).r32 is MCA.r32 or type(self).w32 is MCA.w32:
            raise TypeError('MCA(None, ...) necesita una subclase que redefina '
                            'r32 y w32, como FakeMCA')
        return _libmca.Bus.callbacks(self.r32, self.w32,
                                     getattr(self, '_leer_bloque', None))

    # ---------- apertura ----------

    @classmethod
    def open(cls, phys=MCA_PHYS, size=MCA_SIZE, check_magic=True):
        """Abrir /dev/mem y mapear la región del MCA (en C, `mca_open`).

        Si la PL no está programada, la PRIMERA lectura mata el proceso con
        SIGBUS sin traceback. `API.fpga.fpga_state()` permite chequearlo antes;
        acá se valida el magic, que además distingue un bitstream viejo (sin
        MCA) de uno con MCA.
        """
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.mca_open(ctypes.byref(p), phys, size, 1 if check_magic else 0)
        if rc:
            det = lib.mca_last_error(None).decode('utf-8', 'replace') or None
            _libmca.check(rc, f'/dev/mem @ {phys:#x}', _EXCEPCIONES, det)
        return cls._envolver(p, None)

    @classmethod
    def _sobre_bus(cls, bus, check_magic=True):
        """Un handle sobre un `_libmca.Bus` ya abierto, que pasa a ser suyo:
        lo cierra `close()`. Lee la geometría y valida el magic como `open()`.

        Lo usa `bench/bench_impl.py --shm` para medir el binding con el backend
        devmem apuntando a un fichero (`Bus.archivo`), sin tocar la PL.
        """
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.mca_open_bus(ctypes.byref(p), bus.ptr, 0,
                              1 if check_magic else 0)
        if rc:
            det = lib.mca_last_error(None).decode('utf-8', 'replace') or None
            bus.check(rc, 'mca_open_bus', _EXCEPCIONES, det)
        return cls._envolver(p, bus)

    @classmethod
    def _envolver(cls, p, bus):
        h = cls.__new__(cls)
        h._mmap, h._fd, h._bus, h._c = None, -1, bus, p
        g = [ctypes.c_uint32() for _ in range(4)]
        _cargar().mca_get_geometry(p, *(ctypes.byref(x) for x in g))
        h.caps, h.h_aw, h.h2_aw, h.psd_aw = (x.value for x in g)
        h._has_2d = bool(h.caps & CAP_HIST_H_PSD)
        h.libmca_version = _libmca.version()
        return h

    def close(self):
        c, self._c = getattr(self, '_c', None), None
        if c:
            _C.mca_close(c)
        bus, self._bus = getattr(self, '_bus', None), None
        if bus is not None:
            bus.close()
        # Lo que el constructor recibió ya abierto se cierra como antes.
        mem, self._mmap = getattr(self, '_mmap', None), None
        if mem is not None and hasattr(mem, 'close'):
            mem.close()
        fd, self._fd = getattr(self, '_fd', -1), -1
        if fd is not None and fd >= 0:
            os.close(fd)

    def __del__(self):
        # Un handle olvidado no deja /dev/mem mapeado: reprogramar la PL con
        # un mapeo abierto traba el puerto GP0 (API/fpga.py). En el cierre del
        # intérprete el módulo puede estar a medio desarmar: se ignora.
        try:
            self.close()
        except Exception:                                      # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- acceso /dev/mem ----------

    def w32(self, off, v):
        # En C (`mca_w32`): un store de 32 b alineado, validado antes de llegar
        # al bus. La regla de antes sigue valiendo para quien escriba sobre un
        # mmap a mano: asignación por slice, NO struct.pack_into, que hace un
        # memset previo de a byte y el esclavo AXI lo rechaza (SIGBUS). Ver
        # API/tests/placa/test_rw_dev_mem.py.
        rc = _C.mca_w32(self._c, off, int(v) & 0xFFFFFFFF)
        if rc:
            _ok(self, rc, f'w32 {off:#x}')

    def r32(self, off):
        v = ctypes.c_uint32()
        rc = _C.mca_r32(self._c, off, ctypes.byref(v))
        if rc:
            _ok(self, rc, f'r32 {off:#x}')
        return v.value

    def _read_words(self, offset, n):
        """Lee n palabras de 32 bits DE A UNA (en C). Devuelve un np.ndarray uint32.

        **Sobre un mmap de /dev/mem, NUNCA np.frombuffer(...).copy(), ni slices
        grandes, ni struct.unpack_from con un formato largo.** Todos terminan en
        un memcpy, que sobre memoria de dispositivo emite accesos anchos
        (LDRD/NEON) o en ráfaga. rtl/axi4_slave.sv:101-102 RECHAZA toda ráfaga
        y todo tamaño que no sea 2 o 4 bytes, y el error **REINICIA la placa**
        (API/tests/placa/diag_mca_hw.py, paso `bulk`).

        Por eso el lazo está en C, en libmca/src/bus_devmem.c, que es el único
        fichero que toca la PL y el único que revisa `make -C libmca
        check-bus`: un `ldr` de 32 b por palabra, ~0.24 µs cada uno (~4 ms un
        espectro de 16384 canales, contra ~110 ms desde Python).
        """
        dst = np.empty(n, dtype=np.uint32)
        _ok(self, _C.mca_read_words(self._c, offset, n, _ptr(dst)),
            f'read_words {offset:#x}')
        return dst

    def _r64(self, off_lo, off_hi):
        # Leer la palabra BAJA congela la ALTA en un registro sombra del RTL:
        # C las lee siempre en ese orden.
        v = ctypes.c_uint64()
        _ok(self, _C.mca_r64(self._c, off_lo, off_hi, ctypes.byref(v)),
            'r64')
        return v.value

    # ---------- identificación ----------

    def tiene_features(self):
        """¿Tiene el bus de features (zoom, discriminador)? En el MCA2 viene
        siempre: lo dice el magic. Queda por compatibilidad."""
        si = ctypes.c_int32()
        _ok(self, _C.mca_tiene_features(self._c, ctypes.byref(si)),
            'tiene_features')
        return bool(si.value)

    def exigir_features(self):
        """Aborta (MCANotPresent) si el bitstream cargado no es el MCA2."""
        _ok(self, _C.mca_exigir_features(self._c), 'exigir_features')
        return True

    def identify(self, verbose=True):
        return mca_identify(self, verbose=verbose)

    # ---------- configuración ----------

    def configure(self, baseline=0, bl_auto=False, bl_k=12, bl_holdoff=0,
                  amp_min=0, amp_max=0xFFFF, amp_src=0, q_shift=0, dec=1,
                  channel=0, gate_short=32, gate_long=384, n_acc=1,
                  pre_dly=16, trap_k=64, trap_m=32, trap_mq=0, trap_off=72,
                  trap_lw=4, trap_sh=7, verify=True,
                  sel_1d=None, sel_2dx=None, sel_2dy=None,
                  zoom_1d=(0, 0), zoom_2dx=(0, 0), zoom_2dy=(0, 0),
                  discr=None, keep_if_full=True, **banco):
        """Configurar el MCA2 (en C, `mca_configure`). Termina con run=0.

        Valida TODO antes de escribir: una configuración mala deja los
        registros como estaban. Lo primero que escribe es run=0: la ventana de
        amplitud y `q_shift` no se pueden cambiar con una ranura midiendo.

        La ventana la abre el disparo del multitrigger y la cierra la compuerta
        larga (`gate_long` muestras desde el disparo); la cola arranca en la
        corta (`gate_short`). `n_acc` son las ranuras habilitadas, 1..N_ACC
        (1 = la ventana única de antes). `pre_dly` retrasa la muestra respecto
        del disparo, en ciclos, para que la ventana abra en el pie del pulso:
        16 es lo medido en la placa con el pulso de la campaña y el disparo por
        pendiente L=8, G=4 (el reset del RTL, 11, es para subidas rápidas).

        amp_src: 0 = muestra de pico, 1 = integral de carga (Q_total>>q_shift).
        La integral promedia el ruido blanco como sigma/sqrt(N) y es inmune al
        jitter de muestreo del pico. Escribirlo mueve los selectores de los
        ejes de amplitud; `sel_*` lo pisa.

        **bl_k: la constante del seguidor de base tiene que ser MUCHO más larga
        que el pulso.** Es 2^bl_k muestras (a 125 MSPS, 2^k * 8 ns); si es
        comparable al pulso el seguidor lo persigue y lo borra. Medido con un
        pulso de 62 us: bl_k=6 da 0 eventos, bl_k>=9 los 2000 esperados. Regla:
        tau_base >= 100x el pulso, o base FIJA (bl_auto=False).

        El trapecio (sólo con CAPS bit 2, `identify()['trap']`): `trap_k` la
        subida y `trap_m` la meseta en muestras (k + m <= 1023), `trap_mq` =
        M*16 con M la constante polo-cero, y la ventana de 2^`trap_lw` muestras
        desde `trap_off` sobre la meseta, con escala `>> trap_sh`. Cómo
        elegirlos: docs/mca/register_map_mca.md, "El conformado trapezoidal".

        El banco de trapecios (`**banco`): `n_formas`, `trap_antes`,
        `trap_despues` y `forma<f>_{k,m,off,lw,sh,antes,despues}` con f = 1..3,
        los nombres de `mca_get_config`. **Sin pasarlos queda el reset del RTL, el
        MCA de un solo trapecio**: configure es todo el estado, y lo que una
        corrida anterior dejó no se filtra en la siguiente. Se valida junto con la
        compuerta, antes de escribir. Cómo armarlo: `mca_banco_config`.

        `discr` es None (apagado) o `(feature, min, max[, externo])`; con
        intervalo interno, min > max es un error. Con `verify` se releen ocho
        campos (RuntimeError si no coinciden).
        """
        if self._via == 'c':
            # Directo y posicional: pasar 30 kwargs por dict(locals()), el
            # despacho y mca_configure costaba ~130 µs en la placa, más que
            # todo el resto de configure. El orden es el de la firma de
            # _configurar, que es la misma.
            return _configurar(
                self, baseline, bl_auto, bl_k, bl_holdoff, amp_min, amp_max,
                amp_src, q_shift, dec, channel, gate_short, gate_long, n_acc,
                pre_dly, trap_k, trap_m, trap_mq, trap_off, trap_lw, trap_sh,
                verify, sel_1d, sel_2dx, sel_2dy, zoom_1d, zoom_2dx, zoom_2dy,
                discr, keep_if_full, **banco)
        kw = dict(locals())
        del kw['self']
        kw.update(kw.pop('banco'))
        return mca_configure(self, **kw)

    @property
    def channel(self):
        return mca_get_channel(self)

    # ---------- control de adquisición ----------

    def clear(self, timeout_s=1.0):
        """Borrar histogramas, contadores y relojes, y esperar el barrido.

        El barrido recorre 2^H_AW bins (131 us con 16384). Durante ese lapso el
        puerto de lectura sigue vivo, así que el bus no se cuelga, pero los
        eventos que lleguen se descartan y se cuentan en cnt_dropped.
        """
        mca_clear(self, timeout_s=timeout_s)

    def start(self):
        mca_start(self)

    def stop(self):
        mca_stop(self)

    @property
    def running(self):
        return mca_get_running(self)

    # ---------- lectura ----------

    def counters(self):
        """Contadores de eventos y relojes, en un dict (en C, `mca_read_counters`).

        LOS RELOJES CAMBIARON DE SIGNIFICADO RESPECTO DEL MCA1:

          `livetime_s`       alguna ranura libre: el MCA puede abrir.
          `t_win_s`          sin ranura libre, todas midiendo.
          `t_div_s`          sin ranura libre, alguna esperando al publicador.
          `deadtime_real_s`  t_win + t_div: el tiempo muerto de verdad, el que
                             hay que usar para corregir pérdidas.
          `deadtime_s`       la OCUPACIÓN (alguna ranura ocupada). Con una
                             ranura coincide con el tiempo muerto; con varias
                             NO lo es.
          `t_ocup_s[j]`      tiempo con exactamente j ranuras ocupadas: la
                             medición directa del modelo M/D/N/N.

        La atribución de arribos: `cross` disparos = `open` + `lost_active` +
        lost_busy (dentro de `dropped`) + `lost_veto`. `pileup` cuenta las
        ventanas CON marca de solape, que sí se histogramean. `pub_saturada`
        dice que la cola de publicación llegó a tener todas las ranuras.

        OJO CON LEER EN CALIENTE: `realtime = vetotime + t_win + t_div +
        livetime` vale ciclo a ciclo, pero leída con run=1 no cierra (cada
        acceso al bus se lleva ~6 ciclos). Para verificarla, `stop()` primero.
        """
        return mca_read_counters(self)

    def spectrum(self):
        """Espectro 1D como uint32 de 2^H_AW canales (~4 ms en C, ver _read_words).

        Los bins son contadores SIN signo: a diferencia del buffer del scope
        no hay que extender el signo de 14 a 16 bits.
        """
        return mca_read_histogram(self)

    def map2d(self):
        """Mapa 2D con forma (2^H2_AW, 2^PSD_AW): filas = amplitud, columnas = forma."""
        return mca_read_map2d(self)

    def last_event(self):
        """Último evento procesado. Para depurar la configuración de umbrales."""
        return mca_read_last_event(self)

    def acquire(self, seconds, clear_first=True):
        """Adquirir durante `seconds`. Devuelve (espectro, mapa2d|None, contadores).

        El disparo lo tiene que haber armado el llamador
        (`multitrigger_armar_mca`): sin él no abre ninguna ventana. Después de
        parar espera a que se vacíen las ranuras (las abiertas cierran y
        publican igual). La espera ocurre en C, con el GIL suelto.
        """
        return mca_read_acquire(self, seconds, clear_first=clear_first)

    def acquire_chunks(self, seconds, chunk_s, on_chunk=None):
        """Adquirir `seconds` ACUMULANDO en el mismo histograma.

        A diferencia de `acquire`, el borrado se hace una sola vez al principio
        y el histograma sigue creciendo entre trozos. Entre trozo y trozo llama
        a `on_chunk(k)`, que es donde el llamador puede cambiar el estímulo —
        por ejemplo recargar el ARB con una semilla nueva para que la DNL vea
        amplitudes distintas en vez de las mismas 128 repetidas.

        El MCA queda PARADO y con las ranuras vacías durante `on_chunk`, así
        que el tiempo que tarde el estímulo en recargarse no cuenta como vivo.
        """
        return mca_read_acquire_chunks(self, seconds, chunk_s, on_chunk=on_chunk)

    # ---------- auto-escalado de los desplazamientos ----------

    def autoscale_q_shift(self, target_channel=8000, seconds=0.5, **cfg):
        """Elige `q_shift` para que la INTEGRAL caiga cerca de `target_channel`.

        Con un `q_shift` fijo la amplitud por integral (`Q_total >> q_shift`)
        puede caer en unos pocos canales: ahí el FWHM se cuantiza y el estimador
        parece mejor de lo que es. Esta rutina mide `Q_total` de un evento real
        y despeja el desplazamiento, que es la única forma de comparar pico
        contra integral en la MISMA escala de canales.

        Devuelve el `q_shift` elegido (o None si no se detectaron eventos).
        """
        if cfg:
            self.configure(**cfg)
        s = ctypes.c_int32()
        _ok(self, _C.mca_autoscale_q_shift(
            self._c, float(target_channel), float(seconds), ctypes.byref(s)),
            'autoscale_q_shift')
        return None if s.value < 0 else s.value


# =============================================================================
# API de configuración y estatus
# =============================================================================
#
# Un get/set por campo de registro. Los registros que empaquetan varios campos
# (R_BL_CTRL, R_AMP_SRC, R_GATE_LEN) se tocan por read-modify-write, que es
# seguro porque el RTL los relee enteros: mca_top.sv:340,346,351 devuelven el
# valor escrito, con ceros en los huecos. Sin eso, poner `bl_k` borraría
# `bl_holdoff` en silencio.

# campo -> (offset, desplazamiento, máscara). El orden es el de la tabla de C
# (mca_regs.h, lo verifica test_libmca_mca.py), el de mca_get_config y, por lo
# tanto, el de la metadata guardada. h_shift y h2_shift no están: siguen en el
# mapa pero no afectan al datapath.
_CAMPOS = {
    'baseline':     (R_BASELINE,   0, 0x3FFF),
    'bl_auto':      (R_BL_CTRL,    0, 0x1),
    'bl_k':         (R_BL_CTRL,    4, 0xF),
    'bl_holdoff':   (R_BL_CTRL,   16, 0xFFFF),
    'amp_min':      (R_AMP_MIN,    0, 0xFFFF),
    'amp_max':      (R_AMP_MAX,    0, 0xFFFF),
    'amp_src':      (R_AMP_SRC,    0, 0x1),
    'q_shift':      (R_AMP_SRC,    8, 0x1F),
    'dec':          (R_DEC,        0, 0xFFFF),
    'gate_short':   (R_GATE_LEN,   0, 0xFFFF),
    'gate_long':    (R_GATE_LEN,  16, 0xFFFF),
    'channel':      (R_CTRL,       8, 0x1),
    'n_acc':        (R_N_ACC,      0, 0x7),
    'pre_dly':      (R_PRE_DLY,    0, 0x7F),
    'trap_k':       (R_TRAP_KM,    0, 0x3FF),
    'trap_m':       (R_TRAP_KM,   16, 0x3FF),
    'trap_mq':      (R_TRAP_MQ,    0, TRAP_MQ_MAX),
    'trap_off':     (R_TRAP_MED,   0, 0xFFFF),
    'trap_lw':      (R_TRAP_MED,  16, 0x7),
    'trap_sh':      (R_TRAP_MED,  24, 0x3F),
    'sel_1d':       (R_HIST_SEL,   0, 0xF),
    'sel_2dx':      (R_HIST_SEL,   4, 0xF),
    'sel_2dy':      (R_HIST_SEL,   8, 0xF),
    'zoom_1d_z':    (R_ZOOM_1D,    0, 0xF),
    'zoom_1d_k':    (R_ZOOM_1D,    8, 0xFF),
    'zoom_2dx_z':   (R_ZOOM_2DX,   0, 0xF),
    'zoom_2dx_k':   (R_ZOOM_2DX,   8, 0xFF),
    'zoom_2dy_z':   (R_ZOOM_2DY,   0, 0xF),
    'zoom_2dy_k':   (R_ZOOM_2DY,   8, 0xFF),
    'discr_en':     (R_DISCR_CTRL, 0, 0x1),
    'discr_ext':    (R_DISCR_CTRL, 1, 0x1),
    'discr_sel':    (R_DISCR_CTRL, 4, 0xF),
    'discr_min':    (R_DISCR_MIN,  0, 0xFFFF),
    'discr_max':    (R_DISCR_MAX,  0, 0xFFFF),
    'keep_if_full': (R_HIST_CTRL,  0, 0x1),
    # el banco de trapecios, al final: no corre el orden de la metadata vieja
    'n_formas':      (R_N_FORMAS,     0, 0x7),
    'trap_antes':    (R_TRAP_UMBR,    0, 0xFFFF),
    'trap_despues':  (R_TRAP_UMBR,   16, 0xFFFF),
    'forma1_k':      (R_FORMA1_KM,    0, 0x3FF),
    'forma1_m':      (R_FORMA1_KM,   16, 0x3FF),
    'forma1_off':    (R_FORMA1_MED,   0, 0xFFFF),
    'forma1_lw':     (R_FORMA1_MED,  16, 0x7),
    'forma1_sh':     (R_FORMA1_MED,  24, 0x3F),
    'forma1_antes':  (R_FORMA1_UMBR,  0, 0xFFFF),
    'forma1_despues':(R_FORMA1_UMBR, 16, 0xFFFF),
    'forma2_k':      (R_FORMA2_KM,    0, 0x3FF),
    'forma2_m':      (R_FORMA2_KM,   16, 0x3FF),
    'forma2_off':    (R_FORMA2_MED,   0, 0xFFFF),
    'forma2_lw':     (R_FORMA2_MED,  16, 0x7),
    'forma2_sh':     (R_FORMA2_MED,  24, 0x3F),
    'forma2_antes':  (R_FORMA2_UMBR,  0, 0xFFFF),
    'forma2_despues':(R_FORMA2_UMBR, 16, 0xFFFF),
    'forma3_k':      (R_FORMA3_KM,    0, 0x3FF),
    'forma3_m':      (R_FORMA3_KM,   16, 0x3FF),
    'forma3_off':    (R_FORMA3_MED,   0, 0xFFFF),
    'forma3_lw':     (R_FORMA3_MED,  16, 0x7),
    'forma3_sh':     (R_FORMA3_MED,  24, 0x3F),
    'forma3_antes':  (R_FORMA3_UMBR,  0, 0xFFFF),
    'forma3_despues':(R_FORMA3_UMBR, 16, 0xFFFF),
}


def _indice_campo(nombre):
    # El orden de _CAMPOS es el de la tabla de C (lo verifica
    # API/tests/test_libmca_mca.py), así que el índice es la posición.
    return _ORDEN_CAMPOS[nombre]


_ORDEN_CAMPOS = {n: i for i, n in enumerate(_CAMPOS)}


# El banco de trapecios: un get/set por campo de la tabla. Validan `n_formas` y
# los k (setters ESP de libmca, que reciben int64); los demás son GEN. Se generan
# de _CAMPOS_BANCO, con el mismo despacho que las escritas a mano.
_CAMPOS_BANCO = [n for n in _CAMPOS if n == 'n_formas' or n.startswith(('trap_antes',
                 'trap_despues', 'forma'))]


def _accesores_banco(nombre):
    def get(h):
        return _get(h, nombre)

    def set_(h, v):
        (_set_i64 if nombre in _SET_ESPECIALES else _set)(h, nombre, v)
    for fn, pre in ((get, 'mca_get_'), (set_, 'mca_set_')):
        fn.__name__ = fn.__qualname__ = pre + nombre
        fn.__doc__ = f'Campo {nombre} del banco de trapecios (register_map_mca.md).'
    return _api()(get), _api()(set_)


for _n in _CAMPOS_BANCO:
    globals()[f'mca_get_{_n}'], globals()[f'mca_set_{_n}'] = _accesores_banco(_n)
del _n


def _leer_campo(h, nombre):
    """Un campo cualquiera por nombre (`mca_get_field`), sin validaciones."""
    return _u32(h, _C.mca_get_field, _indice_campo(nombre))


def _escribir_campo(h, nombre, valor):
    """Read-modify-write genérico (`mca_set_field`), SIN las validaciones de
    los setters que las tienen (dec, n_acc, pre_dly, trapecio, selectores,
    zoom z)."""
    _ok(h, _C.mca_set_field(h._c, _indice_campo(nombre),
                                   int(valor) & 0xFFFFFFFF), 'set_field')


# ---------- apertura y ciclo de vida ----------

def mca_open(phys=MCA_PHYS, size=MCA_SIZE, check_magic=True, impl=None):
    """Abre /dev/mem y mapea el MCA. Devuelve el handle que usan las demás.

    `impl` elige la implementación: 'c' (libmca) o 'py' (la referencia Python,
    para benchmarks). Sin pedir ninguna se usa `$MCA_IMPL`, y si tampoco está,
    C; si libmca no carga se cae a Python **y se avisa**, para no medir con la
    implementación equivocada sin enterarse.

    Con 'py' y el bitstream MCA1 cargado, abre la referencia congelada del
    MCA1 (`API/ref_py/mca.py`): es la única que todavía habla ese mapa, y las
    funciones de este módulo van a ella (`h._referencia`). Las que no existen
    en el MCA1 dan NotImplementedError.
    """
    impl, aviso = _elegir_impl(impl)
    if aviso:
        print(f'warn: {aviso}', file=sys.stderr)
    if impl == 'py':
        try:
            h = _ref.MCA.open(phys, size, check_magic)
        except MCANotPresent:
            h = _ref_mca1.MCA.open(phys, size, check_magic)
            h._referencia = _ref_mca1.__name__
            h.mapa = 'MCA1'
        h._via = 'py'
        h.impl = 'py'
        return h
    return MCA.open(phys, size, check_magic)


def mca_close(h):
    h.close()


@_api()
def mca_identify(h, verbose=True):
    info = _Info()
    _ok(h, _C.mca_identify(h._c, ctypes.byref(info)), 'identify')
    d = {
        'magic':       info.magic,
        'hist_h':      bool(info.hist_h),
        'hist_h_psd':  bool(info.hist_h_psd),
        'trap':        bool(info.trap),
        'h_aw':        info.h_aw,
        'h2_aw':       info.h2_aw,
        'psd_aw':      info.psd_aw,
        'n_channels':  info.n_channels,
        'map2d_shape': (info.map2d_rows, info.map2d_cols),
        'n_acc_max':   info.n_acc_max,
        'features':    bool(info.features),
        'n_formas_max': info.n_formas_max,
    }
    if verbose:
        print(f"MCA2 presente (magic {d['magic']:#010x})")
        print(f"  espectro 1D : {'si' if d['hist_h'] else 'NO'} "
              f"({d['n_channels']} canales)")
        print(f"  mapa 2D     : {'si' if d['hist_h_psd'] else 'NO'} "
              f"({d['map2d_shape'][0]} x {d['map2d_shape'][1]})")
        print(f"  ranuras     : {d['n_acc_max']}")
        print(f"  trapecio    : {'si' if d['trap'] else 'NO'}")
        print(f"  banco       : {d['n_formas_max']} formas")
    return d


@_api()
def mca_start(h):
    """Arranca la acumulación (bit run de R_CTRL)."""
    _ok(h, _C.mca_start(h._c), 'start')


@_api()
def mca_stop(h):
    _ok(h, _C.mca_stop(h._c), 'stop')


@_api()
def mca_clear(h, timeout_s=1.0):
    """Borra histogramas, contadores y relojes; espera al barrido del RTL."""
    _ok(h, _C.mca_clear(h._c, float(timeout_s)), 'clear')


# ---------- configuración: un get/set por campo ----------

@_api()
def mca_get_baseline(h):     return _get(h, 'baseline')
@_api()
def mca_set_baseline(h, v):  _set(h, 'baseline', v)
@_api()
def mca_get_bl_auto(h):      return bool(_get(h, 'bl_auto'))
@_api()
def mca_set_bl_auto(h, v):   _set_bandera(h, 'bl_auto', v)
@_api()
def mca_get_bl_k(h):         return _get(h, 'bl_k')
@_api()
def mca_get_bl_holdoff(h):   return _get(h, 'bl_holdoff')
@_api()
def mca_set_bl_holdoff(h, v): _set(h, 'bl_holdoff', v)
@_api()
def mca_get_amp_min(h):      return _get(h, 'amp_min')
@_api()
def mca_set_amp_min(h, v):   _set(h, 'amp_min', v)
@_api()
def mca_get_amp_max(h):      return _get(h, 'amp_max')
@_api()
def mca_set_amp_max(h, v):   _set(h, 'amp_max', v)
@_api()
def mca_get_amp_src(h):      return _get(h, 'amp_src')
@_api()
def mca_set_amp_src(h, v):   _set_bandera(h, 'amp_src', v)
@_api()
def mca_get_q_shift(h):      return _get(h, 'q_shift')
@_api()
def mca_set_q_shift(h, v):   _set(h, 'q_shift', v)
@_api()
def mca_get_gate_short(h):   return _get(h, 'gate_short')
@_api()
def mca_set_gate_short(h, v): _set(h, 'gate_short', v)
@_api()
def mca_get_gate_long(h):    return _get(h, 'gate_long')
@_api()
def mca_set_gate_long(h, v): _set(h, 'gate_long', v)
@_api()
def mca_get_channel(h):      return _get(h, 'channel')
@_api()
def mca_set_channel(h, v):   _set_bandera(h, 'channel', v)


@_api()
def mca_set_bl_k(h, v):
    """Constante del seguidor de base: tau = 2^v muestras (8 ns cada una).

    Tiene que ser MUCHO más larga que el pulso. Si es comparable, el seguidor
    persigue el pulso y lo borra. Medido en la placa con un pulso de 62 us,
    bl_k=6 (tau=0.5 us) da 0 eventos y bl_k>=9 da los 2000 esperados. Regla:
    tau >= 100x el pulso.
    """
    _set(h, 'bl_k', v)


@_api()
def mca_set_dec(h, v):
    """Decimación. Tiene que ser >= 1."""
    _set_i64(h, 'dec', v)


@_api()
def mca_get_dec(h):
    return _get(h, 'dec')


# ---------- las ranuras ----------

@_api()
def mca_get_n_acc(h):        return _get(h, 'n_acc')


@_api()
def mca_set_n_acc(h, v):
    """Ranuras habilitadas, 1..N_ACC (`mca_get_n_acc_max`). Con 1 es la ventana
    única de antes. Se puede cambiar en caliente: vale desde el próximo
    disparo, y las que quedaron afuera terminan lo que estaban midiendo."""
    _set_i64(h, 'n_acc', v)


@_api()
def mca_get_pre_dly(h):      return _get(h, 'pre_dly')


@_api()
def mca_set_pre_dly(h, v):
    """Retardo de la muestra respecto del disparo, en ciclos (0..127), para que
    la ventana abra en el pie del pulso. La regla y la tabla medida están en
    docs/mca/register_map_mca.md, "La línea de retardo"."""
    _set_i64(h, 'pre_dly', v)


# ---------- el conformado trapezoidal (CAPS bit 2) ----------

@_api()
def mca_get_trap_k(h):       return _get(h, 'trap_k')


@_api()
def mca_set_trap_k(h, v):
    """Subida del trapecio, en muestras (1..1023). Reinicia su estado."""
    _set_i64(h, 'trap_k', v)


@_api()
def mca_get_trap_m(h):       return _get(h, 'trap_m')
@_api()
def mca_set_trap_m(h, v):    _set(h, 'trap_m', v)
@_api()
def mca_get_trap_mq(h):      return _get(h, 'trap_mq')


@_api()
def mca_set_trap_mq(h, v):
    """M*16, con M la constante polo-cero en muestras (0..2^20-1). Reinicia el
    trapecio. M ~ tau - 0.5 de la cola que llega al ADC, y se ajusta en la
    placa (register_map_mca.md)."""
    _set_i64(h, 'trap_mq', v)


@_api()
def mca_get_trap_off(h):     return _get(h, 'trap_off')
@_api()
def mca_set_trap_off(h, v):  _set(h, 'trap_off', v)
@_api()
def mca_get_trap_lw(h):      return _get(h, 'trap_lw')
@_api()
def mca_set_trap_lw(h, v):   _set(h, 'trap_lw', v)
@_api()
def mca_get_trap_sh(h):      return _get(h, 'trap_sh')
@_api()
def mca_set_trap_sh(h, v):   _set(h, 'trap_sh', v)


# ---------- campos de fase 1-3 ----------
#
# Los selectores de eje validan en C (`validar_feature` de mca.c), que rechaza
# un índice sin productor: una ranura reservada vale cero y el síntoma sería el
# espectro entero en el canal 0, sin ningún error. Aceptan el nombre de la
# feature, su índice o None (el default del eje).

def _set_sel(h, nombre, v):
    rc = _SET[nombre](h._c, _feat(v))
    if rc:
        _ok(h, rc, f'mca_set_{nombre}')


@_api()
def mca_get_sel_1d(h):       return _get(h, 'sel_1d')
@_api()
def mca_set_sel_1d(h, v):    _set_sel(h, 'sel_1d', v)
@_api()
def mca_get_sel_2dx(h):      return _get(h, 'sel_2dx')
@_api()
def mca_set_sel_2dx(h, v):   _set_sel(h, 'sel_2dx', v)
@_api()
def mca_get_sel_2dy(h):      return _get(h, 'sel_2dy')
@_api()
def mca_set_sel_2dy(h, v):   _set_sel(h, 'sel_2dy', v)

@_api()
def mca_get_zoom_1d_k(h):    return _get(h, 'zoom_1d_k')
@_api()
def mca_set_zoom_1d_k(h, v): _set(h, 'zoom_1d_k', v)
@_api()
def mca_get_zoom_2dx_k(h):   return _get(h, 'zoom_2dx_k')
@_api()
def mca_set_zoom_2dx_k(h, v): _set(h, 'zoom_2dx_k', v)
@_api()
def mca_get_zoom_2dy_k(h):   return _get(h, 'zoom_2dy_k')
@_api()
def mca_set_zoom_2dy_k(h, v): _set(h, 'zoom_2dy_k', v)

@_api()
def mca_get_discr_en(h):     return bool(_get(h, 'discr_en'))
@_api()
def mca_set_discr_en(h, v):  _set_bandera(h, 'discr_en', v)
@_api()
def mca_get_discr_ext(h):    return bool(_get(h, 'discr_ext'))
@_api()
def mca_set_discr_ext(h, v): _set_bandera(h, 'discr_ext', v)
@_api()
def mca_get_discr_sel(h):    return _get(h, 'discr_sel')
@_api()
def mca_set_discr_sel(h, v): _set_sel(h, 'discr_sel', v)
@_api()
def mca_get_discr_min(h):    return _get(h, 'discr_min')
@_api()
def mca_set_discr_min(h, v): _set(h, 'discr_min', v)
@_api()
def mca_get_discr_max(h):    return _get(h, 'discr_max')
@_api()
def mca_set_discr_max(h, v): _set(h, 'discr_max', v)

@_api()
def mca_get_keep_if_full(h):    return bool(_get(h, 'keep_if_full'))
@_api()
def mca_set_keep_if_full(h, v): _set_bandera(h, 'keep_if_full', v)

def _z_max(h_aw, amp_w=AMP_W):
    """Zoom máximo útil: más allá no quedan bits que rebanar.

    Es la misma saturación que hace el RTL (`mca_zoom.sv`: "z SE SATURA a
    FW-AW"), replicada acá para que el software no pida algo que el hardware va
    a recortar en silencio.
    """
    return max(0, int(amp_w) - int(h_aw))



@_api()
def mca_set_zoom_1d_z(h, v):
    """Nivel de zoom del eje 1D. La ventana es 2^-z del fondo de escala.

    Se satura a `AMP_W - h_aw` igual que el RTL (en C), en vez de dejar pasar
    un valor que el hardware va a recortar sin avisar.
    """
    _set_i64(h, 'zoom_1d_z', v)


@_api()
def mca_get_zoom_1d_z(h):    return _get(h, 'zoom_1d_z')


@_api()
def mca_set_zoom_2dx_z(h, v):
    _set_i64(h, 'zoom_2dx_z', v)


@_api()
def mca_get_zoom_2dx_z(h):   return _get(h, 'zoom_2dx_z')


@_api()
def mca_set_zoom_2dy_z(h, v):
    _set_i64(h, 'zoom_2dy_z', v)


@_api()
def mca_get_zoom_2dy_z(h):   return _get(h, 'zoom_2dy_z')

# ---------- amplitud <-> canal ----------

def mca_canal_de_amplitud(valor, h_aw, z=0, k=0, amp_w=AMP_W):
    """Canal del histograma en el que cae una amplitud de `amp_w` bits.

    Es el espejo en software de `mca_zoom.sv`, y existe porque **no hay otra
    forma de ubicar en el eje un valor que vive en cuentas de amplitud** — los
    límites de la ventana de aceptación (`amp_min`/`amp_max`), los del
    discriminador, o un umbral que se quiera dibujar sobre el espectro.

    La ventana del zoom es `[k*2^(amp_w-z), (k+1)*2^(amp_w-z))` y el bin son los
    `h_aw` bits siguientes a los `z` bits altos::

        dentro de la ventana  <=>  los z bits ALTOS de la amplitud valen k
        bin                    =   los h_aw bits siguientes

    **Satura, no envuelve**: un valor por encima de la ventana cae en el último
    canal y uno por debajo en el canal 0. Es el contrato del RTL
    (`mca_zoom.sv:29-32`) y es lo que hace que los bines de los extremos sirvan
    de indicadores de desborde.

    NO confundir con `h_shift`, que gobernaba esto en el bitstream viejo y hoy
    está deprecado: se sigue leyendo y escribiendo pero **ya no afecta al
    datapath** (ver `docs/mca/register_map_mca.md`). Usar `h_shift` acá daba el
    canal equivocado por un factor de `2^(amp_w-h_aw)`.
    """
    h_aw = int(h_aw)
    z = min(int(z), _z_max(h_aw, amp_w))
    k = int(k) & ((1 << z) - 1) if z > 0 else 0     # el RTL enmascara k a z bits
    n_canales = 1 << h_aw

    ancho = 1 << (int(amp_w) - z)                   # ancho de la ventana
    lo = k * ancho
    v = int(valor)
    if v < lo:
        return 0
    if v >= lo + ancho:
        return n_canales - 1
    return ((v - lo) >> (int(amp_w) - z - h_aw)) & (n_canales - 1)


def mca_amplitud_de_canal(canal, h_aw, z=0, k=0, amp_w=AMP_W):
    """La inversa: el borde INFERIOR de la amplitud que cae en ese canal.

    Es una inversa por izquierda —el canal cubre un rango de amplitudes— así que
    `mca_canal_de_amplitud(mca_amplitud_de_canal(c, ...), ...) == c`, pero no al
    revés. Sirve para etiquetar el eje en cuentas o en volts.
    """
    h_aw = int(h_aw)
    z = min(int(z), _z_max(h_aw, amp_w))
    k = int(k) & ((1 << z) - 1) if z > 0 else 0
    ancho = 1 << (int(amp_w) - z)
    return k * ancho + (int(canal) << (int(amp_w) - z - h_aw))



# El banco en el reset del RTL (mca_config_default): cada forma es la mitad de la
# anterior, con la ventana en el centro de su meseta y la misma altura. En el
# orden de mca_config_t.
_BANCO_RESET = {
    'n_formas': 1, 'trap_antes': 0, 'trap_despues': 0,
    'forma1_k': 32, 'forma1_m': 16, 'forma1_off': 40, 'forma1_lw': 3, 'forma1_sh': 6,
    'forma1_antes': 0, 'forma1_despues': 0,
    'forma2_k': 16, 'forma2_m': 8, 'forma2_off': 22, 'forma2_lw': 2, 'forma2_sh': 5,
    'forma2_antes': 0, 'forma2_despues': 0,
    'forma3_k': 8, 'forma3_m': 4, 'forma3_off': 13, 'forma3_lw': 1, 'forma3_sh': 4,
    'forma3_antes': 0, 'forma3_despues': 0,
}
_VALS_BANCO_RESET = tuple(_BANCO_RESET.values())


def _valores_banco(banco):
    if not banco:
        return _VALS_BANCO_RESET
    for n in banco:
        if n not in _BANCO_RESET:
            raise TypeError(f'configure() got an unexpected keyword argument {n!r}')
    return tuple(banco.get(n, d) for n, d in _BANCO_RESET.items())


# El banco de la campaña, para el pulso del Rigol y el disparo con polo-cero:
# (k, m, lw, c, antes, despues), de la más larga a la más corta.
# Ver docs/mca/pruebas_banco_trapecios.md.
BANCO_PZ = ((64, 48, 4, 69, 97, 96), (32, 24, 3, 29, 49, 48),
            (16, 12, 2, 9, 26, 24), (8, 8, 1, 0, 15, 13))


def mca_banco_config(mq, pre_dly=16, formas=BANCO_PZ, gate_long=None, altura=8.0):
    """Los argumentos de `mca_configure` para el banco de trapecios.

    Es una cuenta, no toca el hardware: `mca_configure(h, n_acc=4, sel_1d='trapecio',
    **mca_banco_config(mq))`. Trae también `pre_dly` y `gate_long`, de los que
    dependen las ventanas, para que no se puedan pasar otros.

    `mq` es M*16 con M la constante polo-cero, común a todas las formas (la del
    ajuste de la cola en la placa, y la misma que el disparo: ver
    `API.multitrigger.multitrigger_armar_banco`). Cada forma de `formas` es
    `(k, m, lw, c, antes, despues)`:

      - `c` es dónde cae la ventana respecto del pie del pulso; el registro es
        `off = c + pre_dly + 2`. **Por eso cambiar `pre_dly` solo mueve todas las
        ventanas**, y nada lo avisa: `trap_ok` mira que entren en la compuerta, no
        que caigan sobre la meseta.
      - `sh` sale de la altura pedida: `feature = altura · amplitud`, redondeada a
        una potencia de 2 porque es un corrimiento. Si los k no van por potencias
        de 2, las formas no pueden tener la misma ganancia: `mca_configure` lo
        rechaza, porque el pico se partiría.
      - `gate_long=None` es la compuerta más corta que las contiene a todas,
        redondeada a múltiplo de 8 (112 con el banco de la campaña).
    """
    if not 1 <= len(formas) <= N_FORMAS_TOPE:
        raise ValueError(f'{len(formas)} formas: el banco tiene de 1 a {N_FORMAS_TOPE}')
    M = int(mq) / 16.0
    kw = {'n_formas': len(formas), 'trap_mq': int(mq), 'pre_dly': int(pre_dly)}
    fin = 0
    for f, (k, m, lw, c, antes, despues) in enumerate(formas):
        off = c + int(pre_dly) + 2
        sh = int(round(math.log2(16.0 * k * (1.0 + M) / altura)))
        pref = 'trap_' if f == 0 else f'forma{f}_'
        kw.update({f'{pref}k': k, f'{pref}m': m, f'{pref}off': off, f'{pref}lw': lw,
                   f'{pref}sh': sh, f'{pref}antes': antes, f'{pref}despues': despues})
        fin = max(fin, off + TRAP_LAT + (1 << lw), despues)
    kw['gate_long'] = int(gate_long) if gate_long is not None else -(-fin // 8) * 8
    return kw


def _configurar(h, baseline=0, bl_auto=False, bl_k=12, bl_holdoff=0,
                amp_min=0, amp_max=0xFFFF, amp_src=0, q_shift=0, dec=1,
                channel=0, gate_short=32, gate_long=384, n_acc=1, pre_dly=16,
                trap_k=64, trap_m=32, trap_mq=0, trap_off=72, trap_lw=4,
                trap_sh=7, verify=True, sel_1d=None, sel_2dx=None, sel_2dy=None,
                zoom_1d=(0, 0), zoom_2dx=(0, 0), zoom_2dy=(0, 0),
                discr=None, keep_if_full=True, **banco):
    # Los kwargs de MCA.configure() -> mca_config_t, en el orden de sus campos.
    # Las banderas con la verdad de Python; los enteros como int64, porque C
    # compara el valor pedido (dec >= 1, n_acc en 1..N_ACC) antes de
    # enmascarar. Se empaquetan de una vez: asignar los campos de ctypes uno
    # por uno costaba ~150 µs en la placa.
    z1, k1 = zoom_1d
    zx, kx = zoom_2dx
    zy, ky = zoom_2dy
    if discr is None:
        d_en, d_sel, d_min, d_max, d_ext = 0, _F_DEFAULT, 0, 0, 0
    else:
        d_en, d_sel = 1, _feat(discr[0])
        d_min, d_max = discr[1], discr[2]
        d_ext = 1 if (len(discr) > 3 and discr[3]) else 0
    vals = (baseline, 1 if bl_auto else 0, bl_k, bl_holdoff, amp_min, amp_max,
            1 if amp_src else 0, q_shift, dec, 1 if channel else 0,
            gate_short, gate_long, n_acc, pre_dly, trap_k, trap_m, trap_mq,
            trap_off, trap_lw, trap_sh, 1 if verify else 0,
            _feat(sel_1d), _feat(sel_2dx), _feat(sel_2dy),
            z1, k1, zx, kx, zy, ky,
            d_en, d_sel, d_min, d_max, d_ext, 1 if keep_if_full else 0)
    vals += _valores_banco(banco)
    try:
        buf = _ST_CONFIG.pack(*vals)
    except (struct.error, TypeError):
        # Algo que no es un entero en rango (un float, un str, un número
        # enorme): la conversión de siempre, que trunca y satura.
        buf = _ST_CONFIG.pack(*(_i64(v) if i in _ENTEROS_CONFIG else v
                                for i, v in enumerate(vals)))
    c = _Config.from_buffer_copy(buf)
    rc = _C.mca_configure(h._c, ctypes.byref(c))
    if rc:
        _ok(h, rc, 'configure')


@_api()
def mca_configure(h, **kw):
    """Escribe el bloque de configuración entero. Firma idéntica a
    `MCA.configure()`, que es la que usa `testbench_mca.py`."""
    _configurar(h, **kw)


# ---------- estatus (sólo lectura) ----------

@_api()
def mca_get_status(h):       return _u32(h, _C.mca_get_status)
@_api()
def mca_get_running(h):      return bool(_u32(h, _C.mca_get_running))
@_api()
def mca_get_clear_busy(h):   return bool(_u32(h, _C.mca_get_clear_busy))
@_api()
def mca_get_busy(h):         return bool(_u32(h, _C.mca_get_busy))
@_api()
def mca_get_puede_abrir(h):  return bool(_u32(h, _C.mca_get_puede_abrir))
@_api()
def mca_get_n_ocup(h):       return _u32(h, _C.mca_get_n_ocup)
@_api()
def mca_get_n_acc_max(h):    return _u32(h, _C.mca_get_n_acc_max)
@_api()
def mca_get_trap_ok(h):      return bool(_u32(h, _C.mca_get_trap_ok))
@_api()
def mca_get_n_formas_max(h): return _u32(h, _C.mca_get_n_formas_max)
@_api()
def mca_get_umbr_ok(h):      return bool(_u32(h, _C.mca_get_umbr_ok))
@_api()
def mca_get_formas_ok(h):
    """La ventana de cada forma EN USO entra en la compuerta: una lista de bools."""
    m, n = ctypes.c_uint32(), ctypes.c_uint32()
    _ok(h, _C.mca_get_formas_ok(h._c, ctypes.byref(m), ctypes.byref(n)), 'get_formas_ok')
    return [bool((m.value >> f) & 1) for f in range(n.value)]
@_api()
def mca_get_baseline_stale(h): return bool(_u32(h, _C.mca_get_baseline_stale))
@_api()
def mca_get_vetoed(h):       return bool(_u32(h, _C.mca_get_vetoed))
@_api()
def mca_get_caps(h):         return _u32(h, _C.mca_get_caps)


@_api()
def mca_get_baseline_now(h):
    v = ctypes.c_int32()
    _ok(h, _C.mca_get_baseline_now(h._c, ctypes.byref(v)), 'baseline_now')
    return v.value


@_api()
def mca_get_widths(h):
    """Anchos de dirección de los histogramas, como los publica el RTL."""
    a, b, c = ctypes.c_uint32(), ctypes.c_uint32(), ctypes.c_uint32()
    _ok(h, _C.mca_get_widths(h._c, ctypes.byref(a), ctypes.byref(b),
                                    ctypes.byref(c)), 'widths')
    return {'h_aw': a.value, 'h2_aw': b.value, 'psd_aw': c.value}


@_api()
def mca_get_config(h):
    """Todos los campos de configuración, releídos del hardware."""
    vals = (ctypes.c_uint32 * len(_CAMPOS))()
    rc = _C.mca_get_config(h._c, vals, len(_CAMPOS))
    if rc:
        _ok(h, rc, 'get_config')
    return dict(zip(_CAMPOS, struct.unpack_from(f'{len(_CAMPOS)}I', vals)))


def mca_get_metadata(h):
    """Config + contadores + geometría + sello de tiempo: lo que acompaña a un
    espectro guardado para que el fichero se entienda solo dentro de un año.

    No lleva `@_api`: no es una operación de hardware sino una composición de
    otras, y cada una de ésas despacha sola. Por eso corre igual sobre un
    handle de C, uno de referencia o uno remoto, y la marca `api_impl` sale
    siempre del handle que se pasó.
    """
    meta = {'schema_version': SCHEMA_VERSION_MCA}
    meta.update(mca_get_config(h))
    meta.update(mca_get_widths(h))
    meta.update(mca_read_counters(h))
    meta['n_channels'] = 1 << h.h_aw
    meta['fs_hz'] = FS_HZ
    meta['adc_cnt_per_V'] = ADC_CNT_PER_V
    meta['t_wall'] = time.time()
    # Con qué implementación de la API se midió: 'py', 'c' (libmca), 'remoto'
    # o 'fake'. Sin esto, dos espectros de la misma campaña tomados antes y
    # después de pasar a C no se distinguen, y la comparación de rendimiento
    # no se puede reconstruir desde los datos. Un fichero sin la clave es 'py':
    # es lo único que existía antes.
    meta['api_impl'] = getattr(h, 'impl', 'py')
    meta['libmca_version'] = getattr(h, 'libmca_version', None)
    # El mapa de registros con que se midió: las claves de config y de
    # contadores, y lo que significa `deadtime_s`, dependen de él. Un fichero
    # sin la clave es del MCA1 (schema_version 1).
    meta['mapa'] = getattr(h, 'mapa', 'MCA2')
    return meta


# =============================================================================
# API de lectura
# =============================================================================

@_api()
def mca_read_histogram(h):
    """Espectro 1D de amplitud. uint32[2**h_aw].

    Se lee DE A UNA palabra a propósito (ver MCA._read_words), en C: ~4 ms
    por espectro de 16384 canales, contra ~110 ms desde Python.
    """
    dst = np.empty(1 << h.h_aw, dtype=np.uint32)
    _ok(h, _C.mca_read_histogram(h._c, _ptr(dst), dst.size), 'histogram')
    return dst


@_api()
def mca_read_map2d(h):
    """Mapa 2D amplitud x factor de forma. uint32[2**h2_aw, 2**psd_aw]."""
    dst = np.empty(1 << (h.h2_aw + h.psd_aw), dtype=np.uint32)
    _ok(h, _C.mca_read_map2d(h._c, _ptr(dst), dst.size), 'map2d')
    return dst.reshape(1 << h.h2_aw, 1 << h.psd_aw)


@_api()
def mca_read_counters(h):
    c = _Counters()
    _ok(h, _C.mca_read_counters(h._c, ctypes.byref(c)), 'counters')
    return _contadores(c)


@_api()
def mca_read_last_event(h):
    """Rasgos del último evento procesado: para depurar umbral y compuertas."""
    ev = _LastEvent()
    _ok(h, _C.mca_read_last_event(h._c, ctypes.byref(ev)), 'last_event')
    return _evento(ev)


def _buffers(h):
    hist = np.empty(1 << h.h_aw, dtype=np.uint32)
    m2d = (np.empty(1 << (h.h2_aw + h.psd_aw), dtype=np.uint32)
           if h._has_2d else None)
    return hist, m2d


def _resultado(h, hist, m2d, cnt):
    if m2d is not None:
        m2d = m2d.reshape(1 << h.h2_aw, 1 << h.psd_aw)
    return hist, m2d, _contadores(cnt)


# Las dos que esperan NO van por red (`remoto=False`): un `call` de diez
# segundos tendría tomado el lock del servidor. Un cliente remoto usa
# ctrl.start(seconds=...) y status.

@_api(remoto=False)
def mca_read_acquire(h, seconds, clear_first=True):
    """Una adquisición temporizada -> (histograma, mapa2d|None, contadores)."""
    hist, m2d = _buffers(h)
    cnt = _Counters()
    _ok(h, _C.mca_read_acquire(
        h._c, float(seconds), 1 if clear_first else 0,
        _ptr(hist), hist.size,
        _ptr(m2d) if m2d is not None else None,
        m2d.size if m2d is not None else 0, ctypes.byref(cnt)), 'acquire')
    return _resultado(h, hist, m2d, cnt)


@_api(remoto=False)
def mca_read_acquire_chunks(h, seconds, chunk_s, on_chunk=None):
    """Acumula `seconds` en el MISMO histograma, llamando a `on_chunk` por
    rebanada. Sirve para ver la deriva sin cortar la acumulación."""
    hist, m2d = _buffers(h)
    cnt = _Counters()
    # Una excepción de on_chunk no puede cruzar C: se guarda, el callback
    # devuelve != 0, C corta, y acá se relanza la original.
    error = []

    def cb(_ctx, k):
        try:
            on_chunk(int(k))
            return 0
        except BaseException as e:                              # noqa: BLE001
            error.append(e)
            return 1

    fn = _CHUNK(cb) if on_chunk is not None else _CHUNK()
    rc = _C.mca_read_acquire_chunks(
        h._c, float(seconds), float(chunk_s), fn, None,
        _ptr(hist), hist.size,
        _ptr(m2d) if m2d is not None else None,
        m2d.size if m2d is not None else 0, ctypes.byref(cnt))
    if error:
        raise error[0]
    _ok(h, rc, 'acquire_chunks')
    return _resultado(h, hist, m2d, cnt)

# =============================================================================
# API de guardado
# =============================================================================
#
# Tres formatos para el mismo par (histograma, metadata):
#
#   write_file_histogram  csv  texto, cabecera '# clave: valor'  <- por defecto
#   save_file_binary      npz  compacto, es lo que usa el resto del árbol
#   save_file_json        json legible por cualquier cosa, sin numpy
#
# `mca_load_file` relee los tres y devuelve siempre (histograma, metadata), así
# que el formato es una decisión de almacenamiento y no cambia el análisis.
#
# schema_version 2: la metadata del MCA2 (otras claves de config y contadores,
# `t_ocup_s`, y la clave `mapa`). La 1 es la del MCA1.

SCHEMA_VERSION_MCA = 2


def _meta_serializable(meta):
    """numpy -> tipos de Python, para que json y el csv no escupan repr raros."""
    limpio = {}
    for k, v in (meta or {}).items():
        if isinstance(v, (np.integer,)):
            v = int(v)
        elif isinstance(v, (np.floating,)):
            v = float(v)
        elif isinstance(v, (np.bool_,)):
            v = bool(v)
        elif isinstance(v, np.ndarray):
            v = v.tolist()
        limpio[k] = v
    return limpio


def _parse_valor(s):
    """Texto de la cabecera csv -> int/float/bool/None/str, en ese orden.

    Sin esto la metadata vuelve del csv como cadenas y un `thr` releído no
    compara igual que el que se escribió.
    """
    s = s.strip()
    if s in ('True', 'False'):
        return s == 'True'
    if s in ('None', ''):
        return None
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            pass
    return s


def mca_write_file_histogram(hist, path, meta=None):
    """Guarda el espectro como csv con la metadata en cabecera de comentarios.

    Es el formato por defecto: se abre en cualquier lado (Excel, Origin, un
    editor) y sigue siendo autodescriptivo, que es lo que un csv pelado no da.
    """
    hist = np.asarray(hist)
    meta = _meta_serializable(meta)
    with open(path, 'w') as f:
        for k, v in meta.items():
            f.write(f'# {k}: {v}\n')
        f.write('canal,cuentas\n')
        for i, c in enumerate(hist):
            f.write(f'{i},{int(c)}\n')


def mca_save_file_binary(hist, path, meta=None):
    """Guarda el espectro como .npz. La metadata va como array 0-d de objeto,
    igual que en osciloscope_store.storage, para no partir el fichero en dos."""
    np.savez_compressed(path, hist=np.asarray(hist),
                        meta=np.array(_meta_serializable(meta) or {}, dtype=object))


def mca_save_file_json(hist, path, meta=None):
    """Guarda el espectro como .json: {'meta': {...}, 'hist': [...]}."""
    with open(path, 'w') as f:
        json.dump({'meta': _meta_serializable(meta) or {},
                   'hist': np.asarray(hist).astype(int).tolist()},
                  f, indent=2, ensure_ascii=False)


def mca_load_file(path):
    """Relee cualquiera de los tres formatos -> (histograma uint32, metadata)."""
    ext = os.path.splitext(path)[1].lower()

    if ext == '.npz':
        with np.load(path, allow_pickle=True) as z:
            meta = z['meta'].item() if 'meta' in z.files else {}
            return z['hist'].astype(np.uint32), meta

    if ext == '.json':
        with open(path) as f:
            d = json.load(f)
        return np.asarray(d['hist'], dtype=np.uint32), d.get('meta', {})

    if ext in ('.csv', '.txt'):
        meta, cuentas = {}, []
        with open(path) as f:
            for linea in f:
                if linea.startswith('#'):
                    if ':' in linea:
                        k, v = linea[1:].split(':', 1)
                        meta[k.strip()] = _parse_valor(v)
                elif linea.strip() and not linea.startswith('canal'):
                    cuentas.append(int(linea.split(',')[1]))
        return np.asarray(cuentas, dtype=np.uint32), meta

    raise ValueError(f'formato no reconocido: {ext!r} (esperaba .csv/.npz/.json)')

