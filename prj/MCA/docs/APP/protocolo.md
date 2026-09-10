# Referencia del protocolo

**Código:** [`API/mca_net.py`](../../software/API/mca_net.py) (framing) · [`app/mca_server.py`](../../software/app/mca_server.py) (despacho) · [`API/mca_remote.py`](../../software/API/mca_remote.py) (cliente)
**Puerto por defecto:** 1001 · **Versión:** 1
**Por qué es así:** [`flujo_de_datos.md`](flujo_de_datos.md)

Todas las operaciones, sus argumentos y lo que devuelven. El *porqué* del diseño
está en [`flujo_de_datos.md`](flujo_de_datos.md); acá está el contrato.

---

## La trama

Un mensaje es **una línea JSON UTF-8 terminada en `\n`**, seguida opcionalmente
de `nbytes` crudos. Nada más. No hay handshake, no hay longitud previa, no hay
números mágicos.

**Petición** — el cliente nunca manda payload:

```json
{"op": "read.spectrum", "args": {}}
```

**Respuesta sin datos:**

```json
{"ok": true, "result": {"val": 317}}
```

**Respuesta con datos** — la cabecera describe el bloque que viene detrás:

```json
{"ok": true, "result": {}, "dtype": "uint32", "shape": [16384], "nbytes": 65536}
```
seguida de exactamente 65536 bytes.

**Error:**

```json
{"ok": false, "error": "MCANotPresent", "msg": "no hay MCA en 0x40700000...", "hint": "cargá mca_red_pitaya.bit.bin"}
```

`error` es el nombre del tipo de la excepción original, y es lo que permite al
cliente distinguir un `MCANotPresent` (hay que cargar el bitstream) de un
`TimeoutError` (el barrido de borrado no terminó). `hint` siempre está presente;
vale `null` si no se pasó.

> **El framing exige un lector con buffer.** Se mezclan líneas y bloques, así
> que un `recv()` suelto se queda corto con 64 KB y se come el principio de la
> cabecera siguiente. `Channel` envuelve el socket en dos ficheros separados
> (`'rb'` y `'wb'`) y no en un `makefile('rwb')`, porque el par de
> lectura/escritura hereda el `readline()` genérico, que va byte a byte.

Guarda de integridad: si el JSON serializado llegara a contener un `\n` se
aborta antes de escribir, en vez de desincronizar el stream sin diagnóstico.

---

## Las operaciones

