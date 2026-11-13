# Respaldo: el MCA de 3 ranuras y 3 formas (6156e5a3)

El bitstream del MCA que quedó por defecto en la placa el 2026-11-09: 3 ranuras, 3 formas
(64/48, 32/24, 8/8) y el arreglo del bus. Ver `docs/mca/pruebas_banco_trapecios.md` §7.

El 2026-11-12 lo reemplazó en `out/` el que agrega el re-armado del disparo (`t_rearm` en
0x0D8 del MCA, `trig_arm` del multitrigger). Está acá para volver a él sin rearmarlo, y
porque no está commiteado.

- `mca_red_pitaya_Z10_2CH.bit.bin`: md5 `6156e5a33c588916f3710ac6726ff1a9`
- `build_Z10_2CH.log`, `post_route_util.rpt`, `post_route_timing_summary.rpt`, `post_route.dcp`
- `bd_system_antes_del_build.tar.gz`: los archivos del block design de `.srcs/` como
  estaban antes del build nuevo (modificados respecto de git). Se restauran con
  `tar xzf out/mca_6156e5a3/bd_system_antes_del_build.tar.gz` desde `prj/MCA`.
