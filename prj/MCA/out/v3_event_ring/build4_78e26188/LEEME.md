# El MCA con el event_ring y los dos generadores (2026-11-09, cuarto build)

`make bitstream-event-ring`, con Vivado 2020.1, sobre el commit `6a5d1aa` y los cambios
sin commitear de ese día. **Probado en la placa el 2026-11-09:** pasa la batería entera
(bus, buffer, MCA, integración, multitrigger, osciloscopio y ring), y `gen_pulsos` por el
lazo digital da los mismos contadores y espectros que la simulación
(`docs/gen_eventos/generador_pulsos.md` §8). Desde libmca 0.9.0 los dos generadores
tienen API, y con ella pasa `make verificar-placa-generadores` (2026-11-09, 60 de 60):
`gen_pulsos` contra la réplica del MCA y `gen_eventos` en el ring, con el patrón.

**Qué cambió respecto del tercer build** (e58f7888, probado en la placa el 2026-11-09,
respaldado en `build3_e58f7888/` con su LEEME):

- **El generador de eventos** (`modulos/gen_eventos/rtl/gen_eventos.sv`), adentro del
  ring (`EN_GEN = 1`), con los registros en 0x4020_0100. Ver
  `docs/event_ring/generador.md`.
- **El generador de pulsos** (`gen_pulsos.sv`) en el lugar del ASG, en 0x4021_0000.
  Maneja `asg_dat` (vuelve como `adc_dat` con `digital_loop[0]`) y la fuente ASG del
  multitrigger. `sys_bus_split` parte el slot 2 entre los dos. Ver
  `docs/gen_eventos/generador_pulsos.md`.
- **`integration_cfg`** anuncia el generador de pulsos: bit 6 de `MODULES` y
  `SLOTS[23:20]` = 2. libmca los lee desde 0.9.0.
- **El arreglo de la parada del ring:** DRAINING espera a que se vacíe el `axi_wr_fifo`
  antes de pasar a STOPPED, y el último evento ya no se pierde.
- **La captura del ADC vuelve al IOB.** Con `gen_pulsos` manejando `dac_a`, el mux de
  `digital_loop` dejaba de ser constante y el flop de entrada se iba a la fábrica (un
  primer build, 5131228d, daba 28 CRITICAL WARNING `Place 30-722`). Ahora el dato
  crudo se registra solo, en el IOB, y el mux va en el flop siguiente. **El ADC llega un
  ciclo más tarde a `adc_dat`.** El lazo digital no cambia, y tampoco las latencias
  entre el disparo y el dato.

**Lo que tiene, además:** el MCA del banco con 3 ranuras y 3 formas, el ring en el slot 2
(0x4020_0000, DDR por HP2) y el arreglo del bus. No tiene la captura del osciloscopio a
DDR por AXI (`EN_AXI = 0`).

- **El top** es `rtl/mine/tops/event_ring_red_pitaya_top.sv`, que genera
  `gen_event_ring_top.py` a partir del top del MCA.
- **Timing:** WNS +0.025 ns, WHS +0.025 ns, sin caminos en falla. Los CRITICAL WARNING
  son los 47 de siempre, los mismos que el tercer build.
- **Recursos:** 14 280 LUT (81.1 %), 15 389 FF, 4400 de 4400 slices, 33 tiles de BRAM y
  10 DSP. Por instancia, en `post_route_util_hier.rpt`:

  | | tercer build | este build |
  |---|---|---|
  | `i_mca` | 6261 LUT | 6251 LUT |
  | `i_event_ring` | 1100 LUT | 1537 LUT (378 son `gen_eventos`) |
  | `i_gen_pulsos` | — | 734 LUT, 1 RAMB18, 1 DSP |
  | `i_slot2` (`sys_bus_split`) | — | 35 LUT |
  | `i_scope` | 4089 LUT | 4147 LUT |
  | total | 13 051 LUT, 14 377 FF | 14 280 LUT, 15 389 FF |

- **md5 de `event_ring_red_pitaya_Z10_2CH.bit.bin`:** `78e26188bf55a34a7e9357f22f77d6d9`.

**Para probarlo**, en la placa, sin tocar el enlace `/root/mca_red_pitaya.bit.bin` (ya
está copiado en `/root/event_ring_red_pitaya_Z10_2CH.bit.bin`; el e58f7888 quedó en
`/root/event_ring_red_pitaya_Z10_2CH_e58f7888.bit.bin.bak`):

    python3 campanas/preparar_placa.py --cargar --bitstream /root/event_ring_red_pitaya_Z10_2CH.bit.bin
    make verificar-placa-bus
    make verificar-placa-ring

    make verificar-placa-generadores

Los dos generadores se manejan desde libmca 0.9.0: `API/generadores.py` (`GenPulsos`)
y `OsciloscopeRing.gen_*`. El MAGIC de `gen_pulsos` es `0x50554C31` ("PUL1") en
0x4021_0020.

---

**Respaldo (2026-11-13).** Este directorio guarda el cuarto build tal como estaba en
`out/v3_event_ring/` antes del quinto (el que trae `trig_arm` / `t_rearm`).
`bd_system_antes_del_build.tar.gz` es `.srcs/sources_1/bd/system` antes del quinto build:
el build lo regenera y se restauró de acá.