La lista viva es el dict `_OPS` de
[`mca_server.py:277`](../../software/app/mca_server.py#L277), que además
**valida los nombres de los argumentos**: un argumento no reconocido es un
`ValueError`, no un valor ignorado en silencio.

| op | args | devuelve |
|---|---|---|
| `identify` | — | geometría y estado del bitstream (dos formas, abajo) |
| `r32` | `off` | `{"val": int}` |
| `w32` | `off`, `val` | `{}` |
| `config.get` | — | **todos** los campos de `_CAMPOS` (hoy 34) |
| `config.set` | `fields` | la configuración **releída del hardware** |
| `ctrl.start` | `seconds`, `clear_first` | `{"running": true, "exposure_target_s": float\|null}` |
| `ctrl.stop` | — | `{"running": false}` |
| `ctrl.clear` | `timeout_s` | `{}` |
| `status` | — | contadores, tasas y estado de la exposición |
| `read.spectrum` | — | **binario** `uint32[2^h_aw]` |
| `read.map2d` | — | **binario** `uint32[2^h2_aw, 2^psd_aw]` |
| `read.metadata` | — | las ~39 claves que acompañan a un espectro guardado |
| `read.last_event` | — | `{amp, psd, q_tot, q_tail, baseline}` |
| `fpga.state` | — | `{"state": str}` |
| `fpga.load_bitstream` | `path` | el `identify` del bitstream nuevo |
| `integracion.get` | — | `modules`, `slots`, `caps`, `routes`, `status`, `run` |
| `integracion.set_route` | `consumidor`, `tap`, `enable` | el `get` de vuelta |
| `integracion.reset_routes` | — | el `get` de vuelta |
| `integracion.ctrl` | `que` | el `get` de vuelta |

Sólo `read.spectrum` y `read.map2d` traen payload binario.

**Las `integracion.*` fallan si el bitstream no trae el slot 6**, con un
`RuntimeError` que lo dice. No es una condición de error del cliente: cualquier
bitstream anterior al refactor de registros no lo trae y el MCA anda igual. Por
eso `identify` publica `has_integracion` y el cliente ni siquiera crea la
pestaña — mismo criterio que con `has_2d`.

Las tres que escriben devuelven el `get` completo en vez de `{}`: el ruteo es
estado compartido y releerlo entero después de tocarlo evita que el cliente
mantenga una copia que puede quedar vieja.

> **`OPS` de `mca_net.py` es documentación**, no se importa en ningún lado, y
> por eso podía desincronizarse del despacho real sin que nada lo notara. Ahora
> hay un test que compara las dos listas
> ([`test_mca_remote.py`](../../software/app/tests/test_mca_remote.py)).

### `r32` / `w32`, y por qué existen

Son las dos que sostienen todo lo demás. `MCARemote` hereda de `class MCA` y
redefine sólo estas dos, así que **toda la superficie `mca_*` de `API/mca.py`
funciona por red sin cambiar una línea**:

```python
from API.mca import mca_set_thr, mca_get_config, mca_read_histogram
from API.mca_remote import MCARemote

h = MCARemote.connect('10.73.28.27')
mca_set_thr(h, 317)              # read-modify-write: 2 idas y vueltas
cfg  = mca_get_config(h)         # 1, porque hay operación en bloque
hist = mca_read_histogram(h)     # 1, con payload binario
```

Las demás operaciones existen sólo para ahorrar idas y vueltas (`config.get`
son 19 registros) o para que una secuencia sea **atómica del lado de la placa**
(`ctrl.clear` poléa `clear_busy` cada milisegundo: por red serían decenas de
vueltas, y además podría cruzarse con el hilo de exposición).

### `identify`

Con MCA presente:

```json
{"presente": true, "magic": 1296253233, "caps": 3, "h_aw": 14, "h2_aw": 7,
 "psd_aw": 6, "n_channels": 16384, "map2d_shape": [128, 64], "has_2d": true,
 "hist_h": true, "hist_h_psd": true, "features": false, "running": false,
 "protocol": 1, "fake": false, "fpga_state": "operating",
 "bitstream": "/root/mca_red_pitaya.bit.bin"}
```

Sin MCA —bitstream equivocado o PL sin programar— **la operación no falla**:

```json
{"presente": false, "error": "MCANotPresent: ...", "caps": 0, "h_aw": 0,
 "h2_aw": 0, "psd_aw": 0, "n_channels": 0, "map2d_shape": [0, 0],
 "protocol": 1, "fake": false, "fpga_state": "operating"}
```

> **`identify` contesta siempre, y eso es deliberado.** Es lo que permite
> conectarse a un servidor sin MCA para pedirle `fpga.load_bitstream` y
> arreglarlo desde la GUI. Todas las demás operaciones contestan
> `MCANotPresent` mientras tanto.

La geometría (`h_aw`, `h2_aw`, `psd_aw`) sale del registro `WIDTHS` del propio
`mca_top`, no de constantes: el cliente **nunca hardcodea 16384**.

### `status`

Es lo que poléa la GUI cada 200 ms: todo lo que va en pantalla salvo el
espectro, en una sola vuelta.

```json
{"presente": true, "running": true, "baseline_now": 2129,
 "rate_inst_hz": 3048.2, "rate_avg_hz": 3051.7,
 "counters": {"total": 41502, "accepted": 41502, "rej_amp": 0, "rej_psd": 0,
              "pileup": 0, "dropped": 4, "realtime_s": 13.83,
              "livetime_s": 13.59, "deadtime_s": 0.245,
              "clear_busy": false, "busy": false, "baseline_stale": false},
 "exposure": {"target_s": 50.0, "left_s": 36.4, "done": false}}
```

`rate_inst_hz` es Δ`accepted`/Δ`livetime` entre dos `status` consecutivos —el
servidor guarda la muestra anterior—, y `rate_avg_hz` es `accepted`/`livetime`.
Son los dos números de la aplicación de referencia.

`exposure.target_s` es **livetime absoluto acumulado**, no un delta: una segunda
exposición sin borrar antes continúa donde iba.

### `ctrl.start`

`seconds` a `null` arranca sin límite. Con un valor, arma el hilo vigilante que
parará solo al llegar a ese tiempo **vivo**. `clear_first` borra histogramas,
contadores y relojes antes de arrancar.

### `fpga.load_bitstream`

`path` a `null` usa el bitstream con el que arrancó el servidor. Rechaza si hay
una adquisición corriendo, y en modo `--fake` rechaza siempre. La secuencia
completa está en [`flujo_de_datos.md`](flujo_de_datos.md#la-carga-de-bitstream-paso-a-paso).

---

## Errores

Dos familias, con dos tratamientos distintos.

**`ProtocolError`** — la trama no se entiende o la conexión se cortó a la mitad:
cabecera ilegible, cabecera de más de 64 KB sin terminar, payload truncado,
falta el `dtype`/`shape` de un bloque. Es local a `mca_net.py`; **no viaja por
la red**. Del lado del servidor rompe el lazo de atención sin contestar.

**`RemoteError`** — el otro lado contestó `ok: false`. Conserva `.error`,
`.msg` y `.hint`. Se levanta en un único punto, al desempaquetar la respuesta.

Política del cliente, que son dos y conviene no confundirlas:

| qué pasó | qué hace el cliente |
|---|---|
| `OSError` (el transporte se murió) | **tira la conexión**: para los temporizadores y cierra el socket |
| cualquier otra, incluidas `RemoteError` y `ProtocolError` | la reporta en la pestaña de mensajes y **sigue poleando** |

La distinción importa: un `RemoteError` por un `tail_dly` inválido no debe
cortar una medición de media hora.

### El caso `Ocupado`

El servidor acepta **un cliente a la vez** —regla de hardware: un solo proceso
puede tener `/dev/mem` abierto— y al segundo le contesta y le cierra el socket:

```json
{"ok": false, "error": "Ocupado", "msg": "ya hay un cliente (10.73.28.47)",
 "hint": "un solo proceso puede tocar /dev/mem"}
```

> **Ese error llega antes de que el cliente pida nada.** `MCARemote.connect`
> manda `identify` y espera; lo que recibe es directamente el rechazo, que se
> convierte en `RemoteError('Ocupado', ...)` y cierra el canal.

---

## Una sesión con `nc`

Que esto se pueda hacer es el argumento entero a favor de que el control sea
JSON:

```console
$ printf '{"op":"identify","args":{}}\n' | nc 10.73.28.27 1001
{"ok": true, "result": {"magic": 1296253233, "n_channels": 16384, ...}}

$ printf '{"op":"r32","args":{"off":20}}\n' | nc 10.73.28.27 1001
{"ok": true, "result": {"val": 100}}
```

`off` va en decimal porque JSON no tiene literales hexadecimales: `20` es
`0x014`, o sea `R_THR`.

Para `read.spectrum` la cabecera se lee igual, pero los 64 KB que siguen son
binarios y `nc` los escupe crudos — para eso está el cliente.

---

## Ver también

[`flujo_de_datos.md`](flujo_de_datos.md), por qué el protocolo es así ·
[`referencia_api.md`](../API/referencia_api.md), las funciones que el servidor
expone y a qué registro pega cada una ·
[`register_map_mca.md`](../mca/register_map_mca.md), los offsets que aceptan
`r32`/`w32`
