# Respaldo: el MCA con 4 ranuras y 4 formas (c1be6d6d)

El bitstream del MCA que se midió en la placa del 2026-11-05 al 2026-11-09: el banco de
trapecios 64/48, 32/24, 16/12, 8/8 con el disparo con polo-cero, y 4 ranuras. Armado el
2026-11-03 con Vivado 2020.1; LUT 14 257 (81.0 %), 4394 de 4400 slices, WNS +0.007 ns.
Tiene el CDC viejo del bus (`rtl/sys_bus_cdc.sv` sin `reg_rdata`): lee mal los
contadores que cambian (876 lecturas rotas de `wp_cur` en 2 millones).

El 2026-11-09 lo reemplazó en `out/` el de 3 ranuras y 3 formas (6156e5a3), que trae
además el arreglo del bus: ver `docs/mca/pruebas_banco_trapecios.md` §7. Está acá para
volver a él sin rearmarlo, y porque no está commiteado. En la placa sigue como
`/root/mca_red_pitaya_Z10_2CH.bit.bin` hasta que se cargue el nuevo.

- `mca_red_pitaya_Z10_2CH.bit.bin`: md5 `c1be6d6db41c7837cd2e111d8a3d2d33`
- `build_Z10_2CH.log`, `post_route_util.rpt`, `post_route_timing_summary.rpt`, `post_route.dcp`
