# El bus de sistema de la Red Pitaya

Cómo llega una escritura de `/dev/mem` desde el ARM hasta un registro en la PL,
qué contrato tiene que cumplir un esclavo, y cuáles son los modos de falla —
incluido uno que estuvo latente en este diseño hasta el refactor de registros
(§7.1).

Referencia para escribir bloques nuevos. El ejemplo trabajado es
[`mca_top.sv`](../../rtl/mine/mca/mca_top.sv); las decisiones de ese bloque están
en [`decisiones_diseno_mca.md`](../mca/decisiones_diseno_mca.md).

---

## 1. Qué es

No es AXI. Es un bus **propio de Red Pitaya**, muy simple, que cuelga de un
único puerto AXI del PS y se reparte entre 8 esclavos. Existe porque los
bloques de la PL sólo necesitan registros de 32 bits sueltos: montar un
crossbar AXI completo para eso sería desproporcionado en un Zynq-7010.

Características, y sus consecuencias:

| Propiedad | Consecuencia práctica |
|---|---|
| Una sola transacción en vuelo | No hay pipelining: cada acceso paga la latencia completa |
| Sólo transferencias simples (sin ráfagas) | Leer un buffer de 16k palabras son 16k transacciones |
| Lectura y escritura mutuamente excluyentes | — |
| Handshake por `ack`, sin límite de tiempo del lado del esclavo | Un esclavo puede tomarse los ciclos que quiera… **pero si nunca contesta, rompe cosas** (§7) |

---

## 2. Mapa de direcciones

```
0x4000_0000  ┌──────────────────────┐  slot 0   red_pitaya_hk      (LEDs, GPIO, DNA)
0x4010_0000  ├──────────────────────┤  slot 1   OSC                (osc_cfg)
0x4020_0000  ├──────────────────────┤  slot 2   event_ring         (libre en el build MCA)
0x4030_0000  ├──────────────────────┤  slot 3   MULTITRIGGER       (multitrigger_cfg)
0x4040_0000  ├──────────────────────┤  slot 4   red_pitaya_ams     (XADC/PDM)
0x4050_0000  ├──────────────────────┤  slot 5   red_pitaya_daisy
0x4060_0000  ├──────────────────────┤  slot 6   TOP / integración  (integration_cfg)*
0x4070_0000  ├──────────────────────┤  slot 7   MCA                (mca_top)
0x4080_0000  └──────────────────────┘
```

\* El slot 6 no está libre en todas las variantes: en `` `ifdef Z20_G2 `` lo
ocupa `i_serlines_add`. El build del MCA es `xc7z010` con `` `define Z10 ``, así
que esa rama nunca se toma.

Cada módulo propio del proyecto tiene **su slot, su decodificador y su `ack`**.
El detalle de cada región —incluida la ventana de compatibilidad legacy del
OSC, que mantiene vivos los offsets que usa `librp`— está en
[`register_map_top.md`](register_map_top.md).

En el build del MCA los slots 2 (ASG) y 3 (PID) quedaron libres al eliminar
esos módulos; el 3 lo ocupa ahora el multitrigger.

**Parámetros** (`red_pitaya_top.sv:361`):

```systemverilog
sys_bus_interconnect #(.SN (8), .SW (20)) sys_bus_interconnect (...)
```

- `SN = 8` esclavos → `SL = $clog2(8) = 3` bits de selección
- `SW = 20` → cada slot tiene `2^20 = 1 MB`

**Decodificación** (`rtl/sys_bus_interconnect.sv:63-64`):

```systemverilog
assign bus_s_a  = bus_m.addr[SW +: SL];   // addr[22:20] -> índice de slot
assign bus_s_cs = SN'(1) << bus_s_a;      // chip select one-hot
```

El esclavo recibe la dirección **absoluta y sin enmascarar** (p. ej.
`0x40100218`), no un offset. Por eso todos decodifican sobre `sys_addr[19:0]` y
simplemente ignoran los bits altos.

### Aliasing

La ventana asignada a GP0 es de **1 GB** (`ip/systemZ10.tcl:883`:
`-offset 0x40000000 -range 0x40000000`), pero el interconnect sólo mira
`addr[22:20]`. Los bits `[31:23]` **no se decodifican**, así que el bloque de
8 MB se repite cada 8 MB hasta `0x7FFF_FFFF`.

