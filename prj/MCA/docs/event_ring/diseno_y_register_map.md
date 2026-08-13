# event_ring — diseño y mapa de registros (Fase 1)

Ring de slots de evento en DDR. Reemplaza el ciclo
`capturar → congelar → que el PS lea por GP0 → re-armar` (K=1, τ = 252.7 µs) por
una cola productor/consumidor de N_SLOTS eventos.

## Por qué "ring" y no "arbiter"

El módulo original se llamaba `multievent_arbiter`. Un *árbitro* elige entre
solicitantes que compiten por un recurso; acá no hay competencia: hay **una cola**
con un productor (el PL) y un consumidor (el PS), y el único mecanismo es control
de flujo por créditos. El nombre `event_ring` dice lo que es y anticipa lo que hay
que verificar (wrap, lleno-vs-vacío, commit), que es la mitad del valor de un
nombre. El stub viejo quedó como
`rtl/mine/event_ring/NOTAS_diseno_original.txt`.

## Estructura

```
trigger ──► event_window_capture ──► event_stage_fifo ──► event_slot_writer
            (ventana pre+post)       (E eventos, BRAM)     (serializa el slot)
                                                                  │
                                                          axi_wr_fifo ──► HP2 ──► DDR
                    wr_slot ──────── comparador de créditos ──────── rd_slot (PS)
```

| módulo | archivo | qué hace |
|---|---|---|
| `event_window_capture` | `rtl/mine/event_ring/event_window_capture.sv` | pre-buffer circular + ventana pre/post; cuenta `drop_busy` y `drop_full` |
| `event_stage_fifo` | `.../event_stage_fifo.sv` | buffer elástico de E eventos; garantiza "evento entero o nada" |
| `event_slot_writer` | `.../event_slot_writer.sv` | layout del slot, relleno, footer de commit |
| `event_ring_top` | `.../event_ring_top.sv` | FSM global, créditos, contadores, bus de sistema |

**Un solo dominio de reloj.** `rp_scope_multitrigger_com.sv:686` hace
`assign axi_clk = adc_clk_i`, y el bus llega ya sincronizado a `adc_clk` por
`sys_bus_cdc`. Captura, writer y registros comparten `adc_clk`: **no hace falta
CDC ni codificación Gray** entre `WR_SLOT` y `RD_SLOT`.

## Layout del slot

`SLOT_SZ = 2^SLOT_SHIFT` bytes, escrito siempre completo y en orden creciente de
dirección (el generador del `axi_wr_fifo` es lineal, sin saltos).

| offset | contenido |
|---|---|
| `0x00` | `timestamp[63:0]` — ciclos de `adc_clk` desde el start |
| `0x08` | `{flags[7:0], n_ch[7:0], n_samp[15:0], seq[31:0]}` |
| `0x10` | `{event_id[31:0], 15'b0, snapshot[16:0]}` |
| `0x18` | reservado |
| `0x20…` | muestras int16, 4 por palabra, canales **intercalados**: `ch0[k], ch1[k], ch0[k+1], …` |
| … | relleno de ceros |
| `SLOT_SZ-8` | **footer** `{~seq[31:0], seq[31:0]}` |

### El footer es el commit — y por qué no se usa el BRESP

El plan original decía "incrementar `wr_slot` recién con el `BRESP` del último
burst". Es correcto pero **inaplicable**: ni `axi_wr_fifo` ni `axi_master` exponen
el canal B (`axi_wr_fifo.v` sólo saca `werr`/`wrdy`), así que no hay forma de
observarlo sin tocar RTL compartido con otros proyectos.

La solución estándar de descriptor-ring es mejor y más barata: **una marca al
final**. Todas las escrituras salen por un master con un único ID hacia el mismo
esclavo, y AXI garantiza que las escrituras con el mismo ID se observan en orden.
Si el PS ve el footer del slot con el `seq` esperado, todo lo anterior ya está en
DDR.

Ventaja adicional, y es grande: **el PS no necesita leer ningún registro por GP0
en el lazo caliente**. Polea el footer directamente en DDR, que es más rápido que
una lectura de registro (2.3 µs) y saca el bus GP0 del camino crítico por
completo. `WR_SLOT` queda como diagnóstico.

El footer lleva `{~seq, seq}` para que una lectura vieja o rota se detecte
comparando las dos mitades, sin depender de que "0" sea un valor especial.

## Mapa de registros — slot 2, base `0x4020_0000`

| off | acc | nombre | notas |
|---|---|---|---|
| `0x00` | RW | `CTRL` | `[0]` run, `[1]` clr (autolimpiante) |
| `0x00` | R | | `{gst[2:1], run[0]}` |
| `0x04` | R | `STATUS` | `[2:0]` estado, `[4]` no_credit, `[5]` err_cfg, `[6]` err_slot_ovf, `[7]` fifo_ovf |
| `0x08` | RW | `SLOT_BASE` | dirección física de DDR. **Latchea sólo en STOPPED** |
| `0x0C` | RW | `RING_SZ` | bytes. **Latchea sólo en STOPPED** |
| `0x10` | RW | `SLOT_SHIFT` | `log2(bytes/slot)`. **Latchea sólo en STOPPED** |
| `0x14` | RW | `PRE` | muestras antes del trigger. **STOPPED** |
| `0x18` | RW | `POST` | muestras desde el trigger. **STOPPED** |
| `0x20` | R | `WR_SLOT` | contador libre de slots escritos |
| `0x24` | RW | `RD_SLOT` | lo publica el PS **por batch**, no por evento |
| `0x28` | R | `SEQ` | secuencia del próximo evento |
| `0x2C` | R | `N_SLOTS` | derivado: `RING_SZ >> SLOT_SHIFT`, no es registro |
| `0x30` | R | `DROP_BUSY` | trigger durante el drenaje (tiempo muerto del **PL**) |
| `0x34` | R | `DROP_FULL` | sin lugar aguas abajo (tiempo muerto del **consumidor**) |
| `0x38` | R | `EV_CNT` | eventos capturados |
| `0x3C` | R | `LVL` | `{stage_lvl, ev_lvl}` |
| `0x40/0x44` | R | `TS_LO/HI` | timestamp libre |
| `0x48` | R | `AXI_ADDR` | dirección corriente del `axi_wr_fifo` |
| `0x50` | R | `MAGIC` | `0x45564E54` = `"EVNT"` |

