#!/usr/bin/env python3
"""Analizador Multicanal (MCA) en la PL: registros, lectura y guardado.

El MCA vive en el slot 7 del bus de sistema (base 0x4070_0000) del bitstream
`mca_red_pitaya.bit`. Acumula en hardware:

  - un espectro 1D de amplitud de pulso (16384 canales por defecto), y
  - un mapa 2D amplitud x factor de forma (PSD = Q_cola/Q_total).

El ARM lee espectros ya formados en vez de formas de onda crudas, que es lo que
saca la tasa de eventos del cuello de botella del bus.

Nomenclatura (ver API/README.md)::

    h = mca_open()
    mca_set_thr(h, 200)              # config y estatus: mca_get_* / mca_set_*
    mca_start(h)
    hist = mca_read_histogram(h)     # lectura:  mca_read_*
    mca_write_file_histogram(hist, 'esp.csv', meta=mca_get_metadata(h))

`class MCA` sigue existiendo y ES el handle que devuelve `mca_open()`: los
métodos delegan en las funciones de este módulo, así que el código viejo
(`testbench_mca.py`, 2137 líneas) sigue andando sin tocarlo.

Los helpers de análisis viven en `API/analisis.py`: son puros, no tocan
hardware, y así se prueban contra .npz guardados sin la placa.
"""

import ctypes
import json
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

MAGIC    = 0x4D434131           # "MCA1"

# --- identificación ---
R_MAGIC        = 0x000
R_CAPS         = 0x004
R_WIDTHS       = 0x008
# --- control y estado ---
R_CTRL         = 0x00C          # bit0 run, bit1 clear (autolimpiante), bit8 chan
R_STATUS       = 0x010          # bit0 clear_busy, bit1 feat_busy, bit2 bl_stale
# --- configuración ---
R_THR          = 0x014
R_HYST         = 0x018
R_BASELINE     = 0x01C
R_BL_CTRL      = 0x020          # {holdoff[31:16], k[7:4], auto[0]}
R_BASELINE_NOW = 0x024
R_MAXLEN       = 0x028
R_TAIL_DLY     = 0x02C
R_AMP_MIN      = 0x030
R_AMP_MAX      = 0x034
R_AMP_SRC      = 0x038          # {q_shift[12:8], amp_src[0]}
R_H_SHIFT      = 0x03C
R_H2_SHIFT     = 0x040
R_DEC          = 0x044
R_GATE_MODE    = 0x048     # bit0: 0 = ventana por histeresis, 1 = compuertas fijas
R_GATE_LEN     = 0x04C     # {larga[31:16], corta[15:0]} en muestras

# --- selector de feature por eje, y zoom (bus de features) ---
R_HIST_SEL     = 0x090     # {sel_2dy[11:8], sel_2dx[7:4], sel_1d[3:0]}
R_ZOOM_1D      = 0x094     # {k[15:8], z[3:0]}
R_ZOOM_2DX     = 0x0B8
R_ZOOM_2DY     = 0x0BC

# --- discriminador ---
R_DISCR_CTRL   = 0x098     # {sel[7:4], externo[1], enable[0]}
R_DISCR_MIN    = 0x09C
R_DISCR_MAX    = 0x0A0

# --- histograma lleno ---
R_HIST_CTRL     = 0x0A4    # bit0 keep_counter_if_full
R_HIST_STATUS   = 0x0A8    # bit0 full_1d, bit1 full_2d (pegajosos)
R_CNT_REJ_DISCR = 0x0AC
R_CNT_FULL_SUPP = 0x0B0

# Indices del bus de features. Son los localparam F_* de mca_pulse_feature.sv:
# un solo espacio de numeracion compartido por los tres ejes del histograma y
# por el discriminador, para que no puedan desincronizarse.
F_PEAK, F_INT, F_PSD, F_INVW, F_LEN, F_TRISE = 0, 1, 2, 3, 4, 5

def _feat_idx(f, por_defecto):
    """Acepta el nombre de una feature, su indice, o None.

    Se valida contra FEATURES en vez de dejar pasar cualquier entero: un indice
    fuera de rango apunta a una ranura RESERVADA, que vale cero, y el sintoma
    seria un espectro entero en el canal 0 sin ningun error. Es exactamente el
    tipo de falla silenciosa que conviene convertir en excepcion.
    """
    if f is None:
        return por_defecto
    if isinstance(f, str):
        if f not in FEATURES:
            raise ValueError(f'feature {f!r} desconocida; hay: '
                             f'{sorted(FEATURES)}')
        return FEATURES[f]
    f = int(f)
    if f not in FEATURES.values():
        raise ValueError(
            f'indice de feature {f} sin productor: las ranuras validas son '
            f'{sorted(FEATURES.values())} ({sorted(FEATURES)}). Las demas estan '
            f'reservadas y valen cero, asi que el espectro caeria entero en el '
            f'canal 0 sin avisar.')
    return f