Consecuencia: `0x4000_0000` y `0x4080_0000` son **la misma dirección física**.
No es un problema en la práctica, pero explica por qué agregar un slot 9 exige
cambiar `SN` y no basta con elegir una dirección más alta.

---

## 3. La cadena completa

```
   ARM  (/dev/mem, mmap)
    │
    │  AXI4  @ clk_fpga_0 = 125 MHz
    ▼
  PS7  M_AXI_GP0
    │
    ▼
  axi4_slave              rtl/axi4_slave.sv
    │   traduce AXI -> sys_bus. Impone: sin ráfagas, una transacción
    │   en vuelo, y un TIMEOUT de 32 ciclos (§7).
    ▼
  ps_sys  (sys_bus_if)    @ fclk[0]
    │
    ▼
  sys_bus_interconnect    rtl/sys_bus_interconnect.sv
    │   decodifica addr[22:20], hace broadcast de addr/wdata,
    │   habilita wen/ren sólo del slot seleccionado,
    │   y multiplexa rdata/err/ack de vuelta.
    │
    ├── sys_bus_cdc ──► sys[0]  ─► red_pitaya_hk
    ├── sys_bus_cdc ──► sys[1]  ─► rp_scope_multitrigger_com  (contiene osc_cfg)
    ├── sys_bus_cdc ──► sys[3]  ─► multitrigger_cfg
    ├── sys_bus_cdc ──► sys[6]  ─► integration_cfg
    │        ...                        (un CDC por slot)
    └── sys_bus_cdc ──► sys[7]  ─► mca_top          @ adc_clk
```

Detalle importante del interconnect (`sys_bus_interconnect.sv:96-97, 123-125`):

```systemverilog
assign bus_int_i[i].wen = bus_s_cs[i] & bus_m.wen;   // sólo el slot elegido
assign bus_int_i[i].ren = bus_s_cs[i] & bus_m.ren;
...
assign bus_m.rdata = bus_s_rdata[bus_s_a];           // mux de retorno
assign bus_m.ack   = bus_s_ack  [bus_s_a];
```

`addr` y `wdata` van a **todos** los esclavos; lo que discrimina es `wen`/`ren`.

---

## 4. La interfaz `sys_bus_if`

`rtl/interface/sys_bus_if.sv`:

```systemverilog
interface sys_bus_if #(
  int unsigned DW = 32, int unsigned AW = 32, int unsigned SW = DW/8
)(input logic clk, input logic rstn);
  logic          wen  ;   // write enable
  logic          ren  ;   // read enable
  logic [AW-1:0] addr ;   // dirección ABSOLUTA de 32 bits
  logic [DW-1:0] wdata;
  logic [DW-1:0] rdata;
  logic          ack  ;
  logic          err  ;
  modport m (input clk, rstn, output wen, ren, addr, wdata, input rdata, ack, err);
  modport s (input clk, rstn, wen, ren, addr, wdata, output rdata, ack, err);
endinterface
```

Siete señales. No hay `strobe` de bytes: **todos los accesos son de 32 bits**.

---

## 5. Los dos dominios de reloj

Éste es el punto que más confusión genera:

| Dominio | Reloj | Origen |
|---|---|---|
| Controlador | `clk_fpga_0` (`fclk[0]`) | PS7, 125 MHz (`ip/systemZ10.tcl:384`) |
| Registros | `adc_clk` | PLL alimentado por el reloj del ADC, 125 MHz |

**Son 125 MHz los dos, pero son ASÍNCRONOS**: vienen de fuentes distintas y no
tienen relación de fase. Por eso hace falta un CDC por slot, y por eso los
`set_max_delay -datapath_only` del XDC.

En el top, los 8 esclavos se declaran directamente en `adc_clk`
(`red_pitaya_top.sv:226-227`):

```systemverilog
sys_bus_if ps_sys      (.clk (fclk[0]), .rstn (frstn[0]));
sys_bus_if sys [8-1:0] (.clk (adc_clk), .rstn (adc_rstn));
```

**Un esclavo nuevo no necesita CDC propio**: ya trabaja en `adc_clk` y el cruce
lo hace el interconnect.

---

## 6. El handshake del CDC

`rtl/sys_bus_cdc.sv`. Es un **handshake por toggle**, no un FIFO.

**Lado controlador** (`fclk[0]`):

