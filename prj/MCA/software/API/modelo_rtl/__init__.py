"""Espejos en software de contratos del RTL.

No son tests ni simulaciones: son **la definición del lado software** de cosas
que el hardware fija, escritas para que exista UNA sola copia que el test
offline, el lector real y la campaña compartan.

    API.modelo_rtl.estimadores    réplica exacta en NumPy de mca_pulse_feature.sv
                                  (segmentar_rtl, psd_rtl), más las alternativas
                                  no-RTL con las que se la compara
    API.modelo_rtl.ring_format    layout de los slots del event_ring en DDR
                                  (decode_slot, footer_is_valid, credits_used)

Vivían bajo `tests/` —en `tests/estimadores/` y `tests/fase0/`— pero no son
tests:
los importan siete ficheros, y el propio RTL los cita como referencia
(`rtl/mine/mca/mca_pulse_feature.sv`, `sim/tb_event_ring_top.sv`). Estar bajo
`API/` les da un path de import estable (`API.modelo_rtl.x`) que se puede citar
desde un `.sv` sin que dependa de dónde vivan los tests.

Que la réplica y el RTL coincidan lo verifica `API/tests/test_estimadores.py`
contra los números de `sim/tb_mca_pulse_feature.sv`.
"""
