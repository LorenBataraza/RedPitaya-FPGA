# mcamon — aplicación cliente/servidor del MCA

Un servidor en la Pitaya que expone [`API/mca.py`](../API/mca.py) por TCP, y una
aplicación PyQt5 en la PC que muestra el espectro creciendo en vivo.

```
    PC                                  Red Pitaya
┌──────────────┐   JSON + binario   ┌──────────────────┐
│  mcamon.py   │ ◄────────────────► │  mca_server.py   │
│  PyQt5 +     │      TCP 1001      │  API/mca.py      │
│  matplotlib  │                    │  /dev/mem 0x4070…│
└──────────────┘                    └──────────────────┘
```

---

## Puesta en marcha

**En la Pitaya** (una sola vez por sesión; ojo: el servidor tiene que ser el
único proceso con `/dev/mem` abierto, así que hay que parar el kernel de
Jupyter si estaba usando la placa):

```bash
# desde la PC, el rsync de siempre
rsync -avz prj/MCA/software/API prj/MCA/software/app \
      pitaya:/home/jupyter/RedPitaya/remote_soft/

ssh pitaya
cd /home/jupyter/RedPitaya/remote_soft
/opt/redpitaya/bin/fpgautil -b /root/mca_red_pitaya.bit.bin
python3 app/mca_server.py --selftest      # opcional: comprueba el camino de lectura
python3 app/mca_server.py --port 1001
```

**En la PC:**

```bash
python3 prj/MCA/software/app/mcamon.py --host 10.73.28.27
```

Sin placa a mano, todo funciona igual contra un MCA simulado:

```bash
python3 app/mca_server.py --fake --port 5001 &
python3 app/mcamon.py --host 127.0.0.1 --port 5001 --conectar
```

> **En la PC hay que usar un puerto ≥ 1024.** El 1001 por defecto es el de
> `mcpha` y en la Pitaya anda porque ahí se corre como root; en una sesión de
> usuario, Linux reserva todo lo que está por debajo de 1024 y el `bind` falla
> con `PermissionError`.

---

## Qué hay en cada pestaña

| Pestaña | Contenido |
|---|---|
| **Mensajes** | cada operación y cada error con hora. Es lo que permite reconstruir qué pasó cuando el síntoma llega tarde |
| **Espectro** | el histograma 1D, umbrales, exposición, contadores, ROI y guardado |
| **Mapa 2D (PSD)** | amplitud × factor de forma y la FOM. **Aparece sólo si el bitstream lo trae** (bit `CAP_HIST_H_PSD` de `CAPS`) |

En la barra superior van la IP, el puerto, el canal (IN1/IN2), el estimador
(pico o integral de carga), la decimación y el período de refresco.

`Placa → Cargar bitstream del MCA…` reprograma la PL: el servidor cierra sus
mapeos antes, que es lo que evita dejar el puerto GP0 trabado.

---

## Diferencias con el hardware de referencia (`mcpha`)

| `mcpha` | Acá |
|---|---|
| dos MCA independientes | **uno solo** con mux de canal (`0x00C[8]`): una pestaña y un selector IN1/IN2 |
| 4096 canales | `2^h_aw` = 16384, leído del registro `WIDTHS`, no hardcodeado |
| temporizador de exposición en hardware | no existe: lo implementa el hilo `_vigilante` del servidor contra `livetime_s` |
| `negator` por canal | no hay negador en el RTL; en su lugar está el selector `amp_src` |
| — | `rej_amp`, `rej_psd`, `pileup`, `dropped` y real/vivo/muerto |
| — | mapa 2D de forma de pulso y FOM |

---

## Cómo está armado

**El handle remoto ES un `MCA`.** `MCARemote`
([`API/mca_remote.py`](../API/mca_remote.py)) hereda de `class MCA` y sólo
redefine `r32`/`w32` y las lecturas en bloque. Como todas las funciones de
`API/mca.py` acceden al hardware únicamente por ahí, **la superficie `mca_*`
entera funciona por red sin tocar una línea**:

```python
from API.mca import mca_set_thr, mca_get_metadata, mca_read_histogram
from API.mca_remote import MCARemote

h = MCARemote.connect('10.73.28.27')
mca_set_thr(h, 317)
hist = mca_read_histogram(h)
```

Es lo mismo que hace `RingSource` para ser drop-in de `BramSource`: la interfaz
la fija el consumidor, no el transporte. La consecuencia práctica es que el
cliente reusa el guardado tal cual — un fichero escrito desde la GUI es
indistinguible de uno escrito en la placa, y `mca_load_file()` los relee igual.

**El protocolo** ([`API/mca_net.py`](../API/mca_net.py)) es una línea JSON de
control seguida de un bloque binario opcional. Los comandos se leen con `nc`;
los 64 KB del espectro no pagan el peaje de JSON.

**El refresco en vivo es barato.** Leer el espectro colisiona con el pipeline
del histograma —el bus tiene prioridad y el evento perdido se cuenta en
`dropped`— pero ocupa el puerto ~2 ciclos cada 6.7 µs. Con un refresco por
segundo la pérdida es del orden del 0.01 %, y está a la vista en el contador.

---

## Reglas de la placa que el código respeta (y hay que seguir respetando)

1. **Un solo proceso sobre `/dev/mem`.** El servidor acepta un cliente a la vez
   y rechaza el segundo con un error explícito.
2. **Lectura palabra a palabra.** No tocar `MCA._read_words`: un slice o un
   `np.frombuffer` sobre la apertura **reinicia la placa**.
3. **Escritura por asignación de slice**, nunca `struct.pack_into`.
4. **Bitstream antes que los mapeos.** `fpga.load_bitstream` cierra el handle
   primero y sondea el bus en un proceso hijo antes de reabrir.
5. La adquisición **no** se detiene al desconectar el cliente: una medida larga
   sobrevive a cerrar la GUI.

---

## Pruebas

En la PC, sin placa:

```bash
cd prj/MCA/software
python3 API/tests/test_mca_net.py       # framing: payloads de 64 KB, truncados, errores
python3 app/tests/test_mca_remote.py    # la superficie mca_* entera, por socket
python3 app/tests/test_mcamon_gui.py    # la GUI de punta a punta, sin pantalla
python3 API/tests/test_compat_api.py    # nada público de API/mca.py cambió
```

En la placa:

```bash
python3 app/mca_server.py --selftest   # identify + 1 s + espectro, con /proc/uptime
python3 API/tests/placa/diag_mca_hw.py           # el camino de lectura sigue intacto
```

---

## Lo que falta para las pestañas de DSP, triggering y OSC

El servidor está armado alrededor de un handle y una tabla de operaciones
(`ServidorMCA._OPS`), así que añadir un bloque es añadir un handle y sus
operaciones; y un panel nuevo es un `QWidget` con sus señales, como
[`panel_mapa2d.py`](panel_mapa2d.py). Los bloques ya tienen API:
[`API/osciloscope.py`](../API/osciloscope.py) (slot 1),
[`API/multitrigger.py`](../API/multitrigger.py) (slot 3) y
[`API/osciloscope_ring.py`](../API/osciloscope_ring.py) (slot 2).

Lo que sí hay que decidir antes es el descubrimiento: el registro `SLOTS` de
`integration_cfg` (`0x4060_0024`) publica en qué slot está cada bloque, y
conviene leerlo en el `identify` en vez de hardcodear bases, como ya se hace
con `WIDTHS` para la geometría del histograma.