```systemverilog
if ((ctrl_do == ctrl_done_csff[2]) && (ctrl_we_iw || ctrl_re_iw))
   ctrl_do <= !ctrl_do ;                      // arranca una transacción
ctrl_done_csff <= {ctrl_done_csff[1:0], reg_done} ;   // sincroniza la vuelta

assign ctrl_ack = ctrl_done_csff[1] != ctrl_done_csff[2] ;  // pulso de 1 ciclo
```

**Lado registros** (`adc_clk`):

```systemverilog
reg_do <= reg_do_csff[1];                     // ctrl_do sincronizado
if (reg_ack_sync) reg_done <= reg_do ;        // reg_ack_sync = (rd||wr) && bus_m.ack

assign reg_write_synced = (reg_do != reg_done) && reg_we_csff[1] ;
assign reg_read_synced  = (reg_do != reg_done) && reg_re_csff[1] ;

reg_write <= reg_write ? !bus_m.ack : reg_write_synced ;
reg_read  <= reg_read  ? !bus_m.ack : reg_read_synced ;
```

Lo que hay que retener:

1. **`wen`/`ren` quedan altos hasta el ack**, típicamente ~5 ciclos. Un esclavo
   que ejecute su `case` incondicionalmente lo va a ejecutar **varias veces por
   transacción**. Si algún registro es autolimpiante o dispara un pulso, hace
   falta un estrobo de un ciclo (§8).
2. **`addr` y `wdata` quedan estables** toda la transacción
   (`sys_bus_cdc.sv:132-139`), así que se pueden usar directo como dirección de
   BRAM.
3. **La transacción avanza SÓLO cuando el esclavo hace `ack`**: `reg_done` se
   actualiza únicamente con `reg_ack_sync`. De ahí sale el modo de falla de §7.
4. `bus_s.rdata = pll_locked_i ? bus_m.rdata : 32'hDEADBEEF`
   (`sys_bus_cdc.sv:74`): **leer `0xDEADBEEF` significa que el PLL del ADC no
   está enganchado**, no que el registro valga eso.

Costo: unos **8-12 ciclos de ida y vuelta** por acceso.

---

## 7. Modos de falla

### 7.1 El grave: un esclavo que nunca hace `ack`

Es un **deadlock latente** del slot, no un simple error de lectura.

Si `sys_ack` nunca se levanta para una dirección:

1. `reg_done` nunca alcanza a `reg_do` → **`reg_do != reg_done` para siempre**.
2. `reg_read` (o `reg_write`) **queda alto permanentemente**: sólo se limpia con
   `bus_m.ack`.
3. Del lado controlador, `ctrl_done_csff` nunca cambia, así que
   `ctrl_do == ctrl_done_csff[2]` es **falso para siempre** → **`ctrl_do` no
   puede volver a togglear**: el CDC de ese slot no acepta más transacciones.
4. Mientras tanto, arriba, `axi4_slave.sv:180-193` salva al ARM:

   ```systemverilog
   assign ack = bus.ack || ack_cnt[5] || (rd_do && rd_errorw) || (wr_do && wr_errorw);
   ```

   `ack_cnt` es de 6 bits: a los **32 ciclos** de `clk_fpga_0` el AXI slave
   **fabrica un ack por su cuenta**, completa la transacción y devuelve lo que
   haya en `axi.RDATA` (que sigue a `bus.rdata` ciclo a ciclo,
   `axi4_slave.sv:174`).

**Resultado neto:** el ARM no se cuelga —el timeout lo rescata— pero
- el acceso tarda 32 ciclos en vez de ~12,
- devuelve un valor sin sentido **sin ninguna indicación de error**, y
- **el CDC del slot queda desincronizado**, con el strobe de lectura pegado en
  alto y la máquina del lado controlador incapaz de arrancar otra transacción.

El slot se "descongela" recién si una transacción posterior consigue un ack
—porque `reg_read_synced` sigue activo y `bus_m.addr` se sigue actualizando, así
que un acceso a una dirección válida sí puede hacer ack y destrabar el
handshake— pero ese acceso también sale corrupto.

**Conclusión de diseño: un esclavo tiene que hacer `ack` de TODA dirección de su
slot, mapeada o no.** El timeout de `axi4_slave` es una red de seguridad, no
parte del protocolo.

#### El caso concreto que hay en el árbol

`multitrigger_rp_scope_cfg.sv:504-507` decodifica cuatro aperturas de BRAM, una
por canal:

