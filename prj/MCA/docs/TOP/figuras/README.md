# Figuras: el datapath del top en integración

Dos figuras para una sola pregunta: **qué muestras ve cada sección del sistema,
y dónde se puede cambiar eso**. `datapath_top` es TikZ, con el estilo común de
los panoramas ([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex));
`conformado_mca_interno` la genera
[`figuras_datapath_top.py`](figuras_datapath_top.py), que también escribe los
epígrafes de las dos:

```bash
cd prj/MCA/docs/TOP/figuras
pdflatex datapath_top.tex && pdftocairo -svg datapath_top.pdf datapath_top.svg
python3 figuras_datapath_top.py
```

Son **esquemas de la estructura del RTL**, no datos medidos: salen de leer
`mca_red_pitaya_top.sv`, `rp_scope_mt_com.sv`, `dsp_tap_mux.sv`,
`integration_cfg.sv` y los módulos del MCA. Si cambia el RTL, hay que volver a
pasar el script por las coordenadas a mano — no hay extracción automática.

`conformado_mca_interno.svg` lleva paleta clara y oscura
(`prefers-color-scheme`); las figuras TikZ tienen fondo blanco siempre.

| Figura | Qué muestra | Dónde está embebida |
|---|---|---|
| [`datapath_top.svg`](datapath_top.svg) ([`.tex`](datapath_top.tex)) | La cadena DSP única con sus cuatro nodos (A a D) y **un `dsp_tap_mux` 4:1 por consumidor**, con la letra del nodo en cada entrada: de dónde puede tomar cada consumidor y cuál es su valor de reset (la entrada 0, el nativo). También el lazo digital de `gen_pulsos`, lo que el multitrigger da a los otros consumidores y el `event_ring` | [`register_map_top.md`](../register_map_top.md) §Ruteo del datapath |
| [`conformado_mca_interno.svg`](conformado_mca_interno.svg) | Dentro del MCA: **un solo flujo** de muestras y tres procesamientos (detección, caracterización, restauración de base) | [`datasheet_mca_top.md`](../../datasheet/datasheet_mca_top.md) §1.1 |
| [`tm_integracion.svg`](tm_integracion.svg) ([`.tex`](tm_integracion.tex), epígrafe en [`.txt`](tm_integracion.txt)) | El **tiempo muerto en la integración**: de qué bloque (multitrigger o MCA) sale cada casillero del teselado de relojes, y los tres cables del top que los llevan (`mca_veto`, `trig`, `trig_arm`) | la sección *Tiempo muerto en la integración* del documento del top (vault) |

Los epígrafes están en [`epigrafes.txt`](epigrafes.txt), que escribe el mismo
script para que no puedan desincronizarse.

---

## Las figuras van sin prosa adentro

Lo que los dibujos llevan son **nombres de señal, códigos de registro y marcas
numeradas**. Cada marca es una fila de la tabla del documento que embebe la
figura. Es la regla que
[`figuras_movimiento_de_datos.py`](../../figuras/figuras_movimiento_de_datos.py)
ya declaraba para el overlay de la placa, y la razón es la misma: con el texto
adentro había **dos copias de lo mismo** —el dibujo y el epígrafe— y tarde o
temprano se desincronizan.

Antes de eso, `datapath_top.svg` tenía 71 nodos de texto contra 20 cajas,
incluida una leyenda de cuatro párrafos; ahora tiene 47, y ninguno es una
oración.

## Una de las figuras era una tabla

Había una tercera, `conformado_por_tap.svg`: cuatro columnas (los nodos) por
cinco filas (las etapas de la cadena), con un «la vio / no la vio» en cada
celda. El SVG tenía 64 nodos de texto, 22 rectángulos y **un solo** `<path>` —o
sea, ni una flecha: nada que una tabla no pudiera decir mejor.

Está ahora como tabla en [`register_map_top.md`](../register_map_top.md)
§Ruteo del datapath, donde se puede copiar, buscar con `grep` y corregir sin
regenerar nada. El panel «Lo que NO hay» que llevaba al costado era prosa pura
y estaba duplicado palabra por palabra en el epígrafe; ahora está una sola vez,
en el documento.

La versión de esa misma información **con el dato encima** —el mismo pulso
medido dibujado en los cuatro nodos, donde se ve el cambio de ritmo— está en
[`docs/comun/figuras/transacciones/`](../../comun/figuras/transacciones/).

---

## Las dos cosas que las figuras están para dejar claras

