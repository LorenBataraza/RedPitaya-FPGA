# El MCA con el event_ring y los dos generadores (2026-11-13, quinto build)

`make bitstream-event-ring`, con Vivado 2020.1 (7 min), sobre el commit `6a5d1aa` y los
cambios sin commitear hasta el 2026-11-13. **Sin probar en la placa.**

**Qué cambió respecto del cuarto build** (78e26188, probado en la placa el 2026-11-09,
respaldado en `build4_78e26188/` con su LEEME): sólo el **re-armado del disparo en el
teselado del MCA**, lo mismo que el bitstream del MCA `cce7b66b` (validado en la placa el
2026-11-13, ver `docs/mca/tiempo_muerto.md`):

- el multitrigger da `trig_arm` (nivel: algún canal puede disparar), que el top lleva
  a `mca_top.trig_arm_i`; se lee en `SHIELD_STAT` bit 18 (0x4030_0014);
- el MCA cuenta en `t_rearm` (0x0D8/0x0DC) los ciclos con ranura libre y el disparo sin
  re-armar, y el teselado pasa a
  `realtime = vetotime + t_win + t_div + t_rearm + livetime`; bit 4 de STATUS
  (0x010) = `rearm_pend`;
- hace falta libmca 0.11.0 (`t_rearm_s`, `rearm_pend`, `deadtime_real_s` con
  `t_rearm`, `trig_arm` en `multitrigger_get_status`).

Todo lo del cuarto build sigue: los dos generadores, el arreglo de DRAINING, la captura
del ADC en el IOB, el MCA con 3 ranuras y 3 formas, el arreglo del bus, sin
`rp_axi_sm` (`EN_AXI = 0`).

- **El top** es `rtl/mine/tops/event_ring_red_pitaya_top.sv`, regenerado con
  `gen_event_ring_top.py` desde el del MCA (`--check` pasa).
- **Timing:** WNS +0.008 ns, WHS +0.040 ns, sin caminos en falla. Los CRITICAL WARNING
  son los 47 de siempre (`set_false_path` sobre pines que este top no tiene), los mismos
  que el cuarto build.
- **Recursos:** 14 358 LUT (81.6 %), 15 513 FF, 4400 de 4400 slices, 33 tiles de BRAM y
  10 DSP. Por instancia, en `post_route_util_hier.rpt`:

  | | cuarto build | este build |
  |---|---|---|
  | `i_mca` | 6251 LUT, 5549 FF | 6293 LUT, 5662 FF |
  | `mt_event_logic` | 112 LUT, 94 FF | 151 LUT, 105 FF |
  | `i_scope` | 4147 LUT | 4193 LUT |
  | `i_event_ring` | 1537 LUT | 1527 LUT |
  | total | 14 280 LUT, 15 389 FF | 14 358 LUT, 15 513 FF |

- **md5 de `event_ring_red_pitaya_Z10_2CH.bit.bin`:** `c18759198f36f5aa426bb49e69924429`.

El build regeneró `.srcs/sources_1/bd/system`; se restauró del respaldo de
`build4_78e26188/` (quedan sin seguimiento los directorios `ip/*_30` y `*_31` nuevos).

**Para probarlo**, en la placa, sin tocar el enlace `/root/mca_red_pitaya.bit.bin`:
copiarlo a `/root/event_ring_red_pitaya_Z10_2CH.bit.bin` (respaldar antes el 78e26188),
compilar libmca 0.11.0 allá, y

    python3 campanas/preparar_placa.py --cargar --bitstream /root/event_ring_red_pitaya_Z10_2CH.bit.bin
    make verificar-placa-bus
    make verificar-placa-ring
    make verificar-placa-generadores
