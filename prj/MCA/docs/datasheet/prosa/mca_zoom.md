<!-- Prosa a mano del datasheet de `mca_zoom`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mca_zoom.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Lleva una feature de `FW` bits al bin de un eje de `AW` bits,
con **zoom alineado a potencias de 2**. Es la etapa que hay entre el mux de eje
y la memoria del histograma en [`mca_top`](../datasheet_mca_top.md), y hay una por
eje.

Sobre una feature de `FW` bits, una ventana `[k·2^(FW−z), (k+1)·2^(FW−z))` es
**puro rebanado de bits**: estar dentro de la ventana es que los `z` bits altos
valgan `k`, y el bin son los `AW` bits siguientes. Ni restador ni
multiplicador: un comparador y un corrimiento variable. Alinear a potencias de
2 sale **más barato** que un offset arbitrario, no más caro.

**Por qué alineado y no un offset libre.** Con offsets arbitrarios, dos
espectros tomados con ventanas distintas tienen bordes de bin que **no
coinciden**, y combinarlos exige re-samplear — con su jacobiano y el peine de
DNL que eso introduce
([`limites_resolucion_y_deriva.md`](../../mca/limites_resolucion_y_deriva.md) §5).
Alineados, los bins de cada nivel son subdivisiones **exactamente anidadas** de
los del nivel anterior: un bin de nivel `z` es la suma **entera** de dos de
nivel `z+1`. Se cosen con aritmética entera, sin interpolar y sin agregar DNL.

**Lo que el zoom NO hace: no mejora la resolución.** Sólo recupera la pérdida
por binning (Sheppard), que a 8.6 canales/FWHM ya es el **0.31 % de σ**. Sirve
para *ubicar* el eje sobre dos picos juntos y para poder usar un histograma más
chico — no para inventar precisión que la feature no tiene.

**Fuera de la ventana satura: no envuelve ni descarta.** Un evento por encima
va al último canal y uno por debajo al canal 0. Es el mismo contrato que ya
tenía el eje sin zoom —un evento nunca puede aparecer en el extremo opuesto— y
deja los bins de los extremos como **indicadores visibles de desborde**. Con la
deriva medida esto importa de verdad: a `z = 3`, un corrimiento del 6.45 % mueve
el pico un **41 % del ancho de la ventana**, así que los extremos avisan antes
de que el pico se vaya.

Dos saturaciones de configuración, por el mismo motivo —evitar ajustes que
parecen funcionar y no—: `z` se satura a `FW − AW`, porque más allá no quedan
bits que rebanar; y `k` se enmascara a los `z` bits útiles, para que `z = 0`
fuerce `k = 0` en vez de mandar todo al canal 0 en silencio si quedó escrito un
`k` viejo.
