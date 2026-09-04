# Tests / benchmarks de lectura del buffer ADC (`prj/MCA/software/tests/`)

Tests para los métodos de lectura del buffer ADC del Red Pitaya y para el fix de
`capture_window_np` (que usa `rp_AcqGetDataPosV`).

> Este README cubre sólo los tests de **lectura del buffer**. Los otros dos
> grupos de este directorio están documentados aparte:
>
> - `test_mca_hw.py`, `test_mca_datapath.py`, `diag_mca_hw.py` →
>   [`../../docs/mca/testbenches_software_mca.md`](../../docs/mca/testbenches_software_mca.md)
> - `test_mca_pipeline.py` y los bloques de escritor/GIL de
>   `bench_reader_budget.py` →
>   [`../../docs/testbenches_escritura_archivos.md`](../../docs/testbenches_escritura_archivos.md)

**Corren en la Pitaya** (necesitan el módulo `rp` y el bitstream multitrigger
cargado). **No necesitan el Rigol**: congelan el buffer con un SW trigger, así
que funcionan con cualquier señal (o sin señal, leyendo el ruido del ADC).

> ⚠️ **NO correr con el kernel de Jupyter activo.** Estos scripts hacen su
> propio `rp.rp_Init()` + captura; si el kernel del notebook también está usando
> `rp`/el scope, los dos procesos pelean por `/dev/mem` y da **Bus error
> (SIGBUS)** (y puede corromper la captura del kernel). Reiniciá/cerrá el kernel,
> o corré estos tests DENTRO del propio notebook (misma sesión `rp`).

## Contexto del fix

`capture_window_np` devolvía **todo ceros** con `rp_AcqGetDataPosV`. Causa (fuente
rp-api `acq_handler.c`): `end_pos` es **inclusivo** y la API exige
`buffer_size >= end-start+1`; si es menor devuelve `RP_BTS` y **no escribe nada**.
El código pasaba `end=ref+post` con `buffer_size=pre+post` (uno corto) → `RP_BTS`
silencioso (el return code se ignoraba). El fix usa `end=ref+post-1` (inclusivo,
`n` samples exactos) y **chequea el return code**. Ver
[`../multitrigger_utils.py`](../multitrigger_utils.py) `capture_window_np`.

## Correr

```bash
# copiar a la Pitaya (o ya está por el rsync del software)
rsync -avz tests/ pitaya:/home/jupyter/RedPitaya/remote_soft/tests/

ssh pitaya 'cd /home/jupyter/RedPitaya/remote_soft/tests && python3 test_capture_window_np.py'
ssh pitaya 'cd /home/jupyter/RedPitaya/remote_soft/tests && python3 bench_buffer_read.py'
```

## `test_capture_window_np.py`

Correctness: compara la ventana de `capture_window_np` (PosV, arreglado) contra la
misma ventana recortada del buffer completo leído con `rp_AcqGetOldestDataV`.
Falla si difieren o si PosV devuelve ceros. Imprime `RESULT: PASS/FAIL`.

## `bench_buffer_read.py`

Benchmark: congela el buffer y mide el tiempo de leer `N` samples con cada método
disponible del módulo `rp` (via `hasattr`): `rp_AcqGetOldestDataV`,
`rp_AcqGetDataV`, `rp_AcqGetDataPosV`, y las variantes `*NP` si existen. Compara
dos dimensiones:

- **read en C** (`rp_AcqGet...`),
- **extracción a numpy**: `fBuffer` + `np.fromiter` (loop Python, lento) vs las
  variantes `*NP` (escriben directo a un `np.array`, sin loop).

```
python3 bench_buffer_read.py [N] [REPS]
  N    = samples a leer  (default 16384)
  REPS = repeticiones     (default 200)
```

Reporta `mean/median/min` (ms), `match` (mismos datos que el primer método) y
`zeros` (si devolvió ceros = bug), más el speedup relativo. Sirve para justificar
qué método usar (p. ej. confirmar si PosV o las variantes NP son más rápidas para
tu tamaño de ventana).
