# Puesta en marcha — de la placa apagada al espectro en pantalla

Este documento es el orden completo, sin saltos. Cada sección dice **el
comando**, **qué tiene que salir**, y **qué significa si sale otra cosa**.

Está escrito para alguien que llega de cero: si ya conocés el sistema y sólo
querés la secuencia, está en [el camino rápido](#el-camino-rápido).

> **El orden no es negociable en dos puntos.** Cargar el bitstream **después**
> de mapear `/dev/mem` puede dejar el puerto GP0 trabado hasta reiniciar la
> placa, y medir contra el bitstream equivocado da campañas enteras con números
> plausibles que no responden a lo que se pidió. Las dos trampas están
> explicadas donde corresponde (§2 y §4) y las dos costaron una sesión.

**Dónde estás:** [`software/README.md`](../software/README.md) es el mapa del
árbol · [`docs/API/guia_de_uso.md`](API/guia_de_uso.md) son las recetas por tema
· [`docs/APP/`](APP/) es la aplicación en detalle · esto es el **orden**.

---

## El camino rápido

Con todo ya conectado, desde la PC:

```bash
cd prj/MCA/software

make placa-estado                    # ¿responde? ¿qué PL tiene? ¿hay servidor?
make app-servidor-off-remoto         # que nadie más tenga /dev/mem
make placa-sync && make verificar-remoto
make placa-cargar-remoto             # tiene que decir PLACA LISTA
make verificar-placa-remoto          # la batería de hardware

make app                             # servidor + generador + GUI
make app-off                         # cerrar la sesión
```

Si algo de eso falla, la sección correspondiente de abajo explica por qué.

---

## 0. Lo que hace falta

### El montaje

| | |
|---|---|
| Placa | Red Pitaya STEMlab 125-14 (Zynq 7010), RP OS 2.00, kernel 5.15-xilinx |
| Bitstream | `prj/MCA/out/mca_red_pitaya.bit.bin` — ya está compilado en el repo |
| Generador | Rigol DG4162 **conectado por USB a la Red Pitaya**, no a la PC |
| Señal | CH1 del generador → **IN1** de la Pitaya, por cable coaxial |
| Red | la placa y la PC en la misma red; la PC llega por `ssh` |

> **El generador va a la placa, no a la PC.** Todos los objetivos `rigol-*`
> llevan el guard `exige-placa` porque el instrumento se maneja por USB desde la
> Pitaya (`RigolDG4162.usb()`, sin `/dev/usbtmc` — el kernel de la placa no trae
> ese módulo). Desde la PC se usan los `rigol-*-remoto`, que hacen lo mismo por
> ssh.

El generador **no es obligatorio**: sirve para tener señal conocida sin un
detector. Si tenés una fuente y un detector reales, conectalos a IN1 y salteá
todo lo que diga `rigol-`.

### En la PC

`make`, `rsync` y `ssh` — que ya están. Para la GUI hace falta además:

```bash
sudo apt install python3-pyqt5 python3-matplotlib
```

La placa **no** los necesita: allá sólo corre el servidor, que no importa ni
PyQt5 ni matplotlib. Si te faltan, `make app` te lo dice con este comando.

---

## 1. Llegar a la placa

El acceso va por un alias de ssh llamado `pitaya`, definido en
`~/.ssh/config.d/pitaya` (no en `~/.ssh/config`, que sólo tiene el `Include`):

```
Host pitaya
    HostName 10.73.28.27
    User root
    IdentityFile ~/.ssh/id_ed25519_pi
```

Probalo:

```bash
ssh pitaya hostname          # tiene que responder rp-xxxxxx sin pedir password
```

> **La IP cambia seguido** (histórico: `.28` → `.37` → `.45` → `.27`). Cuando
> cambie, se actualiza **solo** el campo `HostName`. Todo el resto del proyecto
> —Makefile, documentación, scripts— habla del alias `pitaya` y no de una IP, así
> que ese es el único lugar donde vive el número.

Con eso andando, el comando al que vas a volver todo el tiempo:

```bash
cd prj/MCA/software
make placa-estado
```

```
esta máquina  : la PC (no es la placa)
alias ssh     : pitaya -> 10.73.28.27, responde (rp-f08768)
PL            : operating · MCA1 · 8192 canales · mapa 2D sí
servidor      : no hay ninguno corriendo (make app-servidor-remoto)
generador     : Rigol Technologies DG4162
árbol remoto  : al día
```

Cada línea se degrada sola: si no hay ssh, las de abajo dicen que no se pudo
consultar en vez de fallar. **Es el primer comando a correr cuando algo no anda.**

---

## 2. Higiene: un solo proceso sobre `/dev/mem`

Esta es la regla que más cuesta cuando se ignora, así que va antes de tocar nada.

**No hay servicios que parar.** No hace falta apagar nginx, ni el servidor web
de Red Pitaya, ni el `scpi-server`. Lo que rompe es otra cosa: **dos procesos
mapeando `/dev/mem` a la vez**. Los dos culpables habituales:

- un **kernel de Jupyter** vivo que haya hecho `rp_Init()` — en un notebook
  abierto, aunque no estés corriendo celdas;
- un **`mca_server` viejo** de una sesión anterior.

El síntoma es SIGBUS: el proceso muere **sin traceback**. No hay mensaje de
error que te diga qué pasó.

```bash
make app-servidor-off-remoto      # para el servidor si quedó uno
```

`make placa-estado` te dice si hay alguien escuchando en el 1001. Para Jupyter:
cerrá el notebook o reiniciá el kernel desde la interfaz.

> **Si ya hubo un SIGBUS, reiniciá la placa.** Si el puerto GP0 llegó a abortar
> una vez queda trabado, y de ese estado **no se sale de otra forma**. Reiniciar
> y cargar el bitstream una sola vez, antes de mapear nada, es más rápido que
> pelearlo.

---

## 3. Desplegar el software

El código vive en la PC y se copia a la placa:

```bash
make placa-sync           # rsync a pitaya:/home/jupyter/RedPitaya/remote_soft/
```

Es **aditivo**: no borra nada del destino. Si querés saber qué se llevaría un
sync con `--delete`, `make placa-sync-dry` te lo lista sin tocar nada. Y **no
copia el bitstream** a propósito — recargar la PL corta el bus AXI, y eso no
debe pasar como efecto secundario de sincronizar unos `.py`.

Comprobá el deploy corriendo allá la misma suite que corre acá:

```bash
make verificar-remoto     # la suite offline, EN la Pitaya
```

Tiene que dar lo mismo en las dos máquinas. Si pasa acá y falla allá, lo que
está mal es el deploy, no el código.

---

## 4. Cargar el bitstream

```bash
make placa-cargar-remoto
```

Copia el `.bit.bin`, **verifica el md5** (un bitstream truncado programa la PL
con basura y el síntoma es un MCA que contesta cualquier cosa), sincroniza el
software, programa la PL y verifica el resultado. Tiene que terminar así:

```
PLACA LISTA. Eje de 8192 canales, bus de features presente,
8 registros nuevos verificados.
```

| Si dice… | Qué pasa |
|---|---|
| `PLACA LISTA`, **8192 canales** | todo bien, seguí |
| `PLACA LISTA` pero **16384 canales** | está cargado el bitstream **viejo**. No sigas: ver el recuadro |
| `bus de features: NO` | ídem — bitstream viejo |
| `LA PLACA NO ESTÁ LISTA` | te dice cuáles de las comprobaciones fallaron |

> ### La trampa que hace que esto importe
>
> El bitstream nuevo **conserva el magic `"MCA1"`** del anterior, y `mca_top.sv`
> **ignora en silencio las escrituras a direcciones no mapeadas**: el `default`
> del decodificador devuelve `0` y no levanta error.
>
> Consecuencia: contra el bitstream viejo, configurar los registros nuevos
> (`sel_1d`, `zoom`, el discriminador) **no falla**. Escribe al vacío, el MCA
> sigue histogrameando con lo que tenía, y la campaña sale entera con números
> plausibles que no responden a lo que pediste. **Mirando los datos después no
> hay forma de darse cuenta.** Por eso la verificación escribe y relee registro
> por registro, y por eso vale un minuto correrla.

Para preguntar sin reprogramar (por ejemplo al empezar una sesión, para ver si
hace falta):

```bash
ssh pitaya 'make -C /home/jupyter/RedPitaya/remote_soft verificar-placa-bitstream'
```

---

## 5. Comprobar que el hardware responde

Antes de medir nada, la batería completa:

```bash
make verificar-placa-remoto
```

Los sueltos, si querés ir por partes (corren **en** la placa, así que van por
ssh):

| Comando | Qué contesta |
|---|---|
| `verificar-placa-mem` | la regresión del SIGBUS al escribir `/dev/mem` |
| `verificar-placa-mca` | el bus y los registros del MCA responden |
| `verificar-placa-datapath` | el camino de datos **con señal real** del Rigol |
| `verificar-placa-e2e` | adquisición de punta a punta, deja datos |

```bash
ssh pitaya 'make -C /home/jupyter/RedPitaya/remote_soft verificar-placa-mca'
```

El que más rinde por minuto es `verificar-placa-datapath`: mete señal de verdad
y comprueba que llegue al histograma.

---

## 6. La primera medida: sólo el MCA

Encendé el generador y leé un espectro. Desde la PC:

```bash
make rigol-pulsos-remoto TASA=3000 AMP=0.6
```

Eso deja un tren de pulsos de 2 µs a 3 kHz, 0.6 Vpp con base en 0.3 V — o sea
altura de pulso 0.3 V, unas 2458 cuentas de ADC. **Queda encendido** hasta que
lo apagues con `make rigol-off-remoto`.

Y en la placa, un espectro de 10 segundos:

```python
import time
from API.mca import (mca_open, mca_configure, mca_clear, mca_start, mca_stop,
                     mca_read_histogram, mca_read_counters, mca_close)

h = mca_open()
mca_configure(h, thr=100, hyst=40, maxlen=4096, tail_dly=8,
              bl_auto=True, bl_k=12, amp_src=0, h_shift=0, dec=1)

mca_clear(h); mca_start(h); time.sleep(10.0); mca_stop(h)

hist = mca_read_histogram(h)          # ~110 ms
cnt  = mca_read_counters(h)
print(f"{cnt['total']} eventos, livetime {cnt['livetime_s']:.3f} s")
mca_close(h)
```

### Qué tiene que dar

| Comprobación | Qué esperar | Si no |
|---|---|---|
| `cnt['total']` | ≈ tasa × tiempo (30000 con lo de arriba) | ver la tabla de §11 |
| `cnt['accepted'] == cnt['total']` | sí, con un tren periódico a 3 kHz | si hay rechazos, mirá `rej_amp` y `pileup` |
| `livetime + deadtime == realtime` | exacto | si no, el reloj está mal |
| El histograma | **un** fotopico, no ruido plano | umbral mal puesto, o `bl_k` corto |

> **`bl_k` demasiado corto no da menos eventos: da CERO.** El seguidor de línea
> de base persigue el pulso y lo borra antes de que cruce el umbral. La regla es
> τ = 2^k muestras ≥ 100× la duración del pulso. Ante la duda, `bl_auto=False`.

Las recetas completas —ajustar campos sueltos, guardar y releer, el mapa 2D—
están en [`API/guia_de_uso.md`](API/guia_de_uso.md).

---

## 7. MCA + APP

Es el camino principal: un servidor en la Pitaya que expone la API por TCP, y
una aplicación PyQt5 en la PC que muestra el espectro creciendo en vivo.

```
        PC                                          Red Pitaya
┌────────────────────┐                        ┌──────────────────────┐
│  mcamon.py         │   JSON  +  binario     │  mca_server.py       │
│  PyQt5 +           │ ◄────────────────────► │  API/mca.py          │
│  matplotlib        │       TCP 1001         │  mmap /dev/mem       │
└────────────────────┘                        └──────────────────────┘
```

### Arrancarlo

Un solo comando levanta las tres cosas —servidor en la placa, estímulo en el
generador, cliente acá:

```bash
make app
```

```
  servidor   : pitaya:1001
  estímulo   : pulsos a 3000 Hz, 0.6 Vpp por CH1
  cliente    : mcamon -> 10.73.28.27:1001
```

Variantes:

```bash
make app ESTIMULO=psd TASA=30000       # dos poblaciones: llena el mapa 2D
make app ESTIMULO=poisson TASA=30000   # arribos exponenciales, apilamiento realista
make app ESTIMULO=ninguno              # no toca el generador (fuente real, detector)
make app TASA=10000 AMP=0.4            # otra tasa y amplitud
```

**Antes de tener la placa delante**, para conocer la interfaz sin arriesgar nada:

```bash
make app-demo      # servidor con un MCA simulado + GUI, todo en la PC
```

### Qué hay en la ventana

| Pestaña | Contenido |
|---|---|
| **Mensajes** | cada operación y cada error, con hora. Es lo que te deja reconstruir qué pasó cuando el síntoma llega tarde |
| **Espectro** | el histograma 1D, umbrales, exposición, contadores, ROI con ajuste gaussiano, y guardado |
| **Mapa 2D (PSD)** | amplitud × factor de forma, y la FOM |

En la barra de arriba van la IP, el puerto, el canal (IN1/IN2), el estimador
(pico o integral de carga), la decimación y el período de refresco.
`Placa → Cargar bitstream del MCA…` reprograma la PL sin salir.

> **La pestaña del mapa 2D aparece sólo si el bitstream la trae.** El cliente
> lee las capacidades del hardware al conectarse (bit `CAP_HIST_H_PSD`) y arma
> la interfaz con lo que hay. Si no aparece, no es un bug de la app.

Lo mismo pasa con el eje: el cliente **no hardcodea** la cantidad de canales, la
lee del registro `WIDTHS`. Por eso el mismo binario sirve para el bitstream de
8192 y el de 16384.

### Cerrar

Al cerrar la ventana, **el servidor y el generador quedan andando**. Es a
propósito: una medida larga tiene que sobrevivir a que cierres la GUI, y al
reconectar el servidor te informa que la adquisición sigue corriendo.

```bash
make app-off       # apaga el generador y para el servidor
```

### Dos cosas que vas a encontrar

**`PermissionError` al levantar el servidor en la PC.** El puerto 1001 por
defecto es el de `mcpha`; en la Pitaya anda porque ahí se corre como root, pero
en una sesión de usuario Linux reserva todo lo que está por debajo de 1024. Los
objetivos del Makefile ya usan 5001 en la PC.

**`Ocupado: ya hay un cliente`.** El servidor acepta **uno solo**, por la regla
de §2. Si es una GUI tuya de antes, cerrala; si es un proceso colgado,
`make app-servidor-off-remoto` y volvé a levantarlo.

El detalle completo —las 15 operaciones del protocolo, el flujo de datos hilo
por hilo, y qué prueba cada test— está en [`docs/APP/`](APP/).

---

## 8. OSC: adquisición de formas de onda a disco

El otro camino de datos. En vez de histogramear en la FPGA, guarda **las formas
de onda completas** de cada evento, en chunks `.npz`.

```bash
make campana-adquirir-remoto DURACION=60 THR=0.2 OUT=datos/adq_prueba
```

Corre en la placa y **trae los datos a la PC** al terminar. Mientras corre
imprime una tabla que se actualiza cada medio segundo:

```
Evento | Tasa (ev/s) | Descartes | Chunks | Cola libre
```

| Columna | Qué mirar |
|---|---|
| Tasa | tiene que seguir al generador |
| Descartes | si sube, el lector no da abasto (backpressure) |
| Cola libre | si llega a cero, el escritor a disco es el cuello de botella |

**Ctrl-C corta limpio**: cierra el chunk en curso y escribe el resumen. No
pierde más que lo que estaba en vuelo. También corta sola si el disco baja de
200 MB libres, y te lo dice.

### Qué queda escrito

Un directorio `Data_<fecha>_TCH1_TL<umbral>/` con:

- `chunk_000000.npz`, `chunk_000001.npz`, … — escritos de forma atómica
  (`.tmp` + `rename`), así que **nunca hay un `.npz` a medias** aunque se corte
  la luz;
- `run_summary.json` — el resumen de la corrida.

Cada chunk lleva `wave` (`int16`, forma `(eventos, canal, muestra)`, escala 8192
cuentas/V), y por evento `t_ns` (marca de tiempo), `snap` (qué fuentes
dispararon) y `gap` (descartes antes de ese evento).

### Releerlos

En la PC, sin placa:

```python
from API.osciloscope_store import load_chunk
arrays, meta = load_chunk('datos/adq_prueba/Data_.../chunk_000000.npz')
print(arrays['wave_V'].shape)      # ya convertido a volts
```

Y el análisis que ya existe sobre esas trazas:

```bash
make analizar-estimadores          # compara los estimadores sobre pulsos reales
make graficar-formas               # catálogo de formas en volts vs microsegundos
```

---

## 9. OSC + MCA a la vez

Los dos caminos sobre el **mismo estímulo y al mismo tiempo**:

```bash
ssh pitaya 'make -C /home/jupyter/RedPitaya/remote_soft campana-e2e'
```

El pipeline de adquisición (slot 1) guarda las formas de onda y de ahí sale un
histograma **calculado por software**; el MCA (slot 7) histogramea **en la
FPGA**. Los dos miran la misma entrada del ADC.

Es la validación cruzada que cierra el círculo: si el histograma del hardware
coincide con el que sale de analizar las formas crudas, el camino de datos del
MCA está bien de punta a punta.

> **Comparar centroide y ancho, NO áreas.** El pipeline de software arrastra
> ~683 µs de tiempo muerto por evento (leer 1024 muestras por el bus) mientras
> que el MCA vive en los microsegundos, así que ve muchísimos más eventos. Las
> **cuentas** de los dos no tienen por qué parecerse; la **forma** sí.

---

## 10. Apéndice: el event_ring

Opcional, y **necesita otro bitstream**. El build del MCA deja el slot 2 vacío,
así que contra `mca_red_pitaya.bit.bin` esto no puede funcionar y el error
("`el bitstream cargado no tiene el event_ring en el slot 2`") no es un
problema tuyo.

```bash
make placa-cargar-remoto BIT_LOCAL=../out/v3_event_ring/v3_event_ring.bit.bin
ssh pitaya 'make -C /home/jupyter/RedPitaya/remote_soft verificar-placa-ring'
```

Ese top **también trae el MCA** en el slot 7, así que no es uno o el otro.

Dos cosas que conviene saber antes de empezar:

- **No hay que tocar el device tree ni el arranque del kernel.** El RP OS ya
  trae regiones de DDR reservadas y el código elige una sola
  (`labuf@a000000`, 32 MB). Es **prestada al analizador lógico**: si esa app de
  Red Pitaya corre a la vez, se pisan.
- **`run_acquire.py` todavía no sabe usar el ring.** El camino de §8 va por
  BRAM. El ring está validado a nivel de plumbing pero no conectado a la
  adquisición a disco.

El diseño está en [`docs/event_ring/`](event_ring/).

---

## 11. Cuando algo no anda

Primero, siempre:

```bash
make placa-estado
```

### A nivel de sistema

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `esto necesita la Red Pitaya` | pediste un objetivo `(P)` desde la PC | usá el `-remoto`; el mensaje te dice cuál |
| `es la GUI, y necesita PyQt5` | falta el paquete en la PC | `sudo apt install python3-pyqt5 python3-matplotlib` |
| `ssh pitaya` no responde | la IP cambió | actualizá `HostName` en `~/.ssh/config.d/pitaya` |
| `Ocupado: ya hay un cliente` | otra GUI o un proceso colgado | `make app-servidor-off-remoto` |
| `PermissionError` en el bind | puerto < 1024 sin root | usá `PUERTO=5001` (ya es el default en la PC) |
| El ssh no vuelve nunca | el proceso remoto retiene las tuberías | ya está resuelto con `ssh -f` en los objetivos |
| La tasa medida es la de la corrida **anterior** | el generador todavía no aplicó la forma nueva | rehacé el `rigol-*`; hay un handshake que debería evitarlo |

### A nivel de hardware

| Síntoma | Causa |
|---|---|
| El proceso muere **sin traceback** | SIGBUS: la PL no está programada, o hay otro proceso en `/dev/mem` |
| **La placa se reinicia** al leer | alguien cambió la lectura palabra a palabra por un slice o un `np.frombuffer` |
| `MCANotPresent` al abrir | está cargado el bitstream del scope, donde el slot 7 es un stub |
| 0 eventos con señal buena | `bl_k` demasiado corto: el seguidor de base se come el pulso |
| Números plausibles pero sin relación con lo pedido | bitstream viejo: §4 |

La tabla completa de errores de la API está en
[`guia_de_uso.md`](API/guia_de_uso.md#errores-frecuentes).

---

## Ver también

[`docs/APP/`](APP/), la aplicación en detalle (protocolo, flujo de datos,
pruebas) · [`docs/API/guia_de_uso.md`](API/guia_de_uso.md), las recetas por tema
· [`docs/mca/sesion_placa_deriva.md`](mca/sesion_placa_deriva.md), un runbook de
campaña real · [`docs/resultados_validacion_hw.md`](resultados_validacion_hw.md),
qué se midió y cuánto dio
