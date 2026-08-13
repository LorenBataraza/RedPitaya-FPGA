# Síntesis v1 — ventana por HISTÉRESIS (previa a las compuertas fijas)

Es el bitstream **validado en placa** con el que se corrieron las dos campañas de
caracterización (ver `docs/mca/resultados_validacion_hw.md`). Se archiva acá
antes de resintetizar con el modo de compuertas fijas (etapa B).

No tiene los registros `0x048` (`cfg_gate_mode`) ni `0x04C` (`cfg_gate_len`):
en este bitstream la ventana **siempre** cierra por histéresis.

Para volver a él:

    fpgautil -b mca_red_pitaya.bit.bin