```systemverilog
20'h1???? : begin sys_ack <= bram_ack_i[0]; sys_rdata <= ...bram_rd_dat_i[0]...; end
20'h2???? : begin sys_ack <= bram_ack_i[1]; sys_rdata <= ...bram_rd_dat_i[1]...; end
20'h3???? : begin sys_ack <= bram_ack_i[2]; sys_rdata <= ...bram_rd_dat_i[2]...; end
20'h4???? : begin sys_ack <= bram_ack_i[3]; sys_rdata <= ...bram_rd_dat_i[3]...; end
```

Pero el scope se instancia con `N_CH = 2`, así que los canales 2 y 3 no existen,
y un lazo de relleno los ata a cero (`rp_scope_multitrigger_com.sv:572-573`):

```systemverilog
assign bram_rd_dat[(GM+1)*DW-1:GM*DW] = {DW{1'b0}};
assign bram_ack[GM]                   =  1'b0;      // <-- ack CONSTANTE 0
```

Entonces **cualquier lectura en `0x4013_0000`–`0x4014_FFFF` cae en el escenario
de arriba**: `sys_ack <= 1'b0` para siempre.

El `ack` de las aperturas buenas viene de `rp_acq_bram.v:50-56`, que es un
registro de desplazamiento de 4 etapas alimentado por `sys_en`:

```systemverilog
adc_rval <= {adc_rval[2:0], bram_ack_i};   // bram_ack_i = sys_en
assign bram_ack_o = adc_rval[3];
```

O sea que el ack **se genera a partir de la señal de habilitación**, no de nada
que confirme que la lectura ocurrió. Es un ack "a ciegas" con latencia fija — lo
cual funciona, pero deja el patrón expuesto a que alguien lo ate a cero.

**Estado: ARREGLADO.** `osc_cfg` reemplazó a `multitrigger_rp_scope_cfg` y hace
`ack` de latencia fija para toda dirección, sin ninguna ruta de `ack` por
canal. Para los canales que sí existen el timing no cambió: `rp_acq_bram`
generaba `bram_ack_o` = `sys_en` retrasado 4 ciclos, que es exactamente el
`en_sr[3]` del esquema de §8.

`tb_osc_cfg` instancia los dos módulos y barre las mismas direcciones: **cero**
timeouts en el nuevo, **cuatro** en el viejo (`0x30000`, `0x40000`, `0x3FFFC`,
`0x4FFFC`). Esos cuatro accesos son la evidencia del bug y la regresión que
impide que vuelva.

Antes del arreglo era latente, no activo: el driver mapea
`SCOPE_SIZE = 0x30000` (`multitrigger_utils.py:40`), o sea offsets
`0x00000`–`0x2FFFF`, y nunca tocaba las aperturas rotas. Se habría disparado con
un `N_CH` distinto, un barrido de direcciones, o un off-by-one en un lazo de
lectura.

**Cómo lo evita `mca_top`**: ack de latencia fija desde un shift register
incondicional, sin ninguna ruta de ack por motor (§8). `tb_mca_top.sv` es la
regresión: barre todas las direcciones —incluidas las de motores apagados por
parámetro y las no mapeadas— y **falla si el ack no llega en ≤20 ciclos**.

### 7.2 Ráfagas y anchos raros

`axi4_slave.sv:101-102`:

```systemverilog
assign wr_errorw = (axi.AWLEN != 4'h0) | ~((axi.AWSIZE == 3'b010) | (axi.AWSIZE == 3'b001));
assign rd_errorw = (axi.ARLEN != 4'h0) | ~((axi.ARSIZE == 3'b010) | (axi.ARSIZE == 3'b001));
```

Ráfaga (`LEN != 0`) o transferencia que no sea de 4 o 2 bytes → error inmediato,
sin llegar al esclavo. Por eso **desde Python hay que escribir de a 32 bits
alineados**.

### 7.3 Lecturas MASIVAS: reinician la placa

**Verificado en hardware.** Un `np.frombuffer(mem, ...).copy()` de 16384
palabras sobre una apertura de la PL **reinicia la Red Pitaya**. Las mismas
16384 direcciones leídas de a una funcionan perfecto.

| Patrón | Resultado |
|---|---|
| 16384 lecturas de 32 b, de a una | OK, 6.7 us cada una (110 ms en total) |
| `np.frombuffer(...).copy()` del mismo rango | **REINICIA la placa** |
| 646 lecturas sueltas, incluidas direcciones no mapeadas | OK |

