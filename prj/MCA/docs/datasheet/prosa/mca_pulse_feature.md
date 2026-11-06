<!-- Prosa a mano del datasheet de `mca_pulse_feature`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mca_pulse_feature.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es el extractor de características: por cada disparo abre una
ventana en una ranura libre, acumula las características del pulso y publica un
evento coherente con 16 features. Que salga de un único registro es lo que
garantiza que el espectro 1D y el mapa 2D cuenten exactamente los mismos pulsos.
Mide varios pulsos a la vez: tiene `N_ACC` ranuras y `cfg_n_acc` elige cuántas
se usan.

**Es cableado.** El trabajo está en `mca_baseline` (la base, **D3**),
`mca_window` (el disparo, el asignador, las ranuras y la contabilidad, **D8**),
`mca_slot` (cada ranura, con la ventana de amplitud de **D7**) y `mca_publish`
(la cola y los divisores). Las fronteras están donde lo que cruza sale de un
registro, porque el sintetizador no aplana jerarquía. Ver la
[vista general](../../mca/vista_general_mca.md) §2.
