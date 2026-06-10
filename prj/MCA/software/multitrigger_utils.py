"""
Utilidades para el scope multitrigger del Red Pitaya MCA.

Importable desde Jupyter o cualquier script:

    from multitrigger_utils import MultiTriggerScope, BIT_ADC_P0, decode_snap

    sc = MultiTriggerScope.open()
    sc.debug_trigger()
    sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, thr=0.5)
    events, dur = sc.capture_n_events(n=50)
    sc.disarm()
    sc.close()

Incluye:
    - MultiTriggerScope: clase que envuelve /dev/mem + helpers de arm,
      captura, debug, SW trigger forzado.
    - Constantes de bits de la máscara OR (BIT_SW, BIT_ADC_*, BIT_EXT_*).
    - decode_snap(s): nombres de las fuentes activas en el snapshot.
    - events_to_intervals, efficiency, pulses_from_buffer: análisis offline.
"""

import time
import struct
import mmap
import os

import numpy as np
import rp


# ---------- constantes del scope ----------

SCOPE_PHYS = 0x4010_0000
SCOPE_SIZE = 0x30000
N_BUF      = 16384
FS         = 125e6                # Hz, sampling rate con decim=1


# ---------- bits de la OR_MASK (matchean trg_src_bits de multitrigger_trig_src.sv) ----------

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


# ---------- decoder del snapshot @0x218 ----------

_SNAP_NAMES = [
    'sw_any',
    'adc_p0', 'adc_p1', 'adc_p2', 'adc_p3',
    'adc_n0', 'adc_n1', 'adc_n2', 'adc_n3',
    'ext_p', 'ext_n', 'asg_p', 'asg_n',
    'trig_ch0', 'trig_ch1', 'trig_ch2', 'trig_ch3',
]


def decode_snap(s):
    """Lista de nombres de fuentes activas en un snapshot @0x218."""
    return [n for i, n in enumerate(_SNAP_NAMES) if s & (1 << i)]


# ---------- clase scope ----------