FEATURES = {
    'pico':      F_PEAK,   # amplitud de pico, alineada a la izquierda
    'integral':  F_INT,    # Q_total >> q_shift
    'psd':       F_PSD,    # Q_cola/Q_total  -- DONDE esta la carga
    'ancho_inv': F_INVW,   # Pico/Q_total    -- ancho inverso: rechaza apilamiento
    'largo':     F_LEN,    # muestras de la ventana
    't_subida':  F_TRISE,  # muestras del disparo al pico
}
# --- contadores de eventos ---
R_CNT_TOTAL    = 0x050
R_CNT_ACCEPTED = 0x054
R_CNT_REJ_AMP  = 0x058
R_CNT_REJ_PSD  = 0x05C
R_CNT_PILEUP   = 0x060
R_CNT_DROPPED  = 0x064
# --- relojes (64 b; leer la palabra BAJA congela la ALTA) ---
R_REALTIME_LO  = 0x068
R_REALTIME_HI  = 0x06C
R_LIVETIME_LO  = 0x070
R_LIVETIME_HI  = 0x074
R_DEADTIME_LO  = 0x078
R_DEADTIME_HI  = 0x07C
# --- último evento (depuración) ---
R_LAST_AMP     = 0x080
R_LAST_PSD     = 0x084
R_LAST_QTOT    = 0x088
R_LAST_QTAIL   = 0x08C
# --- aperturas de histograma ---
APERTURE_H     = 0x10000        # espectro 1D
APERTURE_2D    = 0x20000        # amplitud x factor de forma

CAP_HIST_H     = 1 << 0
CAP_HIST_H_PSD = 1 << 1

FS_HZ          = 125e6          # muestreo del ADC
ADC_CNT_PER_V  = 8192           # cuentas por volt (mismo que multitrigger_utils)

_U32 = struct.Struct('<I')


class MCANotPresent(RuntimeError):
    """El bitstream cargado no tiene el MCA en el slot 7."""


# =============================================================================
# Driver
# =============================================================================

