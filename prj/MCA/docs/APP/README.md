# mcamon — la aplicación cliente/servidor del MCA

**Código:** [`prj/MCA/software/app/`](../../software/app/)
**Puesta en marcha:** `make app` la sesión entera · `make app-demo` sin placa
**Tests:** los cuatro niveles de [`pruebas.md`](pruebas.md), tres corren sin hardware

Un servidor en la Pitaya que expone [`API/mca.py`](../../software/API/mca.py)
por TCP, y una aplicación PyQt5 en la PC que muestra el espectro creciendo en
vivo. Es el equivalente de la aplicación `mcpha` de pavel-demin, adaptado al
MCA de este proyecto, que tiene otro hardware debajo.

```
        PC                                          Red Pitaya
┌────────────────────┐                        ┌──────────────────────┐
│  mcamon.py         │   JSON  +  binario     │  mca_server.py       │
│  PyQt5 +           │ ◄────────────────────► │  API/mca.py          │
│  matplotlib        │       TCP 1001         │  mmap /dev/mem       │
└────────────────────┘                        └──────────────────────┘
```

---

## Documentos

| Documento | Qué contiene |
|---|---|
| [`flujo_de_datos.md`](flujo_de_datos.md) | **empezar por acá**: el camino de control y el de datos, hilo por hilo, con las restricciones de cada salto |
| [`protocolo.md`](protocolo.md) | las 15 operaciones, el formato de trama, los errores, y una sesión con `nc` |
| [`pruebas.md`](pruebas.md) | qué demuestra cada test — y, sobre todo, **qué no cubre ninguno** |

---

## La arquitectura, en corto

**El handle remoto ES un `MCA`.** `MCARemote`
([`API/mca_remote.py`](../../software/API/mca_remote.py)) hereda de `class MCA`
y sólo redefine `r32`/`w32` y las lecturas en bloque. Como todas las funciones
de `API/mca.py` acceden al hardware únicamente por ahí, **la superficie `mca_*`
entera funciona por red sin tocar una línea**:

```python
from API.mca import mca_set_thr, mca_read_histogram
from API.mca_remote import MCARemote

h = MCARemote.connect('10.73.28.27')
mca_set_thr(h, 317)
hist = mca_read_histogram(h)
```

Es el mismo patrón con el que `RingSource` es drop-in de `BramSource`: la
interfaz la fija el consumidor, no el transporte. La consecuencia práctica es
que el cliente reusa el guardado tal cual — un fichero escrito desde la GUI es
indistinguible de uno escrito en la placa, y `mca_load_file()` los relee igual.

**Dos caminos, un socket.** Los comandos son decenas de bytes y se leen con
`nc`; el espectro son 64 KB que cuestan del orden de 110 ms de lectura palabra a
palabra en la placa. Cada mensaje es una línea JSON de control seguida
opcionalmente de un bloque binario. El desarrollo está en
[`flujo_de_datos.md`](flujo_de_datos.md).

**Un hilo dueño del socket.** La GUI nunca lo toca: con ~110 ms por espectro, un
refresco en el hilo de la interfaz la congelaría.

---

## Qué hay en cada pestaña

| Pestaña | Contenido |
|---|---|
| **Mensajes** | cada operación y cada error con hora. Es lo que permite reconstruir qué pasó cuando el síntoma llega tarde y desfigurado |
| **Espectro** | el histograma 1D, umbrales, exposición, contadores, ROI con ajuste gaussiano, y guardado |
| **Mapa 2D (PSD)** | amplitud × factor de forma y la FOM. **Aparece sólo si el bitstream lo trae** (bit `CAP_HIST_H_PSD` de `CAPS`) |

En la barra superior van la IP, el puerto, el canal (IN1/IN2), el estimador
(pico o integral de carga), la decimación y el período de refresco.
`Placa → Cargar bitstream del MCA…` reprograma la PL.

---

## Diferencias con `mcpha`, y por qué

Casi todas las impone el hardware, que no es el mismo:

| `mcpha` | Acá |
|---|---|
| dos MCA independientes, dos pestañas de espectro | **uno solo** con mux de canal (`0x00C[8]`): una pestaña y un selector IN1/IN2 |
| 4096 canales | `2^h_aw`, leído del registro `WIDTHS` — el cliente **no hardcodea** la geometría |
| temporizador de exposición en hardware | no existe: lo implementa un hilo del servidor contra `livetime_s` |
| `negator` por canal | no hay negador en el RTL; en su lugar está el selector `amp_src` (pico o integral de carga) |
| — | contadores propios: `rej_amp`, `rej_psd`, `pileup`, `dropped`, y real/vivo/muerto |
| — | mapa 2D de forma de pulso y figura de mérito |

---

## Reglas de la placa que el código respeta

Y que hay que seguir respetando al tocarlo:

1. **Un solo proceso sobre `/dev/mem`.** El servidor acepta un cliente a la vez
   y rechaza el segundo con un error explícito. Si un kernel de Jupyter está
   vivo y hace `rp_Init()`, los dos pelean y sale SIGBUS.
2. **Lectura palabra a palabra.** No tocar `MCA._read_words`: un slice o un
   `np.frombuffer` sobre la apertura **reinicia la placa**.
3. **Escritura por asignación de slice**, nunca `struct.pack_into`.
4. **Bitstream antes que los mapeos.** `fpga.load_bitstream` cierra el handle
   primero y sondea el bus en un proceso hijo antes de reabrir.
5. La adquisición **no** se detiene al desconectar el cliente: una medida larga
   sobrevive a cerrar la GUI.

---

## Estado

- [x] MCA completo: configuración, control, espectro, mapa 2D, contadores.
- [x] Exposición por tiempo vivo.
- [x] Guardado y relectura en los tres formatos, compatibles con la placa.
- [x] Validado contra pulsos reales del generador ([`pruebas.md`](pruebas.md)).
- [ ] OSC, multitrigger y event_ring: no están expuestos.
- [ ] Descubrimiento de slots por el registro `SLOTS` de `integration_cfg`.

### Lo que falta para las pestañas de DSP, triggering y OSC

El servidor está armado alrededor de un handle y una tabla de operaciones, así
que añadir un bloque es añadir un handle y sus operaciones; y un panel nuevo es
un `QWidget` con sus señales, como
[`panel_mapa2d.py`](../../software/app/panel_mapa2d.py). Los bloques ya tienen
API: [`API/osciloscope.py`](../../software/API/osciloscope.py) (slot 1),
[`API/multitrigger.py`](../../software/API/multitrigger.py) (slot 3) y
[`API/osciloscope_ring.py`](../../software/API/osciloscope_ring.py) (slot 2).

Lo que sí hay que decidir antes es el **descubrimiento**: el registro `SLOTS` de
`integration_cfg` (`0x4060_0024`) publica en qué slot está cada bloque, y
conviene leerlo en el `identify` en vez de hardcodear bases — como ya se hace
con `WIDTHS` para la geometría del histograma. Sin eso, la aplicación queda
atada a un top concreto.

La deuda conocida del código está listada al final de
[`flujo_de_datos.md`](flujo_de_datos.md#estado-y-deuda-conocida).

---

## Ver también

[`referencia_api.md`](../API/referencia_api.md), la API que el servidor expone ·
[`register_map_mca.md`](../mca/register_map_mca.md), los registros del otro lado ·
[`arquitectura_adquisicion_software.md`](../multitrigger/arquitectura_adquisicion_software.md),
el pipeline de adquisición de formas de onda, que es el otro camino de datos del
proyecto y no pasa por acá
