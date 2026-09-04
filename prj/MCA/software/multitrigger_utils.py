"""SHIM de compatibilidad — el scope vive ahora repartido en tres módulos.

El refactor partió este fichero por concepto:

    API/osciloscope.py    osciloscopio clásico: umbral, decimación, delay,
                          histéresis, filtros, calibración, punteros, BRAM
    API/multitrigger.py   lo que este proyecto AÑADIÓ: máscaras OR (0x240/0x244),
                          trigger_shield (0x210), snapshot (0x218)
    API/fpga.py           bring-up de la PL: bitstream y puentes AXI, que no
                          tenían nada que ver con el osciloscopio

Se mantiene el shim para no tocar los ~40 importadores, los notebooks ni los
scripts que ya corren en la placa. Código nuevo::

    from API.osciloscope import Osciloscope, osciloscope_set_decim
    from API.multitrigger import MultiTrigger, multitrigger_arm, BIT_ADC_P0

    osc = Osciloscope.open()
    mt  = MultiTrigger.open(osc=osc)
    multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, thr=0.5)

`MultiTriggerScope` sigue acá porque es una clase de COMPATIBILIDAD, no de la
API nueva: compone un `Osciloscope` y un `MultiTrigger` sobre el mismo mapeo y
delega. Se listan todos sus métodos explícitamente en vez de heredarlos para
que la superficie que este shim garantiza esté escrita, no implícita en un MRO.

Sin DeprecationWarning a propósito: saltaría en cada corrida en la Pitaya.
"""

from API.fpga import *                                          # noqa: F401,F403
from API.fpga import (                                          # noqa: F401
    BITSTREAM_DEFAULT, FPGA_STATE, FPGA_BRIDGE_DIR, FPGAUTIL_PATHS,
    fpgautil_bin, fpga_state, fpga_bridges, set_fpga_bridges,
    pl_probe, pl_bus_ready, load_bitstream,
)
from API.osciloscope import *                                   # noqa: F401,F403
from API.osciloscope import (                                   # noqa: F401
    Osciloscope, SCOPE_PHYS, SCOPE_SIZE, N_BUF, FS, ADC_CNT_PER_V, DEC_LEGAL,
    RESET_SET_DEC, RESET_CALIB_GAIN,
    events_to_intervals, efficiency, pulses_from_buffer,
)
from API.multitrigger import *                                  # noqa: F401,F403
from API.multitrigger import (                                  # noqa: F401
    MultiTrigger, multitrigger_arm, multitrigger_disarm, decode_snap,
    OR_MASK_ALL, BIT_SW,
    BIT_ADC_P0, BIT_ADC_N0, BIT_ADC_P1, BIT_ADC_N1,
    BIT_ADC_P2, BIT_ADC_N2, BIT_ADC_P3, BIT_ADC_N3,
    BIT_EXT_P, BIT_EXT_N, BIT_ASG_P, BIT_ASG_N,
    BIT_TRIG_CH0, BIT_TRIG_CH1, BIT_TRIG_CH2, BIT_TRIG_CH3,
)


class MultiTriggerScope(Osciloscope):
    """Clase de compatibilidad: el scope y el multitrigger en un solo objeto.

    Compone un `MultiTrigger` sobre EL MISMO mapeo, así que las escrituras de
    los dos módulos salen por el mismo mmap y en el mismo orden que antes del
    refactor — que es justo lo que verifican las trazas de
    `tests/test_compat_api.py`.

    Código nuevo: usar `Osciloscope` + `MultiTrigger` por separado.
    """

    def __init__(self, scope_mmap, fd):
        super().__init__(scope_mmap, fd)
        # fd=-1: el mmap es del Osciloscope, MultiTrigger.close() no lo toca.
        self._mt = MultiTrigger(scope_mmap, -1)

    # ---------- delegado al bloque multitrigger ----------

    def set_or_mask(self, mask_ch0=OR_MASK_ALL, mask_ch1=None):
        return self._mt.set_or_mask(mask_ch0, mask_ch1)

    def configure_shield_autorearm(self, channels=3, dur=0):
        return self._mt.configure_shield_autorearm(channels, dur)

    def disable_shield(self):
        return self._mt.disable_shield()

    # ---------- secuencias que cruzan los dos bloques ----------

    def arm_for_adc_trigger(self, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                            thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                            auto_rearm=True):
        """Ver `API.multitrigger.multitrigger_arm`, incluido el ORDEN CRÍTICO
        de armar antes de habilitar la máscara."""
        return multitrigger_arm(self, self._mt, mask_ch0=mask_ch0,
                                mask_ch1=mask_ch1, thr=thr, hyst=hyst,
                                delay=delay, we_keep_both=we_keep_both,
                                auto_rearm=auto_rearm)

    def disarm(self):
        return multitrigger_disarm(self, self._mt)
