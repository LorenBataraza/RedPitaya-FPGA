# Tests de la escritura de archivos (`mca/` → disco)

El camino evento→disco es la parte del software con menos verificación visible y
la que más invariantes finos tiene: hilos, colas, contabilidad de descartes y
escritura atómica. Este documento dice **qué está verificado, con qué test, y
qué queda sin cubrir**.

El *diseño* del pipeline está en
[`arquitectura_adquisicion_software.md`](multitrigger/arquitectura_adquisicion_software.md);
acá está la **verificación**.

| Archivo | Rol |
|---|---|
| [`../software/mca/events.py`](../software/mca/events.py) | esquema del evento y `EventBatch` preasignado |
| [`../software/mca/reader.py`](../software/mca/reader.py) | hilo lector |
| [`../software/mca/storage.py`](../software/mca/storage.py) | hilo escritor: un `.npz` por chunk |
| [`../software/mca/session.py`](../software/mca/session.py) | orquestador |
| [`../software/tests/test_mca_pipeline.py`](../software/tests/test_mca_pipeline.py) | **el test**: corre en la PC, sin placa |
| [`../software/tests/bench_reader_budget.py`](../software/tests/bench_reader_budget.py) | los benchmarks que fijan los defaults |

---

## 1. Los invariantes que hay que proteger

Antes de mirar los tests, qué es lo que puede salir mal y por qué importa:

- **Escritura atómica.** El escritor escribe `.tmp` y hace `os.replace`, así que
  **todo `.npz` visible en el directorio está completo**. Es la condición para
  que un consumidor (un *file pusher*, un notebook de análisis) pueda leer el
  directorio mientras la corrida avanza, sin carreras.
  > Detalle que ya mordió: a `np.savez` se le pasa un **handle**, no el path,
  > porque si no le agrega `.npz` al nombre y quedaría `chunk.npz.tmp.npz`.
- **Contabilidad cerrada.** Todo evento generado o se guarda, o se **cuenta**
  como descarte. Ninguno se pierde sin registro. Y los descartes tienen que
  quedar localizables en el tiempo, no sólo en un total.
- **El lector nunca se bloquea.** Si el escritor se atrasa, se descartan eventos
  —no se frena la adquisición—. Es una decisión de diseño, y el test la
  verifica.
- **RAM acotada.** El pool de batches se asigna al arrancar y no crece con la
  duración de la corrida (el problema de `guardado_mariana.py`, donde la lista
  crece hasta el final y un corte se lleva todo).
- **El esquema no está hardcodeado.** Las columnas se arman en runtime a partir
  de lo que declaren la fuente y los *annotators*, así que agregar columnas no
  toca ni al lector, ni al escritor, ni al formato de archivo.

### Cómo se marcan los descartes: la columna `gap`

`gap` es un `uint8` por evento que dice **cuántos eventos se descartaron justo
antes de éste**. Es lo que permite saber *dónde* en el tiempo hubo pérdidas, no
sólo cuántas. Tiene dos límites que el test ejercita a propósito:

- **satura en 255** (`GAP_MAX`), así que `sum(gap) ≤ chunk_dropped`;
- **no puede registrar los descartes del final** de la corrida, porque no hay un
  evento posterior donde anotarlos: ésos van a `trailing_dropped` del
  `run_summary.json`.

Por eso el invariante completo es
`sum(chunk_dropped) + trailing_dropped == n_dropped`, y **no** `sum(gap) == n_dropped`.

---

## 2. `test_mca_pipeline.py` — el test principal

Corre **en la PC, sin placa**, usando `FakeSource`. Cubre la mecánica que no
depende del hardware.

```bash
cd prj/MCA/software && python3 tests/test_mca_pipeline.py
```

Imprime `[PASS]`/`[FAIL]` por chequeo y `RESULT: PASS|FAIL` al final, con exit
code distinto de cero si falló.

### Bloque 1/2/5 — contabilidad, integridad y atomicidad

512 eventos a 20 kHz, `capacity=64`:

- **no quedan `.tmp` huérfanos** y se escribió al menos un chunk;
- la `meta` de cada chunk es consistente (`chunk_events == len(t_ns)`,
  `schema_version >= 1`);
- `leídos == generados`, sin descartes a esa tasa, y `sum(gap) == n_dropped`;
- forma del array `(eventos, canal, muestra)`;
- **la forma del pulso sobrevivió el viaje**: el pulso sintético sube en `pre=8`,
  así que el `argmax` mediano tiene que caer exactamente ahí. Es lo que detecta
  un `reshape` mal hecho o un canal cruzado, cosas que la contabilidad no ve;
- **`int16` en disco** y error de cuantización ≤1 cuenta en la ida y vuelta
  float32 volts → int16 cuentas.

### Bloque 3 — backpressure: descartar y contar, nunca bloquear

