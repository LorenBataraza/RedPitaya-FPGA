# El MCA con el event_ring (2026-11-08, segundo build)

`make bitstream-event-ring`, con Vivado 2020.1, sobre el commit `6a5d1aa` y los cambios
sin commitear de ese día.

**En la placa (2026-11-09):** `make verificar-placa-bus` pasa (0 lecturas rotas de
`wp_cur` y de `TS_LO` en 2 millones cada una; el bitstream del MCA, sin el arreglo, da
876), `make verificar-placa-ring` pasa entero, y `run_poisson_loss.py --fuente ring`
corre sin cortarse de 396 Hz a 100 kHz: la pérdida es la del apilamiento del estímulo,
el ring no descarta nada hasta 50 kHz, y a 100 kHz descarta el 1.1 % porque el escritor
no da abasto. Las tablas, en `docs/API/arquitectura_adquisicion_software.md`; los datos,
en `software/datos/placa_ring_20261109/`.

**Qué cambió respecto del primer build** (md5 `4e9326d8…`, el que se probó en la placa
ese día): sólo el bus de sistema. `rtl/sys_bus_cdc.sv` congela el dato leído en el ack
del esclavo (`reg_rdata`) antes de cruzarlo a `clk_fpga_0`, y `sdc/red_pitaya.xdc`
acota ese cruce con `set_max_delay -datapath_only 8` en vez del `false_path` que no
enganchaba nada. Ver `docs/TOP/bus_sistema_redpitaya.md` §6.1.

**Lo que dio el primer build en la placa:** `make verificar-placa-ring` pasó entero
(plumbing, trigger por SW y el lector de C, 14 de 14; la onda calibrada en C es igual al
slot crudo). `run_poisson_loss.py --fuente ring` falló: el lector de C se cortó con
`MCA_EVERIFY` por una lectura rota de `WR_SLOT`, que es lo que arregla este build. Con
el ring lleno, además, la parada no termina (`DRAINING` espera créditos), y eso este
build no lo cambia: `CTRL ← 0x2` lo destraba. Datos en
`software/datos/placa_ring_20261108/`.

- **Lo que tiene:** lo mismo que el bitstream del MCA (`out/mca_red_pitaya_Z10_2CH.bit.bin`,
  el del banco de trapecios y el disparo con polo-cero), más el event_ring en el slot 2
  (0x4020_0000), que escribe a la DDR por HP2. Ventanas de hasta 1024 muestras por canal
  (`PRE_AW = 11`, `DATA_AW = 12`) y el writer acelerado. Tiene además los dos arreglos
  que encontró `tb_ring_sistema` el 2026-11-06 (TRIG_SW por flanco, el snapshot del
  mismo evento) y el del bus, que el bitstream del MCA, del 2026-11-03, no tiene.
- **Lo que no tiene:** la captura del osciloscopio a DDR por AXI (`rp_axi_sm`, con
  `EN_AXI = 0`), que el ring reemplaza: `rp_AcqAxi*` de librp no anda. La BRAM del
  osciloscopio sigue.
- **El top** es `rtl/mine/tops/event_ring_red_pitaya_top.sv`, que genera
  `gen_event_ring_top.py` a partir del top del MCA.
- **Timing:** WNS +0.151 ns, WHS +0.015 ns, sin caminos en falla y sin `phys_opt`
  post-ruta. El cruce `reg_rdata → RDATA` son 32 caminos, el peor de 5.15 ns contra 8.
- **Recursos:** 14 404 LUT (81.8 %), 15 369 FF, 4400 de 4400 slices, 34 tiles de BRAM y
  10 DSP. Por instancia, en `post_route_util_hier.rpt`:

  | | MCA | ring, primer build | ring, este build |
  |---|---|---|---|
  | `i_event_ring` | — | 1102 LUT, 1047 FF, 5 RAMB36 | 1100 LUT, 1047 FF, 5 RAMB36 |
  | `i_scope` | 4918 LUT, 8 RAMB36 | 4078 LUT, 6 RAMB36 | 4072 LUT, 6 RAMB36 |
  | `ps` (los `axi_master`) | 947 LUT | 827 LUT | 830 LUT |
  | total | 14 257 LUT | 14 402 LUT, 15 135 FF | 14 404 LUT, 15 369 FF |

  El arreglo del bus cuesta 232 flops (`reg_rdata`; los de los slots con stub quedan en
  constante y se van) y ningún slice.

- **md5 de `event_ring_red_pitaya_Z10_2CH.bit.bin`:** `726da4510517fe7b8040bd20d8a473d4`.

La región de DDR donde escribe el ring es `labuf` (0x0A00_0000, 32 MB) del device tree
de la placa, prestada del analizador lógico: ver `docs/event_ring/diseno_y_register_map.md`.

Para probarlo, en la placa, sin tocar el enlace `/root/mca_red_pitaya.bit.bin`:

    python3 campanas/preparar_placa.py --cargar --bitstream /root/event_ring_red_pitaya_Z10_2CH.bit.bin
    make verificar-placa-bus         # las lecturas de un registro que cambia: tiene que pasar
    make verificar-placa-ring        # plumbing, trigger por SW y el lector de C
    bash -lc 'python3 campanas/run_poisson_loss.py <dir> --rhos 0.1,0.5,1,2 --fuente ring'

`bash -lc` porque el módulo `rp` sólo está en el path con un login. Al terminar,
`preparar_placa.py --cargar` vuelve al bitstream del MCA.
