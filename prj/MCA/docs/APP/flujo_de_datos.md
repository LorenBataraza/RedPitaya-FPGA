# Flujo de datos de la aplicación

**Código:** [`software/app/`](../../software/app/) · [`API/mca_net.py`](../../software/API/mca_net.py) · [`API/mca_remote.py`](../../software/API/mca_remote.py)
**Protocolo:** la referencia operación por operación está en [`protocolo.md`](protocolo.md)
**Pruebas:** [`pruebas.md`](pruebas.md)

Este documento cuenta **cómo viaja un dato** entre el histograma que la PL
acumula en su BRAM y el píxel que se dibuja en la PC, y cómo viaja un comando en
la dirección contraria. Es lo que hace falta para tocar el código sin romperlo.

Lo que **no** cubre: el presupuesto de rendimiento del lector de formas de onda
del osciloscopio, que está medido y cerrado en
[`arquitectura_adquisicion_software.md`](../multitrigger/arquitectura_adquisicion_software.md)
(Parte 3); y el volcado masivo de ficheros por NFS, que es otro problema con
otras respuestas y vive en
[`salida_por_red.md`](../event_ring/salida_por_red.md). Acá hay un solo socket
TCP, y lo que pasa por él son comandos y espectros.

---

## Por qué hay dos caminos y no uno

Los dos tipos de tráfico que cruzan el socket no se parecen en nada:

| | camino de control | camino de datos |
|---|---|---|
| tamaño | decenas de bytes | 64 KB por espectro |
| frecuencia | cuando alguien toca algo | 1 por segundo, configurable |
| coste de producirlo | ~2 µs de bus | **~110 ms** de lectura palabra a palabra |
| qué lo hace bueno | que se pueda leer y extender | que no se pague por transportarlo |

Un formato único obliga a elegir cuál de los dos se sacrifica. Todo JSON infla
el espectro alrededor de diez veces y obliga a parsear 16384 enteros del otro
lado; todo binario convierte cada comando en una constante mágica que hay que ir
a buscar al código fuente. La aplicación no elige: **cada mensaje es una línea
JSON de control, seguida opcionalmente de un bloque binario**. Los comandos se
leen con `nc` y el espectro llega como bytes crudos que `np.frombuffer` adopta
sin copiar.

```
        PC                                          Red Pitaya
┌────────────────────┐                        ┌──────────────────────┐
│  mcamon.py         │   {"op": "...", ...}   │  mca_server.py       │
│  PyQt5 +           │ ─────────────────────► │  API/mca.py          │
│  matplotlib        │                        │  mmap /dev/mem       │
│                    │ ◄───────────────────── │        │             │
│  MCARemote         │   {"ok": true, ...}    │        ▼             │
│  (es un `MCA`)     │   + 64 KB de uint32    │  0x4070_0000 (slot 7)│
└────────────────────┘        TCP 1001        └──────────────────────┘
```

---

## Camino de control

### Un comando de punta a punta

El caso completo, con el umbral de disparo, que toca todas las capas:

```
   hilo GUI                         hilo del socket           hilo mca-cliente
      │                                    │                    (en la placa)
 spinbox thr                               │                          │
      │ valueChanged                       │                          │
      ├──► QTimer 250 ms ──► pedir_campo   │                          │
      │                          │         │                          │
      │                    sig_campo ══════╪═► escribir_campo         │
      │                     (encolada)     │        │                 │
      │                                    │  mca_set_thr(h, 317)     │
      │                                    │        │                 │
      │                                    │  _escribir_campo: RMW    │
      │                                    │    r32(0x014) ───────────┼─► trama 1
      │                                    │    w32(0x014) ───────────┼─► trama 2
      │                                    │                          │
      │                                    │  ◄── config.get ─────────┤
      │ ◄══ config (encolada) ═════════════┤                          │
 actualizar_config                         │                          ▼
 (repinta con _cargando)                                    _mmap[0x14:0x18]
```

