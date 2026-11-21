# El generador de eventos del ring

`modulos/gen_eventos/` genera disparos y un dato conocido dentro de la FPGA, para medir
a qué tasa anda el `event_ring` sin depender del estímulo analógico. Este doc explica
por qué hace falta, qué hace, cómo se verificó y cómo se va a usar en la placa.

**Estado (2026-11-12):** RTL, testbenches y modelo hechos y en verde, integrado en
`event_ring_top` (`EN_GEN = 1`). Lo trae el cuarto bitstream del ring (78e26188). En la
placa ese bitstream pasa la batería entera. **En libmca desde 0.9.0**
(`osciloscope_ring_gen_*`), probado contra el modelo del ring y **en la placa** (2026-11-09,
`make verificar-placa-generadores`, parte C): un caso periódico sin pérdidas (20 000
eventos) y uno aleatorio a 3 MHz (100 000 disparos, 40 237 escritos, 59 762 por
`DROP_BUSY` y 1 por `DROP_FULL`). En los dos la cuenta cierra, cada marca y cada
snapshot son los que predice el modelo, y cada muestra desde el arranque es el patrón.
**Los modos del lector de §6**, en libmca 0.10.0 (`osciloscope_ring_medir`), pasaron en
la placa el 2026-11-12 (parte D del mismo test, 114 de 114). **La campaña de §6**
(`campanas/run_etapas_ring.py`) se corrió en la placa el mismo día: A y B en las seis
ventanas, y C contra la SD y contra `/dev/shm`, sin anomalías (ver §6, «En la placa»).
**El criterio de 10⁸ eventos con el ARM ocupado** (mismo día, 32 muestras): A lo cumple
a 1,4 M/s, y B a 200 k/s pero sin margen; a 300 k/s no, porque el lector de C, con los
dos núcleos ocupados, lee 233 k/s. **La etapa C por la red** (el servidor con las ops
`ring.*`, y un directorio de la PC montado por NFS en la placa) está hecha y probada sin
placa; **falta** correrla en la placa (§6, «La etapa C por la red»).

## 1. Por qué

Con el Rigol, lo que se mide es el estímulo y no el ring:

- **El apilamiento tapa la pérdida del ring.** A 100 kHz de Poisson se pierde el 31 %
  porque los pulsos se apilan en un solo cruce de umbral, y eso es todo lo que se pierde
  (`docs/API/arquitectura_adquisicion_software.md`). El ring queda escondido abajo.
- **El ring no se exigió nunca.** En esa corrida guardó 77 k eventos/s de 256 B, unos
  20 MB/s, cuando la simulación le da al writer 1420 k eventos/s con ventanas de 32
  muestras (`logica_de_captura_y_axi.md` §4.5). El writer a esa velocidad no se probó
  en la placa.
- **Contar no alcanza.** Con el Rigol se sabe cuántos eventos llegaron, pero no si cada
  muestra es la que tenía que ser.

## 2. Qué hace

Va entre la cadena del scope y la captura del ring:

```
mca_dat_bus, ring_trig, ring_snap ──► gen_eventos ──► event_window_capture ──► stage ──► writer ──► DDR
                                         ▲     ▲
                         ts_cnt del ring ┘     └ gst == RUNNING
```

**Apagado es un cable:** el dato, el valid, el disparo y el snapshot pasan por un mux
combinacional. Con el generador instanciado y apagado, el ring escribe en la DDR lo
mismo, byte por byte, que sin él: el volcado de `tb_event_ring_top` que lee
`test_ring_format.py` no cambió.

Prendido reemplaza dos cosas, cada una con su bit:

**Los disparos** (bit `en`), de dos maneras. Los decide
[`gen_disparos.sv`](../../modulos/gen_eventos/rtl/gen_disparos.sv), el motor que
comparte con el [generador de pulsos](../gen_eventos/generador_pulsos.md) (su panorama:
[`panorama_gen_disparos.svg`](../gen_eventos/figuras/panorama_gen_disparos.svg)):