La causa es §7.2: el `memcpy` que hay detrás de la copia emite accesos anchos
(LDRD/NEON) o en ráfaga, y `axi4_slave` los rechaza. El error de AXI se propaga
como *external abort* y en esta placa **no da SIGBUS: reinicia el sistema**, sin
dejar nada en dmesg (sólo se nota porque `/proc/uptime` se resetea).

Reproducible con `prj/MCA/software/API/tests/placa/diag_mca_hw.py`, pasos `bulk` y `word`.

> **Ojo con el código existente.** `API/bench/bench_reader_budget.py` usa el mismo
> patrón (`np.frombuffer` + slicing) sobre las aperturas del scope. Que no haya
> dado problemas puede deberse a que las rebanadas son chicas y el memcpy no
> llega a usar instrucciones anchas — conviene revisarlo.

### 7.4 `struct.pack_into` sobre `/dev/mem`

No es del bus, pero se manifiesta acá y cuesta caro. `pack_into` hace un
`memset` previo que sobre memoria de dispositivo sale como **stores de a byte**;
el esclavo AXI no los reconoce, la transacción no se completa y el puente GP0
tira un *external abort* → **SIGBUS** (en Jupyter: "el kernel murió"). Hay que
escribir por asignación de slice, que es un `memcpy` alineado de 4 bytes. Ver
`multitrigger_utils.py:393-403` y `API/tests/placa/test_rw_dev_mem.py`.

---

## 8. El contrato del esclavo

Lo mínimo para no romper nada:

```systemverilog
wire sys_en = sys_wen | sys_ren;

// Estrobo de UN ciclo: wen/ren quedan altos hasta el ack (~5 ciclos), así que
// sin esto el case se ejecuta varias veces por transacción.
reg [7:0] en_sr;
always @(posedge adc_clk_i) en_sr <= {en_sr[6:0], sys_en};
wire rd_stb = sys_en && !en_sr[0];
wire wr_stb = sys_wen && !en_sr[0];

always @(posedge adc_clk_i)
  if (!adc_rstn_i) begin sys_ack <= 1'b0; sys_err <= 1'b0; end
  else begin
    sys_err   <= 1'b0;
    sys_ack   <= en_sr[3];     // 4 ciclos FIJOS, para CUALQUIER dirección
    sys_rdata <= rdata_mux;    // registro plano
  end
```

Reglas:

1. **Hacer `ack` de toda dirección del slot**, mapeada o no (§7.1). El `default`
   del `casez` también.
2. **Latencia fija en vez de ack por camino.** Si el ack sale de una señal que
   puede quedar constante en cero, es una bomba de tiempo.
3. **Presupuesto: ~20 ciclos.** Son 32 de timeout menos ~8-12 del CDC.
4. **`sys_rdata` tiene que ser un registro plano.** El XDC trae un
   `set_false_path` sobre `inst_sys_bus_cdc/reg_rdata*`, pero `sys_bus_cdc.sv`
   **no tiene ese registro** (hace `assign bus_s.rdata = ...`), así que la
   restricción no engancha nada y el cruce de datos de lectura se timea de
   verdad, con ~0.94 ns de margen. Nada de lógica combinacional ancha ahí.
5. **`sys_err` en `1'b0`.** El único que devuelve `err=1` es `sys_bus_stub`
   (`rtl/sys_bus_stub.sv:11-13`), y eso es útil: permite distinguir "slot vacío"
   de "slot ocupado". Aun así conviene poner un valor mágico de identificación
   en el offset 0 del bloque, que es más explícito.
6. En el `casez`, los matches exactos **antes** de los comodines, y nunca un
   comodín que se trague el archivo de registros (`20'h0????`).

---

## 9. Restricciones (XDC)

`prj/MCA/sdc/red_pitaya.xdc:25-63` — cuatro `set_max_delay -datapath_only 8.000`
por slot, sobre las cuatro señales que cruzan el handshake:

```tcl
set_max_delay -datapath_only 8.000 \
  -from [get_pins sys_bus_interconnect/for_bus[7].inst_sys_bus_cdc/ctrl_do_reg/C] \
  -to   [get_pins sys_bus_interconnect/for_bus[7].inst_sys_bus_cdc/reg_do_csff_reg[0]/D]
# ... reg_done, ctrl_we, ctrl_re
```

**Ya están escritas para `for_bus[0]` hasta `for_bus[7]`**, así que un esclavo
nuevo en el slot 6 o 7 queda constrained sin tocar el XDC.

