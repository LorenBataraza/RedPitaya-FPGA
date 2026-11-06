<!-- Prosa a mano del datasheet de `mca_trap`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mca_trap.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Conforma la muestra relativa a la base con el trapecio recursivo de
Jordanov y Knoll: una doble diferencia con retardos k y l = k + m, dos
integradores, y el término `M·d` que cancela el polo de la cola. Un pulso
exponencial sale como un trapecio de subida k, meseta m y bajada k, que **vuelve a
cero en 2k + m muestras** aunque la cola de la entrada dure mucho más. Es la
corrección de lo que las ranuras de `mca_window` solo marcan: dos pulsos
separados k + m o más tienen mesetas limpias aunque se pisen en la entrada. Hay
uno por forma del banco (`N_FORMAS`), común a todas las ranuras; cada ranura
promedia la salida de cada uno sobre su propia ventana, y la que se publica en
`F_TRAP` se elige al publicar. Vive en `modulos/comun/` porque también es el
trapecio del disparo con polo-cero del multitrigger
([`mt_pz_trig`](../datasheet_mt_pz_trig.md)), con las líneas en LUT
(`RAM_STYLE = "distributed"`). Cómo elegir k, m, M y la ventana:
[`register_map_mca.md`](../../mca/register_map_mca.md) §El conformado trapezoidal.

**Tres decisiones.**

- **Enteros exactos, y un `clr`.** La forma recursiva es un FIR solo si el estado
  es consistente con las líneas de retardo. Al cambiar la forma, `clr_i` pone el
  estado en cero y las líneas cuentan como vacías hasta llenarse (la convención
  `v[<0] = 0` del modelo de Python), así que la salida es exactamente
  `16 × estimadores.trapecio` desde el `clr`. Sin eso a `p` le quedaría un escalón
  permanente y `s` derivaría hasta desbordar.
- **Todo avanza por muestra válida.** Cada etapa es un registro con
  habilitación y la BRAM sostiene su salida entre lecturas: la latencia es de 8
  **muestras** sea cual sea la decimación, y `mca_window` la descuenta al ubicar
  la ventana de cada ranura.
- **Las líneas en BRAM y el polo-cero en un DSP48.** Tres RAMB18 de 1024 muestras
  en vez de ~700 LUT de SRL más sus multiplexores. Las comparaciones que dicen si
  una línea ya se llenó se hacen en la entrada y viajan como banderas: en la
  etapa de la doble diferencia costaban 0.2 ns de un camino que termina en el DSP.
