<!-- Prosa a mano del datasheet de `integration_cfg`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_integration_cfg.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es el registro de identidad y el panel de ruteo del bitstream.
No mueve muestras: contesta dos preguntas que antes no tenían a quién
preguntárselas —**qué trae este bitstream** y **de dónde toma sus muestras cada
consumidor**— y deja que el software cambie la segunda en runtime.

Antes de que existiera, los bloques propios del proyecto vivían cableados a
mano en el top y el software no tenía forma de descubrirlos: `mca_utils.py` y
`multitrigger_utils.py` todavía arrastran una constante `*_PHYS` hardcodeada
por ese motivo. Ahora hay tres grupos de registros: **identificación** (`MAGIC`,
`VERSION`, hash de git), **descripción** (qué módulos hay, en qué slot vive cada
uno y con qué parámetros se sintetizaron) y **ruteo** (`ROUTE_*`). Los dos
primeros salen de parámetros de síntesis, así que no cuestan flops: son cableado
constante hacia el mux de lectura.

Esto **no es housekeeping.** `red_pitaya_hk` (slot 0) es un módulo de Red Pitaya
—LEDs, conector de expansión, DNA del chip— y sigue donde estaba.

Dos decisiones que explican la forma:

- **El ack es de latencia fija**, igual que en `mca_top`: sale de un shift
  register incondicional y responde a los 4 ciclos para *cualquier* dirección,
  mapeada o no. Un esclavo que no hace ack no produce sólo una lectura mala —
  deja el CDC del slot desincronizado para siempre, y ese slot no acepta más
  transacciones ([§7.1](../../TOP/bus_sistema_redpitaya.md)).
- **`tap_sel = 0` y `enable = 1` son los valores de reset**, y el código `0`
  significa «como estaba cableado antes de que hubiera mux». Un bitstream
  recién cargado se comporta exactamente como el anterior al refactor:
  cualquier diferencia es porque el software escribió un `ROUTE_*`.

El `dsp_tap_mux` que estos registros manejan, y qué muestra entrega cada nodo,
están en [`register_map_top.md`](../../TOP/register_map_top.md) §Ruteo del
datapath; el mismo pulso dibujado en los cuatro nodos, en [§1.6](#16-transacciones).