class MCA:
    """Acceso al MCA por /dev/mem.

    Uso típico::

        mca = MCA.open()
        mca.identify()
        mca.configure(thr=200, hyst=80, maxlen=512, tail_dly=8)
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
        SIGBUS sin traceback. `multitrigger_utils.fpga_state()` permite
        chequearlo antes; acá se valida el magic, que además distingue un
        bitstream viejo (sin MCA) de uno con MCA.
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
            raise MCANotPresent(
                f'no hay MCA en {phys:#x}: magic={magic:#010x}, esperado '
                f'{MAGIC:#010x}. En el bitstream del scope ese slot es un '
                'sys_bus_stub. Cargá mca_red_pitaya.bit.')

        caps   = _U32.unpack_from(m, R_CAPS)[0]
        widths = _U32.unpack_from(m, R_WIDTHS)[0]
        h_aw   = (widths >>  0) & 0xFF
        h2_aw  = (widths >>  8) & 0xFF
        psd_aw = (widths >> 16) & 0xFF
        return cls(m, fd, caps, h_aw, h2_aw, psd_aw)

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
        # el esclavo AXI de la PL no los reconoce y el puente GP0 tira un
        # external abort -> SIGBUS. Ver multitrigger_utils.w32 y
        # API/tests/placa/test_rw_dev_mem.py.
        self._mmap[off:off + 4] = _U32.pack(v & 0xFFFFFFFF)

    def r32(self, off):
        return _U32.unpack_from(self._mmap, off)[0]

    def _read_words(self, offset, n):
        """Lee n palabras de 32 bits DE A UNA. Devuelve un np.ndarray uint32.

        **NO usar np.frombuffer(...).copy(), ni slices grandes del mmap, ni
        struct.unpack_from con un formato largo.** Todos terminan en un memcpy,
        y sobre esta memoria de dispositivo el memcpy emite accesos anchos
        (LDRD/NEON) o en ráfaga. rtl/axi4_slave.sv:101-102 RECHAZA toda ráfaga
        y todo tamaño que no sea 2 o 4 bytes:

            rd_errorw = (ARLEN != 0) | ~((ARSIZE == 3'b010) | (ARSIZE == 3'b001))

        El error de AXI se propaga como *external abort*, y en esta placa no da
        SIGBUS sino que **REINICIA el sistema**. Verificado con
        API/tests/placa/diag_mca_hw.py: el paso `bulk` (copia numpy de 16384 palabras)
        reinicia la Pitaya; el paso `word` lee exactamente el mismo rango de a
        una y funciona.

        Costo: ~6.7 us por palabra, o sea ~110 ms por un espectro de 16384
        canales. Para un MCA es irrelevante — se lee una vez por adquisición,
        no una vez por evento.
        """
        unpack = _U32.unpack_from      # hoisted: es el lazo caliente
        mem = self._mmap
        return np.array([unpack(mem, offset + 4 * i)[0] for i in range(n)],
                        dtype=np.uint32)

    def _r64(self, off_lo, off_hi):
        # Leer la palabra BAJA congela la ALTA en un registro sombra del RTL,
        # así que este orden es obligatorio: al revés la lectura se parte.
        lo = self.r32(off_lo)
        hi = self.r32(off_hi)
        return (hi << 32) | lo

    # ---------- identificación ----------

    def tiene_features(self):
        """¿El bitstream cargado tiene el bus de features (zoom, discriminador)?

        **El magic NO alcanza para distinguirlo.** Sigue siendo "MCA1" en los dos
        bitstreams, y el RTL devuelve `32'h0` para toda dirección no mapeada y
        **ignora las escrituras sin dar error** (ver el `default` del decodificador
        en `mca_top.sv`). O sea que contra el bitstream viejo `configure(sel_1d=...,
        zoom_1d=...)` no falla: escribe al vacío y el MCA sigue histogrameando con
        la configuración anterior. Una campaña entera saldría plausible y sin
        relación con lo que se pidió.

        La prueba es escribir y releer `R_DISCR_MIN`, que existe sólo en el
        bitstream nuevo. Es INERTE: con el discriminador deshabilitado (su
        default) ese registro no afecta a nada, así que la sonda se puede correr
        en cualquier momento sin perturbar una medición. Se restaura igual.

        Se prueban dos patrones complementarios para no confundir "registro que
        existe" con un bus que devuelve siempre lo mismo.
        """
        # Atajo que además hace la sonda no perturbadora del todo: si el
        # discriminador figura HABILITADO, ese bit sólo pudo quedar puesto en un
        # bitstream donde el registro existe. Se contesta sin escribir nada, que
        # es lo que hay que hacer si hay una medición en curso con corte activo.
        if self.r32(R_DISCR_CTRL) & 0x1:
            return True
        previo = self.r32(R_DISCR_MIN)
        try:
            for patron in (0xA5A5, 0x5A5A):
                self.w32(R_DISCR_MIN, patron)
                if self.r32(R_DISCR_MIN) != patron:
                    return False
        finally:
            self.w32(R_DISCR_MIN, previo)
        return True

    def exigir_features(self):
        """Aborta si el bitstream cargado no es el del bus de features.

        Para el arranque de una campaña: más vale perder un segundo acá que una
        sesión de laboratorio midiendo contra el bitstream anterior.
        """
        if not self.tiene_features():
            raise MCANotPresent(
                'el bitstream cargado NO tiene el bus de features: el registro '
                f'{R_DISCR_MIN:#05x} no retiene lo que se le escribe. El magic es '
                '"MCA1" en los dos, así que esto no se detecta solo. '
                'Cargá el bitstream nuevo:\n'
                '  /opt/redpitaya/bin/fpgautil -b /root/mca_red_pitaya.bit.bin')
        return True

    def identify(self, verbose=True):
        info = {
            'magic':      self.r32(R_MAGIC),
            'hist_h':     bool(self.caps & CAP_HIST_H),
            'hist_h_psd': bool(self.caps & CAP_HIST_H_PSD),
            'h_aw':       self.h_aw,
            'h2_aw':      self.h2_aw,
            'psd_aw':     self.psd_aw,
            'n_channels': 1 << self.h_aw,
            'map2d_shape': (1 << self.h2_aw, 1 << self.psd_aw),
            'features':   self.tiene_features(),
        }
        if verbose:
            print(f"MCA presente (magic {info['magic']:#010x})")
            print(f"  espectro 1D : {'si' if info['hist_h'] else 'NO'} "
                  f"({info['n_channels']} canales)")
            print(f"  mapa 2D     : {'si' if info['hist_h_psd'] else 'NO'} "
                  f"({info['map2d_shape'][0]} x {info['map2d_shape'][1]})")
            print(f"  bus de features (zoom, discriminador): "
                  f"{'si' if info['features'] else 'NO — bitstream viejo'}")
        return info

    # ---------- configuración ----------

    def configure(self, thr=200, hyst=80, baseline=0, bl_auto=False, bl_k=12,
                  bl_holdoff=0, maxlen=1024, tail_dly=8, amp_min=0,
                  amp_max=0xFFFF, amp_src=0, q_shift=0, h_shift=0, h2_shift=0,
                  dec=1, channel=0, gate_mode=0, gate_short=32, gate_long=384,
                  verify=True,
                  # --- opciones nuevas (fase 1-3), TODAS al final -----------
                  # Van despues de `verify` a proposito: asi la firma vieja
                  # sigue siendo un PREFIJO exacto de la nueva y una llamada
                  # posicional existente no puede caer en el parametro
                  # equivocado. Lo verifica test_compat_api.
                  sel_1d=None, sel_2dx=None, sel_2dy=None,
                  zoom_1d=(0, 0), zoom_2dx=(0, 0), zoom_2dy=(0, 0),
                  discr=None, keep_if_full=True):
        """Configurar el MCA.

        amp_src: 0 = muestra de pico, 1 = integral de carga (Q_total>>q_shift).

        La integral promedia el ruido blanco como sigma/sqrt(N) y es inmune al
        jitter de muestreo del pico, así que es la que justifica un eje de
        16384 canales. Con la muestra de pico la amplitud sale de UNA muestra y
        el muestreo casi nunca cae en el máximo real, lo que ensancha el
        fotopico por razones instrumentales. Alternar entre las dos sobre el
        mismo estímulo ES el experimento que mide esa contribución.

        tail_dly tiene que ser >= 1: con 0 la cola integra desde el arranque y
        Q_cola == Q_total, que el RTL rechaza (saturaría el eje de forma).

        **bl_k: la constante del seguidor de base tiene que ser MUCHO más larga
        que el pulso.** La constante es 2^bl_k muestras (a 125 MSPS, 2^k * 8 ns).
        Si es comparable al pulso, el seguidor lo persigue y lo borra: la señal
        nunca cruza el umbral y no se detecta NADA. Medido en la placa con un
        pulso de 62 us:

            bl_k= 6  ->  tau=0.5 us   ->      0 eventos   <-- se come el pulso
            bl_k= 9  ->  tau=4.1 us   ->   2002 eventos
            bl_k=12  ->  tau=32.8 us  ->   2001 eventos
            bl_k=15  ->  tau=262 us   ->   2002 eventos

        Regla práctica: tau_base >= 100x la duración del pulso. Si hay dudas,
        usar base FIJA (bl_auto=False), que es inmune a este efecto.
        """
        if tail_dly < 1:
            raise ValueError('tail_dly tiene que ser >= 1 (ver docstring)')
        if dec < 1:
            raise ValueError('dec tiene que ser >= 1')

        self.w32(R_THR,      thr      & 0x3FFF)
        self.w32(R_HYST,     hyst     & 0x3FFF)
        self.w32(R_BASELINE, baseline & 0x3FFF)
        self.w32(R_BL_CTRL,  ((bl_holdoff & 0xFFFF) << 16) |
                             ((bl_k & 0xF) << 4) | (1 if bl_auto else 0))
        self.w32(R_MAXLEN,   maxlen   & 0xFFFF)
        self.w32(R_TAIL_DLY, tail_dly & 0xFFFF)
        self.w32(R_AMP_MIN,  amp_min  & 0xFFFF)
        self.w32(R_AMP_MAX,  amp_max  & 0xFFFF)
        self.w32(R_AMP_SRC,  ((q_shift & 0x1F) << 8) | (1 if amp_src else 0))
        self.w32(R_H_SHIFT,  h_shift  & 0x1F)
        self.w32(R_H2_SHIFT, h2_shift & 0x1F)
        self.w32(R_DEC,      dec      & 0xFFFF)
        self.w32(R_GATE_MODE, 1 if gate_mode else 0)
        self.w32(R_GATE_LEN, ((gate_long & 0xFFFF) << 16) | (gate_short & 0xFFFF))

        # --- que feature alimenta cada eje ---------------------------------
        # Los defaults reproducen el comportamiento historico: eje 1D con el
        # estimador que elige amp_src, eje X del 2D igual, eje Y el factor de
        # forma. Se escribe DESPUES de R_AMP_SRC porque este registro gana.
        s1 = _feat_idx(sel_1d,  (F_INT if amp_src else F_PEAK))
        sx = _feat_idx(sel_2dx, (F_INT if amp_src else F_PEAK))
        sy = _feat_idx(sel_2dy, F_PSD)
        self.w32(R_HIST_SEL, (sy << 8) | (sx << 4) | s1)

        # --- zoom por eje: (z, k) ------------------------------------------
        for off, zk in ((R_ZOOM_1D, zoom_1d), (R_ZOOM_2DX, zoom_2dx),
                        (R_ZOOM_2DY, zoom_2dy)):
            z, k = zk
            self.w32(off, ((k & 0xFF) << 8) | (z & 0xF))

        # --- discriminador --------------------------------------------------
        # `discr=None` lo deja apagado, que es el default y deja pasar todo.
        if discr is None:
            self.w32(R_DISCR_CTRL, 0)
        else:
            feat, lo, hi = discr[0], int(discr[1]), int(discr[2])
            externo = bool(discr[3]) if len(discr) > 3 else False
            if lo > hi and not externo:
                raise ValueError(
                    f'discr con min ({lo}) > max ({hi}) e intervalo INTERNO: '
                    f'el conjunto es vacio y el MCA va a rechazar TODOS los '
                    f'eventos. Si lo que querias es cortar por fuera de un '
                    f'rango, pasa externo=True.')
            self.w32(R_DISCR_MIN, lo & 0xFFFF)
            self.w32(R_DISCR_MAX, hi & 0xFFFF)
            self.w32(R_DISCR_CTRL,
                     (_feat_idx(feat, F_PEAK) << 4) | (2 if externo else 0) | 1)

        self.w32(R_HIST_CTRL, 1 if keep_if_full else 0)
        self.w32(R_CTRL,     (1 << 8) if channel else 0)   # run=0, canal

        if verify:
            bad = []
            for name, off, exp, mask in (
                ('thr',      R_THR,      thr,      0x3FFF),
                ('hyst',     R_HYST,     hyst,     0x3FFF),
                ('maxlen',   R_MAXLEN,   maxlen,   0xFFFF),
                ('tail_dly', R_TAIL_DLY, tail_dly, 0xFFFF),
                ('dec',      R_DEC,      dec,      0xFFFF),
                ('h_shift',  R_H_SHIFT,  h_shift,  0x1F),
                ('gate_mode', R_GATE_MODE, 1 if gate_mode else 0, 0x1),
            ):
                got = self.r32(off) & mask
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
        """Borrar histogramas, contadores y relojes, y esperar el barrido.

        El barrido recorre 2^H_AW bins (131 us con 16384). Durante ese lapso el
        puerto de lectura sigue vivo, así que el bus no se cuelga, pero los
        eventos que lleguen se descartan y se cuentan en cnt_dropped.
        """
        ctrl = self.r32(R_CTRL)
        self.w32(R_CTRL, ctrl | (1 << 1))          # clear autolimpiante
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

    # ---------- lectura ----------

    def counters(self):
        """Contadores de eventos y relojes, en un dict.

        `livetime_s` es el tiempo en que el MCA pudo aceptar eventos;
        `deadtime_s` el que estuvo ocupado. La suma da `realtime_s`.
        """
        rt = self._r64(R_REALTIME_LO, R_REALTIME_HI)
        lt = self._r64(R_LIVETIME_LO, R_LIVETIME_HI)
        dt = self._r64(R_DEADTIME_LO, R_DEADTIME_HI)
        st = self.r32(R_STATUS)
        return {
            'total':     self.r32(R_CNT_TOTAL),
            'accepted':  self.r32(R_CNT_ACCEPTED),
            'rej_amp':   self.r32(R_CNT_REJ_AMP),
            'rej_psd':   self.r32(R_CNT_REJ_PSD),
            'pileup':    self.r32(R_CNT_PILEUP),
            'dropped':   self.r32(R_CNT_DROPPED),
            'realtime_s': rt / FS_HZ,
            'livetime_s': lt / FS_HZ,
            'deadtime_s': dt / FS_HZ,
            'clear_busy':     bool(st & 1),
            'busy':           bool(st & 2),
            'baseline_stale': bool(st & 4),
        }

    def spectrum(self):
        """Espectro 1D como uint32 de 2^H_AW canales (~110 ms, ver _read_words).

        Los bins son contadores SIN signo: a diferencia del buffer del scope
        no hay que extender el signo de 14 a 16 bits.
        """
        return self._read_words(APERTURE_H, 1 << self.h_aw)

    def map2d(self):
        """Mapa 2D con forma (2^H2_AW, 2^PSD_AW): filas = amplitud, columnas = forma."""
        if not self._has_2d:
            raise RuntimeError('este bitstream no tiene el motor 2D '
                               '(CAPS sin CAP_HIST_H_PSD)')
        n = 1 << (self.h2_aw + self.psd_aw)
        return self._read_words(APERTURE_2D, n).reshape(
            1 << self.h2_aw, 1 << self.psd_aw)

    def last_event(self):
        """Último evento procesado. Para depurar la configuración de umbrales."""
        return {
            'amp':    self.r32(R_LAST_AMP) & 0xFFFF,
            'psd':    self.r32(R_LAST_PSD),
            'q_tot':  self.r32(R_LAST_QTOT),
            'q_tail': self.r32(R_LAST_QTAIL),
            'baseline': _sign14(self.r32(R_BASELINE_NOW)),
        }

    def acquire(self, seconds, clear_first=True):
        """Adquirir durante `seconds`. Devuelve (espectro, mapa2d|None, contadores)."""
        if clear_first:
            self.stop()
            self.clear()
        self.start()
        time.sleep(seconds)
        self.stop()
        m2d = self.map2d() if self._has_2d else None
        return self.spectrum(), m2d, self.counters()

    def acquire_chunks(self, seconds, chunk_s, on_chunk=None):
        """Adquirir `seconds` ACUMULANDO en el mismo histograma.

        A diferencia de `acquire`, el borrado se hace una sola vez al principio
        y el histograma sigue creciendo entre trozos. Entre trozo y trozo llama
        a `on_chunk(k)`, que es donde el llamador puede cambiar el estímulo —
        por ejemplo recargar el ARB con una semilla nueva para que la DNL vea
        amplitudes distintas en vez de las mismas 128 repetidas.

        El MCA queda PARADO durante `on_chunk`, así que el tiempo que tarde el
        estímulo en recargarse no cuenta como tiempo vivo.
        """
        self.stop()
        self.clear()
        n = max(1, int(round(seconds / max(chunk_s, 1e-3))))
        for k in range(n):
            self.start()
            time.sleep(chunk_s)
            self.stop()
            if on_chunk is not None and k < n - 1:
                on_chunk(k)
        m2d = self.map2d() if self._has_2d else None
        return self.spectrum(), m2d, self.counters()

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
        self.acquire(seconds)
        q = self.last_event()['q_tot']
        if q <= 0:
            return None
        shift = int(round(np.log2(max(q / max(target_channel, 1), 1e-9))))
        return int(np.clip(shift, 0, 31))

    def autoscale_h2_shift(self, seconds=0.5, margin=1.3, **cfg):
        """Elige `h2_shift` para que la amplitud entre en las 2^H2_AW rebanadas.

        Sin esto, todos los eventos caen en una sola rebanada del mapa 2D y la
        FOM por rebanada de energía no se puede calcular (da nan en todas menos
        una). `margin` deja aire por encima de la amplitud observada.

        Devuelve el `h2_shift` elegido (o None si no se detectaron eventos).
        """
        if cfg:
            self.configure(**cfg)
        self.acquire(seconds)
        amp = self.last_event()['amp']
        if amp <= 0:
            return None
        # amp >> h2_shift tiene que entrar en 2^h2_aw bins
        shift = int(np.ceil(np.log2(max(amp * margin / (1 << self.h2_aw), 1.0))))
        return int(np.clip(shift, 0, 31))


def _sign14(v):
    v &= 0x3FFF
    return v - 0x4000 if v & 0x2000 else v

# =============================================================================
# API de configuración y estatus
# =============================================================================
#
# Un get/set por campo de registro. Los registros que empaquetan varios campos
# (R_BL_CTRL, R_AMP_SRC, R_GATE_LEN) se tocan por read-modify-write, que es
# seguro porque el RTL los relee enteros: mca_top.sv:340,346,351 devuelven el
# valor escrito, con ceros en los huecos. Sin eso, poner `bl_k` borraría
# `bl_holdoff` en silencio.

# campo -> (offset, desplazamiento, máscara)
_CAMPOS = {
    'thr':        (R_THR,       0, 0x3FFF),
    'hyst':       (R_HYST,      0, 0x3FFF),
    'baseline':   (R_BASELINE,  0, 0x3FFF),
    'bl_auto':    (R_BL_CTRL,   0, 0x1),
    'bl_k':       (R_BL_CTRL,   4, 0xF),
    'bl_holdoff': (R_BL_CTRL,  16, 0xFFFF),
    'maxlen':     (R_MAXLEN,    0, 0xFFFF),
    'tail_dly':   (R_TAIL_DLY,  0, 0xFFFF),
    'amp_min':    (R_AMP_MIN,   0, 0xFFFF),
    'amp_max':    (R_AMP_MAX,   0, 0xFFFF),
    'amp_src':    (R_AMP_SRC,   0, 0x1),
    'q_shift':    (R_AMP_SRC,   8, 0x1F),
    'h_shift':    (R_H_SHIFT,   0, 0x1F),
    'h2_shift':   (R_H2_SHIFT,  0, 0x1F),
    'dec':        (R_DEC,       0, 0xFFFF),
    'gate_mode':  (R_GATE_MODE, 0, 0x1),
    'gate_short': (R_GATE_LEN,  0, 0xFFFF),
    'gate_long':  (R_GATE_LEN, 16, 0xFFFF),
    'channel':    (R_CTRL,      8, 0x1),
}


def _leer_campo(h, nombre):
    off, sh, msk = _CAMPOS[nombre]
    return (h.r32(off) >> sh) & msk


def _escribir_campo(h, nombre, valor):
    off, sh, msk = _CAMPOS[nombre]
    palabra = h.r32(off) & ~(msk << sh)          # read-modify-write
    h.w32(off, palabra | ((int(valor) & msk) << sh))


# ---------- apertura y ciclo de vida ----------

def mca_open(phys=MCA_PHYS, size=MCA_SIZE, check_magic=True):
    """Abre /dev/mem y mapea el MCA. Devuelve el handle que usan las demás."""
    return MCA.open(phys, size, check_magic)


def mca_close(h):
    h.close()


def mca_identify(h, verbose=True):
    return h.identify(verbose=verbose)


def mca_start(h):
    """Arranca la acumulación (bit run de R_CTRL)."""
    h.w32(R_CTRL, h.r32(R_CTRL) | 1)


def mca_stop(h):
    h.w32(R_CTRL, h.r32(R_CTRL) & ~1)


def mca_clear(h, timeout_s=1.0):
    """Borra histogramas, contadores y relojes; espera al barrido del RTL."""
    h.w32(R_CTRL, h.r32(R_CTRL) | (1 << 1))      # autoclear en el RTL
    t0 = time.time()
    while h.r32(R_STATUS) & 1:                   # clear_busy
        if time.time() - t0 > timeout_s:
            raise TimeoutError('el clear del MCA no terminó')
        time.sleep(0.001)


# ---------- configuración: un get/set por campo ----------

def mca_get_thr(h):          return _leer_campo(h, 'thr')
def mca_set_thr(h, v):       _escribir_campo(h, 'thr', v)
def mca_get_hyst(h):         return _leer_campo(h, 'hyst')
def mca_set_hyst(h, v):      _escribir_campo(h, 'hyst', v)
def mca_get_baseline(h):     return _leer_campo(h, 'baseline')
def mca_set_baseline(h, v):  _escribir_campo(h, 'baseline', v)
def mca_get_bl_auto(h):      return bool(_leer_campo(h, 'bl_auto'))
def mca_set_bl_auto(h, v):   _escribir_campo(h, 'bl_auto', 1 if v else 0)
def mca_get_bl_k(h):         return _leer_campo(h, 'bl_k')
def mca_get_bl_holdoff(h):   return _leer_campo(h, 'bl_holdoff')
def mca_set_bl_holdoff(h, v): _escribir_campo(h, 'bl_holdoff', v)
def mca_get_maxlen(h):       return _leer_campo(h, 'maxlen')
def mca_set_maxlen(h, v):    _escribir_campo(h, 'maxlen', v)
def mca_get_tail_dly(h):     return _leer_campo(h, 'tail_dly')
def mca_get_amp_min(h):      return _leer_campo(h, 'amp_min')
def mca_set_amp_min(h, v):   _escribir_campo(h, 'amp_min', v)
def mca_get_amp_max(h):      return _leer_campo(h, 'amp_max')
def mca_set_amp_max(h, v):   _escribir_campo(h, 'amp_max', v)
def mca_get_amp_src(h):      return _leer_campo(h, 'amp_src')
def mca_set_amp_src(h, v):   _escribir_campo(h, 'amp_src', 1 if v else 0)
def mca_get_q_shift(h):      return _leer_campo(h, 'q_shift')
def mca_set_q_shift(h, v):   _escribir_campo(h, 'q_shift', v)
def mca_get_h_shift(h):      return _leer_campo(h, 'h_shift')
def mca_set_h_shift(h, v):   _escribir_campo(h, 'h_shift', v)
def mca_get_h2_shift(h):     return _leer_campo(h, 'h2_shift')
def mca_set_h2_shift(h, v):  _escribir_campo(h, 'h2_shift', v)
def mca_get_gate_mode(h):    return _leer_campo(h, 'gate_mode')
def mca_set_gate_mode(h, v): _escribir_campo(h, 'gate_mode', 1 if v else 0)
def mca_get_gate_short(h):   return _leer_campo(h, 'gate_short')
def mca_set_gate_short(h, v): _escribir_campo(h, 'gate_short', v)
def mca_get_gate_long(h):    return _leer_campo(h, 'gate_long')
def mca_set_gate_long(h, v): _escribir_campo(h, 'gate_long', v)
def mca_get_channel(h):      return _leer_campo(h, 'channel')
def mca_set_channel(h, v):   _escribir_campo(h, 'channel', 1 if v else 0)


def mca_set_bl_k(h, v):
    """Constante del seguidor de base: tau = 2^v muestras (8 ns cada una).

    Tiene que ser MUCHO más larga que el pulso. Si es comparable, el seguidor
    persigue el pulso y lo borra: la señal nunca cruza el umbral y no se
    detecta NADA. Medido en la placa con un pulso de 62 us, bl_k=6 (tau=0.5 us)
    da 0 eventos y bl_k>=9 da los 2000 esperados. Regla: tau >= 100x el pulso.
    """
    _escribir_campo(h, 'bl_k', v)


def mca_set_tail_dly(h, v):
    """Retardo de la compuerta de cola. Tiene que ser >= 1: con 0 la cola
    integra desde el arranque y Q_cola == Q_total, que el RTL rechaza."""
    if v < 1:
        raise ValueError('tail_dly tiene que ser >= 1 (ver docstring)')
    _escribir_campo(h, 'tail_dly', v)


def mca_set_dec(h, v):
    if v < 1:
        raise ValueError('dec tiene que ser >= 1')
    _escribir_campo(h, 'dec', v)


def mca_get_dec(h):
    return _leer_campo(h, 'dec')


def mca_configure(h, **kw):
    """Escribe el bloque de configuración entero. Firma idéntica a
    `MCA.configure()`, que es la que usa `testbench_mca.py`."""
    return h.configure(**kw)


# ---------- estatus (sólo lectura) ----------

def mca_get_status(h):       return h.r32(R_STATUS)
def mca_get_running(h):      return bool(h.r32(R_CTRL) & 1)
def mca_get_clear_busy(h):   return bool(h.r32(R_STATUS) & 1)
def mca_get_baseline_stale(h): return bool(h.r32(R_STATUS) & (1 << 2))
def mca_get_baseline_now(h): return _sign14(h.r32(R_BASELINE_NOW))
def mca_get_caps(h):         return h.r32(R_CAPS)


def mca_get_widths(h):
    """Anchos de dirección de los histogramas, como los publica el RTL."""
    w = h.r32(R_WIDTHS)
    return {'h_aw': w & 0xFF, 'h2_aw': (w >> 8) & 0xFF, 'psd_aw': (w >> 16) & 0xFF}


def mca_get_config(h):
    """Todos los campos de configuración, releídos del hardware."""
    return {n: _leer_campo(h, n) for n in _CAMPOS}


def mca_get_metadata(h):
    """Config + contadores + geometría + sello de tiempo: lo que acompaña a un
    espectro guardado para que el fichero se entienda solo dentro de un año."""
    meta = {'schema_version': SCHEMA_VERSION_MCA}
    meta.update(mca_get_config(h))
    meta.update(mca_get_widths(h))
    meta.update(mca_read_counters(h))
    meta['n_channels'] = 1 << h.h_aw
    meta['fs_hz'] = FS_HZ
    meta['adc_cnt_per_V'] = ADC_CNT_PER_V
    meta['t_wall'] = time.time()
    return meta


# =============================================================================
# API de lectura
# =============================================================================

def mca_read_histogram(h):
    """Espectro 1D de amplitud. uint32[2**h_aw].

    ~110 ms por espectro de 16384 canales: se lee DE A UNA palabra a propósito
    (ver MCA._read_words). No es optimizable con un slice.
    """
    return h.spectrum()


def mca_read_map2d(h):
    """Mapa 2D amplitud x factor de forma. uint32[2**h2_aw, 2**psd_aw]."""
    return h.map2d()


def mca_read_counters(h):
    return h.counters()


def mca_read_last_event(h):
    """Rasgos del último evento procesado: para depurar umbral y compuertas."""
    return h.last_event()


def mca_read_acquire(h, seconds, clear_first=True):
    """Una adquisición temporizada -> (histograma, mapa2d|None, contadores)."""
    return h.acquire(seconds, clear_first=clear_first)


def mca_read_acquire_chunks(h, seconds, chunk_s, on_chunk=None):
    """Acumula `seconds` en el MISMO histograma, llamando a `on_chunk` por
    rebanada. Sirve para ver la deriva sin cortar la acumulación."""
    return h.acquire_chunks(seconds, chunk_s, on_chunk=on_chunk)


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

SCHEMA_VERSION_MCA = 1


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
