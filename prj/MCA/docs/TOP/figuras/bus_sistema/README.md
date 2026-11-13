# Figuras: el protocolo del bus de sistema

Cuatro diagramas de tiempo del handshake entre `clk_fpga_0` (PS) y `adc_clk` (PL).
**No son esquemas**: salen de una simulación del RTL de verdad —
`sys_bus_interconnect`, con un `sys_bus_cdc` por slot, y `mca_top` colgado del
slot 7 — y las latencias que aparecen escritas las mide el script sobre el VCD.

```bash
cd prj/MCA/docs/TOP/figuras/bus_sistema
python3 figuras_bus_sistema.py                # usa el FST versionado de acá al lado
python3 figuras_bus_sistema.py --render cli   # baja wavedrom-cli con npx y saca el SVG
python3 figuras_bus_sistema.py --min-run 0    # sin saltos temporales, la figura entera
```

| Figura | Archivo | Qué muestra |
|---|---|---|
| Escritura en el bus de sistema | [`bus_escritura.svg`](bus_escritura.svg) | Una escritura de punta a punta: el toggle de `ctrl_do`, el cruce de ida, el estrobo de un ciclo del esclavo y el dato aterrizando en el registro |
| Lectura en el bus de sistema | [`bus_lectura.svg`](bus_lectura.svg) | Una lectura: `sys_rdata` se asienta en `adc_clk` mucho antes de que vuelva el `ack`, y **no pasa por ningún sincronizador** — el `ack` es la garantía |
| Lectura a una dirección no mapeada | [`bus_no_mapeada.svg`](bus_no_mapeada.svg) | Una lectura a una dirección que no está en el mapa: devuelve 0 pero **hace `ack` con la misma latencia**. Es la figura del modo de falla de [§7.1](../../bus_sistema_redpitaya.md) |
| La escritura con el CDC por dentro | [`bus_escritura_cdc.svg`](bus_escritura_cdc.svg) | La misma escritura, con el toggle de `ctrl_do`, los sincronizadores y `reg_done`. Es la que acompaña al paso a paso de [§6.1](../../bus_sistema_redpitaya.md) |

## Dos vistas: el protocolo y el CDC por dentro

Las tres primeras dibujan el **CDC como caja negra**: sólo los dos puertos del
bus, el del master (`addr`, `wdata`, `wen`/`ren`, `ack`, `rdata`) y el del
esclavo (`sys_*`, el estrobo y el registro de destino), y cada cruce como una
flecha con lo que tarda medido sobre el VCD (**ida** y **vuelta**). La cuarta
agrega las cinco señales del handshake por toggle: `ctrl_do`, `done_csff[2]`,
`reg_do`, `reg_do != reg_done` y `reg_done`.

Sacar esas cinco no sólo ahorra filas. Mientras el toggle cruza no cambia
ninguna de las señales que quedan, así que `ondas.cortar()` encuentra tramos
quietos más largos y mete un segundo salto temporal: la vista del protocolo
tiene 11-12 señales y 22 columnas, contra 17 señales y 27 columnas de la del
CDC. Qué filas van en cada vista lo decide `filas(vcd, kind, vista)`.

Los epígrafes, con los números recalculados del VCD, están en
[`epigrafes.txt`](epigrafes.txt), que escribe el mismo script.

## Los dos convenios de lectura

Ninguno de los dos se deduce mirando el dibujo, así que están escritos en el
subtítulo del visor, en los epígrafes y en el `.md`:

- **El color del bus dice qué hay ahí.** Azul (`#b9e0ff`) es la **carga útil de
  esa transacción** —la dirección que se va a decodificar, el dato que se
  escribe, el que vuelve—, así que se puede seguir con la vista bajando por la
  figura: `addr` → `sys_addr`, `wdata` → `sys_wdata` → el registro del esclavo.
  Blanco es el bus parado, o todavía con la sobra de la transacción anterior,
  que es lo que se ve en `sys_addr` antes del cruce porque `sys_bus_cdc` sólo
  recarga `bus_m.addr` cuando arranca una transacción nueva.

  Los valores que van en azul los **lee el script del VCD** (`m_addr` y
  `m_wdata` con el enable arriba, `m_rdata` con el ack arriba): no hay ninguna
  dirección escrita a mano que se pueda desincronizar del testbench. El skin
  `default` de WaveDrom no tiene gris, así que el neutro es el blanco con
  contorno: lo que importa es que contraste.

