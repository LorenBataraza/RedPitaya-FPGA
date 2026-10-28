<!-- Prosa a mano del datasheet de `mca_hist`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mca_hist.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es **el motor de histograma**: una memoria de `2^AW` bins de `CW`
bits que acepta **un incremento por ciclo**. Una sola implementación, varias
instancias — el espectro 1D de 8192 canales y el mapa 2D de 128 × 64 de
[`mca_top`](../datasheet_mca_top.md) son el mismo módulo con parámetros distintos.

El read-modify-write de un bin y el caso difícil —dos eventos seguidos al
mismo bin— están medidos sobre la simulación en
[`mca_hist_rmw.svg`](../../mca/figuras/ondas/mca_hist_rmw.svg).

**Un incremento por ciclo, y lo que cuesta.** Un puerto de BRAM tiene **una**
dirección por ciclo, así que no puede leer `addr(n)` y escribir `addr(n−2)` a
la vez. Poniendo la lectura en un puerto y la escritura en el otro se consigue
el incremento por ciclo, al precio de necesitar **forwarding de 2 etapas**: el
evento que lee en el ciclo *m* escribe en *m+2*, así que otro evento al mismo
bin en *m+1* o *m+2* leería un valor viejo y hay que puentearlo. La alternativa
—la máquina de 3 estados del `axis_histogram.v` de pavel-demin— acepta un
evento cada 3 ciclos, lo que obligaría a decimar un futuro mapa de
persistencia.

**El barrido de borrado no puede frenar al bus, y por eso usa sólo el puerto de
escritura.** Un barrido de 16384 bins son 16384 ciclos = **131 µs**, unas 500
veces el timeout de 32 ciclos del esclavo AXI. Si el barrido bloqueara el ack,
el bus se colgaría. Con el puerto de lectura vivo durante todo el barrido, se
puede leer el histograma **mientras se borra** — que es lo que muestra
[`mca_ack_borrado.svg`](../../mca/figuras/ondas/mca_ack_borrado.svg), y lo que la
cabecera del RTL de `mca_top` marca como lo más importante del módulo.

**La pérdida es medible, no silenciosa.** La lectura del bus tiene prioridad;
un evento que llegue en ese ciclo, o durante el barrido, se descarta y se
**cuenta** en `dropped_o`. Con eventos separados por cientos de ciclos y
lecturas separadas por microsegundos la colisión es despreciable, y leer con
`run = 0` la elimina del todo — pero si ocurre, queda escrita.

**La saturación congela TODO el histograma, no el bin que se llenó.** `full_o`
es pegajoso y con `cfg_keep = 0` la acumulación se detiene en el histograma
entero: un espectro con unos canales congelados y otros no ya no es un
espectro, porque las áreas relativas dejan de corresponder al mismo *live
time*. Para escala: 2³² cuentas a 794 kcps con **todo** en un solo pico son
~14 h. Es alcanzable en una corrida larga, pero está cuatro órdenes de
magnitud por encima de la deriva, que es lo que de verdad limita
([`limites_resolucion_y_deriva.md`](../../mca/limites_resolucion_y_deriva.md) §7).
Sirve sobre todo como disparador de rebanada y como seguro contra la
saturación silenciosa.

> **Una trampa de cableado.** `rd_i` tiene que ser un **pulso de un ciclo**, no
> el `ren` sostenido del bus: `sys_bus_cdc` mantiene `ren` alto hasta el ack
> (~4 ciclos) y conectarlo directo haría que cada acceso del bus le robara 4
> ciclos al pipeline en vez de 1.
>
> **Candidato a formal.** «Dos eventos al mismo bin no pierden cuenta» es datos
> sin acotar con control mínimo: el caso de libro. Hoy se prueba con vectores
> puntuales ([`verificacion_formal.md`](../../verificacion_formal.md)).
