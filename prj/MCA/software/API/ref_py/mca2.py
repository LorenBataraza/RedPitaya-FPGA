#!/usr/bin/env python3
# REFERENCIA del mapa "MCA2". Se escribió para el port de libmca al MCA2 y se
# congela cuando ese port cierra: NO EDITAR después (ver ref_py/__init__.py).
"""Analizador Multicanal con ranuras ("MCA2"), en Python: la referencia.

Es la implementación Python de la API de hardware del MCA para el mapa
"MCA2" (`docs/mca/register_map_mca.md`, `modulos/mca/rtl/mca_top.sv`). La
API que se usa es la de `API/mca.py`, sobre libmca (C); ésta existe para:

  - **Equivalencia.** `API/tests/test_libmca_equivalencia.py` exige que C y
    esta implementación hagan EXACTAMENTE las mismas escrituras, en el mismo
    orden, devuelvan lo mismo y fallen igual.
  - **Rendimiento.** Es la columna `py` del bench sobre un MCA2.
  - **Selección explícita.** `mca_open(impl='py')` abre un handle de acá.

Lo que cambió respecto del MCA1 (`ref_py/mca.py`):

  - La ventana la abre SÓLO el disparo externo (`trig_i`, el multitrigger) y la
    cierra la compuerta larga. Se fueron el Schmitt interno, la histéresis,
    `maxlen`, `tail_dly`, el modo de compuerta y las políticas de re-armado y
    de publicación. `h_shift` y `h2_shift` siguen en el mapa pero no afectan
    al datapath (los subsume el zoom): la API ya no los escribe.
  - Las ranuras: hasta `N_ACC` juegos de acumuladores midiendo a la vez
    (`n_acc`), con la muestra retrasada `pre_dly` ciclos respecto del disparo.
  - El conformado trapezoidal (`F_TRAP`), si el bitstream lo trae (CAPS bit 2).
  - Cuatro features nuevas: `dt_anterior`, `dt_siguiente`, `solape`, `trapecio`.

Diferencias de diseño con la referencia del MCA1, a propósito:

  - `configure()` valida TODO antes de escribir nada: una configuración mala
    deja los registros como estaban.
  - `configure()` para el MCA lo primero (run=0), no lo último: la ventana de
    amplitud y `q_shift` no se pueden cambiar con una ranura midiendo.
  - `acquire()` espera a que se vacíen las ranuras después de parar: con
    run=0 las abiertas igual cierran y publican, y si no se espera el último
    evento queda afuera de la lectura.
"""

import mmap
import os
import struct
import time

import numpy as np

# =============================================================================
# Mapa de memoria
# =============================================================================

MCA_PHYS = 0x4070_0000          # slot 7 del sys bus
MCA_SIZE = 0x30000              # registros + las dos aperturas

MAGIC      = 0x4D434132         # "MCA2"
MAGIC_MCA1 = 0x4D434131         # "MCA1": el mapa anterior (ver ref_py/mca.py)

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
R_H_SHIFT      = 0x03C          # DEPRECADO: sin efecto en el datapath
R_H2_SHIFT     = 0x040          # DEPRECADO: sin efecto en el datapath
R_DEC          = 0x044
R_GATE_LEN     = 0x04C          # {larga[31:16], corta[15:0]} desde el disparo
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
# --- contadores de eventos ---
R_CNT_TOTAL    = 0x050          # ventanas cerradas
R_CNT_ACCEPTED = 0x054
R_CNT_REJ_AMP  = 0x058
R_CNT_REJ_PSD  = 0x05C
R_CNT_PILEUP   = 0x060          # ventanas cerradas CON marca de solape
R_CNT_DROPPED  = 0x064          # lost_busy + colisiones + borrado
# --- relojes (64 b; leer la palabra BAJA congela la ALTA) ---
# realtime == vetotime + t_win + t_div + livetime, exacto en todo ciclo.
R_REALTIME_LO  = 0x068
R_REALTIME_HI  = 0x06C
R_LIVETIME_LO  = 0x070          # alguna ranura libre
R_LIVETIME_HI  = 0x074
R_DEADTIME_LO  = 0x078          # OCUPACIÓN: alguna ranura ocupada
R_DEADTIME_HI  = 0x07C
R_VETOTIME_LO  = 0x0C0
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
# --- el trapecio ---
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
APERTURE_H     = 0x10000
APERTURE_2D    = 0x20000

CAP_HIST_H     = 1 << 0
CAP_HIST_H_PSD = 1 << 1
CAP_TRAP       = 1 << 2

FS_HZ          = 125e6
ADC_CNT_PER_V  = 8192
AMP_W          = 16             # ancho del bus de features

# Tope de las ranuras que puede tener el MCA: cfg_n_acc es de 3 bits. Es el
# largo máximo de `t_ocup` (N_ACC + 1 casilleros).
N_ACC_TOPE     = 7
PRE_DLY_MAX    = 127            # cfg_pre_dly es de 7 bits
TRAP_KL_MAX    = 1023           # las líneas de retardo del trapecio
TRAP_MQ_MAX    = (1 << 20) - 1  # M*16 en 20 b
TRAP_LAT       = 8              # la latencia de mca_trap: entra en trap_ok
N_FORMAS_TOPE  = 4              # el banco: el mapa tiene cuatro bloques

# El banco en el reset del RTL: cada forma es la mitad de la anterior, con la
# ventana en el centro de su meseta y la misma altura. Sin umbrales gana siempre
# la forma 0, y con n_formas = 1 las otras no se miran.
BANCO_RESET = {
    'n_formas': 1, 'trap_antes': 0, 'trap_despues': 0,
    'forma1_k': 32, 'forma1_m': 16, 'forma1_off': 40, 'forma1_lw': 3, 'forma1_sh': 6,
    'forma1_antes': 0, 'forma1_despues': 0,
    'forma2_k': 16, 'forma2_m': 8, 'forma2_off': 22, 'forma2_lw': 2, 'forma2_sh': 5,
    'forma2_antes': 0, 'forma2_despues': 0,
    'forma3_k': 8, 'forma3_m': 4, 'forma3_off': 13, 'forma3_lw': 1, 'forma3_sh': 4,
    'forma3_antes': 0, 'forma3_despues': 0,
}

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
    'trapecio':     F_TRAP,     # altura de la meseta del trapecio
    'forma':        F_FORMA,    # la forma del banco que se publico, 0xFFFF = marcado
}

