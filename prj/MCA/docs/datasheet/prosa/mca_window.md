<!-- Prosa a mano del datasheet de `mca_window`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mca_window.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Es el núcleo del extractor: resta la base de la muestra, la
registra y la reparte a las `N_ACC` ranuras (`mca_slot`); toma el disparo
(`trig_i`, por flanco, sostenido hasta la muestra válida siguiente) y le asigna
la ranura libre de menor índice entre las `cfg_n_acc` habilitadas; y reparte cada
ciclo y cada disparo en los casilleros de tiempo muerto y de atribución. Es la
decisión **D8** de la [vista general](../../mca/vista_general_mca.md), cuántas
ranuras miden a la vez.

**Por qué la muestra se registra antes de repartirse.** El sintetizador corre con
`-flatten_hierarchy none`, así que una frontera es gratis solo si lo que cruza
sale de un registro. `xc_q` es ese registro, y lo que el asignador decide para
cada muestra (abrir, qué ranura, las marcas de solape) viaja registrado con ella.
La ranura elegida queda **reservada** el ciclo siguiente, porque recién abre en
ese flanco: sin la reserva, un disparo en la muestra siguiente elegiría la misma.

**Por qué ya no hay Schmitt.** La ventana la abría un Schmitt interno, que no
puede ver un pulso montado sobre la cola de otro (la señal nunca baja del umbral
entre los dos), y esos son los pulsos para los que existen las ranuras. Abre
solo el disparo por pendiente del multitrigger; `mca_delay` compensa que llega
tarde.
