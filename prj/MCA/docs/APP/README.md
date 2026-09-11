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
| [`protocolo.md`](protocolo.md) | las 23 operaciones, el formato de trama, los errores, y una sesión con `nc` |
| [`pruebas.md`](pruebas.md) | qué demuestra cada test — y, sobre todo, **qué no cubre ninguno** |
| [`../puesta_en_marcha.md`](../puesta_en_marcha.md) | el paso a paso de todo el sistema, si venís de cero y la placa todavía no está lista |
| [`../publicar_release.md`](../publicar_release.md) | armar el paquete instalable y publicarlo en GitHub — para quien sólo quiere **usar** el sistema |

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
| **Espectro** | el histograma 1D, umbrales, exposición, contadores, **la lista de picos detectados con su FWHM**, y guardado |
| **MCA** | los 24 parámetros del slot 7, agrupados, con **cuándo se puede tocar cada uno** |
| **Mapa 2D (PSD)** | amplitud × factor de forma y la FOM. **Aparece sólo si el bitstream lo trae** (bit `CAP_HIST_H_PSD` de `CAPS`) |
| **Integración** | ruteo del datapath y control global del slot 6. **Aparece sólo si el bitstream trae `integration_cfg`** |
| **OSC** | **las últimas formas capturadas** y, con el mismo eje de tiempo, **la tasa instantánea** de ese momento. Más los registros del osciloscopio |
| **Multitrigger** | máscaras OR con los bits nombrados, `trigger_shield`, y qué fuente disparó |

En la barra superior van la IP, el puerto, el canal (IN1/IN2), el estimador
(pico o integral de carga), la decimación y el período de refresco.
`Placa → Cargar bitstream del MCA…` reprograma la PL.

### Cuándo se puede tocar cada parámetro

La pestaña del MCA marca cada control, porque no todos cuestan lo mismo. El
criterio es **avisar, no prohibir**: parar la adquisición un instante no es
problema, y esconder un control lo es más.

| Marca | Qué significa | Ejemplos |
|---|---|---|
| *(sin marca)* | se puede cambiar con la medición corriendo | `thr`, `hyst`, ventana de amplitud, discriminador |
| **·** | reinicia la cuenta en curso | `dec`, `channel`, `maxlen`, `tail_dly`, compuertas |
| **··** | cambia el significado del eje: lo ya acumulado se mezcla con lo nuevo | `sel_1d`, zoom, `amp_src`, `q_shift` |
| **⚠** | mal puesto deja el sistema **sin eventos** | `bl_k`, `bl_auto` |

Los `··` llevan un botón de borrar al pie de la pestaña: mezclar dos ejes en el
mismo histograma no tiene sentido físico y conviene resolverlo en el momento.

---

## Diferencias con `mcpha`, y por qué

Casi todas las impone el hardware, que no es el mismo:

| `mcpha` | Acá |
|---|---|
| dos MCA independientes, dos pestañas de espectro | **uno solo** con mux de canal (`0x00C[8]`): una pestaña y un selector IN1/IN2 |
| 4096 canales | `2^h_aw`, leído del registro `WIDTHS` — el cliente **no hardcodea** la geometría (ver el recuadro de abajo) |
| temporizador de exposición en hardware | no existe: lo implementa un hilo del servidor contra `livetime_s` |
| `negator` por canal | no hay negador en el RTL; en su lugar está el selector `amp_src` (pico o integral de carga) |
| — | contadores propios: `rej_amp`, `rej_psd`, `pileup`, `dropped`, y real/vivo/muerto |
| — | mapa 2D de forma de pulso y figura de mérito |

---

## La lista de picos

La pestaña del espectro **no** pide una región y ajusta una gaussiana ahí:
lista los picos que hay, con su ancho. El cambio no es de presentación. Para
ajustar una región había que saber **dónde** estaba el pico, y en un espectro
desconocido eso es justamente lo que no se sabe; la lista contesta *qué hay*.

Cada fila trae canal, **FWHM**, resolución (FWHM/canal, en %), cuentas en la
cima y área neta. Elegir una fila **centra el eje en ese pico**, que es cómo se
va de la lista al espectro sin buscar el canal a mano con el zoom. En el gráfico
cada pico lleva un marcador en la cima y **una barra horizontal a media altura
que es el FWHM dibujado** — de un vistazo se ve si el ancho de la tabla
corresponde al pico que uno está mirando.

