#!/usr/bin/env python3
"""Driver del Analizador Multicanal (MCA) en la PL + helpers de análisis.

El MCA vive en el slot 7 del bus de sistema (base 0x4070_0000) del bitstream
`mca_red_pitaya.bit`. Acumula en hardware:

  - un espectro 1D de amplitud de pulso (16384 canales por defecto), y
  - un mapa 2D amplitud x factor de forma (PSD = Q_cola/Q_total).

El ARM lee espectros ya formados en vez de formas de onda crudas, que es lo que
saca la tasa de eventos del cuello de botella del bus.

Separación de responsabilidades (igual que multitrigger_utils.py /
testbench_multitrigger.py): acá va el acceso al hardware y los helpers de
análisis PUROS; la campaña de caracterización va en testbench_mca.py.

Los helpers de análisis no tocan hardware a propósito: así se pueden probar
contra archivos .npz guardados, sin la placa.
"""

import ctypes
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
        # tests/test_rw_dev_mem.py.
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
        tests/diag_mca_hw.py: el paso `bulk` (copia numpy de 16384 palabras)
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
        }
        if verbose:
            print(f"MCA presente (magic {info['magic']:#010x})")
            print(f"  espectro 1D : {'si' if info['hist_h'] else 'NO'} "
                  f"({info['n_channels']} canales)")
            print(f"  mapa 2D     : {'si' if info['hist_h_psd'] else 'NO'} "
                  f"({info['map2d_shape'][0]} x {info['map2d_shape'][1]})")
        return info

    # ---------- configuración ----------

    def configure(self, thr=200, hyst=80, baseline=0, bl_auto=False, bl_k=12,
                  bl_holdoff=0, maxlen=1024, tail_dly=8, amp_min=0,
                  amp_max=0xFFFF, amp_src=0, q_shift=0, h_shift=0, h2_shift=0,
                  dec=1, channel=0, gate_mode=0, gate_short=32, gate_long=384,
                  verify=True):
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
# Helpers de análisis (funciones puras: no tocan hardware)
# =============================================================================

def gauss_fit_peak(spec, lo=None, hi=None):
    """Ajuste gaussiano a un pico del espectro.

    Devuelve dict con centroide, sigma, fwhm, area y resolucion_pct.

    El FWHM del pico de un PULSER (amplitud fija) ES la contribución de ruido
    electrónico de la cadena: se resta en cuadratura del FWHM total para
    separar detector de electrónica.
    """
    spec = np.asarray(spec, dtype=float)
    lo = 0 if lo is None else int(lo)
    hi = len(spec) if hi is None else int(hi)
    x = np.arange(lo, hi, dtype=float)
    y = spec[lo:hi]
    if y.sum() <= 0:
        # Ventana vacía: es un resultado posible (todo rechazado, umbral mal
        # puesto, generador apagado). Se devuelve NaN en vez de romper, para que
        # una campaña de varios puntos no se caiga por uno malo.
        return {'centroid': float('nan'), 'sigma': float('nan'),
                'fwhm': float('nan'), 'area': 0.0,
                'resolution_pct': float('nan'), 'empty': True}

    # Semilla por momentos, después refinamiento gaussiano por mínimos
    # cuadrados sobre log(y) (sólo con los bins de estadística suficiente).
    c0 = float((x * y).sum() / y.sum())
    s0 = float(np.sqrt(max((y * (x - c0) ** 2).sum() / y.sum(), 1e-9)))

    m = y > max(3.0, 0.05 * y.max())
    if m.sum() >= 4:
        # log(A) - (x-c)^2/(2 s^2)  ->  polinomio de grado 2 en x
        p = np.polyfit(x[m], np.log(y[m]), 2, w=np.sqrt(y[m]))
        if p[0] < 0:
            s0 = float(np.sqrt(-1.0 / (2.0 * p[0])))
            c0 = float(-p[1] / (2.0 * p[0]))

    # Un pico que cae en UN solo canal es un resultado legítimo, no un error:
    # pasa cuando el estimador es tan reproducible que no hay dispersión (es el
    # caso de la integral de carga con un pulser sintético). El ancho se acota
    # entonces por el propio bin, que es el límite de lo que se puede resolver.
    n_pobl = int((y > 0).sum())
    if n_pobl <= 1 or not np.isfinite(s0) or s0 <= 0:
        s0 = 1.0 / np.sqrt(12.0)        # desvío de una distribución uniforme de 1 bin

    fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0)) * s0
    return {
        'centroid': c0,
        'sigma':    s0,
        'fwhm':     fwhm,
        'area':     float(y.sum()),
        'resolution_pct': 100.0 * fwhm / c0 if c0 else float('nan'),
        'bins_poblados': n_pobl,
        'empty': False,
    }