_U32 = struct.Struct('<I')


class MCANotPresent(RuntimeError):
    """El bitstream cargado no tiene el MCA2 en el slot 7."""


def _feat_idx(f, por_defecto, h):
    """Acepta el nombre de una feature, su índice, o None.

    Un índice fuera de rango apunta a una ranura RESERVADA del bus, que vale
    cero: el síntoma sería el espectro entero en el canal 0 sin ningún error.
    Lo mismo `trapecio` en un bitstream sin el conformado trapezoidal.
    """
    if f is None:
        return por_defecto
    if isinstance(f, str):
        if f not in FEATURES:
            raise ValueError(f'feature {f!r} desconocida; hay: '
                             f'{sorted(FEATURES)}')
        f = FEATURES[f]
    f = int(f)
    if f not in FEATURES.values():
        raise ValueError(
            f'indice de feature {f} sin productor: las ranuras validas son '
            f'{sorted(FEATURES.values())} ({sorted(FEATURES)}). Las demas estan '
            f'reservadas y valen cero, asi que el espectro caeria entero en el '
            f'canal 0 sin avisar.')
    if f in (F_TRAP, F_FORMA) and not h.caps & CAP_TRAP:
        raise ValueError(
            f'la feature {"trapecio" if f == F_TRAP else "forma"} necesita el '
            'conformado trapezoidal (CAPS bit 2) y el bitstream cargado no lo trae: '
            'vale cero, asi que el espectro caeria entero en el canal 0 sin avisar.')
    if f == F_FORMA and not (h.r32(R_N_FORMAS) >> 8) & 7:
        # Un bitstream con el trapecio pero sin el banco: 0x134 lee cero.
        raise ValueError(
            'la feature forma necesita el banco de trapecios (0x134, N_FORMAS) y '
            'el bitstream cargado no lo trae: vale cero, asi que el espectro '
            'caeria entero en el canal 0 sin avisar.')
    return f


def _sign14(v):
    v &= 0x3FFF
    return v - 0x4000 if v & 0x2000 else v


# =============================================================================
# Validación de los campos que el RTL satura o envuelve en silencio
# =============================================================================

def _validar_dec(v):
    if v < 1:
        raise ValueError('dec tiene que ser >= 1')


def _validar_n_acc(v, n_max):
    if not 1 <= v <= n_max:
        raise ValueError(
            f'n_acc={v}: tiene que estar entre 1 y {n_max}, las ranuras con '
            f'que se sintetizo el MCA (el RTL toma 0 como 1 y satura arriba '
            f'sin avisar)')


def _validar_pre_dly(v):
    if not 0 <= v <= PRE_DLY_MAX:
        raise ValueError(f'pre_dly={v}: tiene que estar entre 0 y '
                         f'{PRE_DLY_MAX} ciclos')


def _validar_trap_k(v):
    if not 1 <= v <= TRAP_KL_MAX:
        raise ValueError(f'trap_k={v}: tiene que estar entre 1 y '
                         f'{TRAP_KL_MAX} muestras')


def _validar_trap_mq(v):
    if not 0 <= v <= TRAP_MQ_MAX:
        raise ValueError(f'trap_mq={v}: tiene que estar entre 0 y '
                         f'{TRAP_MQ_MAX} (M*16, con M hasta 65535.94 muestras)')


def _validar_n_formas(v, n_max):
    if n_max == 0:
        if v != 1:
            raise ValueError(f'n_formas={v}: el bitstream cargado no tiene el banco '
                             f'de trapecios (0x134, N_FORMAS = 0), usa una sola forma')
        return
    n_max = min(n_max, N_FORMAS_TOPE)
    if not 1 <= v <= n_max:
        raise ValueError(
            f'n_formas={v}: tiene que estar entre 1 y {n_max}, las formas del banco '
            f'(el RTL toma 0 como 1 y satura arriba sin avisar)')


def _validar_forma_k(f, v):
    if not 1 <= v <= TRAP_KL_MAX:
        raise ValueError(f'forma{f}_k={v}: tiene que estar entre 1 y '
                         f'{TRAP_KL_MAX} muestras')


def _banco_de(banco):
    """Los kwargs del banco de `configure`, sobre el reset del RTL."""
    for n in banco:
        if n not in BANCO_RESET:
            raise TypeError(f'configure() got an unexpected keyword argument {n!r}')
    return {**BANCO_RESET, **banco}


# =============================================================================
# Driver
# =============================================================================