- **Periódicos:** uno cada `PERIODO` ciclos.
- **Aleatorios:** en cada ciclo dispara con probabilidad `UMBRAL / 2^32` y después
  espera `DT_MIN − 1` ciclos. Es un Poisson discreto con tiempo muerto no paralizable:

  ```
  intervalo medio = (DT_MIN − 1) + 2^32 / UMBRAL   ciclos
  ```

  El número aleatorio es un **xorshift32**, un paso por ciclo. No sirve un LFSR común:
  dos estados seguidos son la misma palabra corrida un bit, y comparar contra un umbral
  daría ráfagas. Se comprobó recorriendo todos los estados que disparan: la probabilidad
  de volver a disparar 1, 2 y 3 pasos después es exactamente p, para p de 10⁻⁴ a 0.02.

**El dato** (bit `patron`). El canal par lleva el reloj del ring (`ts_cnt`) y el impar
su complemento, en 14 bits. Como el ring escribe ese mismo reloj en la cabecera del
slot, cada muestra se puede verificar en forma absoluta:

```
ch0[j] = (TS − PRE + j) mod 2^14        ch1[j] = ~ch0[j]   (14 bits; el slot los guarda con signo)
```

con `TS` el timestamp de la cabecera y `j` de 0 a `PRE + POST − 1`. Detecta un
pre-trigger pisado, una ventana corrida, slots cruzados, la caché vieja del lector y
slots escritos a medias. Vale para las muestras desde el arranque (`TS − PRE + j ≥ 0`):
las de antes son lo que quedó en el buffer de pre-trigger
([logica_de_captura_y_axi.md §2.3](logica_de_captura_y_axi.md#23-una-sola-memoria-para-el-pre-y-el-post)),
y el modo aleatorio puede disparar en el primer ciclo (`TS = 2`).

### La cuenta que tiene que cerrar

Los disparos generados salen **sólo con el ring en RUNNING**: el pulso se decide un
ciclo antes y se multiplica por `gst == RUNNING` en el ciclo en que sale. En DRAINING
la captura ya no acepta disparos, y uno que saliera ahí no lo contaría nadie. Así, sin
excepciones:

```
EV_CNT + DROP_BUSY + DROP_FULL == GEN_CNT
```

El snapshot de cada disparo es `{1, k[15:0]}`, con k su índice desde el arranque: el
lector sabe cuáles se perdieron, uno por uno, y no sólo cuántos.

### El reloj del generador

El estado del generador (el xorshift, el contador del período, `GEN_CNT`) vuelve a cero
al arrancar el ring y al prender `en`, y avanza sólo en RUNNING. Con la misma semilla,
los disparos caen siempre en el mismo `ts`, y el modelo de Python los predice:

```python
from gen_eventos_model import disparos, umbral_para
ts = disparos(n_ciclos, aleatorio=True, umbral=umbral_para(500e3, dt_min=5), dt_min=5, semilla=7)
```

El disparo decidido en el ciclo g sale con `ts = g + 2` (el ring está en 0 el primer
ciclo en RUNNING). `tb_event_ring_gen` lo confirma sobre el ring entero.

## 3. Registros

Están en el slot del ring, desde `0x4020_0100`, en la misma página de 4 KB que ya mapea
el lector. Con `EN_GEN = 0` leen 0.

| off | acc | nombre | qué |
|---|---|---|---|
| `0x100` | RW | `CTRL` | `[0]` en, `[1]` aleatorio, `[2]` patron |
| `0x104` | RW | `PERIODO` | ciclos entre disparos, modo periódico; menos de 2 vale 2 |
| `0x108` | RW | `UMBRAL` | probabilidad por ciclo × 2³², modo aleatorio |
| `0x10C` | RW | `DT_MIN` | ciclos mínimos entre disparos, modo aleatorio; 16 bits, menos de 2 vale 2 |
| `0x110` | RW | `N` | cuántos disparos; 0 = sin fin |
| `0x114` | RW | `SEMILLA` | del xorshift; 0 usa `0x2545F491` |
| `0x118` | R | `GEN_CNT` | disparos que salieron desde el arranque |
| `0x11C` | R | `ESTADO` | `[0]` generando, `[1]` llegó a N |
| `0x120` | R | `MAGIC` | `0x47454E31` = `"GEN1"` |

El mínimo de 2 en `PERIODO` y `DT_MIN` es porque la captura toma el disparo por flanco:
dos pulsos seguidos serían un solo evento y `GEN_CNT` contaría dos.

**Uso:** configurar el generador, `CTRL ← en (+ patron)`, arrancar el ring. Al parar el
ring, el generador se detiene solo; `GEN_CNT` se lee después de STOPPED, junto con
`EV_CNT` y los `DROP_*`, que tampoco se borran al parar.

## 4. Cuánto cuesta

OOC con Vivado 2021.2: **399 LUT y 392 FF**, sin BRAM ni DSP, WNS +3.07 ns a 125 MHz.
Es más de lo que estimé antes de escribirlo (150–250): seis registros de 32 bits con su
lectura, el xorshift y tres comparadores de 32 bits. Entra holgado en los ~1350 LUT que
liberó el recorte del MCA del mismo día.

## 5. Cómo se verificó

- **`tb_gen_eventos`** (el generador solo, 50 chequeos):
  - registros;
  - apagado igual a la entrada, ciclo por ciclo;
  - el patrón durante 20 000 ciclos, con la vuelta de los 14 bits;
  - periódico y los mínimos;
  - `N`;
  - el aleatorio contra los vectores del modelo de Python, disparo por disparo, y la
    misma secuencia al rearrancar;
  - cortes del ring a mitad, incluido el ciclo exacto en que hay un disparo decidido en
    vuelo.

  Detecta las 4 mutaciones que se probaron: el `hold` corrido en uno, otro corrimiento
  en el xorshift, el pulso sin el gateo de RUNNING y contar el pulso decidido en vez del
  que sale. Se repitieron sobre `gen_disparos.sv` después de sacar el motor a ese archivo
  (2026-11-09), con el mismo resultado.
- **`tb_event_ring_gen`** (el ring entero con el generador prendido, 61 chequeos).
  Tiene un PS de mentira que lee cada slot de la DDR modelada, verifica el commit del
  footer como el lector de C y devuelve los créditos por lote. En cuatro escenarios
  (periódico sin pérdida, aleatorio con `DROP_BUSY`, un PS lento con `DROP_FULL` y el
  ring parado con el generador andando) la cuenta cierra exacta, y cada slot tiene:
  - el `ts` que predice el modelo;
  - todas las muestras del patrón;
  - `seq` consecutivos;
  - los huecos de k iguales a los descartados.
- **Los TB del ring de siempre** corren con `EN_GEN = 1` y pasan sin cambios.

### Lo que encontró: el último evento se perdía al parar

`tb_event_ring_gen` encontró un error del ring que no es del generador. Al parar,
DRAINING pasaba a STOPPED cuando el writer terminaba, pero la última palabra del
último slot (el footer, que es el commit) podía estar todavía en el `axi_wr_fifo`.
STOPPED es `flush`, y el clear del FIFO la tiraba. En la DDR quedaba el footer de la
vuelta anterior, y el lector descartaba ese slot por no comprometido: **en cada
adquisición se perdía el último evento**, sin que ningún contador lo dijera.

El arreglo (2026-11-09) es que DRAINING espere además `fifo_occ == 0`. El FIFO larga
solo lo que le queda cuando deja de entrar dato (`fifo_flush_cond` en `axi_wr_fifo.v`),
así que no agrega ningún caso de traba. Lo tiene el bitstream 78e26188; en la placa pasa
`verificar-placa-ring`, que no ejercita la parada con el ring lleno.

## 6. Cómo se va a usar en la placa

Por etapas, para saber qué parte limita:

| etapa | qué corre | qué mide |
|---|---|---|
| A | el generador y un lector que sólo devuelve los créditos, sin copiar | PL + AXI + DDR. `DROP_BUSY` tiene que dar lo mismo que en la simulación; `DROP_FULL` dice dónde se satura la DDR |
| B | más la copia y la verificación del patrón en C, sin disco | el lector |
| C | más el escritor npz/LH5, a la SD, a tmpfs o por red | el sistema completo |

Cada etapa barre la tasa (periódica para el techo, aleatoria para la pérdida contra un
modelo de cola) para cada largo de ventana. **El criterio de que anda a una tasa R con
una ventana W:** cero descartes y cero errores de patrón en 10⁸ eventos o más, también
con el ARM ocupado en otra cosa.

**Desde libmca** (0.9.0), con el ring parado:

```python
from API.generadores import disparos, predecir
from API.osciloscope_ring import GEN_LAT_TS, LectorRing, OsciloscopeRing, patron_gen

d = disparos(aleatorio=True, tasa=500e3, dt_min=5, n=100_000, semilla=7)
lector = LectorRing(ring, pre, post, 2, [identidad] * 2)
lector.configurar()
ring.gen_configurar(d, patron=True)       # queda prendido
ring.correr()
# ... lector.leer(...) hasta que gen_estado()['terminado'] y estén todos ...
ring.parar()
ts = predecir(n_ciclos, GEN_LAT_TS, **d)   # la marca del slot de cada disparo k
```

`patron_gen(ts_hw, pre, pre + post)` es lo que tiene que haber en cada slot, y el
snapshot `{1, k}` dice qué `ts[k]` le toca.

**Para las etapas** (libmca 0.10.0) va `medir` en vez de `leer`: consume y devuelve el
crédito igual, pero no entrega nada, y acumula lo medido de una llamada a la otra:

```python
m = lector.medir('creditos', plazo_ns)               # etapa A: RD_SLOT <- WR_SLOT
m = lector.medir('copia', plazo_ns)                  # el footer y la copia de cada slot
m = lector.medir('verificar', plazo_ns, disparos=d)  # etapa B: la verificación, en C
```

| campo | qué es |
|---|---|
| `eventos`, `bytes` | lo consumido, y lo copiado de la DDR |
| `t0_ns`, `t1_ns`, `trabajo_ns` | del primer bloque al fin del último, y cuánto de eso fue trabajo y no sondeo vacío |
| `ocupacion_max` | los slots que llegó a tener ocupados el ring: el margen |
| `descartados` | `DROP_BUSY + DROP_FULL`, leídos al volver de cada llamada |
| `err_cabecera`, `err_marca`, `err_k`, `err_ts`, `err_patron`, `muestras_malas` | los slots con cada error, y `primer_error_seq` |
| `k_saltos`, `k_ultimo` | los k que faltan antes de cada slot, y el último |

'verificar' compara cada muestra desde el arranque con el patrón, exige el snapshot
`{1, k}` con k y ts que avanzan y, con `disparos`, la marca del motor: exacta en el
periódico (que además da k sin la vuelta de 16 bits) y al menos `dt_min` ciclos por cada
k en el aleatorio. Un slot con error se cuenta y se sigue. Al terminar, con todo leído:

```
k_saltos + (GEN_CNT − 1 − k_ultimo) == DROP_BUSY + DROP_FULL
```

La parte C de
`API/tests/placa/test_generadores_placa.py` lo hace con un caso periódico sin pérdidas
y otro aleatorio a 3 MHz, que pierde por `DROP_BUSY`, verificado en numpy. Pasó en la
placa el 2026-11-09 (60 de 60; los datos, en `software/datos/placa_generadores_20261109/`).
El primer disparo del caso aleatorio cae en `ts = 2`, y sus 6 primeras muestras son de
antes del arranque (§2): el test no las compara.

### La campaña: `campanas/run_etapas_ring.py`

Barre etapa × ventana × modo × tasa con el generador como estímulo, sin el Rigol:

```
make campana-etapas-ring-remoto OUT=datos/etapas_<fecha> ETAPAS=A,B,C ARGS="--carga 2"
```

| etapa | qué corre |
|---|---|
| A | `medir('creditos')` |
| `copia` | `medir('copia')`, si se la pide: separa el costo de copiar del de verificar |
| B | `medir('verificar')` |
| C | `AdquisicionRing` (`RingSource` con el generador y `AcquisitionSession`, npz o LH5) a `--destino`; después lee los archivos y los verifica en numpy con las reglas de B. Con `--red`, la sesión corre en el servidor de la placa (abajo) |
| D0 | el ring por red, sin disco (siempre con `--red`): la placa manda los slots desde C (`EmisionRing`) y la PC los recibe y los descarta. Es el techo de la placa y la red juntas ([`salida_por_red.md`](salida_por_red.md), «El ring por red») |
| D | lo mismo guardando: el stream a `ring_*.bin` en la PC, `convertir` a la sesión y la verificación de C. Las cuentas del stream (`EV_CNT`, los descartes de las cabeceras) también tienen que cerrar |

- **Las ventanas por defecto** son las seis de la simulación del RTL
  (`figuras/tiempos/geometrias.txt`), con su `slot_shift`.
- **Las tasas** van de 10 k/s a 3 M/s. El periódico agrega a cada ventana los dos períodos
  del techo del writer de la simulación: `writer − 2`, donde el RTL pierde, y `writer`,
  donde no.
- **Cada punto** dura como mucho `--seg-max` segundos de estímulo, con hasta `--n`
  disparos.
- **La salida** es `etapas_ring.json`, que se reescribe después de cada punto. Al
  final hay una tabla con el techo del periódico por etapa y ventana: la tasa más alta
  sin descartes y la más baja con `DROP_FULL`, contra los techos de la simulación.

**Contra qué se compara cada punto:**

- **La cuenta cierra:** `EV_CNT + DROP_BUSY + DROP_FULL = GEN_CNT = N`, y se consumió
  todo lo escrito.
- **B, C y D no tienen errores.**
- **`DROP_BUSY` es el que predice el tiempo muerto de la captura.** Un disparo que cae a
  menos de `2·(pre + post) + 3` ciclos de la marca del último aceptado se descarta. Un
  descarte no extiende ese tiempo.
  - Con las marcas de `predecir` el número es exacto mientras no haya `DROP_FULL`: un
    descarte por lleno no abre ventana, y cambia la cadena.
  - Son los `2·S + 2` de la simulación (`logica_de_captura_y_axi.md` §2.4) más uno.
  - **El `+ 3` se ajustó en la placa:** el caso C2 del 2026-11-09 dio 59 762, y la cadena
    con `2·S + 3` da 59 762 exactos; con `2·S + 2` da 59 373.

Lo que no cierra es una anomalía y el script sale con 1. Un `DROP_FULL` no es anomalía:
es lo que se mide. El criterio de esta sección (10⁸ eventos sin descartes ni errores, con
el ARM ocupado) es una corrida aparte en el punto elegido: `--n 1e8 --seg-max 0
--carga 2`. **Vale para A y B.** En C el punto entero queda en el disco hasta
verificarlo, y 10⁸ ventanas de 32 muestras son unos 15 GB. El script saltea el punto
que no entra en `--destino`; para 10⁸ en C haría falta verificar y borrar mientras se
escribe.

Se probó sin placa contra el ring simulado con el generador (`API/ring_falso.py`,
`RingFalsoGen`; `campanas/tests/test_etapas_ring.py`), con 48 mutaciones del script, de
`RingSource`, de la sesión y del servidor, todas atrapadas. El modelo se comprobó contra la placa (C2) y la tabla de techos contra
`geometrias.txt`.

**Un punto sin descartes no es un techo si el lector se atrasó.** El ring tiene 131 072
slots de 256 B: un punto de 0,2 s puede no perder nada aunque el lector lea a la mitad
de la tasa. Por eso el resumen cuenta como saturado el punto donde:

- hay `DROP_FULL`;
- el ring pasó de 1/16, o de 1/16 del punto si el punto es más largo que el ring (el
  atraso de un lector lento crece con N, y el de una demora pasajera, no);
- el lector trabajó el 95 % del tiempo;
- o, en C, la sesión leyó a menos del 90 % de la tasa de los aceptados.

De los saturados da lo que pasa por la etapa: en A, el writer de la PL; en B, el
lector; en C, el lector de la sesión. `--resumen` lo reimprime desde el JSON.

### La etapa C por la red

**La sesión corre en la placa y escribe en un directorio de la PC montado por NFS.** La
campaña corre en la PC: inicia, sigue y para cada punto por el servidor, y verifica
los archivos en el mismo directorio, del lado de la PC. Por el socket va sólo el
control; los datos van por el montaje.

```
make placa-montar-red                     # una vez: ~/pitaya_red de la PC en /mnt/pc
make app-servidor-remoto                  # con el bitstream del ring cargado
make campana-etapas-ring-red OUT=datos/etapas_red_<fecha> ARGS="--ventanas 8+24,16+240,32+992"
```

- **El servidor** (`app/mca_server.py`) tiene tres ops para el ring: `ring.iniciar`,
  `ring.estado` y `ring.parar`. Detrás está `AdquisicionRing`
  (`API/osciloscope_ring.py`), la misma clase que usa la campaña en la placa.
  - Hay una adquisición por vez, y sigue aunque el cliente se vaya.
  - `fpga.load_bitstream` se rechaza mientras corre una.
  - Está en `docs/APP/protocolo.md`.
- **El montaje.** El kernel de la placa trae el cliente NFS v3 y no trae `mount.nfs`, así
  que se monta con las opciones del kernel, dando los puertos: `port=2049`,
  `mountport=20048`, `nolock`. Eso pide tres cosas en la PC, que van con sudo:
  - el export en `/etc/exports` (`rw,async,all_squash`, con el uid del usuario);
  - `mountd` en un puerto fijo (`[mountd] port=20048` en `/etc/nfs.conf`);
  - el firewall abierto a la placa en esos dos puertos.
- **Cada corrida dice dónde escribió:** `fs` (`nfs`, `ext4`, `tmpfs`) va en la fila del
  JSON y en el `meta` de cada archivo.
- **Las reglas y el criterio de fin son los mismos** que contra la SD: el mismo
  `correr_sesion`, con un ejecutor local o remoto.

### En la placa (2026-11-12)

Con el bitstream del ring 78e26188 y libmca 0.10.0. Los datos están en
`software/datos/placa_etapas_20261112/`.

**Los modos del lector (parte D de `verificar-placa-generadores`):** 114 de 114. En los
tres modos la cuenta cierra con lo consumido, `verificar` no encuentra errores, y los k
que faltan son los descartados. A 1 M/s con 32 muestras, `creditos` sigue sin perder,
`copia` lee 753 k/s y `verificar` 383 k/s.

**A y B: 168 puntos en las seis ventanas, sin anomalías.**

- **El techo del writer es el de la simulación en las seis ventanas.** Con un período de
  `writer` ciclos A no pierde, y con `writer − 2` pierde por `DROP_FULL`. El AXI y la
  DDR de la placa no frenan al writer.
- **`DROP_BUSY` es el del tiempo muerto `2·S + 3`** en cada punto sin `DROP_FULL`, en
  las seis ventanas.
- **Ningún slot tuvo errores en B.**

| ventana | A: techo (sim) | B: al día / lo que lee saturado |
|---|---|---|
| 8 + 24 | 1420 k/s (1420) | 300 / 439 k/s, 70 MB/s |
| 16 + 112 | 381 k/s (381) | 100 / 146 k/s, 79 MB/s |
| 16 + 240 | 193 k/s (193) | 30 / 88 k/s, 93 MB/s |
| 16 + 479 | 99 k/s (99) | 30 / 47 k/s, 95 MB/s |
| 16 + 998 | 61 k/s (61) | 10 / 24 k/s, 98 MB/s |
| 32 + 992 | 49 k/s (49) | 10 / 23 k/s, 96 MB/s |

«Al día» es la tasa más alta del barrido (10, 30, 100, 300 k/s…) sin descartes y sin
atraso. Lo que lee el lector saturado es el número fino. Con ventanas chicas lo limita
el costo por slot, y con las grandes el ancho de banda, cerca de 95 MB/s copiando y
verificando.

**C: la sesión entera, npz.** 36 puntos contra la SD y 31 contra `/dev/shm`, sin
anomalías. En los dos casos, todos los archivos son el patrón y cierran con `EV_CNT`.

| ventana | SD: al día / pasa | `/dev/shm`: al día / pasa |
|---|---|---|
| 8 + 24 | 100 / 167 k/s (26 MB/s) | 100 / 203 k/s (32 MB/s) |
| 16 + 240 | 30 / 37 k/s (39 MB/s) | 30 / 42 k/s (44 MB/s) |
| 32 + 992 | 10 / 10 k/s (40 MB/s) | 10 / 10 k/s (40 MB/s) |

Con 1024 muestras tmpfs da lo mismo que la SD: **el límite de C es el software de la
sesión, no el disco**. Hay que tomarlo con cuidado: cada punto escribe como mucho unos
400 MB, que el page cache absorbe, así que la SD sostenida puede ser más lenta.

**El criterio de 10⁸ eventos, con el ARM ocupado.** 32 muestras, periódico, 10⁸
disparos y `--carga 2` (un proceso que ocupa cada núcleo), en el punto «al día» de cada
etapa. Comando: `--ventanas 8+24 --modos periodico --sin-techo --n 1e8 --seg-max 0
--carga 2`.

| etapa | tasa | descartes | lee | ring, ocupación máxima | |
|---|---|---|---|---|---|
| A | 1404,5 k/s (período 89, uno más que el writer) | 0 | 1404,7 k/s | 42 191 slots (909 sin carga) | **cumple** |
| B | 299,8 k/s | 22 216 700 por `DROP_FULL` (22,2 %) | 232,8 k/s | lleno | **no cumple** |
| B | 200,0 k/s | 0 | 200,0 k/s | 105 654 slots (81 %) | **cumple, sin margen** |

- **En A**, el ARM ocupado demoró al lector unos 30 ms (42 191 slots a 1,4 M/s), y el
  ring lo absorbió. En el promedio, lee a la tasa del estímulo.
- **En B**, el lector ya trabajaba el 88 % del tiempo sin carga. Con dos procesos más en
  los dos núcleos le toca unos 2/3 de núcleo, que cuadra con lo medido: 2/3 ÷ 0,88 ×
  300 ≈ 228 k/s. Igual, en los 77,8 M slots que leyó no hay un solo error de patrón ni
  de k, y la cuenta cierra (`EV_CNT + DROP_FULL = GEN_CNT`).
- **B a 200 k/s cumple, pero justo.** Ningún descarte ni error en 10⁸, leyendo a la tasa
  del estímulo, con el lector trabajando el 94 % del tiempo. Una demora le costó medio
  segundo de atraso, que llenó el ring hasta el 81 %. Una demora un poco más larga
  habría dado `DROP_FULL`: con el ARM ocupado, el número seguro de B con 32 muestras
  está por debajo de 200 k/s.

**Lo que encontró la corrida, ya corregido en el script:**

1. **El resumen de B daba «sin pérdidas hasta 1 M/s» con 32 muestras.** El ring había
   absorbido el atraso del lector, con 124 992 de 131 072 slots ocupados. De ahí el
   criterio de saturación de arriba.
2. **En `/dev/shm` el escritor de la sesión paraba solo.** Para con menos de 200 MB
   libres (`MIN_FREE_MB`), y tmpfs tiene 231 MB. Ahora `--margen-mb` va a la guarda y
   al escritor; con `/dev/shm`, `--margen-mb 16`.
3. **`destrabar` fallaba si el ring terminaba de parar después del `parar` vencido.**
   Al parar `WR_SLOT` vuelve a 0 (`flush` en `event_ring_top.sv`), y `medir` lo tomaba
   como 2³² slots llenos. Ahora mira el estado primero, y como último recurso usa
   `CTRL ← 0x2`.
4. **El resumen daba A del criterio por saturado.** Los 42 191 slots de la demora
   pasaban de 1/16 del ring. En un punto más largo que el ring, ahora la ocupación se
   compara con 1/16 del punto. En los 250 puntos de las otras corridas no cambia nada.

**Lo que falta para las etapas:**

1. ~~**libmca:** los registros del generador y una función que lo configure por tasa.~~
   Hecho en 0.9.0.
2. ~~**El lector de C:** un modo que sólo devuelva los créditos (etapa A) y una
   verificación del patrón y de k que no pase por Python (etapa B), con lo que cuenta
   como errores.~~ Hecho en 0.10.0 (`osciloscope_ring_medir`), con un modo intermedio
   que copia sin verificar. Pasó en la placa el 2026-11-12 (parte D de
   `make verificar-placa-generadores`).
3. ~~**Un script de campaña** que barra la tasa y la ventana y guarde cada etapa.~~
   Hecho: `campanas/run_etapas_ring.py` (arriba).
4. ~~**Correrlo en la placa:** el barrido de A y B, y después C contra la SD y
   tmpfs.~~ Hecho el 2026-11-12 (arriba).
5. **El criterio de 10⁸ eventos** en los puntos elegidos, con `--carga 2` (C no entra
   en el disco). A lo cumple a 1,4 M/s con 32 muestras, y B a 200 k/s sin margen
   (2026-11-12, arriba).
6. **C por la red, y C con LH5.** Por la red: el servidor, el montaje y la campaña
   están hechos y probados sin placa (arriba); falta correrla en la placa, contra las
   mismas tres ventanas que la SD y `/dev/shm`. LH5: la placa tiene h5py 3.6; falta
   correrla, por la red y contra la SD.
7. **El ring por red, D0 y D** (libmca 0.12.0, [`salida_por_red.md`](salida_por_red.md)):
   hechos y probados sin placa el 2026-11-14. Falta medirlos en la placa: primero
   `make bench-tcp-placa` (TCP solo), después `make campana-etapas-ring-por-red`, con la
   PC cableada a la red de la placa.

## Dónde está

- RTL: [`modulos/gen_eventos/rtl/gen_eventos.sv`](../../modulos/gen_eventos/rtl/gen_eventos.sv),
  con el motor de disparos en [`gen_disparos.sv`](../../modulos/gen_eventos/rtl/gen_disparos.sv);
  la instancia y el reparto del bus en `event_ring_top.sv` (`EN_GEN`).
- Modelo: [`modulos/gen_eventos/modelos/python_model/gen_eventos_model.py`](../../modulos/gen_eventos/modelos/python_model/gen_eventos_model.py);
  con `--vectores` reescribe `sim/vectores/gen_*.hex`.
- TB: `modulos/gen_eventos/sim/tb_gen_eventos.sv` (con `sva/gen_eventos_sva.sv`) y
  `modulos/event_ring/sim/tb_event_ring_gen.sv`.
- Correr: `make -C modulos/gen_eventos/work` y `make -C modulos/event_ring/work tb_event_ring_gen`.