**No hay tres conformados, hay tres tomas.** La tentación es pensar que cada
sección corre su propio filtro. No: hay **una** cadena de acondicionado por canal
—calibración, ecualizador opcional, diezmado, retardo— y cada consumidor elige de
qué punto de esa cadena toma sus muestras. La diferencia entre secciones es
*dónde pincha cada una*, no qué filtro corre.

**Dentro del MCA tampoco hay un conformado por función.** La detección, la
caracterización y la restauración de base consumen el mismo
`x = dat_q − baseline`. Lo que cambia es el procesamiento. El seguidor de base es
el único bloque que *modifica* el flujo que ven los otros dos —por eso es el
único lazo de la figura—. El apilamiento no es un bloque: es una condición de
cierre de la FSM de segmentación. Y el discriminador configurable no mira
muestras: mira una *feature* del registro de evento, con el pulso ya cerrado.

(La tercera, «en la FPGA no hay conformador de espectrometría», está donde
corresponde: en [`register_map_top.md`](../register_map_top.md), junto a la
tabla de conformado por nodo.)

---

Aparte, los **panoramas para la tesis**, en TikZ con el estilo común
([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex)); el `.pdf`
va a la tesis y el `.svg` a los documentos:

| Fuente | Qué muestra | Dónde está embebida |
|---|---|---|
| [`panorama_mca_red_pitaya_top.tex`](panorama_mca_red_pitaya_top.tex) | El top del MCA: el PS con sus dos caminos, los ocho slots, el datapath ADC → scope → MCA y los pines | [`register_map_top.md`](../register_map_top.md) §El mapa de slots |
| [`panorama_event_ring_red_pitaya_top.tex`](panorama_event_ring_red_pitaya_top.tex) | El mismo top con el `event_ring_top` en el slot 2 y HP2 | ídem |
| [`panorama_sys_bus.tex`](panorama_sys_bus.tex) | El camino de control: `M_AXI_GP0` → `axi4_slave` → interconnect → un CDC por slot → esclavos | [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md) §3 |
| [`estructura_sys_bus.tex`](estructura_sys_bus.tex) | El bus como diagrama de rieles: `addr`/`wdata` difundidos, `wen`/`ren` seleccionados por slot, `rdata`/`ack`/`err` multiplexados, y un CDC por slot | [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md) §3 |
| [`fsm_sys_bus.tex`](fsm_sys_bus.tex) | Las máquinas de estados del lado maestro (`axi4_slave` + CDC) y del lado esclavo (CDC + esclavo), con las señales internas y los dos toggles que cruzan de reloj | [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md) §6 |
| [`latencia_sys_bus.tex`](latencia_sys_bus.tex) | El mismo camino reducido a un slot, ida y vuelta, con los ciclos de cada etapa: dónde se va la latencia de un acceso | [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md) §10 |
| [`panorama_modulo_cfg.tex`](panorama_modulo_cfg.tex) | El esclavo por dentro: decodificador de dirección y banco de registros para escribir, multiplexor y registro de salida para leer. Es el patrón que repiten `osc_cfg`, `mt_cfg`, `integration_cfg` y los bancos en línea de `mca_top` y `event_ring_top` | [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md) §8 |
| [`contrato_sys_bus.tex`](contrato_sys_bus.tex) | El contrato del bus como máquina de estados vista desde el esclavo: qué hace el maestro, qué tiene que hacer el esclavo y qué pasa si no hace `ack` | [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md) §8 |

Los dos tops salen de un solo dibujo,
[`panorama_top_cuerpo.tex`](panorama_top_cuerpo.tex), con un interruptor
`\ifring`; los `.tex` de cada top son envoltorios de tres líneas. Para
regenerar:

```bash
for f in panorama_mca_red_pitaya_top panorama_event_ring_red_pitaya_top panorama_sys_bus estructura_sys_bus fsm_sys_bus latencia_sys_bus panorama_modulo_cfg contrato_sys_bus datapath_top; do
  pdflatex $f.tex && pdftocairo -svg $f.pdf $f.svg
done
rm -f *.aux *.log
```

Y en [`bus_sistema/`](bus_sistema/) están los **diagramas de tiempo del
protocolo del bus de sistema**. Ésos no son esquemas: salen de un VCD de
`prj/MCA/sim/tb_sys_bus_proto.sv`, dibujados con WaveDrom.

El detalle registro por registro del ruteo está en
[`register_map_top.md`](../register_map_top.md) §Ruteo del datapath.