- **El par de eses encontradas es un salto temporal.** Marca un tramo en el que
  no cambia **ninguna** de las señales dibujadas —un sincronizador corriendo, o
  el shift register del esclavo contando sus cuatro ciclos— y que se sacó para
  acortar la figura. De las 31 columnas de la ventana, la vista del CDC
  dibuja 27 con un salto y la del protocolo 22 con dos.

  Lo ubica `ondas.cortar()` midiendo el VCD, no está puesto a mano: busca las
  corridas de columnas quietas de `--min-run` o más (default 5) y les saca el
  centro, dejando `--contexto` columnas de cada lado para que el hueco no quede
  pegado a un flanco. Los relojes quedan afuera del cálculo a propósito, porque
  cambian en cada columna. `--min-run 0` desactiva el corte y la figura sale
  entera. Lo que no se toca es el eje: las latencias de las etiquetas se siguen
  midiendo sobre el VCD y no contando columnas.

Además queda [`bus_protocolo.html`](bus_protocolo.html): las cuatro juntas con sus
notas, renderizadas en el browser desde el CDN. No necesita nada instalado y es
la forma cómoda de mirarlas mientras se edita el testbench.

---

## De dónde salen las ondas

De [`prj/MCA/sim/tb_sys_bus_proto.sv`](../../../../sim/tb_sys_bus_proto.sv), que
es el **único testbench del árbol que instancia el camino completo**. Todos los
demás le hablan al esclavo con un BFM que *imita* al CDC (sostiene `wen`/`ren`
hasta el `ack`), que alcanza para verificar el esclavo pero no puede mostrar el
protocolo: el toggle, los sincronizadores y los dos dominios no existen en esa
simulación.

```bash
cd prj/MCA/sim
make tb_sys_bus_proto                 # corre los chequeos
make vcd TB=tb_sys_bus_proto VCD_ADD="/tb_sys_bus_proto/*"   # waves/tb_sys_bus_proto.vcd
vcd2fst waves/tb_sys_bus_proto.vcd \
        ../docs/TOP/figuras/bus_sistema/tb_sys_bus_proto.fst
```

`VCD_ADD` vuelca sólo el scope raíz del testbench, que es lo único que lee el
script (los espías con nombre plano). Con el default (`-r /*`) entra todo
`mca_top` y el FST pasa de 7 a 100 kB sin cambiar ninguna figura.

Lo que se versiona es el **FST** (7 kB contra 75 kB del VCD), así que las
figuras se regeneran en un clon limpio sin Questa: el script lo destraduce con
`fst2vcd` de la oss-cad-suite. El `.vcd` está en `.gitignore`.

Las tres transacciones se encuentran solas leyendo `dbg_showcase` (1 = escritura,
2 = lectura, 3 = no mapeada) y las fases salen de los flancos reales de
`wen`/`ren`/`ack`. **No hay tiempos hardcodeados**: si cambia el testbench, las
figuras siguen apuntando a donde tienen que apuntar.

## Por qué WaveDrom y no matplotlib

Porque es la herramienta hecha para esto: buses hexagonales, grupos por dominio
de reloj, flechas de causalidad entre señales y salida vectorial. Lo que se paga
es que **WaveDrom dibuja ciclos, no tiempo**, así que el VCD hay que muestrearlo:

- una columna es un **semiciclo de `clk_fpga_0`** (4 ns);
- `adc_clk` es asíncrono y queda **cuantizado** a esa grilla — se ve como un
  reloj corrido una columna, no con su desfasaje real de 2.6 ns;
- los tiempos de las etiquetas (`96 ns`, `12 ciclos`) se miden **sobre el VCD**,
  no sobre la grilla.

Con `--step events` cada columna pasa a ser un evento del VCD: el orden de los
flancos queda exacto y el ancho deja de ser proporcional al tiempo. Sirve para
mirar un cruce de cerca; para el informe conviene la grilla uniforme.

## El reensamblado de los buses

Questa escribe los vectores **bit por bit** en el VCD:

```
$var wire 1 5 m_addr [31] $end
$var wire 1 6 m_addr [30] $end   ...
```

El parser del script los junta de vuelta antes de dibujar. Sin eso los 32 bits
de `m_addr` se pisarían entre sí y las filas de dirección y dato saldrían como
un bit suelto — que es exactamente lo que pasa si se le pasa este VCD a un
lector de VCD ingenuo.

Y para que las señales del testbench estén en el VCD hace falta `+acc`:
`make vcd` lo pasa (`module.mk`), pero si se corre `vsim` a mano sin eso, `vopt`
se come todo el scope del TB y el VCD sale **lleno de señales de los submódulos
y sin ninguna de las que dibujan las figuras**.
