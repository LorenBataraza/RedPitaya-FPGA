<!-- Prosa a mano del datasheet de `mca_slot`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mca_slot.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Es una ranura de medición: un juego entero de acumuladores con su
estado (**libre → midiendo → cerrada → libre**). La abre el asignador de
`mca_window` con un disparo; mientras mide, cada muestra válida actualiza el
pico, $Q_\mathrm{tot}$, $Q_\mathrm{cola}$ (desde la compuerta corta), el largo y
el tiempo de subida; cierra a la compuerta larga y, si la amplitud cae en
`[amp_min, amp_max]`, se queda con el resultado hasta que `mca_publish` lo toma.
O sea que la ranura es a la vez el juego de acumuladores y el lugar de la cola de
publicación. Ver la [vista general](../../mca/vista_general_mca.md) §2.3.

**Las marcas de solape.** Una ventana que abre con otras abiertas, o dentro de la
cual llega otro disparo, mide un pulso montado sobre otro. La ranura no lo
corrige: deja `dt_prev`, `dt_next` y `{perdido, adentro, otras}` con el
resultado, y salen al bus como `F_DTPREV`, `F_DTNEXT` y `F_SOLAPE`.

**Dos decisiones que explican su forma.** Las compuertas se **retienen al
abrir**: cada ranura cierra sola, con su `len` contra su `g_long`, y mide lo que
se configuró cuando abrió aunque se toque `gate_long` a mitad de una corrida. Si
se lo toca entre dos aperturas, dos ranuras pueden cerrar en la misma muestra, y
el publicador encola las dos. Y la ventana de
amplitud se evalúa **un ciclo antes del cierre**, con sombras de la resta
contra `[min, max]` (`d_min`, `d_max`), igual que en la ventana única: era el
camino crítico del bitstream.
