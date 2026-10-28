<!-- Prosa a mano del datasheet de `mca_baseline`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mca_baseline.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Da la línea de base que [`mca_window`](../datasheet_mca_window.md)
le resta a cada muestra antes de compararla con los umbrales: es la decisión
**D3** de la [vista general](../../mca/vista_general_mca.md#21-línea-de-base--d3).
Hay dos opciones en el mismo bitstream, elegidas por `cfg_bl_auto`: una base
**fija** (`cfg_baseline`, el reset) o un **seguidor IIR**
`bl_acc += x − (bl_acc ≫ k)`.

**La salida es un registro, y la resta no está acá.** La resta `x = dat − base`
es el primer eslabón del camino crítico del bitstream, así que vive en
`mca_window`, junto a los umbrales. Como la base llega registrada, esta frontera
no le cuesta nada al timing aunque el sintetizador no aplane jerarquía.

**Dos detalles que no son menores.** El acumulador es ancho porque con la forma
ingenua `bl += (x − bl) ≫ k` el incremento se cuantiza a cero y el seguidor se
congela. Y el seguidor se descongela `cfg_bl_holdoff` muestras **después** del
pulso, no al cruzar la histéresis, para no agarrar el undershoot de la cola
([`polo_cero.md`](../../mca/polo_cero.md)). Cuándo seguir lo dice la ventana
(`track_i`, `hold_load_i`), porque depende de su estado.