class MultiTriggerScope:
    """Wrapper del cfg del scope multitrigger + helpers de diagnóstico,
    arm y captura.

    No abre por sí solo: usar :py:meth:`open` o pasar (mmap, fd) si ya los
    tenés mapeados.
    """

    def __init__(self, scope_mmap, fd):
        self._mmap = scope_mmap
        self._fd   = fd

    @classmethod
    def open(cls, phys=SCOPE_PHYS, size=SCOPE_SIZE):
        """Abrir /dev/mem y mapear la región del scope."""
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        m  = mmap.mmap(fd, size, mmap.MAP_SHARED,
                       mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)
        return cls(m, fd)

    def close(self):
        try:
            self._mmap.close()
        finally:
            os.close(self._fd)

    # ---------- acceso /dev/mem ----------

    def w32(self, off, v):
        self._mmap[off:off+4] = struct.pack('<I', v & 0xFFFFFFFF)

    def r32(self, off):
        return struct.unpack('<I', self._mmap[off:off+4])[0]

    # ---------- diagnóstico ----------

    def debug_trigger(self):
        """Dump completo de regs del scope (write-side + run-time)."""
        print('--- write-side (config) ---')
        print(f'  set_tresh ch0/ch1 @0x08/0x0C = {self.r32(0x08):#010x} / {self.r32(0x0C):#010x}')
        print(f'  set_hyst  ch0/ch1 @0x20/0x24 = {self.r32(0x20):#010x} / {self.r32(0x24):#010x}')
        print(f'  set_deb_len       @0x90     = {self.r32(0x90):#010x}')
        print(f'  trg_src_stored ch0/ch1 @0x240/0x244 = {self.r32(0x240):#010x} / {self.r32(0x244):#010x}')
        print(f'  shield_cfg            @0x210 = {self.r32(0x210):#010x}')
        print('--- run-time (status / debug) ---')
        print(f'  adc_state         @0x00 = {self.r32(0x00):#010x}  (config + trigger_status por canal)')
        print(f'  trg_state         @0x04 = {self.r32(0x04):#010x}  (set_trig_src[7:0] activo por canal en bytes)')
        print(f'  shield runtime    @0x214 = {self.r32(0x214):#010x}  ({{active, cnt[15:0]}})')
        snap = self.r32(0x218)
        print(f'  snapshot          @0x218 = {snap:#010x}  -> {decode_snap(snap)}')
        dis_we = self.r32(0x21C)
        print(f'  dis+we_keep       @0x21C = {dis_we:#010x}  dis_act={dis_we & 0xF:#x} we_keep={(dis_we>>4) & 0xF:#x}')
        print(f'  wp_trig ch0/ch1   @0x1C/0x11C = {self.r32(0x1C):#010x} / {self.r32(0x11C):#010x}')
        print(f'  wp_cur  ch0/ch1   @0x18/0x118 = {self.r32(0x18):#010x} / {self.r32(0x118):#010x}')

    def debug_dump(self):
        """Versión corta — solo lo más relevante por captura."""
        snap = self.r32(0x218)
        print(f'  snapshot @0x218 = {snap:#010x}  -> {decode_snap(snap)}')
        print(f'  dis_act  @0x21C = {self.r32(0x21C):#010x}')
        print(f'  mask act ch0/ch1 = {self.r32(0x240):#010x} / {self.r32(0x244):#010x}')
        print(f'  wp_trig ch0/ch1 = {self.r32(0x1C):#010x} / {self.r32(0x11C):#010x}')
        print(f'  shield   @0x214 = {self.r32(0x214):#010x}')

    # ---------- configuración acq ----------

    def acq_base(self, thr=0.5, delay=0, decim=1):
        """Reset + decim/threshold/delay básicos vía la rp API."""
        rp.rp_AcqReset()
        if   decim == 1:    rp.rp_AcqSetDecimation(rp.RP_DEC_1)
        elif decim == 8:    rp.rp_AcqSetDecimation(rp.RP_DEC_8)
        elif decim == 64:   rp.rp_AcqSetDecimation(rp.RP_DEC_64)
        elif decim == 1024: rp.rp_AcqSetDecimation(rp.RP_DEC_1024)
        rp.rp_AcqSetTriggerLevel(rp.RP_T_CH_1, thr)
        rp.rp_AcqSetTriggerLevel(rp.RP_T_CH_2, thr)
        rp.rp_AcqSetTriggerDelay(delay)

    def set_or_mask(self, mask_ch0=OR_MASK_ALL, mask_ch1=None):
        """Escribe la máscara en 0x240/0x244 con assert de readback."""
        if mask_ch1 is None:
            mask_ch1 = mask_ch0
        self.w32(0x240, mask_ch0)
        self.w32(0x244, mask_ch1)
        rb0 = self.r32(0x240)
        rb1 = self.r32(0x244)
        assert rb0 == mask_ch0, f'OR_MASK ch0 no latcheada: {rb0:#010x} != {mask_ch0:#010x}'
        assert rb1 == mask_ch1, f'OR_MASK ch1 no latcheada: {rb1:#010x} != {mask_ch1:#010x}'

    def configure_shield_autorearm(self, channels=0x3, dur=0):
        """Configura el trigger_shield para clear automático del adc_trg_dis.
        Con dur=0 el clear se emite en el MISMO ciclo del trigger (ver
        trigger_shield.sv:44-48), lo que reemplaza el pulso manual a 0x94
        después de cada disparo y permite re-triggering a velocidad de HW.

        channels: bits de los canales a auto-rearmar (0x3 = ch0+ch1).
        dur:      ciclos de ADC de holdoff antes del clear (0 = inmediato).
        Layout 0x210: {dur[31:16], 4'h0, dst[11:8], 4'h0, src[3:0]}.
        """
        word = ((dur & 0xFFFF) << 16) | ((channels & 0xF) << 8) | (channels & 0xF)
        self.w32(0x210, word)

    def disable_shield(self):
        """Apaga el shield (vuelve al modo SW-clear manual de 0x94)."""
        self.w32(0x210, 0)

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
        self.w32(0x10,  delay)
        self.w32(0x110, delay)

    def arm_for_adc_trigger(self, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                             thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                             auto_rearm=True):
        """Arma el scope para trigger por flanco del ADC.

        auto_rearm=True (default): activa el trigger_shield para clear
            automático de adc_trg_dis (shield_dur=0, inmediato) Y
            sobreescribe set_dly a 0 raw para eliminar los 65 µs de offset
            que mete rp_AcqSetTriggerDelay. Esto baja drásticamente el
            dead-time del sistema (de ~65 µs a ~µs).
        auto_rearm=False: comportamiento legacy. El SW tiene que pulsar
            0x94 entre triggers (tradicional, más alto dead-time).

        OJO: setea we_keep DESPUÉS de rp_AcqStart porque la API rescribe
        byte0 de 0x00 con 0x01 (arm bit), lo que en la cfg satisface el
        ``if (sys_addr==0x0 && |sys_dats)`` y sobrescribe we_keep con 0.
        Reescribiendo we_keep después del arm restaura el bit sin afectar
        el estado armado (el arm ya pulsó).
        """
        self.acq_base(thr=thr, delay=delay)
        # hyst en counts (14 b signed escala = 8192)
        hyst_cnt = max(1, int(abs(hyst) * 8192))
        self.w32(0x20, hyst_cnt)
        self.w32(0x24, hyst_cnt)
        if auto_rearm:
            self.configure_shield_autorearm(channels=0x3, dur=0)
            self.set_raw_delay()   # default = 1 sample; evita el caso degenerado set_dly=0
        else:
            self.disable_shield()
        self.set_or_mask(mask_ch0, mask_ch1)
        rp.rp_AcqStart()                # ← borra we_keep como side-effect
        cfg = 0x0000_0008 | (0x0000_0800 if we_keep_both else 0)
        self.w32(0x00, cfg)             # ← restaurar we_keep

    def disarm(self):
        """Apaga we_keep, limpia el shield, limpia adc_trg_dis y resetea el
        FSM. Deja el scope en un estado IDLE limpio para la próxima corrida."""
        self.w32(0x00, 0x0000_0000)
        self.disable_shield()           # desactivar trigger_shield
        self.w32(0x94, 0x0000_0101)     # trig_dis_clr: limpia adc_trg_dis
        self.w32(0x00, 0x0000_0202)     # adc_rst_do[0] y [1]: reset FSM

    # ---------- waits ----------

    @staticmethod
    def wait_triggered(timeout_ms=2000):
        """Polea rp_AcqGetTriggerState. CUIDADO: en we_keep=1 es STICKY."""
        for _ in range(timeout_ms):
            if rp.rp_AcqGetTriggerState()[1] == rp.RP_TRIG_STATE_TRIGGERED:
                return True
            time.sleep(0.001)
        return False

    @staticmethod
    def wait_fill(timeout_ms=2000):
        """Polea rp_AcqGetBufferFillState (FSM completó la captura)."""
        for _ in range(timeout_ms):
            if rp.rp_AcqGetBufferFillState()[1]:
                return True
            time.sleep(0.001)
        return False

    @staticmethod
    def read_buffers(n_buf=N_BUF):
        """Lee los dos buffers ADC como numpy arrays (volts)."""
        fb1 = rp.fBuffer(n_buf); rp.rp_AcqGetOldestDataV(rp.RP_CH_1, n_buf, fb1)
        fb2 = rp.fBuffer(n_buf); rp.rp_AcqGetOldestDataV(rp.RP_CH_2, n_buf, fb2)
        d1 = np.fromiter((fb1[i] for i in range(n_buf)), dtype=float, count=n_buf)
        d2 = np.fromiter((fb2[i] for i in range(n_buf)), dtype=float, count=n_buf)
        return d1, d2

    # ---------- captura ----------

    def acq_capture_sw(self, thr=0.5, delay=None, timeout_ms=500):
        """Captura single-shot forzada con SW trigger (mask=BIT_SW + pulso a 0x04).
        Devuelve (d1, d2, snapshot). Sirve para confirmar que el bram_sm
        captura el buffer correctamente, independiente del trigger ADC.
        """
        if delay is None:
            delay = N_BUF // 2
        self.acq_base(thr=thr, delay=delay)
        # Limpiar adc_trg_dis si quedó pegado de una corrida anterior. Sin esto,
        # src_mask = set_trig_src & {!adc_trg_dis} = 0 y el SW pulse no firma.
        self.w32(0x94, 0x0000_0101)
        self.set_or_mask(BIT_SW, BIT_SW)
        rp.rp_AcqStart()
        time.sleep(0.01)
        self.w32(0x04, 0x0000_0101)     # pulso adc_trig_sw[0] y [1]
        self.wait_fill(timeout_ms=timeout_ms)
        d1, d2 = self.read_buffers()
        return d1, d2, self.r32(0x218)

    def capture_n_events(self, n=100, timeout_ms=2000, wp_addr=0x1C,
                          clear_both=True):
        """Captura n triggers consecutivos detectando cambios en wp_trig.
        Requiere `arm_for_adc_trigger` previo.

        Con `arm_for_adc_trigger(auto_rearm=True)` (default) el trigger_shield
        del FPGA limpia adc_trg_dis automáticamente cada disparo, así que el
        loop NO necesita pulsar 0x94. Solo polea cambios de wp_trig.

        Si se llama con `auto_rearm=False`, el pulso inicial al 0x94 cubre
        el caso del trigger durante el arm. El loop sigue sin pulsar (mejor
        usar `auto_rearm=True` para alta tasa).

        Devuelve (events, duration_s) donde events es lista de dicts con
        't_ns' (timestamp SW), 'wp' (write pointer al trigger) y 'snap'
        (snapshot del momento)."""
        clear_mask = 0x0000_0101 if clear_both else 0x0000_0001
        events = []
        # Pulso inicial defensivo: si el primer trigger firmó durante el arm
        # y el shield no está activo, esto destraba el dis.
        self.w32(0x94, clear_mask)
        wp_prev = self.r32(wp_addr)
        t0 = time.perf_counter_ns()
        deadline = t0 + timeout_ms * 1_000_000
        while len(events) < n:
            if time.perf_counter_ns() > deadline:
                break
            wp_cur = self.r32(wp_addr)
            if wp_cur != wp_prev:
                events.append({
                    't_ns': time.perf_counter_ns() - t0,
                    'wp':   wp_cur,
                    'snap': self.r32(0x218),
                })
                wp_prev = wp_cur
        dur_s = (time.perf_counter_ns() - t0) / 1e9
        return events, dur_s


# ---------- helpers offline ----------

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