Cómo se mide, que es lo que hay que saber para creerle
([`API/analisis.py`](../../software/API/analisis.py), `buscar_picos`):

- los máximos se buscan sobre el espectro **suavizado**, porque en un histograma
  de Poisson casi cualquier canal es máximo local de sus vecinos;
- se filtran por **prominencia y no por altura**: un hombro sobre un fondo alto
  es un pico y un rizo sobre el fotopico no lo es, y la altura sola no los
  distingue;
- el **FWHM se cuenta desde la base local** —el valle más alto de los dos— y no
  desde cero: sobre un continuo, medir desde cero ensancha el pico
  sistemáticamente;
- el **centroide** se recalcula como centro de masa de las cuentas **crudas**
  dentro del FWHM: el máximo del suavizado sirve para encontrar el pico, no para
  ubicarlo con precisión de subcanal.

> **El umbral de ruido está calibrado, no elegido.** Se exige que la prominencia
> supere 9.5 veces la fluctuación de conteo del fondo, y ese número sale de
> medir: sobre fondo plano, la prominencia del ruido da mediana 0.8 σ, percentil
> 99 unos 5 σ y **máximo entre 6 y 8.5 σ**, porque el criterio no se aplica a una
> medición sino al mayor de ~2000 máximos locales. Con 3 σ —que es lo que uno
> escribiría— un espectro de puro ruido devolvía una docena de picos, todos
> falsos. Lo que cuesta subir hasta 9.5 es poco: un pico de amplitud 80 sobre un
> fondo de 500 se sigue detectando 10 veces de 10.

Dos resultados que la lista da y conviene saber leer:

- **`FWHM` en `—`** significa que el pico no baja a media altura antes de que se
  acabe el eje. Es lo que pasa con medio pico contra el canal 0 y con el escalón
  de apilamiento contra el tope de escala. El ancho no está definido ahí, y
  decirlo es más útil que inventar un número.
- **Un doblete sin resolver aparece como un pico solo**, con el ancho de la
  mezcla. Es lo honesto: el suavizado y el ruido borran un valle poco profundo,
  y devolver dos filas inventaría una resolución que la medida no tiene. Un FWHM
  mucho mayor que el de los picos vecinos es la señal.

`gauss_fit_peak(spec, lo, hi)` **sigue existiendo** en la API y lo usan diez
ficheros —campañas, Monte-Carlo, el baseline de compatibilidad—: lo que se quitó
es el control de la GUI, no la función.

---

## La geometría del eje, y de dónde sale

El eje pasó de **16384 a 8192 canales** con el bitstream nuevo, y esa geometría
tiene **una sola fuente de verdad**: el registro `WIDTHS` (`0x008`) del propio
MCA. El cliente la lee al conectarse y arma todo con ella.

Dos cosas que **no** hay que usar para esto, las dos por experiencia:

- **`h_shift` (`0x03C`) está deprecado.** Se sigue leyendo y escribiendo pero
  **ya no afecta al datapath**. Quien lo use para convertir amplitudes a canales
  se equivoca por un factor `2^(AMP_W − h_aw)` — 8× sobre un eje de 8192 — y las
  amplitudes altas se le caen del eje sin dibujarse.
- **La copia de `h_aw` que publica `integration_cfg` puede mentir.** Es una
  segunda copia de un dato que ya publica el MCA, y hoy dice 14 mientras el
  hardware histogramea con 13: el commit que cambió el MCA no la actualizó. La
  pestaña de Integración la muestra y **avisa cuando no coincide**, porque ver
  la discrepancia es cómo se diagnostica un top re-sintetizado a medias.

La conversión correcta es `mca_canal_de_amplitud(valor, h_aw, z, k)`, espejo en
software de `mca_zoom.sv`: la ventana del zoom es `[k·2^(AMP_W−z),
(k+1)·2^(AMP_W−z))`, el bin son los `h_aw` bits siguientes, y **satura** fuera de
la ventana en vez de envolver. Los límites de la ventana de aceptación y los del
discriminador viven en cuentas de amplitud y pasan por ahí.

