<!-- Prosa a mano del datasheet de `mt_trig_src`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mt_trig_src.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es el **selector de disparo de un canal**: toma las 25 fuentes
de trigger del sistema (los flancos de nivel de los canales del ADC, los de
pendiente de [`mt_slope_trig`](../datasheet_mt_slope_trig.md), la entrada
externa, el generador, la cadena desde el otro scope y el disparo por
software), las filtra con una máscara, y emite el trigger del canal. Hay una
instancia por canal dentro de
[`mt_event_logic`](../datasheet_mt_event_logic.md).

![Panorama de mt_trig_src](../../mt/figuras/panorama_mt_trig_src.svg)

*Los números sobre el bus son los bits de la máscara (`OR_MASK`); los 25–31
están reservados. El software también pasa por la máscara: es el bit 0, así que
con `OR_MASK = 0` ni `TRIG_SW` dispara. En modo continuo (`we_keep = 1`) la
máscara no se limpia sola; el protect se engancha igual. `NOMBRE=valor`:
parámetros con que lo instancia `mt_event_logic`.*

*Por dentro:* las 25 fuentes, la máscara, el *protect* y la realimentación del disparo. Fuente TikZ en [`panorama_mt_trig_src.tex`](../../mt/figuras/panorama_mt_trig_src.tex).

Es el reemplazo de `rp_trig_src.v`, y las dos diferencias con el original son
las que dan el nombre al módulo:

- **La máscara es un OR, no un selector.** En el original un registro elegía
  **una** fuente. Acá cada bit habilita una clase de fuente y la salida es el
  OR de las habilitadas, así que poner varios bits da el OR entre todas —
  pares, ternas, lo que se configure. Eso es lo que permite disparar por
  coincidencia de condiciones sin un bitstream por combinación.
- **La salida va registrada** (`adc_trig`), que es lo que el camino de captura
  necesitaba para alinearse.

**El enganche es la parte que hay que entender para usarlo.** Al disparar, el
módulo engancha `adc_trg_dis` en el mismo movimiento, y eso es lo que impide
que el flanco siguiente vuelva a disparar. Medido sobre el VCD de
`tb_mt_trig_src` en
[`mt_trig_src_enganche.svg`](../../mt/figuras/ondas/mt_trig_src_enganche.svg):
el disable engancha **1 ciclo** después del disparo y la máscara se limpia a
**1 ciclo**.

| Modo | Qué pasa con la máscara | Para volver a disparar |
|---|---|---|
| single-shot (default) | se **auto-limpia** al disparar | reescribir la máscara |
| continuo (`adc_we_keep`) | **persiste** | basta con limpiar el disable (`trig_dis_clr`) |

Esa es la única diferencia entre los dos modos, y el clear puede venir del
software (registro `0x94`) o del
[`trigger_shield`](../datasheet_trigger_shield.md) al expirar su holdoff — por eso
el escudo puede re-armar un canal sin que el PS intervenga.

El disparo por software está **gateado por `dly_valp`**: no vale por sí solo,
tiene que caer con el pulso de validez del retardo. Es lo que evita que una
escritura de registro dispare en un momento en que la cadena no está lista.

> **Candidato a formal.** «Después de un single-shot la máscara queda limpia y
> no se vuelve a disparar sin `trig_dis_clr`» es una propiedad de secuencia
> sobre una FSM chica: barata de probar y exactamente el tipo de cosa que un
> testbench cubre con casos puntuales. Ver
> [`verificacion_formal.md`](../../verificacion_formal.md).
