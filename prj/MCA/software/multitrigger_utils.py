"""SHIM de compatibilidad — el scope vive ahora repartido en tres módulos.

El refactor partió este fichero por concepto:

    API/osciloscope.py    osciloscopio clásico: umbral, decimación, delay,
                          histéresis, filtros, calibración, punteros, BRAM
    API/multitrigger.py   lo que este proyecto AÑADIÓ: máscaras OR, trigger_shield
                          y snapshot, en su región propia (slot 3)
    API/fpga.py           bring-up de la PL: bitstream y puentes AXI, que no
                          tenían nada que ver con el osciloscopio

Se mantiene el shim para no tocar los ~40 importadores, los notebooks ni los
scripts que ya corren en la placa. Código nuevo::

    from API.osciloscope import Osciloscope, osciloscope_set_decim
    from API.multitrigger import MultiTrigger, multitrigger_arm, BIT_ADC_P0

    osc = Osciloscope.open()
    mt  = MultiTrigger.open()
    multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, thr=0.5)

`MultiTriggerScope` sigue acá porque es una clase de COMPATIBILIDAD, no de la
API nueva: compone un `Osciloscope` y un `MultiTrigger` y delega. Se listan todos sus métodos explícitamente en vez de heredarlos para
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
from API.ref_py import osciloscope2 as _ref_osc


class _Compuesto:
    """Lo que `MultiTriggerScope` agrega, sobre el osciloscopio que sea: el de libmca
    o el de la referencia, que es lo que abre `open(impl='py')`."""

    # ---------- delegado al bloque multitrigger ----------

    def set_or_mask(self, mask_ch0=OR_MASK_ALL, mask_ch1=None):
        return self.mt.set_or_mask(mask_ch0, mask_ch1)

    def configure_shield_autorearm(self, channels=3, dur=0):
        return self.mt.configure_shield_autorearm(channels, dur)

    def disable_shield(self):
        return self.mt.disable_shield()

    # ---------- secuencias que cruzan los dos bloques ----------

    def arm_for_adc_trigger(self, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                            thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                            auto_rearm=True):
        """Ver `API.multitrigger.multitrigger_arm`, incluido el ORDEN CRÍTICO
        de armar antes de habilitar la máscara."""
        return multitrigger_arm(self, self.mt, mask_ch0=mask_ch0,
                                mask_ch1=mask_ch1, thr=thr, hyst=hyst,
                                delay=delay, we_keep_both=we_keep_both,
                                auto_rearm=auto_rearm)

    def disarm(self):
        return multitrigger_disarm(self, self.mt)


class _MultiTriggerScopeRef(_Compuesto, _ref_osc.Osciloscope):
    """Lo que devuelve `MultiTriggerScope.open(impl='py')`."""


class MultiTriggerScope(_Compuesto, Osciloscope):
    """Clase de compatibilidad: el scope y el multitrigger en un solo objeto.

    Compone un `MultiTrigger`, el de `Osciloscope.mt`, que tiene su propio mapeo
    porque vive en otra región. Las trazas de `API/tests/test_compat_api.py`
    verifican que las escrituras de los dos bloques salgan en el mismo orden que
    antes del refactor.

    Código nuevo: usar `Osciloscope` + `MultiTrigger` por separado.
    """

    _CLASE_REF = _MultiTriggerScopeRef
