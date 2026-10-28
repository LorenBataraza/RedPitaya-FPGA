<!-- Prosa a mano del datasheet de `mca_div_restore`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mca_div_restore.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es el divisor que convierte dos acumuladores de carga en un
**índice de bin**: calcula `q = floor(num · 2^Q_W / den)` con `num < den`, o
sea la fracción `num/den` expresada en `Q_W` bits. El resultado **es**
directamente la coordenada del eje de forma, sin escalado posterior.

[`mca_pulse_feature`](../datasheet_mca_pulse_feature.md) instancia **dos**, con el
mismo denominador y el mismo arranque: uno para `Q_cola/Q_total` y otro para
`Pico/Q_total`. Como comparten latencia, el segundo no necesita ni que se le
mire el `valid`.

**El truco que lo hace barato.** Como `num < den`, arrancando con `rem = num` y
haciendo `rem = 2·rem; if (rem ≥ den) { rem −= den; q |= 1; }` sale **un bit de
cociente por iteración**, así que hacen falta exactamente `Q_W` iteraciones sin
importar el ancho de los operandos: no hay que normalizar nada de antemano.
Cero DSP. El invariante `rem < den` vale siempre —si `2·rem ≥ den` entonces
`2·rem − den < den`, porque `2·rem < 2·den`— y por eso `rem` entra en `D_W`
bits aunque el intermedio necesite `D_W+1`.

**La latencia es fija para todos los casos, incluidos los de error.** Es
deliberado: hace predecible el tiempo muerto por evento, que es uno de los
parámetros a caracterizar del MCA
([`tiempo_muerto.md`](../../mca/tiempo_muerto.md)). Tal como está instanciado
—`D_W = 32`, `Q_W = 16`— son 16 ciclos, 128 ns.

**Los tres casos borde rompen cosas distintas si no se tratan.**

| Caso | Sin la guarda | Con la guarda |
|---|---|---|
| `den == 0` | `rem ≥ 0` da siempre cierto y el cociente sale todo unos: **todos** esos eventos caen en el bin superior del eje | `err_o`, y el evento se rechaza |
| `num ≥ den` | `num == den` da `2^Q_W`, que no entra en `Q_W` bits y **envuelve a 0**: manda el evento al extremo **opuesto** del eje. Es el modo de falla peligroso | `sat_o` y `q = 2^Q_W − 1` |
| `num == 0` | — | `q = 0`, sin flags. Es un resultado válido |

> **Dónde no llega el testbench.** `tb_mca_div_restore` hace un barrido
> **exhaustivo** de `num`/`den`… con anchos reducidos: `D_W = 8, Q_W = 6`. El
> diseño lo instancia con `D_W = 32, Q_W = 16`. O sea que la prueba más fuerte
> que tiene el módulo cubre un ancho que el diseño no usa. Es exacto, acotado y
> de espacio de estados chico: el mejor candidato barato a verificación formal
> del repo, con `q·d + r == n` y `start |-> ##N valid` como propiedades. Ver
> [`verificacion_formal.md`](../../verificacion_formal.md).
