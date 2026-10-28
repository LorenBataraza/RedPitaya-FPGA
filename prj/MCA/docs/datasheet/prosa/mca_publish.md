<!-- Prosa a mano del datasheet de `mca_publish`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mca_publish.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Recibe la ventana que [`mca_window`](../datasheet_mca_window.md)
cerró y aceptó, la guarda en una FIFO de `PUB_K` lugares, corre los dos
[`mca_div_restore`](../datasheet_mca_div_restore.md) y arma el bus de features:
16 ranuras de 16 b, todas del mismo pulso. Es la ejecución de la decisión **D8**
de la [vista general](../../mca/vista_general_mca.md#27-la-publicación--d8-y-mca_div_restore).

**Por qué no tiene la entrada `cfg_pub_mode`.** Hace lo mismo en los dos modos:
toda ventana aceptada entra a la FIFO, y si el publicador está libre los
divisores arrancan en ese mismo flanco desde los valores vivos (el *arranque
directo*). La diferencia entre bloqueante y FIFO es solo cuándo puede reabrir la
ventana, y eso lo decide `mca_window`, que espera en `S_DIV` hasta ver
`pub_done_o`. Que `pub_done_o` sea combinacional y no la FIFO vacía es lo que
mantiene `S_DIV` en 17 ciclos exactos y la identidad
`deadtime_cnt == t_win + t_div` que dejó la Fase 1.

**La frontera de entrada es la más justa del MCA.** `acepta_i` es la WE de los
LUTRAM de la FIFO sin ninguna LUT de este lado; en el bitstream es el peor
camino del dominio del ADC (+0.064 ns). Cualquier lógica nueva sobre `acepta_i`
hay que hacerla del otro lado.
