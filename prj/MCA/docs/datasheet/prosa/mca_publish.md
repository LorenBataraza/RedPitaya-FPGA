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

**Qué hace.** Publica los eventos de las ranuras cerradas, **en orden de
cierre**: guarda una cola de índices de ranura, toma la más vieja, la pasa por los
dos `mca_div_restore` (forma $Q_\mathrm{cola}/Q_\mathrm{tot}$ y ancho inverso
pico$/Q_\mathrm{tot}$), arma el bus de features con todas las ranuras del mismo
evento y libera la ranura. Si la cola está vacía, los divisores arrancan en el
mismo flanco del cierre: una ranura espera exactamente 18 ciclos por evento.

**Por qué los operandos salen del índice registrado.** La primera versión cargaba
los operandos en el mismo flanco en que decidía qué ranura atender, y el camino
cierre → aceptación → prioridad → mux de 32 bits → comparador de 32 bits dio
−0.734 ns. El divisor engancha los operandos un ciclo después de `div_start`, así
que salen del índice `cur`, ya registrado: +0.065 ns en la OOC.