class MCA:
    """Acceso al MCA2 por /dev/mem.

    Uso típico::

        mca = MCA.open()
        mca.configure(gate_long=384, n_acc=4)
        # ... armar el disparo: multitrigger_armar_mca(osc, mtr) ...
        spec, m2d, cnt = mca.acquire(10.0)
    """

    def __init__(self, mem, fd, caps, h_aw, h2_aw, psd_aw):
        self._mmap  = mem
        self._fd    = fd
        self.caps   = caps
        self.h_aw   = h_aw
        self.h2_aw  = h2_aw
        self.psd_aw = psd_aw
        self._has_2d = bool(caps & CAP_HIST_H_PSD)

    # ---------- apertura ----------

    @classmethod
    def open(cls, phys=MCA_PHYS, size=MCA_SIZE, check_magic=True):
        """Abrir /dev/mem y mapear la región del MCA.

        Si la PL no está programada, la PRIMERA lectura mata el proceso con
        SIGBUS sin traceback (`API.fpga.fpga_state()` lo chequea antes).
        """
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        try:
            m = mmap.mmap(fd, size, mmap.MAP_SHARED,
                          mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)
        except Exception:
            os.close(fd)
            raise

        magic = _U32.unpack_from(m, R_MAGIC)[0]
        if check_magic and magic != MAGIC:
            m.close()
            os.close(fd)
            raise MCANotPresent(_sin_mca2(phys, magic))

        caps   = _U32.unpack_from(m, R_CAPS)[0]
        widths = _U32.unpack_from(m, R_WIDTHS)[0]
        return cls(m, fd, caps, widths & 0xFF, (widths >> 8) & 0xFF,
                   (widths >> 16) & 0xFF)

    def close(self):
        try:
            self._mmap.close()
        finally:
            os.close(self._fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- acceso /dev/mem ----------

    def w32(self, off, v):
        # Asignación por slice, NO struct.pack_into: pack_into hace un memset
        # previo que sobre memoria de dispositivo sale como stores de a byte,
        # y el esclavo AXI los rechaza (SIGBUS). Ver ref_py/mca.py.
        self._mmap[off:off + 4] = _U32.pack(v & 0xFFFFFFFF)

    def r32(self, off):
        return _U32.unpack_from(self._mmap, off)[0]

    def _read_words(self, offset, n):
        """n palabras de 32 b, DE A UNA: un memcpy sobre memoria de dispositivo
        emite ráfagas o accesos anchos, y en esta placa eso la reinicia (ver
        ref_py/mca.py, `_read_words`)."""
        unpack = _U32.unpack_from
        mem = self._mmap
        return np.array([unpack(mem, offset + 4 * i)[0] for i in range(n)],
                        dtype=np.uint32)

    def _r64(self, off_lo, off_hi):
        # LO primero: leerla congela la HI en un registro sombra del RTL.
        lo = self.r32(off_lo)
        hi = self.r32(off_hi)
        return (hi << 32) | lo

    # ---------- identificación ----------

    def tiene_features(self):
        """¿Tiene el bus de features? En el MCA2 viene siempre: lo dice el magic."""
        return self.r32(R_MAGIC) == MAGIC

    def exigir_features(self):
        if not self.tiene_features():
            raise MCANotPresent(
                f'el bitstream cargado no es el "MCA2": magic '
                f'{self.r32(R_MAGIC):#010x}')
        return True

    def identify(self, verbose=True):
        info = {
            'magic':       self.r32(R_MAGIC),
            'hist_h':      bool(self.caps & CAP_HIST_H),
            'hist_h_psd':  bool(self.caps & CAP_HIST_H_PSD),
            'trap':        bool(self.caps & CAP_TRAP),
            'h_aw':        self.h_aw,
            'h2_aw':       self.h2_aw,
            'psd_aw':      self.psd_aw,
            'n_channels':  1 << self.h_aw,
            'map2d_shape': (1 << self.h2_aw, 1 << self.psd_aw),
            'n_acc_max':   self.r32(R_N_ACC_MAX),
            'features':    self.tiene_features(),
            'n_formas_max': (self.r32(R_N_FORMAS) >> 8) & 7,
        }
        if verbose:
            print(f"MCA2 presente (magic {info['magic']:#010x})")
            print(f"  espectro 1D : {'si' if info['hist_h'] else 'NO'} "
                  f"({info['n_channels']} canales)")
            print(f"  mapa 2D     : {'si' if info['hist_h_psd'] else 'NO'} "
                  f"({info['map2d_shape'][0]} x {info['map2d_shape'][1]})")
            print(f"  ranuras     : {info['n_acc_max']}")
            print(f"  trapecio    : {'si' if info['trap'] else 'NO'}")
            print(f"  banco       : {info['n_formas_max']} formas")
        return info

    # ---------- configuración ----------

    def configure(self, baseline=0, bl_auto=False, bl_k=12, bl_holdoff=0,
                  amp_min=0, amp_max=0xFFFF, amp_src=0, q_shift=0, dec=1,
                  channel=0, gate_short=32, gate_long=384, n_acc=1,
                  pre_dly=16, trap_k=64, trap_m=32, trap_mq=0, trap_off=72,
                  trap_lw=4, trap_sh=7, verify=True,
                  sel_1d=None, sel_2dx=None, sel_2dy=None,
                  zoom_1d=(0, 0), zoom_2dx=(0, 0), zoom_2dy=(0, 0),
                  discr=None, keep_if_full=True, **banco):
        """Configurar el MCA2. Termina con run=0.

        La ventana la abre el disparo del multitrigger y la cierra la compuerta
        larga (`gate_long` muestras desde el disparo); la cola arranca en la
        corta. `n_acc` son las ranuras habilitadas (1 = la ventana única de
        antes). `pre_dly` retrasa la muestra respecto del disparo para que la
        ventana abra en el pie del pulso: 16 es lo medido en la placa con el
        pulso de la campaña y el disparo por pendiente L=8, G=4 (el reset del
        RTL, 11, es para pulsos de subida rápida).

        `amp_src`: 0 = muestra de pico, 1 = integral (`Q_total >> q_shift`).
        Escribirlo mueve los selectores de los ejes de amplitud, así que va
        antes que ellos. `bl_k`: la constante del seguidor de base, 2^bl_k
        muestras, tiene que ser MUCHO más larga que el pulso (ver ref_py/mca.py).

        El trapecio (`trap_*`, sólo con CAPS bit 2): subida `trap_k` y meseta
        `trap_m` en muestras, `trap_mq` = M*16 con M la constante polo-cero, y
        la ventana de 2^`trap_lw` muestras desde `trap_off` sobre la meseta,
        con escala `>> trap_sh`. Ver docs/mca/register_map_mca.md.

        El banco de trapecios (`**banco`): `n_formas`, `trap_antes`,
        `trap_despues` y `forma<f>_{k,m,off,lw,sh,antes,despues}` con f = 1..3.
        Sin pasarlos queda el reset del RTL, el MCA de un solo trapecio: configure
        es todo el estado. Ver `API.mca.mca_banco_config`.

        `discr` es None o `(feature, min, max[, externo])`; con intervalo
        interno, min > max es un error. Todo se valida ANTES de escribir.
        Con `verify` se releen ocho campos (RuntimeError si no coinciden).
        """
        # --- validación: nada se escribe si algo está mal --------------------
        b = _banco_de(banco)
        _validar_dec(dec)
        n_acc = int(n_acc)
        _validar_n_acc(n_acc, self.r32(R_N_ACC_MAX))
        _validar_pre_dly(pre_dly)
        _validar_trap_k(trap_k)
        if trap_k + trap_m > TRAP_KL_MAX:
            raise ValueError(
                f'trap_k + trap_m = {trap_k + trap_m}: la subida mas la meseta '
                f'no pueden pasar de {TRAP_KL_MAX} muestras')
        _validar_trap_mq(trap_mq)
        s1 = _feat_idx(sel_1d,  (F_INT if amp_src else F_PEAK), self)
        sx = _feat_idx(sel_2dx, (F_INT if amp_src else F_PEAK), self)
        sy = _feat_idx(sel_2dy, F_PSD, self)
        zooms = [(off, zk[0], zk[1]) for off, zk in (
            (R_ZOOM_1D, zoom_1d), (R_ZOOM_2DX, zoom_2dx), (R_ZOOM_2DY, zoom_2dy))]
        if discr is not None:
            d_feat, d_lo, d_hi = discr[0], int(discr[1]), int(discr[2])
            d_ext = bool(discr[3]) if len(discr) > 3 else False
            if d_lo > d_hi and not d_ext:
                raise ValueError(
                    f'discr con min ({d_lo}) > max ({d_hi}) e intervalo INTERNO: '
                    f'el conjunto es vacio y el MCA va a rechazar TODOS los '
                    f'eventos. Si lo que querias es cortar por fuera de un '
                    f'rango, pasa externo=True.')
            d_sel = _feat_idx(d_feat, F_PEAK, self)
        # El banco, con la compuerta. Se compara lo que el RTL va a ver: los
        # valores ya enmascarados.
        nf_max = (self.r32(R_N_FORMAS) >> 8) & 7
        n_formas = b['n_formas']
        _validar_n_formas(n_formas, nf_max)
        for f in range(1, N_FORMAS_TOPE):
            k, m = b[f'forma{f}_k'], b[f'forma{f}_m']
            _validar_forma_k(f, k)
            if k + m > TRAP_KL_MAX:
                raise ValueError(
                    f'forma{f}_k + forma{f}_m = {k + m}: la subida mas la meseta '
                    f'no pueden pasar de {TRAP_KL_MAX} muestras')
        usa_trap = (bool({s1, sx, sy} & {F_TRAP, F_FORMA})
                    or (discr is not None and d_sel in (F_TRAP, F_FORMA)))
        gl = gate_long & 0xFFFF
        for f in range(n_formas):
            k, off, lw, sh, de = ((trap_k, trap_off, trap_lw, trap_sh, b['trap_despues'])
                                  if f == 0 else
                                  tuple(b[f'forma{f}_{c}'] for c in ('k', 'off', 'lw',
                                                                     'sh', 'despues')))
            fin = (off & 0xFFFF) + TRAP_LAT + (1 << (lw & 7))
            if (n_formas > 1 or usa_trap) and fin > gl:
                raise ValueError(
                    f'forma {f}: la ventana termina en {fin} (off + {TRAP_LAT} + '
                    f'2^lw) y la compuerta es de {gl}: ninguna ranura la completa y '
                    f'F_TRAP vale cero. Subir gate_long o bajar off.')
            if (de & 0xFFFF) > gl:
                raise ValueError(
                    f'forma {f}: despues = {de & 0xFFFF} y la compuerta es de {gl}: '
                    f'F_DTNEXT solo ve los disparos de adentro de la ventana, asi '
                    f'que un vecino entre los dos no la descartaria.')
            if f > 0 and ((k & 0x3FF) << (trap_sh & 0x3F)
                          != (trap_k & 0x3FF) << (sh & 0x3F)):
                raise ValueError(
                    f'forma {f}: k = {k & 0x3FF} con sh = {sh & 0x3F} no da la '
                    f'ganancia de la forma 0 (k = {trap_k & 0x3FF}, sh = '
                    f'{trap_sh & 0x3F}): las formas con distinta ganancia parten el '
                    f'pico. k tiene que ser k0 por una potencia de 2, y sh correrse '
                    f'lo mismo.')

        # --- escritura ---------------------------------------------------------
        self.w32(R_CTRL, (1 << 8) if channel else 0)       # run=0, canal
        self.w32(R_BASELINE, baseline & 0x3FFF)
        self.w32(R_BL_CTRL,  ((bl_holdoff & 0xFFFF) << 16) |
                             ((bl_k & 0xF) << 4) | (1 if bl_auto else 0))
        self.w32(R_AMP_MIN,  amp_min & 0xFFFF)
        self.w32(R_AMP_MAX,  amp_max & 0xFFFF)
        self.w32(R_AMP_SRC,  ((q_shift & 0x1F) << 8) | (1 if amp_src else 0))
        self.w32(R_DEC,      dec & 0xFFFF)
        self.w32(R_GATE_LEN, ((gate_long & 0xFFFF) << 16) | (gate_short & 0xFFFF))
        self.w32(R_N_ACC,    n_acc & 0x7)
        self.w32(R_PRE_DLY,  pre_dly & 0x7F)
        self.w32(R_TRAP_KM,  ((trap_m & 0x3FF) << 16) | (trap_k & 0x3FF))
        self.w32(R_TRAP_MQ,  trap_mq & TRAP_MQ_MAX)
        self.w32(R_TRAP_MED, ((trap_sh & 0x3F) << 24) | ((trap_lw & 0x7) << 16)
                             | (trap_off & 0xFFFF))
        if nf_max > 0:
            self.w32(R_TRAP_UMBR, ((b['trap_despues'] & 0xFFFF) << 16)
                     | (b['trap_antes'] & 0xFFFF))
            for f in range(1, min(nf_max, N_FORMAS_TOPE)):
                base = R_FORMA1_KM + 16 * (f - 1)
                c = {x: b[f'forma{f}_{x}'] for x in ('k', 'm', 'off', 'lw', 'sh',
                                                     'antes', 'despues')}
                self.w32(base, ((c['m'] & 0x3FF) << 16) | (c['k'] & 0x3FF))
                self.w32(base + 4, ((c['sh'] & 0x3F) << 24) | ((c['lw'] & 0x7) << 16)
                         | (c['off'] & 0xFFFF))
                self.w32(base + 8, ((c['despues'] & 0xFFFF) << 16) | (c['antes'] & 0xFFFF))
            self.w32(R_N_FORMAS, n_formas & 0x7)
        # Después de R_AMP_SRC, que mueve sel_1d/sel_2dx: este registro gana.
        self.w32(R_HIST_SEL, (sy << 8) | (sx << 4) | s1)
        for off, z, k in zooms:
            self.w32(off, ((k & 0xFF) << 8) | (z & 0xF))
        if discr is None:
            self.w32(R_DISCR_CTRL, 0)
        else:
            self.w32(R_DISCR_MIN, d_lo & 0xFFFF)
            self.w32(R_DISCR_MAX, d_hi & 0xFFFF)
            self.w32(R_DISCR_CTRL, (d_sel << 4) | (2 if d_ext else 0) | 1)
        self.w32(R_HIST_CTRL, 1 if keep_if_full else 0)

        if verify:
            bad = []
            releer = [
                ('gate_short', R_GATE_LEN,  0, gate_short, 0xFFFF),
                ('gate_long',  R_GATE_LEN, 16, gate_long,  0xFFFF),
                ('n_acc',      R_N_ACC,     0, n_acc,      0x7),
                ('pre_dly',    R_PRE_DLY,   0, pre_dly,    0x7F),
                ('dec',        R_DEC,       0, dec,        0xFFFF),
                ('bl_k',       R_BL_CTRL,   4, bl_k,       0xF),
            ]
            # Sin el trapecio o sin el banco, sus registros no existen: leen cero.
            if self.caps & CAP_TRAP:
                releer.append(('trap_k', R_TRAP_KM, 0, trap_k, 0x3FF))
            if nf_max > 0:
                releer.append(('n_formas', R_N_FORMAS, 0, n_formas, 0x7))
            for name, off, sh, exp, mask in releer:
                got = (self.r32(off) >> sh) & mask
                if got != (exp & mask):
                    bad.append(f'{name}: escribi {exp}, lei {got}')
            if bad:
                raise RuntimeError('la relectura de config no coincide: ' +
                                   '; '.join(bad))

    @property
    def channel(self):
        return (self.r32(R_CTRL) >> 8) & 1

    # ---------- control de adquisición ----------

    def clear(self, timeout_s=1.0):
        """Borrar histogramas, contadores y relojes, y esperar el barrido."""
        self.w32(R_CTRL, self.r32(R_CTRL) | (1 << 1))      # autolimpiante
        t0 = time.time()
        while self.r32(R_STATUS) & 1:
            if time.time() - t0 > timeout_s:
                raise TimeoutError('el barrido de borrado no terminó')

    def start(self):
        self.w32(R_CTRL, self.r32(R_CTRL) | 1)

    def stop(self):
        self.w32(R_CTRL, self.r32(R_CTRL) & ~1)

    @property
    def running(self):
        return bool(self.r32(R_CTRL) & 1)

    def _esperar_vaciado(self, timeout_s=0.01):
        """Después de parar: las ranuras abiertas cierran y publican igual.

        Se espera a que `busy` (alguna ranura ocupada) baje, con un tope: una
        ventana dura `gate_long` muestras y la publicación 18 ciclos, así que
        10 ms sobran. Si no baja (un bitstream raro, un modelo de prueba) se
        sigue sin error: lo que se lea es lo que había.
        """
        t0 = time.time()
        while self.r32(R_STATUS) & 2:
            if time.time() - t0 > timeout_s:
                return False
        return True

    # ---------- lectura ----------

    def counters(self):
        """Contadores de eventos y relojes, en un dict.

        LOS RELOJES CAMBIARON DE SIGNIFICADO RESPECTO DEL MCA1:

          `livetime_s`       alguna ranura libre: el MCA puede abrir.
          `t_win_s`          sin ranura libre, todas midiendo.
          `t_div_s`          sin ranura libre, alguna esperando al publicador.
          `deadtime_real_s`  t_win + t_div: el tiempo muerto de verdad.
          `deadtime_s`       la OCUPACIÓN (alguna ranura ocupada). Con una
                             ranura coincide con el tiempo muerto; con varias
                             NO lo es: hay ciclos con ranuras midiendo en que
                             el módulo igual puede abrir.
          `t_ocup_s[j]`      tiempo con exactamente j ranuras ocupadas: la
                             medición directa del modelo M/D/N/N.

        `realtime = vetotime + t_win + t_div + livetime` vale ciclo a ciclo,
        pero leída con run=1 no cierra (cada acceso se lleva ~6 ciclos): para
        verificarla, `stop()` primero.
        """
        rt = self._r64(R_REALTIME_LO, R_REALTIME_HI)
        lt = self._r64(R_LIVETIME_LO, R_LIVETIME_HI)
        dt = self._r64(R_DEADTIME_LO, R_DEADTIME_HI)
        vt = self._r64(R_VETOTIME_LO, R_VETOTIME_HI)
        tw = self._r64(R_T_WIN_LO,   R_T_WIN_HI)
        td = self._r64(R_T_DIV_LO,   R_T_DIV_HI)
        tc = self._r64(R_T_CLEAR_LO, R_T_CLEAR_HI)
        n_max = self.r32(R_N_ACC_MAX)
        t_ocup = [self._r64(R_T_OCUP + 8 * j, R_T_OCUP + 8 * j + 4)
                  for j in range(min(n_max, N_ACC_TOPE) + 1)]
        st = self.r32(R_STATUS)
        periodos = self.r32(R_DEAD_PERIODS)
        pub_st = self.r32(R_PUB_STATE)
        hs = self.r32(R_HIST_STATUS)
        muerto = tw + td
        return {
            'total':     self.r32(R_CNT_TOTAL),
            'accepted':  self.r32(R_CNT_ACCEPTED),
            'rej_amp':   self.r32(R_CNT_REJ_AMP),
            'rej_psd':   self.r32(R_CNT_REJ_PSD),
            'pileup':    self.r32(R_CNT_PILEUP),
            'dropped':   self.r32(R_CNT_DROPPED),
            'rej_discr': self.r32(R_CNT_REJ_DISCR),
            'full_supp': self.r32(R_CNT_FULL_SUPP),
            'realtime_s': rt / FS_HZ,
            'livetime_s': lt / FS_HZ,
            'deadtime_s': dt / FS_HZ,           # ocupación
            'vetotime_s': vt / FS_HZ,
            't_win_s':   tw / FS_HZ,
            't_div_s':   td / FS_HZ,
            't_clear_s': tc / FS_HZ,
            'deadtime_real_s': muerto / FS_HZ,
            # --- período muerto: sin ranura libre ---
            'dead_periods':    periodos,
            'dead_len_max_s':  self.r32(R_DEAD_LEN_MAX) / FS_HZ,
            'dead_len_mean_s': muerto / periodos / FS_HZ if periodos else 0.0,
            'dead_ext':        self.r32(R_DEAD_EXT),
            'dead_ext_frac':   (self.r32(R_DEAD_EXT) / periodos
                                if periodos else 0.0),
            # --- atribución de arribos ---
            'cross':       self.r32(R_CNT_CROSS),
            'open':        self.r32(R_CNT_OPEN),
            'lost_active': self.r32(R_LOST_ACTIVE),
            'lost_veto':   self.r32(R_LOST_VETO),
            'windows':     self.r32(R_CNT_WIN),
            'trig_edges':  self.r32(R_CNT_TRIG),
            # --- las ranuras y la cola de publicación ---
            'pub_occ':      pub_st & 0xFF,
            'pub_occ_max':  (pub_st >> 8) & 0xFF,
            'last_win_id':  pub_st >> 16,
            'n_acc':        self.r32(R_N_ACC) & 0x7,
            'n_acc_max':    n_max,
            'pub_saturada': ((pub_st >> 8) & 0xFF) >= n_max > 0,
            # --- estado ---
            'clear_busy':     bool(st & 1),
            'busy':           bool(st & 2),
            'baseline_stale': bool(st & 4),
            'vetoed':         bool(st & 8),
            'puede_abrir':    bool(st & 32),
            'n_ocup':         (st >> 8) & 0x7,
            'full_1d':        bool(hs & 1),
            'full_2d':        bool(hs & 2),
            'trap_ok':        bool(self.r32(R_TRAP_MED) >> 31),
            't_ocup_s':       [t / FS_HZ for t in t_ocup],
        }

    def spectrum(self):
        """Espectro 1D, uint32[2^H_AW] (de a una palabra: ver _read_words)."""
        return self._read_words(APERTURE_H, 1 << self.h_aw)

    def map2d(self):
        """Mapa 2D (2^H2_AW, 2^PSD_AW): filas = eje X, columnas = eje Y."""
        if not self._has_2d:
            raise RuntimeError('este bitstream no tiene el motor 2D '
                               '(CAPS sin CAP_HIST_H_PSD)')
        n = 1 << (self.h2_aw + self.psd_aw)
        return self._read_words(APERTURE_2D, n).reshape(
            1 << self.h2_aw, 1 << self.psd_aw)

    def last_event(self):
        """Último evento publicado. Para depurar la configuración."""
        return {
            'amp':    self.r32(R_LAST_AMP) & 0xFFFF,
            'psd':    self.r32(R_LAST_PSD),
            'q_tot':  self.r32(R_LAST_QTOT),
            'q_tail': self.r32(R_LAST_QTAIL),
            'baseline': _sign14(self.r32(R_BASELINE_NOW)),
        }

    def acquire(self, seconds, clear_first=True):
        """Adquirir durante `seconds`: (espectro, mapa2d|None, contadores).

        El disparo lo tiene que haber armado el llamador
        (`multitrigger_armar_mca`): sin él no abre ninguna ventana.
        """
        if clear_first:
            self.stop()
            self.clear()
        self.start()
        time.sleep(seconds)
        self.stop()
        self._esperar_vaciado()
        m2d = self.map2d() if self._has_2d else None
        return self.spectrum(), m2d, self.counters()

    def acquire_chunks(self, seconds, chunk_s, on_chunk=None):
        """Adquirir `seconds` ACUMULANDO en el mismo histograma, en rebanadas.

        Se borra una sola vez; entre rebanadas, con el MCA parado y las
        ranuras vacías, se llama a `on_chunk(k)` (para cambiar el estímulo).
        """
        self.stop()
        self.clear()
        n = max(1, int(round(seconds / max(chunk_s, 1e-3))))
        for k in range(n):
            self.start()
            time.sleep(chunk_s)
            self.stop()
            self._esperar_vaciado()
            if on_chunk is not None and k < n - 1:
                on_chunk(k)
        m2d = self.map2d() if self._has_2d else None
        return self.spectrum(), m2d, self.counters()

    # ---------- auto-escalado ----------

    def autoscale_q_shift(self, target_channel=8000, seconds=0.5, **cfg):
        """Elige `q_shift` para que la integral caiga cerca de `target_channel`.

        Devuelve el `q_shift` elegido, o None si no hubo eventos.
        """
        if cfg:
            self.configure(**cfg)
        self.acquire(seconds)
        q = self.last_event()['q_tot']
        if q <= 0:
            return None
        shift = int(round(np.log2(max(q / max(target_channel, 1), 1e-9))))
        return int(np.clip(shift, 0, 31))


def _sin_mca2(phys, magic):
    if magic == MAGIC_MCA1:
        return (f'el MCA en {phys:#x} es el bitstream "MCA1" (magic '
                f'{magic:#010x}) y este software habla "MCA2". Para el MCA1: '
                f"mca_open(impl='py'), que usa la referencia congelada.")
    return (f'no hay MCA en {phys:#x}: magic={magic:#010x}, esperado '
            f'{MAGIC:#010x}. En el bitstream del scope ese slot es un '
            f'sys_bus_stub. Cargá mca_red_pitaya.bit.')


# =============================================================================
# API de configuración y estatus
# =============================================================================
#
# Un get/set por campo. Los registros que empaquetan varios campos se tocan por
# read-modify-write: el RTL los relee enteros, con ceros en los huecos.

# campo -> (offset, desplazamiento, máscara). El orden es el de mca_get_config
# y, por lo tanto, el de la metadata guardada.
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


def _leer_campo(h, nombre):
    off, sh, msk = _CAMPOS[nombre]
    return (h.r32(off) >> sh) & msk


def _escribir_campo(h, nombre, valor):
    off, sh, msk = _CAMPOS[nombre]
    palabra = h.r32(off) & ~(msk << sh)          # read-modify-write
    h.w32(off, palabra | ((int(valor) & msk) << sh))


# El banco de trapecios: un get/set por campo. Validan `n_formas` y los k, que el
# RTL recorta en silencio (k = 0 como 1; n_formas = 0 como 1 y arriba lo satura).
# Se generan de _CAMPOS_BANCO para no escribir 46 funciones de una linea.
_CAMPOS_BANCO = [n for n in _CAMPOS if n == 'n_formas' or n.startswith(('trap_antes',
                 'trap_despues', 'forma'))]


def _accesores_banco(nombre):
    def get(h):
        return _leer_campo(h, nombre)

    def set_(h, v):
        if nombre == 'n_formas':
            v = int(v)
            _validar_n_formas(v, (h.r32(R_N_FORMAS) >> 8) & 7)
        elif nombre in ('forma1_k', 'forma2_k', 'forma3_k'):
            v = int(v)
            _validar_forma_k(int(nombre[5]), v)
        _escribir_campo(h, nombre, v)
    get.__name__, set_.__name__ = f'mca_get_{nombre}', f'mca_set_{nombre}'
    return get, set_


for _n in _CAMPOS_BANCO:
    globals()[f'mca_get_{_n}'], globals()[f'mca_set_{_n}'] = _accesores_banco(_n)
del _n


# ---------- apertura y ciclo de vida ----------

def mca_open(phys=MCA_PHYS, size=MCA_SIZE, check_magic=True):
    return MCA.open(phys, size, check_magic)


def mca_close(h):
    h.close()


def mca_identify(h, verbose=True):
    return h.identify(verbose=verbose)


def mca_start(h):
    h.start()


def mca_stop(h):
    h.stop()


def mca_clear(h, timeout_s=1.0):
    """Borra histogramas, contadores y relojes; espera al barrido del RTL."""
    h.clear(timeout_s)


def mca_configure(h, **kw):
    """El bloque de configuración entero: la firma de `MCA.configure()`."""
    return h.configure(**kw)


# ---------- configuración: un get/set por campo ----------

def mca_get_baseline(h):      return _leer_campo(h, 'baseline')
def mca_set_baseline(h, v):   _escribir_campo(h, 'baseline', v)
def mca_get_bl_auto(h):       return bool(_leer_campo(h, 'bl_auto'))
def mca_set_bl_auto(h, v):    _escribir_campo(h, 'bl_auto', 1 if v else 0)
def mca_get_bl_k(h):          return _leer_campo(h, 'bl_k')
def mca_set_bl_k(h, v):       _escribir_campo(h, 'bl_k', v)
def mca_get_bl_holdoff(h):    return _leer_campo(h, 'bl_holdoff')
def mca_set_bl_holdoff(h, v): _escribir_campo(h, 'bl_holdoff', v)
def mca_get_amp_min(h):       return _leer_campo(h, 'amp_min')
def mca_set_amp_min(h, v):    _escribir_campo(h, 'amp_min', v)
def mca_get_amp_max(h):       return _leer_campo(h, 'amp_max')
def mca_set_amp_max(h, v):    _escribir_campo(h, 'amp_max', v)
def mca_get_amp_src(h):       return _leer_campo(h, 'amp_src')
def mca_set_amp_src(h, v):    _escribir_campo(h, 'amp_src', 1 if v else 0)
def mca_get_q_shift(h):       return _leer_campo(h, 'q_shift')
def mca_set_q_shift(h, v):    _escribir_campo(h, 'q_shift', v)
def mca_get_dec(h):           return _leer_campo(h, 'dec')
def mca_get_gate_short(h):    return _leer_campo(h, 'gate_short')
def mca_set_gate_short(h, v): _escribir_campo(h, 'gate_short', v)
def mca_get_gate_long(h):     return _leer_campo(h, 'gate_long')
def mca_set_gate_long(h, v):  _escribir_campo(h, 'gate_long', v)
def mca_get_channel(h):       return _leer_campo(h, 'channel')
def mca_set_channel(h, v):    _escribir_campo(h, 'channel', 1 if v else 0)
def mca_get_n_acc(h):         return _leer_campo(h, 'n_acc')
def mca_get_pre_dly(h):       return _leer_campo(h, 'pre_dly')
def mca_get_trap_k(h):        return _leer_campo(h, 'trap_k')
def mca_get_trap_m(h):        return _leer_campo(h, 'trap_m')
def mca_set_trap_m(h, v):     _escribir_campo(h, 'trap_m', v)
def mca_get_trap_mq(h):       return _leer_campo(h, 'trap_mq')
def mca_get_trap_off(h):      return _leer_campo(h, 'trap_off')
def mca_set_trap_off(h, v):   _escribir_campo(h, 'trap_off', v)
def mca_get_trap_lw(h):       return _leer_campo(h, 'trap_lw')
def mca_set_trap_lw(h, v):    _escribir_campo(h, 'trap_lw', v)
def mca_get_trap_sh(h):       return _leer_campo(h, 'trap_sh')
def mca_set_trap_sh(h, v):    _escribir_campo(h, 'trap_sh', v)


def mca_set_dec(h, v):
    _validar_dec(v)
    _escribir_campo(h, 'dec', v)


def mca_set_n_acc(h, v):
    """Ranuras habilitadas, 1..N_ACC. Se puede cambiar en caliente: vale desde
    el próximo disparo, y las que quedaron afuera terminan lo que medían."""
    v = int(v)
    _validar_n_acc(v, h.r32(R_N_ACC_MAX))
    _escribir_campo(h, 'n_acc', v)


def mca_set_pre_dly(h, v):
    """Retardo de la muestra respecto del disparo, en ciclos (0..127)."""
    v = int(v)
    _validar_pre_dly(v)
    _escribir_campo(h, 'pre_dly', v)


def mca_set_trap_k(h, v):
    """Subida del trapecio, en muestras. Escribirla reinicia su estado."""
    v = int(v)
    _validar_trap_k(v)
    _escribir_campo(h, 'trap_k', v)


def mca_set_trap_mq(h, v):
    """M*16, con M la constante polo-cero. Escribirla reinicia el trapecio."""
    v = int(v)
    _validar_trap_mq(v)
    _escribir_campo(h, 'trap_mq', v)


def mca_get_sel_1d(h):       return _leer_campo(h, 'sel_1d')
def mca_set_sel_1d(h, v):    _escribir_campo(h, 'sel_1d', _feat_idx(v, F_PEAK, h))
def mca_get_sel_2dx(h):      return _leer_campo(h, 'sel_2dx')
def mca_set_sel_2dx(h, v):   _escribir_campo(h, 'sel_2dx', _feat_idx(v, F_PEAK, h))
def mca_get_sel_2dy(h):      return _leer_campo(h, 'sel_2dy')
def mca_set_sel_2dy(h, v):   _escribir_campo(h, 'sel_2dy', _feat_idx(v, F_PSD, h))

def mca_get_zoom_1d_k(h):    return _leer_campo(h, 'zoom_1d_k')
def mca_set_zoom_1d_k(h, v): _escribir_campo(h, 'zoom_1d_k', v)
def mca_get_zoom_2dx_k(h):   return _leer_campo(h, 'zoom_2dx_k')
def mca_set_zoom_2dx_k(h, v): _escribir_campo(h, 'zoom_2dx_k', v)
def mca_get_zoom_2dy_k(h):   return _leer_campo(h, 'zoom_2dy_k')
def mca_set_zoom_2dy_k(h, v): _escribir_campo(h, 'zoom_2dy_k', v)

def mca_get_discr_en(h):     return bool(_leer_campo(h, 'discr_en'))
def mca_set_discr_en(h, v):  _escribir_campo(h, 'discr_en', 1 if v else 0)
def mca_get_discr_ext(h):    return bool(_leer_campo(h, 'discr_ext'))
def mca_set_discr_ext(h, v): _escribir_campo(h, 'discr_ext', 1 if v else 0)
def mca_get_discr_sel(h):    return _leer_campo(h, 'discr_sel')
def mca_set_discr_sel(h, v): _escribir_campo(h, 'discr_sel', _feat_idx(v, F_PEAK, h))
def mca_get_discr_min(h):    return _leer_campo(h, 'discr_min')
def mca_set_discr_min(h, v): _escribir_campo(h, 'discr_min', v)
def mca_get_discr_max(h):    return _leer_campo(h, 'discr_max')
def mca_set_discr_max(h, v): _escribir_campo(h, 'discr_max', v)

def mca_get_keep_if_full(h):    return bool(_leer_campo(h, 'keep_if_full'))
def mca_set_keep_if_full(h, v): _escribir_campo(h, 'keep_if_full', 1 if v else 0)


def _z_max(h_aw, amp_w=AMP_W):
    """Zoom máximo útil: la saturación de `mca_zoom.sv` (z se satura a FW-AW)."""
    return max(0, int(amp_w) - int(h_aw))


def mca_set_zoom_1d_z(h, v):
    _escribir_campo(h, 'zoom_1d_z', min(int(v), _z_max(h.h_aw)))


def mca_get_zoom_1d_z(h):    return _leer_campo(h, 'zoom_1d_z')


def mca_set_zoom_2dx_z(h, v):
    _escribir_campo(h, 'zoom_2dx_z', min(int(v), _z_max(h.h2_aw)))


def mca_get_zoom_2dx_z(h):   return _leer_campo(h, 'zoom_2dx_z')


def mca_set_zoom_2dy_z(h, v):
    _escribir_campo(h, 'zoom_2dy_z', min(int(v), _z_max(h.psd_aw)))


def mca_get_zoom_2dy_z(h):   return _leer_campo(h, 'zoom_2dy_z')


# ---------- estatus (sólo lectura) ----------

def mca_get_status(h):         return h.r32(R_STATUS)
def mca_get_running(h):        return bool(h.r32(R_CTRL) & 1)
def mca_get_clear_busy(h):     return bool(h.r32(R_STATUS) & 1)
def mca_get_busy(h):           return bool(h.r32(R_STATUS) & (1 << 1))
def mca_get_baseline_stale(h): return bool(h.r32(R_STATUS) & (1 << 2))
def mca_get_vetoed(h):         return bool(h.r32(R_STATUS) & (1 << 3))
def mca_get_puede_abrir(h):    return bool(h.r32(R_STATUS) & (1 << 5))
def mca_get_n_ocup(h):         return (h.r32(R_STATUS) >> 8) & 0x7
def mca_get_n_acc_max(h):      return h.r32(R_N_ACC_MAX)
def mca_get_trap_ok(h):        return bool(h.r32(R_TRAP_MED) >> 31)
def mca_get_n_formas_max(h):   return (h.r32(R_N_FORMAS) >> 8) & 7
def mca_get_umbr_ok(h):        return bool(h.r32(R_N_FORMAS) >> 31)


def mca_get_formas_ok(h):
    """La ventana de cada forma EN USO entra en la compuerta: una lista de bools."""
    w = h.r32(R_N_FORMAS)
    tope = min((w >> 8) & 7, N_FORMAS_TOPE) or 1
    n = min((w & 7) or 1, tope)
    return [bool(h.r32(R_TRAP_MED if f == 0 else R_FORMA1_MED + 16 * (f - 1)) >> 31)
            for f in range(n)]


def mca_get_baseline_now(h):   return _sign14(h.r32(R_BASELINE_NOW))
def mca_get_caps(h):           return h.r32(R_CAPS)


def mca_get_widths(h):
    w = h.r32(R_WIDTHS)
    return {'h_aw': w & 0xFF, 'h2_aw': (w >> 8) & 0xFF, 'psd_aw': (w >> 16) & 0xFF}


def mca_get_config(h):
    """Todos los campos de configuración, releídos del hardware."""
    return {n: _leer_campo(h, n) for n in _CAMPOS}


# =============================================================================
# API de lectura
# =============================================================================

def mca_read_histogram(h):
    return h.spectrum()


def mca_read_map2d(h):
    return h.map2d()


def mca_read_counters(h):
    return h.counters()


def mca_read_last_event(h):
    return h.last_event()


def mca_read_acquire(h, seconds, clear_first=True):
    return h.acquire(seconds, clear_first=clear_first)


def mca_read_acquire_chunks(h, seconds, chunk_s, on_chunk=None):
    return h.acquire_chunks(seconds, chunk_s, on_chunk=on_chunk)