Es el bloque con el escenario más armado. Con `ram_budget_mb=0.001` (→ 2
batches) y el escritor **frenado 40 ms en los dos primeros chunks**, se fuerza
una ráfaga de descartes **en medio** de la corrida y después el escritor se
normaliza. Eso es el caso realista —una ráfaga, no una degradación monótona— y
es el que la columna `gap` tiene que marcar.

Verifica:

- que hubo descartes (si no, el test no probaría nada);
- **`leídos + descartados == generados`**: el lector nunca se bloqueó;
- `chunk_dropped ≥ sum(gap)` en cada chunk — o sea que `gap` **saturó**, y el
  test exige que sature (`sum(gap) < sum(chunk_dropped)`) para probar que el
  escenario ejercita el techo del `uint8`;
- **la contabilidad cierra**: `sum(chunk_dropped) + trailing_dropped == n_dropped`;
- los huecos están **marcados en eventos concretos** (hay eventos con `gap > 0`);
- el lector **se recuperó** después de la ráfaga;
- el `run_summary.json` refleja los totales.

### Bloque 4 — esquema dinámico

Con `n_ch=4` y un `ConstantAnnotator`: el `wave` tiene 4 canales, las columnas
del annotator aparecen con los valores correctos, la `meta` lista los campos y
los canales, y `load_chunk` expone las vistas por canal (`d1`…`d4`) en volts.

### Bloque 4b — colisión de columnas

Dos annotators que declaran la misma columna → **`ValueError` explícito al
construir la sesión**, no datos pisados en silencio. Es barato de verificar y
caro de descubrir en producción.

---

## 3. `bench_reader_budget.py` — los números que fijan los defaults

No es un test de correctitud sino la medición que decide la configuración. Corre
**en la Pitaya** con el bitstream multitrigger cargado. Dos bloques hacen a la
escritura:

**Bloque 5 — escritor.** `savez` vs `savez_compressed` sobre un chunk típico:

| | tiempo | tamaño |
|---|---|---|
| `savez` | 86 ms | 1.07 MB (12.4 MB/s) |
| `savez_compressed` | 628 ms | 0.95 MB |

**7.3× de tiempo por 12 % de espacio** → de ahí sale `compress=False` por
default. Y además comprimir es CPU con el GIL disputado, mientras que escribir
es I/O con el GIL suelto.

**Bloque 6 — contención de GIL.** Latencia por evento del lazo lector, primero
solo y después con un hilo de fondo escribiendo chunks sin parar. Es la medición
que decide si hacen falta afinidad de CPU, `SCHED_FIFO` o proceso aparte. El
stall máximo medido fue **5288 µs, exactamente `sys.getswitchinterval()`** — la
firma de libro de la contención de GIL —, y por eso `session.py` baja el
intervalo a 1 ms.

La otra decisión medida que vive en el escritor: **float32 → int16 en el hilo
escritor, no en el lector.** La API del `rp` sólo entrega volts en float, pero
el ADC es de 14 bits: guardar float32 sería el doble de disco por nada, y el
escritor tiene tiempo de sobra.

---

## 4. Los tests de lectura del buffer

`test_capture_window_np.py`, `bench_buffer_read.py` y `bench_read_vs_length.py`
verifican el **otro extremo** del camino (leer del ADC, no escribir a disco) y
ya están descritos en [`../software/tests/README.md`](../software/tests/README.md).

Vale repetir acá el aviso operativo, porque aplica a todo lo que se corra en la
placa:

> ⚠️ **No correrlos con el kernel de Jupyter activo.** Hacen su propio
> `rp.rp_Init()` + captura; si el kernel también está usando `rp`, los dos
> procesos pelean por `/dev/mem` y da **Bus error (SIGBUS)**, además de poder
> corromper la captura del kernel.

---

## 5. Qué NO está cubierto

Explícito, para que nadie suponga cobertura que no hay:

- **Disco lleno a mitad de escritura.** El escritor tiene la lógica
  (`MIN_FREE_MB`, `disk_full`, y el drenaje de la cola para que el lector no se
  trabe), pero **no hay test que la ejercite**.
- **Corte de energía / kill -9 durante un `savez`.** La escritura atómica está
  diseñada para eso y el test verifica que no queden `.tmp` en una corrida
  normal, pero no simula una interrupción.
- **La fuente real.** `FakeSource` no ejercita la API `rp` ni `/dev/mem`; el
  camino real sólo está cubierto por los tests de placa.
- **Un `.npz` corrupto.** `load_chunk` no tiene test de entrada inválida.
- **Corridas largas.** Nada verifica el comportamiento en horas: fragmentación
  del disco, crecimiento del `run_summary`, o el wrap de índices de chunk.

---

## Ver también

- [`arquitectura_adquisicion_software.md`](multitrigger/arquitectura_adquisicion_software.md)
  — el diseño, con los tres niveles de pérdida y el presupuesto de rendimiento.
- [`testbenches_software_mca.md`](mca/testbenches_software_mca.md) y
  [`testbenches_software_multitrigger.md`](multitrigger/testbenches_software_multitrigger.md)
  — las otras dos suites de software.
