<!-- Prosa a mano del datasheet de `mt_pz_trig`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mt_pz_trig.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Es el **disparo con polo-cero de un canal**, el que usa el banco de
trapecios del MCA. Como [`mt_slope_trig`](../datasheet_mt_slope_trig.md), toma
el tap del multitrigger, tiene un Schmitt y saca un pulso de un ciclo por cruce,
que entra a [`mt_trig_src`](../datasheet_mt_trig_src.md) en los bits 25..28 de
la máscara. Lo que cambia es qué compara contra el umbral: la salida de un
trapecio corto **con** cancelación del polo de la cola
([`mca_trap`](../datasheet_mca_trap.md), k = 2 y m = 1 para el Rigol). Cada pulso
sale como un trapecio que vuelve a cero a las 2k + m muestras, apoyado en cero
aunque haya una cola debajo. Por eso separa pares desde 7–8 muestras y ve un
pulso chico en la cola de uno grande, que es donde la pendiente queda ciega
(~20 y ~150 muestras). Por qué y con qué números:
[`disparo_polo_cero.md`](../../mt/disparo_polo_cero.md).

**Tres decisiones.**

- **El mismo `mca_trap` del MCA, con las líneas en LUT.** Es la misma recursión
  entera, bit a bit, con `RAM_STYLE = "distributed"` y líneas de 32 muestras
  (k + m ≤ 31), así que no gasta BRAM. El software le escribe el mismo M que al
  MCA.
- **Re-arranque y arranque como la pendiente.** Un cambio de k, m o M, `en = 0`
  o el reset le pulsan `clr` al trapecio. Como el trapecio ve la continua del tap
  como un escalón, el Schmitt queda "disparado" hasta k + l + 12 muestras
  después, y el primer pulso pide re-armar.
- **No resta la base.** La continua se atenúa por l/(1 + M), unas 80 veces, así
  que con la base de la placa no se nota. Con más de ~+1880 cuentas de offset,
  el Schmitt de 50/25 ya no re-arma: es un límite documentado, no un error.

