#!/usr/bin/env python3
"""Multitrigger: máscaras OR, trigger_shield y snapshot de fuentes.

Es el bloque que el proyecto AÑADIÓ al scope original de RedPitaya, en los
registros 0x210-0x24C del slot 1 (0x4010_0000). El osciloscopio clásico
(umbral, decimación, delay, histéresis, filtros, calibración, BRAM) vive en
`API/osciloscope.py`: son dos APIs sobre el mismo bloque físico.

    from API.osciloscope import Osciloscope
    from API.multitrigger import MultiTrigger, multitrigger_arm, BIT_ADC_P0

    osc = Osciloscope.open()
    mt  = MultiTrigger.open(osc=osc)        # comparte el mmap del osciloscopio
    multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, thr=0.5)

`multitrigger_arm()` recibe LOS DOS handles a propósito: la secuencia de armado
cruza registros de ambos módulos y su orden es load-bearing (ver el docstring
de la función). Con la firma explícita la dependencia se ve; escondida dentro
de una clase sería accidental.
"""

import mmap
import os
import struct

_U32 = struct.Struct('<I')

SCOPE_PHYS = 0x4010_0000        # el multitrigger comparte slot con el scope
SCOPE_SIZE = 0x30000

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


# =============================================================================
# Registros del bloque multitrigger
# =============================================================================
#
# El fichero original no tenía constantes de offset: cada dirección era un
# literal hex inline (`self.w32(0x240, mask)`). Nombrarlas es lo que permite
# que API/tests/test_compat_api.py verifique los valores contra el baseline.

R_CMD         = 0x000           # compartido con el scope: arm / rst / we_keep
R_TRIG_DIS_CLR = 0x094          # compartido: desbloquea adc_trg_dis
R_SHIELD_CFG  = 0x210           # {dur[31:16], dst[11:8], src[3:0]}
R_SHIELD_RUN  = 0x214           # runtime del shield (R)
R_TRIG_SNAP   = 0x218           # snapshot de 17 b, sticky (R)
R_FLAGS       = 0x21C           # dis_act / we_keep (R)
R_OR_MASK_CH0 = 0x240
R_OR_MASK_CH1 = 0x244
R_OR_MASK_CH2 = 0x248
R_OR_MASK_CH3 = 0x24C


class MultiTrigger:
    """Acceso al bloque multitrigger por /dev/mem.

    Abre su propio mapeo salvo que se le pase un `Osciloscope`, en cuyo caso
    reutiliza el suyo: son la misma región física (0x4010_0000) y dos mapeos
    de memoria de dispositivo no dan problema de coherencia, pero un fd de
    menos es un fd de menos.
    """

    def __init__(self, scope_mmap, fd):
        self._mmap = scope_mmap
        self._fd   = fd
        self._propio = fd >= 0

    @classmethod
    def open(cls, osc=None, phys=SCOPE_PHYS, size=SCOPE_SIZE):
        if osc is not None:
            # Comparte el mmap del osciloscopio; fd=-1 marca "no es mío, no lo
            # cierres" (close() del dueño es el que libera).
            return cls(osc._mmap, -1)
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        try:
            m = mmap.mmap(fd, size, mmap.MAP_SHARED,
                          mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)
        except Exception:
            os.close(fd)
            raise
        return cls(m, fd)

    def close(self):
        if not self._propio:
            return                      # el mmap es prestado del osciloscopio
        try:
            self._mmap.close()
        finally:
            os.close(self._fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def w32(self, off, v):
        # Asignación por slice, NO struct.pack_into: pack_into hace un memset
        # previo que sobre memoria de dispositivo sale como stores de a byte,
        # el esclavo AXI no los reconoce y el puente GP0 tira un external abort
        # -> SIGBUS. Ver API/tests/placa/test_rw_dev_mem.py.
        self._mmap[off:off+4] = _U32.pack(v & 0xFFFFFFFF)

    def r32(self, off):
        return _U32.unpack_from(self._mmap, off)[0]

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
    # ---------- estatus ----------

    def get_or_mask(self, ch=0):
        return self.r32((R_OR_MASK_CH0, R_OR_MASK_CH1,
                         R_OR_MASK_CH2, R_OR_MASK_CH3)[ch])

    def get_shield(self):
        palabra = self.r32(R_SHIELD_CFG)
        return {'dur': (palabra >> 16) & 0xFFFF,
                'dst': (palabra >> 8) & 0xF,
                'src': palabra & 0xF,
                'runtime': self.r32(R_SHIELD_RUN)}

    def read_snapshot(self):
        """Fuentes que dispararon, decodificadas. El registro es STICKY."""
        return decode_snap(self.r32(R_TRIG_SNAP))

    def read_snapshot_raw(self):
        return self.r32(R_TRIG_SNAP)

    def get_flags(self):
        return self.r32(R_FLAGS)


# =============================================================================
# Secuencias que cruzan los dos módulos
# =============================================================================

def multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                     thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                     auto_rearm=True):
    """Arma el scope para trigger por flanco del ADC.

    Recibe LOS DOS handles porque la secuencia los cruza: histéresis y arm son
    registros del osciloscopio (0x20/0x24, 0x00), shield y máscara OR son del
    multitrigger (0x210, 0x240/0x244).

    ORDEN CRÍTICO (arm ANTES de la máscara): se arma la bram_sm (0x00) y RECIÉN
    DESPUÉS se habilita la OR-mask (0x240/0x244). Es la misma convención que la
    API de RedPitaya (rp_AcqStart antes de rp_AcqSetTriggerSrc). Si se hiciera
    al revés, con una señal viva un flanco de ADC puede disparar en la ventana
    pre-arm: engancha adc_trg_dis y (en single-shot) auto-limpia set_trig_src
    ANTES de que la bram_sm esté armada, dejándola esperando un trigger
    imposible (wp_trig=0 permanente). El SW trigger es inmune porque adc_trig_sw
    es pasivo hasta el pulso 0x04. Ver docs/multitrigger/orden_arm_trigger_captura.md.

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
