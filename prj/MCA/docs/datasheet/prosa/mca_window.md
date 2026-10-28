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

**Qué hace.** Es el núcleo del extractor: resta la base, abre y cierra la
ventana, re-arma el detector, corre los acumuladores (pico, $Q_\mathrm{tot}$,
$Q_\mathrm{cola}$, largo, tiempo de subida), evalúa la ventana de amplitud y
reparte cada ciclo y cada cruce de umbral en los casilleros de tiempo muerto.
Viven acá cuatro decisiones de la
[vista general](../../mca/vista_general_mca.md): quién abre (**D4**), quién
cierra (**D5**), cómo se re-arma (**D6**) y qué amplitud mira la ventana (**D7**).

**Por qué es un módulo tan grande.** Por acá pasa el camino crítico de todo el
bitstream, `dat → x → umbrales → abrir/cerrar → acumuladores`, y el
sintetizador corre con `-flatten_hierarchy none`. Una frontera en medio de ese
cono le suma un nivel de LUT. El re-armado se probó como módulo aparte y
volvió: abrir consume el armado en el mismo flanco, el flanco de apertura tenía
que salir como puerto, y eso solo costó 576 ps en todo el cono. Lo que sale hacia
[`mca_publish`](../datasheet_mca_publish.md) sale de registros, o va directo a la
WE de la FIFO.

**Dos ajustes de mapeo, documentados en el RTL.** Las sumas de $Q_\mathrm{tot}$ y
$Q_\mathrm{cola}$ llevan `keep`, y $Q_\mathrm{cola}$ se escribe como valor
siguiente en todos los ciclos. Sin eso, al separar la publicación Vivado plegó la
apertura dentro del sumador y `q_tot` cayó a −0.148 ns en la OOC. La lógica es la
misma: lo verifica `tb_mca_pulse_feature_eq` contra la copia congelada del
módulo original.
