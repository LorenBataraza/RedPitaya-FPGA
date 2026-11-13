# El MCA con el event_ring (2026-11-09, tercer build)

`make bitstream-event-ring`, con Vivado 2020.1, sobre el commit `6a5d1aa` y los cambios
sin commitear de ese día. **Probado en la placa el 2026-11-09:** pasan `verificar-placa-bus`
y `verificar-placa-ring`, y `run_poisson_loss.py --fuente ring` da lo mismo que el segundo
build, sin descartes ni a 100 kHz (datos en `software/datos/placa_recorte_20261109/`).

**Qué cambió respecto del segundo build** (726da451, el que se probó en la placa el
2026-11-09, respaldado en `build2_726da451/` con su LEEME): sólo el MCA, que pasó a
**3 ranuras y 3 formas** (64/48, 32/24, 8/8). En el golden model sobre trazas de la
placa da 647 buenos/s a 1 Mcps, contra 650 con 4 y 4. Ver
`docs/mca/pruebas_banco_trapecios.md` §7. El arreglo del bus del segundo build sigue.

**Lo que NO tiene, y está en el RTL de ese mismo día:**

- **El generador de eventos** (`modulos/gen_eventos`, `EN_GEN = 1`): ver
  `docs/event_ring/generador.md`.
- **El arreglo de la parada:** DRAINING esperaba sólo al writer, y el `flush` de STOPPED
  tiraba el footer del último slot si seguía en el `axi_wr_fifo`. Con este bitstream, el
  último evento de cada adquisición puede quedar sin commit.

**Lo que dio el primer y el segundo build en la placa** está en `build2_726da451/LEEME.md`.
En resumen:

- `verificar-placa-ring` pasa;
- con el bus arreglado, `run_poisson_loss.py --fuente ring` corre de 396 Hz a 100 kHz
  con la pérdida igual al apilamiento del estímulo;
- con el ring lleno, la parada no termina (`CTRL ← 0x2` la destraba).

- **Lo que tiene:**
  - el MCA del banco con el disparo con polo-cero, ahora con 3 y 3;
  - el event_ring en el slot 2 (0x4020_0000), que escribe a la DDR por HP2, con
    ventanas de hasta 1024 muestras por canal y el writer acelerado;
  - los arreglos de `tb_ring_sistema` (TRIG_SW por flanco, el snapshot del mismo evento);
  - el arreglo del bus.
- **Lo que no tiene:** la captura del osciloscopio a DDR por AXI (`rp_axi_sm`,
  `EN_AXI = 0`), que el ring reemplaza. La BRAM del osciloscopio sigue.
- **El top** es `rtl/mine/tops/event_ring_red_pitaya_top.sv`, que genera
  `gen_event_ring_top.py` a partir del top del MCA.
- **Timing:** WNS +0.163 ns, WHS +0.018 ns, sin caminos en falla.
- **Recursos:** 13 051 LUT (74.2 %), 14 377 FF, 4370 de 4400 slices (el placer reparte la
  lógica en todos los que haya), 32.5 tiles de BRAM y 9 DSP. Por instancia, en
  `post_route_util_hier.rpt`:

  | | segundo build | este build |
  |---|---|---|
  | `i_mca` | 7642 LUT | 6261 LUT |
  | `i_event_ring` | 1100 LUT, 5 RAMB36 | 1100 LUT, 5 RAMB36 |
  | `i_scope` | 4072 LUT | 4089 LUT |
  | total | 14 404 LUT, 15 369 FF | 13 051 LUT, 14 377 FF |

- **md5 de `event_ring_red_pitaya_Z10_2CH.bit.bin`:** `e58f78884f579cf839a76c12bd363375`.

La región de DDR donde escribe el ring es `labuf` (0x0A00_0000, 32 MB) del device tree
de la placa, prestada del analizador lógico: ver `docs/event_ring/diseno_y_register_map.md`.

Para probarlo, en la placa, sin tocar el enlace `/root/mca_red_pitaya.bit.bin`:

    python3 campanas/preparar_placa.py --cargar --bitstream /root/event_ring_red_pitaya_Z10_2CH.bit.bin
    make verificar-placa-bus         # las lecturas de un registro que cambia
    make verificar-placa-ring        # plumbing, trigger por SW y el lector de C
    bash -lc 'python3 campanas/run_poisson_loss.py <dir> --rhos 0.1,0.5,1,2 --fuente ring'

`bash -lc` porque el módulo `rp` sólo está en el path con un login. Al terminar,
`preparar_placa.py --cargar` vuelve al bitstream del MCA. **La placa todavía tiene el
726da451 en `/root/event_ring_red_pitaya_Z10_2CH.bit.bin`**: hay que copiar este antes.