Dos cosas a saber:

- El nombre de instancia `sys_bus_interconnect` **es parte del contrato**: si se
  renombra, las 32 restricciones dejan de enganchar en silencio. (Lo mismo con
  `i_ams`, por el LOC del XADC en la línea 1.)
- **El parser de XDC de Vivado no soporta `if`**
  (`CRITICAL WARNING [Designutils 20-1307]`). Una guarda condicional anula la
  restricción sin avisar de forma visible.

---

## 10. Rendimiento

Presupuesto por acceso de 32 bits:

| Etapa | Ciclos aprox. |
|---|---|
| AXI + `axi4_slave` | 2-4 |
| CDC ida (toggle + 2-3 flops) | 4-5 |
| Esclavo | 1-5 |
| CDC vuelta | 4-5 |
| **Total** | **~12-20** ≈ 100-160 ns |

Sumado al costo de la llamada desde Python, un `r32()` está en el orden del
microsegundo.

**Implicancia de diseño:** leer un buffer de 16384 muestras son 16384
transacciones ⇒ decenas de milisegundos. Ése era exactamente el cuello de
botella que motivó poner los histogramas en la PL: leer un espectro ya formado
una vez por segundo es gratis; leer formas de onda por evento no.

Para lecturas masivas conviene armar una vista de numpy sobre el mmap **una sola
vez** (crearla cuesta ~200 µs) y después rebanar, en vez de llamar `r32()` en un
lazo. Ver `API/bench/bench_reader_budget.py:193-201`.

Si hiciera falta ancho de banda real, la salida es **AXI-HP** (DMA a DDR), que
es un camino totalmente distinto: los cuatro puertos HP están hoy tomados por el
scope (HP0/HP1) y el ASG (HP2/HP3).

---

## 11. Receta para agregar un esclavo

1. **Elegir slot.** Mirar antes el mapa de §2: en `mca_red_pitaya_top` los slots
   1, 3, 6 y 7 ya están tomados (OSC, MULTITRIGGER, TOP y MCA), y el 0, 4 y 5
   son de RedPitaya. **El único libre es el 2**, reservado para el `event_ring`
   y vacío en el build del MCA. Si hace falta uno más hay que empezar por
   liberar alguno: los ocho son todo el espacio que hay.
2. **Reemplazar el stub** en el top (acá con el slot 2 de ejemplo):
   ```systemverilog
   mi_bloque i_mi_bloque (
     .adc_clk_i(adc_clk), .adc_rstn_i(adc_rstn),
     .sys_addr (sys[2].addr ), .sys_wdata(sys[2].wdata),
     .sys_wen  (sys[2].wen  ), .sys_ren  (sys[2].ren  ),
     .sys_rdata(sys[2].rdata), .sys_err  (sys[2].err  ), .sys_ack(sys[2].ack)
   );
   ```
3. **Implementar el contrato de §8.** Sin CDC propio: ya se está en `adc_clk`.
4. **Poner un valor mágico en el offset 0**, para que el software distinga este
   bitstream de otro.
5. **Testbench con BFM** que sostenga `ren` hasta el ack y **falle si no llega en
   ≤20 ciclos**, barriendo todas las direcciones del slot. `tb_mca_top.sv` sirve
   de plantilla.
6. **Software**: `mmap` en la base del slot elegido, escrituras por slice
   (§7.3), y verificar el magic antes de nada.

---

## 12. Referencias de código

| Archivo | Qué es |
|---|---|
| `rtl/interface/sys_bus_if.sv` | Definición de la interfaz |
| `rtl/axi4_slave.sv` | AXI4 → sys_bus; restricciones de ráfaga; **timeout de 32 ciclos** (L193) |
| `rtl/sys_bus_interconnect.sv` | Decodificación `addr[22:20]`, broadcast, mux de retorno |
| `rtl/sys_bus_cdc.sv` | Handshake por toggle entre `fclk[0]` y `adc_clk` |
| `rtl/sys_bus_stub.sv` | Terminador de slot libre (`ack=1`, `err=1`) |
| `prj/MCA/rtl/red_pitaya_ps.sv` | Instancia del PS7 y del `axi4_slave` de GP0 |
| `prj/MCA/rtl/mine/mca/mca_top.sv` | Esclavo de referencia, con el contrato bien implementado |
| `prj/MCA/sim/tb_mca_top.sv` | BFM y regresión contra el cuelgue de §7.1 |