Los saltos, con su fichero:

1. **`PanelEspectro._spin`** ([`panel_espectro.py:268`](../../software/app/panel_espectro.py#L268))
   fabrica el spinbox y le cuelga el antirrebote. Al expirar emite
   `pedir_campo(campo, valor)`.
2. **La ventana reenvía señal a señal**, sin slot intermedio:
   `self.panel_espectro.pedir_campo.connect(self.sig_campo)`.
3. **`sig_campo` está conectada a un slot del trabajador**, que vive en otro
   `QThread`. Qt detecta el cruce y usa una **conexión encolada**: el slot se
   ejecuta en el hilo del socket, no en el de la GUI.
4. **`Trabajador.escribir_campo`** ([`mcamon.py:195`](../../software/app/mcamon.py#L195))
   resuelve el setter por nombre: `getattr(A, f'mca_set_{campo}')(self.h, valor)`.
5. **`mca_set_thr`** hace read-modify-write en
   [`API/mca.py:676`](../../software/API/mca.py#L676), porque `R_THR` comparte
   palabra con otros campos en varios registros del mapa.
6. **`h` es un `MCARemote`**, así que `r32`/`w32` son idas y vueltas por el
   socket en vez de accesos a `mmap`.
7. **El servidor** valida el nombre de la operación y sus argumentos, toma el
   lock del handle y escribe en `/dev/mem`.

> **La GUI escribe campo por campo, nunca con `mca_configure`.** El bloque
> entero de configuración escribe `R_CTRL` con `run=0`, así que tocar un umbral
> **pararía la medición en curso**. Es la razón por la que
> `Trabajador.escribir_campo` resuelve un `mca_set_<campo>` en vez de armar un
> dict y mandarlo de una. Además, tres de esos setters validan (`bl_k`,
> `tail_dly`, `dec`) y pasar por ellos es lo que mantiene esa validación viva.

### El antirrebote, y por qué son tres mecanismos

En [`panel_espectro.py:268-283`](../../software/app/panel_espectro.py#L268-L283)
hay tres cosas superpuestas, y cada una tapa un agujero distinto:

| mecanismo | qué evita |
|---|---|
| `setKeyboardTracking(False)` | que tipear "317" mande tres escrituras: 3, 31, 317 |
| `QTimer` singleShot de 250 ms, reiniciado en cada cambio | que arrastrar la flecha del spinbox mande una escritura por paso — cada una son dos idas y vueltas de red más un RMW sobre `/dev/mem` |
| el flag `_cargando` | **el eco**: cuando llega la config releída y la GUI repinta los spinbox, `setValue` dispararía `valueChanged` y reescribiría el mismo valor, para siempre |

El temporizador es hijo del spinbox, así que vive en el hilo de la GUI y no
toca la red: lo único que hace al expirar es emitir la señal.

### El lazo se cierra en el hardware

Después de escribir, el trabajador **relee** la configuración completa
(`config.get`) y la emite; el panel repinta los controles con el valor que
devolvió la placa, no con el que el usuario tipeó. La consecuencia es que el
cliente **no tiene estado de configuración propio**: si el hardware satura un
campo a su máscara, lo que se ve en pantalla es el valor saturado.

> **Un `mca_set_*` por red NO es atómico.** Son dos operaciones separadas
> (`r32` y `w32`), cada una con su propia toma del lock del servidor: entre
> ambas puede colarse otra cosa. Es aceptable porque nadie más escribe esos
> registros, pero es la razón por la que `MCARemote` **sí** redefine
> `start`/`stop`/`clear`/`configure` como operaciones únicas del servidor
> ([`mca_remote.py:52-59`](../../software/API/mca_remote.py#L52-L59)): ésas
> pueden cruzarse con el hilo de exposición, que también escribe `R_CTRL`.

---

## Camino de datos

Tres saltos, cada uno con una restricción que no es negociable.

### 1. BRAM → servidor: palabra a palabra

`MCA.spectrum()` ([`API/mca.py:529`](../../software/API/mca.py#L529)) lee
`2^h_aw` palabras de 32 bits desde la apertura `0x10000`, con una comprensión de
lista y `struct.unpack_from` sacado fuera del lazo
([`API/mca.py:247`](../../software/API/mca.py#L247)).

> **Esto no se puede optimizar, y el intento reinicia la placa.** Un
> `np.frombuffer(...).copy()`, un slice grande del mmap o un `unpack_from` con
> formato largo terminan todos en un memcpy, que sobre memoria de dispositivo
> emite accesos anchos o en ráfaga. El esclavo AXI los rechaza, el error se
> propaga como *external abort*, y en esta placa eso **no da SIGBUS: reinicia el
> sistema**. Verificado: el paso `bulk` de `diag_mca_hw.py` reinicia la Pitaya y
> el paso `word` lee el mismo rango de a una palabra sin problema. Detalle en
> [`patrones_memoria_hw.md`](../patrones_memoria_hw.md).

Son ~6.7 µs por palabra, o sea del orden de **110 ms** para 16384 canales. Ese
número es el que gobierna todo el diseño del cliente.

> **Refrescar en vivo cuesta, pero poco, y se puede verificar.** La lectura del
> bus tiene prioridad sobre el pipeline del histograma y el evento que colisiona
> se descarta, pero ocupa el puerto sólo un par de ciclos cada 6.7 µs. Con un
> refresco por segundo la pérdida queda en el orden del 0.01 % de los eventos —
> y no hay que creerlo: cada uno de esos eventos se cuenta en `dropped`, que
> está en pantalla.

### 2. Servidor → cliente: la cabecera describe el bloque

`Channel.send_result` ([`mca_net.py:130`](../../software/API/mca_net.py#L130))
fuerza el array a contiguo, anota `dtype` y `shape` en la cabecera JSON y manda
`tobytes()` detrás; `Channel.send` añade `nbytes`. La cabecera de un espectro
de 16384 canales queda así:

```json
{"ok": true, "result": {}, "dtype": "uint32", "shape": [16384], "nbytes": 65536}
```

Del otro lado, `array_desde`
([`mca_net.py:185`](../../software/API/mca_net.py#L185)) reconstruye con
`np.frombuffer(...).reshape(shape).copy()`.

> **El `.copy()` no es paranoia.** `np.frombuffer` sobre un `bytes` devuelve un
> array de **sólo lectura**, y del otro lado hay una GUI que rebinea, recorta y
> pone a cero. Sin la copia, la primera escritura in-place falla en un sitio muy
> lejano a la causa. Lo fija un test dedicado, `test_array_es_escribible`.

El orden de bytes es el nativo del emisor. Los dos extremos son little-endian
(armv7l y x86-64), así que la cuestión no se plantea; si algún día se plantea,
éste es el punto donde hay que mirar.

### 3. Cliente → pantalla

El array llega al hilo de la GUI por una señal `pyqtSignal(object, dict)`
conectada **directamente** del trabajador al panel, sin pasar por la ventana.
Como los dos objetos viven en hilos distintos, Qt la entrega encolada.

`PanelEspectro._redibujar`
([`panel_espectro.py:372`](../../software/app/panel_espectro.py#L372)) hace, en
orden:

- **Rebin** por `reshape(-1, r).sum(axis=1)`. El eje x se mantiene **en canales
  originales** (`arange(0, n, r)`), no en índices del bin agrupado: así el
  número que se lee bajo el cursor sigue siendo un canal del hardware,
  cualquiera sea el agrupamiento.
- **Escala log con suelo en 0.5** en vez de 1: deja visibles los bins de una
  sola cuenta, que en un espectro son justamente los que interesan, sin que los
  bins vacíos manden el eje a `-inf`.
- **El eje Y se reescala en cada refresco; el X no.** El X se fija una vez al
  conocer la geometría, y a partir de ahí manda el usuario con el zoom de la
  barra de matplotlib. Un espectro que crece no debe moverle la vista a quien
  está mirando un pico.
- **La sombra de la ROI y las líneas de la ventana de amplitud**, borrando
  explícitamente las anteriores — si no, se acumula un artista por refresco.
- **`draw_idle()`**, que encola el repintado en el lazo de eventos en vez de
  bloquear.

> **Los límites de amplitud viven en cuentas y el eje está en canales.** Por eso
> las dos líneas rojas punteadas se dibujan en `valor >> h_shift` y no en
> `valor`. Si algún día `h_shift` deja de ser un desplazamiento puro, éste es
> uno de los lugares que hay que revisar.

### Los temporizadores

| temporizador | hilo | período | qué pide |
|---|---|---|---|
| `_t_estado` | trabajador | 200 ms | `status`: contadores, tasas, exposición |
| `_t_espectro` | trabajador | 1 s, ajustable 0.2–60 s | `read.spectrum` + `read.metadata` (+ `read.map2d` si toca) |
| antirrebote de cada spinbox | GUI | 250 ms, singleShot | nada de red |
| `_vigilante` | servidor, hilo propio | 100 ms | `livetime_s`, y `mca_stop` al llegar |

> **Los dos temporizadores del trabajador se crean en el slot `arrancar`
> ([`mcamon.py:69`](../../software/app/mcamon.py#L69)), no en `__init__`.** Un
> `QTimer` pertenece al hilo donde se construye, y `Trabajador` se construye en
> el hilo de la GUI antes del `moveToThread`. Creados en `__init__`, dispararían
> en el hilo de la interfaz y tocarían el socket desde ahí — que es exactamente
> lo que toda esta arquitectura existe para evitar.

Al conectar se hace un tic manual de cada uno antes de arrancarlos, para que la
pantalla no espere un segundo entero a tener algo que mostrar.

---

## Concurrencia

### En el servidor

Tres hilos: el principal, que sólo hace `accept`; **`mca-exposicion`**, que es
el vigilante; y un `mca-cliente` por conexión — en la práctica como mucho uno,
porque sólo se acepta un cliente.

**El vigilante existe porque el tiempo de exposición no existe en hardware.** El
MCA es free-running: no tiene registro de "medir N segundos". El hilo poléa
`livetime_s` cada 100 ms y para el MCA al llegar al objetivo. Se mide contra el
tiempo **vivo** y no contra el de pared, que es lo que hace comparables dos
medidas tomadas a tasas distintas. El objetivo se guarda como livetime absoluto
acumulado, no como delta, para que una segunda exposición sin borrar continúe
donde iba.

`self._lock` ([`mca_server.py:58`](../../software/app/mca_server.py#L58))
protege todo acceso al handle, y se toma **alrededor de la operación entera**,
no de cada registro: así un `config.set` de 19 escrituras no puede entrelazarse
con el `mca_stop` del vigilante.

### En el cliente

Un solo hilo además del de la GUI, y una regla que se enuncia en las dos
direcciones:

- **El trabajador no toca widgets.** Todo lo que sabe sale por señales; no hay
  una sola referencia a un widget dentro de la clase.
- **La GUI no toca el socket ni el handle.** Todo lo que pide sale por señales
  conectadas a slots del trabajador.

La razón está en el número de arriba: un espectro completo son ~110 ms de
lectura en la placa. Hacerlo en el hilo de la interfaz la congelaría en cada
refresco.

> **La única excepción es deliberada y está en `closeEvent`**
> ([`mcamon.py:494`](../../software/app/mcamon.py#L494)): una
> `BlockingQueuedConnection` para desconectar. Sigue ejecutando el slot en el
> hilo correcto; lo único que cambia es que el hilo de la GUI espera a que
> termine antes de cerrar el `QThread`. Hay que parar los temporizadores y
> cerrar el socket **dentro** del hilo del trabajador, porque Qt no deja parar
> un `QTimer` desde otro hilo.

### Un cliente a la vez

Es una regla de hardware antes que de software: **un solo proceso puede tener
`/dev/mem` abierto**. Si un kernel de Jupyter está vivo y hace `rp_Init()`, los
dos pelean y sale SIGBUS.

El servidor hace un test-and-set bajo su propio lock
([`mca_server.py:340`](../../software/app/mca_server.py#L340)) y al segundo
cliente le contesta un error `Ocupado` y le cierra el socket. El rechazo llega
**antes de que el cliente pida nada**: como `MCARemote.connect` manda `identify`
y espera, lo que recibe es directamente el error.

> **El testigo.** Cada conexión se registra como `(ip, object())` y al terminar
> sólo se borra a sí misma, comparando el testigo **por identidad**. Sin eso, el
> `finally` de un cliente que se va justo cuando entra otro borraría al recién
> llegado y dejaría entrar a un tercero.

### Quién guarda qué

| | estado |
|---|---|
| **la PL** | el estado real: registros y las dos BRAM |
| **el servidor** | el handle, el objetivo de exposición, y la muestra anterior de `(livetime, accepted)` para calcular la tasa instantánea |
| **el cliente** | una copia del último espectro y su metadata, y **estado de presentación**: rebin, escala log, ROI, período de refresco |

El cliente **no guarda configuración**: la reelee del hardware después de cada
escritura. Es lo que permite que dos sesiones distintas de la GUI vean lo mismo,
y que reconectarse a una medición en curso funcione sin más.

---

## Casos especiales

### El mapa 2D se lee sólo si se está mirando

Tres condiciones, todas necesarias
([`mcamon.py:141`](../../software/app/mcamon.py#L141)):

1. **El bitstream lo trae** — bit `CAP_HIST_H_PSD` del registro `CAPS`, que
   publica el propio `mca_top`. Si falta, `MCA.map2d()` levanta `RuntimeError`.
2. **La pestaña existe** — se crea o se destruye según lo que diga `CAPS` al
   conectar, así que recargar un bitstream sin PSD la hace desaparecer sola.
3. **La pestaña está activa** — leer el mapa cuesta del orden de 55 ms más por
   refresco, y no tiene sentido pagarlos para dibujar algo que nadie ve.

### La carga de bitstream, paso a paso

Es la operación más delicada del sistema: **reprogramar la PL con mapeos
abiertos** deja el puerto GP0 trabado hasta reiniciar la placa. La secuencia
([`mca_server.py:241`](../../software/app/mca_server.py#L241)) es:

```
rechaza si hay adquisición corriendo
        │
   mca_close(h)          ◄── el mmap se cierra ANTES de tocar la PL
        │
   bajar puentes AXI ─► fpgautil -b ─► subir puentes  (en un finally)
        │
   fpga_state() == 'operating'    ◄── necesario pero NO suficiente
        │
   pl_bus_ready()  ◄── sondea desde un PROCESO HIJO, hasta 8 s
        │
   mca_open() + validar el magic "MCA1" + releer la geometría
```

> **El sondeo va en un proceso hijo a propósito.** Si la PL todavía no contesta,
> el que muere con SIGBUS es el hijo y el servidor se entera por el código de
> retorno, en vez de morirse él sin traceback.

La conexión TCP no se corta en ningún momento: lo que se rehace es el mapeo del
lado del servidor. El cliente recibe el `identify` nuevo y reconstruye la
geometría del panel y la pestaña 2D con lo que publique el bitstream recién
cargado.

Y si el servidor arranca **sin** MCA (bitstream equivocado), arranca igual y
sirve: todas las operaciones que necesitan handle contestan `MCANotPresent`, y
el cliente puede pedir `fpga.load_bitstream` para arreglarlo desde la GUI. Es un
camino de recuperación, no un error fatal.

### `FakeMCA` sustituye cinco métodos y nada más

`FakeMCA` hereda de `MCA` y redefine `w32`, `r32`, `spectrum`, `map2d` y
`close`. Todo lo demás —`identify`, `configure`, `clear`, `start`, `stop`,
`counters`, `acquire`, los autoscale— se hereda intacto.

**El servidor es idéntico línea a línea en modo real y en modo `--fake`**: la
única diferencia es qué objeto es `self.h`. Ni el protocolo, ni `MCARemote`, ni
el trabajador, ni un solo widget saben que existe. `mcamon` sólo ve
`info['fake']` y lo usa para escribir "simulado" en la etiqueta de estado.

El simulador reproduce el **mapa de registros**, no una API paralela: los
read-modify-write de `_CAMPOS`, la geometría publicada en `WIDTHS`, el barrido
de `clear` autolimpiante y el registro sombra de los relojes de 64 bits. Es una
decisión deliberada — si algo anda contra `FakeMCA` y no contra la placa, la
diferencia está en el hardware y no en el simulador.

### Todo el guardado ocurre en el cliente

El servidor no escribe **un solo fichero de datos**; su única salida a disco es
el log por stdout. Guardar el espectro (csv / npz / json), releerlo, guardar las
imágenes y el log, y también el análisis (`gauss_fit_peak` de la ROI, `fom` del
mapa 2D) pasan todos en la PC, en el hilo de la GUI, sobre las copias locales.

La consecuencia buena es que **un fichero escrito desde la GUI es
indistinguible de uno escrito en la placa**: se usan las mismas funciones de
`API/mca.py`, y `mca_load_file` los relee igual.

> **La metadata guardada tiene hasta un período de refresco de antigüedad.**
> `self.meta` es la última respuesta de `read.metadata`, que llega junto con el
> espectro. Con refresco de 1 s, pulsar Guardar escribe la configuración y los
> contadores de hasta un segundo antes. Para un espectro detenido da igual;
> para uno corriendo, el `livetime_s` del fichero no es el del instante de
> guardar.

---

## Estado y deuda conocida

- [x] Camino de control y de datos, con un cliente y el MCA.
- [x] Exposición por tiempo vivo, implementada en el servidor.
- [x] Recuperación desde un bitstream equivocado sin reiniciar nada.
- [ ] Un solo bloque: OSC, multitrigger y event_ring no están expuestos.
- [ ] Descubrimiento de slots: las bases están fijas en el código en vez de
      leerse del registro `SLOTS` de `integration_cfg`, como ya se hace con
      `WIDTHS` para la geometría del histograma.

Cinco cosas que conviene tener presentes al tocar esto:

1. **La tupla `OPS` de [`mca_net.py:51`](../../software/API/mca_net.py#L51) es
   documentación, no código vivo**: no se importa en ningún sitio. El despacho
   real es el dict `_OPS` de
   [`mca_server.py:277`](../../software/app/mca_server.py#L277), que además
   valida los nombres de los argumentos. Si las dos divergen, nada lo detecta —
   es candidato natural a un test que las compare.
2. **`mca_set_*` por red no es atómico** (dos operaciones separadas). Los que sí
   lo son, y por qué, están más arriba.
3. **La metadata guardada puede tener un refresco de antigüedad.**
4. **`mcamon.py:141` lee `self.h._has_2d`**, un atributo privado de `MCA`,
   habiendo alternativa pública (`info['has_2d']`).
5. **El timeout de la conexión queda aplicado al socket para todas las
   operaciones posteriores**, incluida `fpga.load_bitstream`, que puede tardar
   más de 8 s sólo en esperar a que el bus conteste. El margen actual es
   ajustado.

---

## Ver también

[`protocolo.md`](protocolo.md), la referencia de las operaciones ·
[`pruebas.md`](pruebas.md), qué demuestra cada test ·
[`referencia_api.md`](../API/referencia_api.md), la API que el servidor expone ·
[`register_map_mca.md`](../mca/register_map_mca.md), los registros del otro lado