`DROP_BUSY` y `DROP_FULL` están separados a propósito: distinguen "el PL no dio
abasto" de "el PS no dio abasto", que llevan a decisiones opuestas.

### El invariante que antes no se podía escribir

```
EV_CNT + DROP_BUSY + DROP_FULL == triggers inyectados
```

Hoy un segundo trigger mientras el SW lee el anterior **no queda en ningún
contador** (`docs/arquitectura_adquisicion_software.md:463-478`). Con el ring la
pérdida es exacta. Lo verifica `tb_event_ring_top` test [4].

## Secuencia de uso desde el PS

```
1. CTRL ← 0              parar
2. CTRL ← 0x2            clr (limpia contadores y sticky)
3. SLOT_BASE, RING_SZ, SLOT_SHIFT, PRE, POST     (sólo funcionan en STOPPED)
4. CTRL ← 0x1            run
5. lazo:  polear el footer del slot RD_SLOT en DDR
          si seq == esperado -> consumir el batch
          publicar RD_SLOT una vez por batch
6. CTRL ← 0              stop ordenado (DRAINING termina la ventana en vuelo)
```

## Decisiones de diseño que conviene no revertir sin leer esto

- **Descartar, no sobreescribir.** Sin créditos el writer **se frena**; la
  contrapresión sube hasta la captura, que descarta el evento **entero** y lo
  cuenta. Descartar a mitad de slot dejaría basura indistinguible de un evento
  bueno.
- **`s_accept` se consulta en el SOF**, antes de emitir nada: o entra la ventana
  completa o no entra ninguna.
- **Un evento se ofrece al writer recién con su EOF.** Si se ofreciera en el SOF,
  el writer podría drenar más rápido de lo que entran las muestras.
- **`run` y `accept_trig` están separados.** En `DRAINING` se bajan los triggers
  nuevos pero sigue el drenaje, así la parada no trunca la ventana en vuelo.
- **`stop_addr` del `axi_wr_fifo` es INCLUSIVO** (`axi_wr_fifo.v:283` envuelve
  cuando `axi_waddr_o == stop_addr`, o sea escribe ahí). Por eso el top pasa
  `slot_base + ring_sz - 8`. Sin el `-8` el ring pisa la primera palabra que
  sigue a la región reservada.
- **`ctrl_trig_size_i = 4'hF`**, igual que producción (`rp_axi_sm.v:242`). Con un
  umbral más bajo el FIFO arranca ráfagas cortas y repite el último beat cuando
  se queda sin datos a mitad de ráfaga.
- **El writer no puede re-leer el metadato.** El pop se refleja en `s_meta_val`
  un ciclo después; sin el guard `!s_meta_rd_o`, al volver de `W_DONE` se escribe
  el mismo evento dos veces.

## Testbenches

```bash
cd prj/MCA/sim && make        # 13 TB, todos con RESULT: PASS
```

| TB | qué prueba |
|---|---|
| `tb_event_window_capture` | alineación pre/post por VALOR (rampa), sof/eof, drop_busy, drop_full, pre=0, ventana impar |
| `tb_event_stage_fifo` | `s_accept` como promesa, evento ofrecido sólo con EOF, orden, flush |
| `tb_event_slot_writer` | layout, empaquetado little-endian, footer al final **bajo contrapresión aleatoria**, freno por créditos, `err_slot_ovf` |
| `tb_event_ring_top` | punta a punta: wrap del ring, geometría congelada, **absorción de ráfaga + invariante de pérdida**, parada ordenada, contrapresión de AXI |

El TB de integración además vuelca la DDR a
`software/tests/fase0/ring_dump.hex`, que `test_ring_format.py` decodifica con el
mismo Python que usará el lector: un error de endianness o de intercalado se cae
en la PC, sin placa.

## Estado

- [x] RTL de los cuatro módulos + `event_ring_red_pitaya_top.sv` (slot 2, HP2)
- [x] 4 testbenches nuevos, 13/13 de la suite en PASS, sin regresiones
- [x] elaboración del top completa (sólo faltan primitivas Xilinx, que necesitan
      las libs de simulación)
- [x] decodificador de slots en Python + tests offline contra el volcado del RTL
- [ ] **falta: síntesis en Vivado** — no se corrió; hay que verificar timing y
      utilización (baseline: 40/60 RAMB36, 20 libres)
- [ ] falta: device tree con la región reservada, y correr `hw_ring_plumbing.py`
- [ ] falta: la fuente `RingSource` en `mca/sources.py`
