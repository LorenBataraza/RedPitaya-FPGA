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

        # Las vistas se crean UNA sola vez: construir un np.frombuffer cuesta
        # ~200 us, o sea más que la lectura misma si queda dentro del lazo.
        # count fijo en 2**AW para no caminar sobre el aliasing de la apertura
        # (el casez del RTL decodifica 64 KB, el histograma ocupa menos).
        self._view_h = np.frombuffer(mem, dtype='<u4',
                                     count=1 << h_aw, offset=APERTURE_H)
        if caps & CAP_HIST_H_PSD:
            self._view_2d = np.frombuffer(mem, dtype='<u4',
                                          count=1 << (h2_aw + psd_aw),
                                          offset=APERTURE_2D)
        else:
            self._view_2d = None

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
        self._view_h  = None
        self._view_2d = None
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

    def configure(self, thr=200, hyst=80, baseline=0, bl_auto=False, bl_k=6,
                  bl_holdoff=0, maxlen=1024, tail_dly=8, amp_min=0,
                  amp_max=0xFFFF, amp_src=0, q_shift=0, h_shift=0, h2_shift=0,
                  dec=1, channel=0, verify=True):
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

    def spectrum(self, copy=True):
        """Espectro 1D como uint32 de 2^H_AW canales.

        Los bins son contadores SIN signo: a diferencia del buffer del scope
        no hay que extender el signo de 14 a 16 bits.
        """
        return self._view_h.copy() if copy else self._view_h

    def map2d(self, copy=True):
        """Mapa 2D con forma (2^H2_AW, 2^PSD_AW): filas = amplitud, columnas = forma."""
        if self._view_2d is None:
            raise RuntimeError('este bitstream no tiene el motor 2D '
                               '(CAPS sin CAP_HIST_H_PSD)')
        v = self._view_2d.copy() if copy else self._view_2d
        return v.reshape(1 << self.h2_aw, 1 << self.psd_aw)

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
        m2d = self.map2d() if self._view_2d is not None else None
        return self.spectrum(), m2d, self.counters()


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
        raise ValueError('la ventana no tiene cuentas')

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

    fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0)) * s0
    return {
        'centroid': c0,
        'sigma':    s0,
        'fwhm':     fwhm,
        'area':     float(y.sum()),
        'resolution_pct': 100.0 * fwhm / c0 if c0 else float('nan'),
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


def dnl(spec, lo=None, hi=None):
    """No linealidad diferencial a partir de un espectro de *sliding pulser*.

    Con amplitud uniformemente aleatoria todos los canales deberían recibir la
    misma cuenta; la desviación relativa es la DNL. Spec típica: <±1%.

    Ojo: mide el ADC y el estimador de amplitud, no el binning. La DNL del
    binning digital es exactamente cero por construcción (el bin es un
    desplazamiento a la derecha de un entero, todos los canales igual de anchos).
    """
    spec = np.asarray(spec, dtype=float)
    lo = 0 if lo is None else int(lo)
    hi = len(spec) if hi is None else int(hi)
    y = spec[lo:hi]
    mean = y.mean()
    if mean <= 0:
        raise ValueError('la ventana no tiene cuentas')
    d = (y - mean) / mean
    return {'dnl': d, 'dnl_max_pct': 100.0 * np.abs(d).max(),
            'dnl_rms_pct': 100.0 * float(np.sqrt((d ** 2).mean())),
            'mean_counts': mean}


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