def energy_calibration(centroids, energies):
    """Ajuste lineal canal = a*E + b. Devuelve (a, b, residuos, inl_pct_fs)."""
    c = np.asarray(centroids, dtype=float)
    e = np.asarray(energies, dtype=float)
    a, b = np.polyfit(e, c, 1)
    resid = c - (a * e + b)
    fs = c.max() - c.min()
    inl = 100.0 * np.abs(resid).max() / fs if fs else float('nan')
    return a, b, resid, inl


def dnl(spec, lo=None, hi=None, smooth=64, strict=True, max_empty_frac=0.01):
    """No linealidad diferencial a partir de un espectro de *sliding pulser*.

    Con amplitud uniformemente aleatoria todos los canales deberían recibir la
    misma cuenta; la desviación relativa es la DNL. Spec típica: <±1%.

    Ojo: mide el ADC y el estimador de amplitud, no el binning. La DNL del
    binning digital es exactamente cero por construcción (el bin es un
    desplazamiento a la derecha de un entero, todos los canales igual de anchos).

    `smooth`: ancho (en canales) del promedio móvil contra el que se compara
    cada canal. La media GLOBAL sólo sirve si el estímulo llena la ventana de
    forma perfectamente plana; con cualquier estímulo suave pero no plano —el
    ruido de una modulación AM es gaussiano, no uniforme— la pendiente de la
    envolvente se cuenta como DNL y el número sale inflado. Comparar contra la
    envolvente local separa las dos cosas, que es lo que interesa. `smooth=None`
    vuelve al comportamiento viejo (media global).

    `strict` / `max_empty_frac`: si más de `max_empty_frac` de los canales de la
    ventana están SIN cuentas, levanta ValueError en vez de devolver un número.
    Un canal vacío no es DNL: es que el estímulo no lo excitó nunca (el caso de
    una forma arbitraria cíclica, que produce líneas discretas), y devolver un
    porcentaje ahí es peor que fallar. El umbral es una FRACCIÓN y no cero
    porque con un número finito de amplitudes distintas siempre queda algún
    canal sin visitar por pura estadística: con N amplitudes sobre M canales la
    probabilidad de que un canal quede vacío es exp(-N/M). Unos pocos vacíos son
    muestreo; el 19 % que dio la campaña anterior era el estímulo.
    """
    spec = np.asarray(spec, dtype=float)
    lo = 0 if lo is None else int(lo)
    hi = len(spec) if hi is None else int(hi)
    y = spec[lo:hi]
    if y.size == 0:
        raise ValueError('la ventana está vacía')
    mean = y.mean()
    if mean <= 0:
        raise ValueError('la ventana no tiene cuentas')

    n_vacios = int((y <= 0).sum())
    frac_vacios = n_vacios / y.size
    if strict and frac_vacios > max_empty_frac:
        raise ValueError(
            f'{n_vacios} de {y.size} canales de la ventana ({100*frac_vacios:.1f}%) '
            f'no tienen NINGUNA cuenta: el estímulo no barre la amplitud de '
            f'forma continua (una forma arbitraria cíclica produce líneas '
            f'discretas). La DNL que saldría de acá no significa nada. Subí el '
            f'número de amplitudes distintas (más recargas del ARB) o usá '
            f'modulación de ruido.')

    if smooth:
        k = int(smooth)
        if k % 2 == 0:
            k += 1                       # impar: el promedio queda centrado
        if k >= y.size:
            k = max(3, (y.size // 2) | 1)
        # Promedio móvil con bordes reflejados, para no hundir los extremos.
        pad = k // 2
        yp  = np.pad(y, pad, mode='reflect')
        env = np.convolve(yp, np.ones(k) / k, mode='valid')
    else:
        env = np.full_like(y, mean)

    env = np.where(env > 0, env, np.nan)
    d = (y - env) / env
    return {'dnl': d, 'dnl_max_pct': 100.0 * float(np.nanmax(np.abs(d))),
            'dnl_rms_pct': 100.0 * float(np.sqrt(np.nanmean(d ** 2))),
            'mean_counts': mean, 'n_empty': n_vacios,
            'empty_frac': frac_vacios, 'smooth': smooth, 'envelope': env}


def fom(map2d, amp_lo=None, amp_hi=None):
    """Figure of Merit de la separación por forma de pulso.

    FOM = |c1 - c2| / (FWHM1 + FWHM2) sobre la proyección del eje de forma.
    FOM > 1.27 se considera buena separación.

    `amp_lo`/`amp_hi` permiten calcularla por rebanadas de amplitud, que es
    como se ve que la separación se degrada a baja energía.
    """
    m = np.asarray(map2d, dtype=float)
    lo = 0 if amp_lo is None else int(amp_lo)
    hi = m.shape[0] if amp_hi is None else int(amp_hi)
    proj = m[lo:hi, :].sum(axis=0)
    if proj.sum() <= 0:
        raise ValueError('la rebanada de amplitud no tiene cuentas')

    # Separar las dos poblaciones por el mínimo entre los dos máximos.
    i1 = int(np.argmax(proj))
    # el segundo pico: el máximo fuera de un entorno del primero
    mask = np.ones_like(proj, dtype=bool)
    w = max(2, len(proj) // 16)
    mask[max(0, i1 - w):i1 + w + 1] = False
    if not mask.any() or proj[mask].max() <= 0:
        return {'fom': float('nan'), 'reason': 'no se detectaron dos poblaciones'}
    i2 = int(np.arange(len(proj))[mask][np.argmax(proj[mask])])
    a, b = sorted((i1, i2))
    valley = a + int(np.argmin(proj[a:b + 1]))

    g1 = gauss_fit_peak(proj, 0, valley + 1)
    g2 = gauss_fit_peak(proj, valley, len(proj))
    denom = g1['fwhm'] + g2['fwhm']
    return {
        'fom': abs(g2['centroid'] - g1['centroid']) / denom if denom else float('nan'),
        'peak1': g1, 'peak2': g2, 'valley': valley,
    }


def deadtime_fit(rate_in, rate_out):
    """Ajusta los modelos de tiempo muerto paralizable y no paralizable.

    No paralizable: m = n/(1+n*tau)   Paralizable: m = n*exp(-n*tau)
    Devuelve el tau de cada uno y cuál ajusta mejor. Cuál de los dos describe
    al sistema determina la corrección a aplicar a las cuentas.
    """
    n = np.asarray(rate_in, dtype=float)
    m = np.asarray(rate_out, dtype=float)
    ok = (n > 0) & (m > 0)
    n, m = n[ok], m[ok]
    if len(n) < 3:
        raise ValueError('hacen falta al menos 3 puntos')

    # no paralizable: 1/m = 1/n + tau  ->  tau = media(1/m - 1/n)
    tau_np = float(np.mean(1.0 / m - 1.0 / n))
    # paralizable: ln(m/n) = -n*tau  ->  ajuste por el origen
    tau_p = float(-np.sum(n * np.log(m / n)) / np.sum(n * n))

    def _sse(pred):
        return float(np.sum((m - pred) ** 2))
    sse_np = _sse(n / (1.0 + n * tau_np))
    sse_p = _sse(n * np.exp(-n * tau_p))
    return {
        'tau_nonparalyzable_s': tau_np, 'sse_nonparalyzable': sse_np,
        'tau_paralyzable_s':    tau_p,  'sse_paralyzable':    sse_p,
        'best': 'no paralizable' if sse_np <= sse_p else 'paralizable',
    }


def counts_to_volts(bins, h_shift=0, amp_src=0, q_shift=0):
    """Convierte índice de canal a volts de amplitud de pico.

    Sólo tiene sentido con amp_src=0 (muestra de pico). Con la integral el eje
    es carga, no amplitud, y la escala depende del ancho del pulso.
    """
    if amp_src:
        raise ValueError('con amp_src=1 el eje es carga: calibrá contra el '
                         'generador en vez de convertir')
    return np.asarray(bins, dtype=float) * (1 << h_shift) / ADC_CNT_PER_V


# =============================================================================
# Linealización del eje de amplitud
#
# Modelo:   Ahat = G*A + INL(A)      A = amplitud de referencia (lo que entra)
#                                    Ahat = centroide medido, en canales
#
# Para poder recuperar A a partir de Ahat el mapa tiene que ser estrictamente
# creciente:
#
#       d(Ahat)/dA = G + d(INL)/dA > 0     <=>     min d(INL)/dA > -G
#
# OJO con la dirección de la derivada: la condición es sobre dINL/dA, no sobre
# dA/dINL. Acá se calcula el MARGEN  G + min(dINL/dA)  y no un booleano, porque
# un margen chico dice que la inversión existe pero es numéricamente frágil.
#
# DOS PATOLOGÍAS DISTINTAS, que conviene no mezclar:
#
#   (a) PLEGADO. Si el margen es <= 0 el mapa se pliega y dos regiones no
#       conexas de energía caen en el mismo canal. NINGUNA corrección lo
#       deshace: la información se perdió en el hardware.
#   (b) PEINE DE DNL. Aparece aunque el mapa sea perfectamente monótono, sólo
#       por estirar y comprimir bins: unos canales terminan recibiendo un rango
#       de entrada más ancho que otros. Se mitiga corrigiendo con más bits de
#       los que tiene el eje (es el caso: ev_amp son 16 b y el eje 14), pero hay
#       que MEDIRLO con dnl(), no suponerlo.
#
# UNA CALIBRACIÓN NO SIGNIFICA LO MISMO PARA CADA FEATURE. Una corrección en el
# dominio de MUESTRA (x -> f(x), un filtro sin memoria) se propaga distinto
# según qué se estime después:
#
#   pico     P = max(x)   -> con f monótona el máximo CONMUTA: P' = f(P).
#                           Warp exacto del eje, no depende de la forma.
#   integral Q = sum(x)   -> sum(f(x)) != f(sum(x)). Con f lineal queda
#                           Q' = g*Q + o*N, o sea que el offset entra
#                           multiplicado por el LARGO DE LA VENTANA. Con f no
#                           lineal NO EXISTE ningún mapa escalar Q -> Q': es un
#                           funcional de la forma entera.
#   cocientes             -> una ganancia se cancela; un offset no.
#
# O sea que el pico es la única feature donde calibrar la muestra y calibrar la
# feature son la misma cosa. Para la integral no hay fórmula cerrada y hay que
# replayar pulsos reales: eso es propagar_calibracion_muestra().
# =============================================================================

def _interp_lineal_extrap(x, xp, fp):
    """np.interp pero extrapolando linealmente en vez de saturar.

    np.interp CLAVA el valor de los extremos fuera del rango. Para un eje de
    calibración eso es un modo de falla silencioso: todo lo que caiga fuera del
    rango calibrado se apilaría en el último canal en vez de correrse. Acá se
    extrapola con la pendiente del tramo extremo, y el llamador decide qué
    hacer con lo que quedó afuera (linearize_spectrum lo cuenta y lo reporta).
    """
    x  = np.asarray(x, dtype=float)
    xp = np.asarray(xp, dtype=float)
    fp = np.asarray(fp, dtype=float)
    y  = np.interp(x, xp, fp)

    izq = x < xp[0]
    if izq.any():
        m = (fp[1] - fp[0]) / (xp[1] - xp[0])
        y[izq] = fp[0] + m * (x[izq] - xp[0])
    der = x > xp[-1]
    if der.any():
        m = (fp[-1] - fp[-2]) / (xp[-1] - xp[-2])
        y[der] = fp[-1] + m * (x[der] - xp[-1])
    return y


def axis_calibration(ref, centroids, inl_model='knots', deg=3, n_grid=1024):
    """Construye el mapa directo g: A -> Ahat desde una campaña de amplitud.

    `ref`       amplitudes de referencia (lo que se le pidió al generador, o la
                energía de las líneas de una fuente).
    `centroids` centroide medido de cada una, en canales (de gauss_fit_peak).

    `inl_model`:
      'knots' (default) — la INL es la interpolación lineal de los residuos
          medidos. No inventa estructura entre puntos y representa cualquier
          curva monótona.
      'poly' — ajuste polinómico de grado `deg` al residuo. Es opción y NO
          default: un polinomio puede salir NO MONÓTONO entre los puntos
          medidos sin que se note, y ahí el eje se pliega (patología (a)).

    Devuelve un dict que consumen apply_calibration() y linearize_spectrum().
    Las claves que importan:

      gain, offset   el ajuste lineal global
      inl_pct_fs     INL como residuo máximo en % de fondo de escala
      margen         G + min(dINL/dA). > 0 => invertible. Es EL número.
      invertible     bool, pero mirá el margen

    ADVERTENCIA DE INTERPRETACIÓN: si la referencia es un generador, la INL que
    sale de acá es la del CONJUNTO (MCA + generador + INL estática del ADC), no
    la del MCA. Corregir con ella mete la calibración del generador adentro del
    instrumento. Ver run_formas.py, que separa lo común de lo diferencial.
    """
    a = np.asarray(ref, dtype=float)
    c = np.asarray(centroids, dtype=float)
    ok = np.isfinite(a) & np.isfinite(c)
    a, c = a[ok], c[ok]
    if a.size < 3:
        raise ValueError(f'hacen falta al menos 3 puntos válidos, hay {a.size}')

    o = np.argsort(a)
    a, c = a[o], c[o]
    if np.any(np.diff(a) <= 0):
        raise ValueError('hay amplitudes de referencia repetidas: el mapa '
                         'A -> Ahat no queda definido')

    # El ajuste lineal y el residuo ya los hace energy_calibration.
    G, b, resid, inl_pct = energy_calibration(c, a)
    if G <= 0:
        raise ValueError(f'la ganancia salió {G:.4g} <= 0. Todo el modelo '
                         f'supone un eje creciente; con ganancia negativa hay '
                         f'que revisar el signo del estímulo, no calibrar')

    ag = np.linspace(a[0], a[-1], int(n_grid))
    if inl_model == 'knots':
        p  = None
        ig = np.interp(ag, a, resid)
    elif inl_model == 'poly':
        p  = np.polyfit(a, resid, int(deg))
        ig = np.polyval(p, ag)
    else:
        raise ValueError(f"inl_model tiene que ser 'knots' o 'poly', no {inl_model!r}")

    cg = G * ag + b + ig                      # Ahat sobre la malla densa

    dinl     = np.gradient(ig, ag)
    dinl_min = float(dinl.min())
    margen   = G + dinl_min
    # El chequeo sobre la malla es el mismo criterio, pero directo: si algún
    # tramo no crece, el mapa se pliega ahí.
    monotona = bool(np.all(np.diff(cg) > 0))

    fs = float(c.max() - c.min())
    return {
        'ref': a, 'centroids': c,
        'gain': float(G), 'offset': float(b),
        'resid': resid, 'inl_pct_fs': float(inl_pct),
        'a_grid': ag, 'chat_grid': cg, 'inl_grid': ig,
        'inl_model': inl_model, 'poly': p,
        'dinl_min': dinl_min,
        'margen': float(margen),
        'invertible': bool(margen > 0 and monotona),
        'monotona': monotona,
        'fs_canales': fs,
    }


def _exigir_invertible(cal):
    if not cal['invertible']:
        raise ValueError(
            f"el eje NO es invertible: margen G + min(dINL/dA) = "
            f"{cal['margen']:.4g} (G = {cal['gain']:.4g}). El mapa A -> Ahat se "
            f"pliega, o sea que dos regiones no conexas de energía caen en el "
            f"mismo canal. Eso NO se corrige con ningún rebinning: la "
            f"información se perdió en el hardware. Revisá el estímulo, o usá "
            f"inl_model='knots' si venías con 'poly' (un polinomio puede "
            f"perder la monotonía entre los puntos medidos).")


def apply_calibration(bins, cal):
    """Mapea números de canal MEDIDOS a canales CORREGIDOS. No rebinnea.

    Es para corregir escalares ya ajustados (centroides de gauss_fit_peak). El
    mapa compuesto es  T(chat) = G * g^-1(chat) + b,  o sea: se vuelve a la
    amplitud de entrada y se la re-proyecta con la recta ideal. Así el eje
    corregido queda en las MISMAS unidades de canal que el crudo y los dos
    espectros se superponen.

    Con INL == 0 esto es la identidad, por construcción.
    """
    _exigir_invertible(cal)
    A = _interp_lineal_extrap(bins, cal['chat_grid'], cal['a_grid'])
    return cal['gain'] * A + cal['offset']


def linearize_spectrum(spec, cal):
    """Corrige un espectro entero conservando las cuentas.

    El punto que hace falta entender: linealizar el eje NO es renombrar los
    canales. Si el mapa estira una zona y comprime otra, las ALTURAS del
    histograma también cambian — si no, el pico corregido queda en el lugar
    correcto pero con el área equivocada, y aparece una DNL falsa.

    El método es rebinning por BORDES:

      1. los bordes enteros 0..N del espectro medido se pasan por T,
      2. la cuenta acumulada se interpola en la grilla destino,
      3. np.diff de eso son las cuentas corregidas.

    Conserva las cuentas EXACTAMENTE y absorbe el jacobiano sin derivar nada.
    Es a propósito: la fórmula puntual N(A) = N(g(A)) * g'(A) obliga a derivar
    un interpolante construido sobre datos ruidosos, que es justo lo que no
    conviene hacer, y encima no conserva las cuentas sobre una grilla discreta.

    Convención de bordes: el canal i cubre [i, i+1). Es la del RTL, donde el
    bin es una truncación (amp >> shift). La misma convención se usa para ir y
    para volver, así que cualquier medio bin de sesgo se cancela.

    Devuelve dict con:
      spec              el espectro corregido, mismo largo que el de entrada
      edges_ref         los bordes del eje corregido en unidades de REFERENCIA
      counts_out        cuentas que cayeron fuera del eje y se perdieron
      frac_out          esas cuentas como fracción del total
    """
    _exigir_invertible(cal)
    y = np.asarray(spec, dtype=float)
    n = y.size

    bordes_src = apply_calibration(np.arange(n + 1, dtype=float), cal)
    if np.any(np.diff(bordes_src) <= 0):
        # No debería pasar si el margen es positivo; si pasa es que la malla
        # densa no resolvió una ondulación fina del modelo.
        raise ValueError('los bordes corregidos no quedaron crecientes: subí '
                         'n_grid en axis_calibration, o pasá a inl_model="knots"')

    bordes_dst = np.arange(n + 1, dtype=float)
    cum = np.concatenate(([0.0], np.cumsum(y)))
    # np.interp SATURA fuera de rango, que acá es exactamente lo que se quiere:
    # lo que quedó fuera del eje destino no se reparte en ningún bin, y la
    # diferencia contra el total es la pérdida, que se reporta.
    out = np.diff(np.interp(bordes_dst, bordes_src, cum))

    total = float(y.sum())
    fuera = total - float(out.sum())
    return {
        'spec': out,
        'edges_ref': (bordes_dst - cal['offset']) / cal['gain'],
        'counts_out': fuera,
        'frac_out': fuera / total if total else 0.0,
    }


def inl_residual_vs_knots(cal, n_knots=(8, 16, 32, 64, 128, 256)):
    """INL que QUEDARÍA después de corregir con una LUT de N nodos.

    Sirve para dimensionar la tabla del RTL ANTES de sintetizar nada: para cada
    N se muestrea la curva de INL en N nodos equiespaciados, se interpola
    linealmente entre ellos (que es lo que hace la LUT en hardware) y el residuo
    INL - INL_interpolada es el error que la tabla NO puede corregir.

    Devuelve dict con `n_knots`, `inl_pct_fs` (residual por cada N) y
    `inl_pct_fs_original`, para poder decidir con la curva en la mano en vez de
    elegir 64 o 128 nodos a ojo.
    """
    ag, ig = cal['a_grid'], cal['inl_grid']
    fs = cal['fs_canales']
    res = []
    for n in n_knots:
        n = int(n)
        if n < 2:
            raise ValueError('una LUT necesita al menos 2 nodos')
        nodos = np.linspace(ag[0], ag[-1], n)
        recon = np.interp(ag, nodos, np.interp(nodos, ag, ig))
        res.append(100.0 * float(np.abs(ig - recon).max()) / fs if fs else float('nan'))
    return {
        'n_knots': np.asarray(n_knots, dtype=int),
        'inl_pct_fs': np.asarray(res, dtype=float),
        'inl_pct_fs_original': cal['inl_pct_fs'],
    }


def propagar_calibracion_muestra(ondas, f, estimadores, baseline=0.0):
    """Cómo cambia cada feature al aplicar una corrección x -> f(x) por MUESTRA.

    Para el pico hay respuesta analítica (el máximo conmuta con f monótona), y
    para la integral NO EXISTE ningún mapa escalar: depende de la forma entera
    del pulso. Así que se calcula replayando pulsos reales.

    `ondas`       (n_eventos, n_muestras) en cuentas de ADC.
    `f`           callable sobre un array de muestras. Tiene que ser monótona
                  creciente; se verifica sobre el rango que realmente aparece.
    `estimadores` dict nombre -> callable(ondas_2d, baseline) -> array de un
                  valor por evento. Acá se pasan las réplicas bit-exactas del
                  RTL de tests/estimadores/estimadores.py; se inyectan en vez de
                  importarse para que este módulo no dependa de los tests.

    Devuelve dict nombre -> {'crudo', 'calibrado', 'ratio_medio'}.
    """
    w = np.asarray(ondas)
    if w.ndim != 2:
        raise ValueError(f'ondas tiene que ser (n_eventos, n_muestras), es {w.shape}')

    # La monotonía de f no se asume: se verifica sobre el rango que de verdad
    # aparece en los datos. Si f no es monótona, ni siquiera el pico conmuta y
    # todo lo que salga de acá es basura.
    prueba = np.arange(int(w.min()), int(w.max()) + 1, dtype=float)
    if prueba.size >= 2 and np.any(np.diff(np.asarray(f(prueba), dtype=float)) < 0):
        raise ValueError('f no es monótona creciente sobre el rango de muestras '
                         'presente en los datos: la propagación no está definida')

    wc = np.asarray(f(w.astype(float)))
    salida = {}
    for nombre, est in estimadores.items():
        crudo = np.asarray(est(w, baseline), dtype=float)
        calib = np.asarray(est(wc, float(f(np.array([baseline]))[0])), dtype=float)
        m = np.isfinite(crudo) & np.isfinite(calib) & (crudo != 0)
        salida[nombre] = {
            'crudo': crudo, 'calibrado': calib,
            'ratio_medio': float(np.mean(calib[m] / crudo[m])) if m.any() else float('nan'),
        }
    return salida