> **El zoom viaja en la metadata.** Hasta que `mca_get_config` lo releyó, un
> espectro guardado con zoom decía "8192 canales" sin decir sobre qué ventana de
> amplitud: su eje era irreconstruible. Los ficheros anteriores a eso no lo
> traen y la GUI avisa al abrirlos, asumiendo fondo de escala.

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
- [x] Pestaña de configuración del MCA: los 24 campos, con readback.
- [x] Pestaña de Integración: ruteo de taps y control global del slot 6.
- [x] Pestañas de OSC y Multitrigger, con formas de onda y curva de tasa.
- [x] Descubrimiento de bases por el registro `SLOTS` en vez de hardcodearlas.
- [ ] Pestaña del event_ring (slot 2): tiene API
      ([`osciloscope_ring.py`](../../software/API/osciloscope_ring.py)) y no
      tiene pestaña. Es el mismo patrón, una vez más.
- [ ] **Ninguna de las tres pestañas nuevas está probada contra la placa.** El
      simulado no simula el slot 6 ni el RTL del osciloscopio, así que sus
      pruebas cubren el contrato y no el driver de ese lado. Ver
      [`pruebas.md`](pruebas.md).

### Cómo se agrega una pestaña, ahora que hay tres hechas

El patrón está estable y son cuatro pasos:

1. **Un handle opcional en el servidor.** `_abrir_integracion()` y
   `_abrir_osc()` abren su bloque y **que falte no es un error**: dejan el
   handle en `None` y siguen. Es lo que permite que el mismo servidor sirva
   para un bitstream que no lo trae.
2. **Operaciones con prefijo en `_OPS`**, y las mismas en la tupla `OPS` de
   `mca_net.py` — que tiene un test que las compara, así que desincronizarlas
   falla en CI.
3. **Una bandera en `identify`** (`has_osc`, `has_mtrg`, como `has_2d`), y el
   cliente crea o destruye la pestaña con eso. Nunca se supone.
4. **Un panel con sus señales**, y en el trabajador un slot por cada una.

Para los campos hay algo más corto todavía. `PanelCampos` de
[`widgets_config.py`](../../software/app/widgets_config.py) da spinbox, casilla
y combo ya cableados al antirrebote y al anti-eco; el panel declara a qué bloque
pertenece en `BLOQUE` y la ventana rutea sus campos a `<bloque>.set` con eso.
Del lado de la API, cada bloque publica una tabla `_CAMPOS` de
`campo -> (offset, shift, máscara)` —el MCA, el OSC y el multitrigger ya la
tienen— y `campos_desconocidos()` comprueba de una vez que los nombres del panel
existan ahí. **Las máscaras salen del RTL, no de suponer 32 bits**: leer de más
devuelve bits que no existen y el readback deja de coincidir con lo escrito, que
es de lo que depende el anti-eco.

La deuda conocida del código está listada al final de
[`flujo_de_datos.md`](flujo_de_datos.md#estado-y-deuda-conocida).

---

## La pestaña de OSC, y por qué son dos gráficos

Con el histograma solo, un fotopico corrido puede ser el umbral, la línea de
base, la forma del pulso o el apilamiento, y no hay forma de distinguirlos desde
la GUI. La pestaña muestra las dos cosas que lo deciden y las muestra **atadas
en el tiempo**:

- **arriba**, la ventana capturada alrededor del trigger, IN1 e IN2 en volts
  contra microsegundos, con las últimas capturas en gris debajo (persistencia
  tipo fósforo, que es lo que hace visible la dispersión de forma);
- **abajo**, la tasa instantánea, con **una marca vertical en el instante de
  cada captura**.

Leerlas juntas es el diagnóstico: tasa que salta + formas apiladas es
apilamiento; formas limpias + tasa que cae es el umbral.

La curva lleva tres series. Las dos del MCA —`rate_inst_hz` y `rate_avg_hz`—
**no cuestan ninguna lectura nueva**: ya venían en cada `status`, cada 200 ms, y
antes se mostraban como texto y se tiraban. La tercera es la tasa de disparos
del OSC, de Δ`we_cnt`/Δt, y **no es la misma**: los dos caminos tienen tiempos
muertos distintos, y la distancia entre las curvas *es* la pérdida del camino
lento.

> **La captura sólo se pide con la pestaña visible.** Son hasta 16384 muestras
> por canal; el modo continuo se detiene solo al cambiar de pestaña, mismo
> criterio que el mapa 2D.

---

## Ver también

[`referencia_api.md`](../API/referencia_api.md), la API que el servidor expone ·
[`register_map_mca.md`](../mca/register_map_mca.md), los registros del otro lado ·
[`arquitectura_adquisicion_software.md`](../multitrigger/arquitectura_adquisicion_software.md),
el pipeline de adquisición de formas de onda, que es el otro camino de datos del
proyecto y no pasa por acá
