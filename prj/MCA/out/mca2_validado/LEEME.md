# MCA2 validado en placa (2026-10-30)

Es el bitstream con el que `test_mca2_placa.py` dio 349 PASS: MCA2 con `N_ACC = 4`
ranuras, sin trapecio (`CAPS` = 0x3), y el multitrigger sin polo-cero. Se trajo de la
placa el 2026-11-05, antes de cargar el del banco de trapecios, porque era la única copia.

- **md5 de `mca_red_pitaya_Z10_2CH.bit.bin`:** `2adc757dcf23ffca4850c84f0a76d8c2`.
- **En la placa:** `/root/mca_red_pitaya_Z10_2CH_MCA2_validado.bit.bin.bak`.

Para cargarlo:

    fpgautil -b mca_red_pitaya_Z10_2CH.bit.bin
