# Capas de software: kernel, sistema operativo y API

Cómo se organiza el software que corre sobre la placa, de dónde viene cada capa y
por qué el proyecto entra al hardware por donde entra. Es la vista de conjunto:
el detalle de cada tema vive en los documentos hermanos.

| Documento | Qué contiene |
|---|---|
| [`platform.md`](platform.md) §2.6, §2.11, §2.12, §4.8 | el procesador, el arranque, el inventario de software de fábrica y qué tomamos de él |
| [`API/README.md`](API/README.md) | la convención de nombres y los módulos |
| [`API/referencia_api.md`](API/referencia_api.md) | cada función y el registro que toca |
| [`API/arquitectura_software.md`](API/arquitectura_software.md) | los niveles, los hilos, el filesystem y los tests |
| [`API/arquitectura_adquisicion_software.md`](API/arquitectura_adquisicion_software.md) | el pipeline de eventos y los tiempos medidos |
| [`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) | el bus GP0 → `sys_bus` y sus reglas de acceso |

---

## 1. Capas de software

El software del sistema se organiza en capas, cada una apoyada sobre la anterior.
Las capas superiores ofrecen abstracciones que vuelven el desarrollo más
abordable: desde Python, leer un histograma es una llamada a función, no una
secuencia de accesos al bus. El precio es que cada capa agrega costo de ejecución
y quita control sobre lo que ocurre debajo, y buena parte de este documento trata
de dónde conviene pagar ese precio y dónde no.

La división fundamental es entre el **espacio del kernel** del sistema operativo y
el **espacio de usuario**. El documento presenta primero esa división y cómo la
aprovecha el proyecto (§2), luego la elección del sistema operativo (§3), los
servicios del kernel (§4) y las facilidades del sistema (§5), y por último la API
con la que el software accede al hardware (§6).

---

## 2. Espacio del kernel y espacio de usuario

### 2.1 Qué es el kernel

El **kernel** es el programa que el procesador ejecuta en modo privilegiado. Tiene
dos funciones: **administrar los recursos compartidos** (tiempo de CPU, memoria,
dispositivos) entre todos los programas que corren a la vez, y **ofrecerles
abstracciones** sobre esos recursos, de modo que ningún programa necesite conocer
el hardware en detalle. Las abstracciones principales son:

- el **proceso**: un programa en ejecución, con su propio flujo de control y su
  propio espacio de memoria;
- el **espacio de direcciones virtual**: cada proceso ve su memoria como si fuera
  la única del sistema;
- el **archivo**: una secuencia de bytes con nombre, que en Linux representa tanto
  datos en disco como dispositivos (`/dev/mem`) o parámetros del kernel (`/sys`);
- el **socket**: un extremo de una comunicación por red;
- el **dispositivo**: el hardware, accedido a través de un driver.

Todo lo que no es kernel corre en **espacio de usuario**: el intérprete de Python,
la biblioteca estándar de C, los servicios del sistema y los programas del
proyecto.

### 2.2 Cómo se hace cumplir la separación

La separación no es una convención de software: la impone el hardware. La
arquitectura ARMv7-A del Cortex-A9 define **niveles de privilegio**. El kernel
corre en el nivel privilegiado (PL1) y los procesos de usuario en el no
privilegiado (PL0). Desde PL0 no se pueden ejecutar las instrucciones que
configuran el procesador, ni acceder a memoria que la MMU no haya habilitado para
ese proceso. Cada proceso tiene su propia tabla de traducción, y la MMU traduce
sus direcciones virtuales a físicas en cada acceso: un proceso literalmente no
puede nombrar la memoria de otro ni la del kernel. La MMU del A9 está descripta
en [`platform.md`](platform.md) §2.6.

Para pedir un servicio al kernel, un proceso ejecuta una **llamada al sistema**
(*system call*): la instrucción `svc` cambia el procesador a modo privilegiado y
salta a un punto de entrada fijo del kernel, que valida el pedido, lo atiende y
devuelve el control. Por ejemplo, cuando el software abre el acceso a la memoria
física ([`API/mca.py:254`](../software/API/mca.py#L254)), la cadena es:

```
os.open('/dev/mem', O_RDWR | O_SYNC)        Python (espacio de usuario)
  └─ open()                                  biblioteca de C (espacio de usuario)
       └─ svc #0                             cambio a modo privilegiado
            └─ openat → driver de /dev/mem   kernel
```

### 2.3 El entorno de ejecución

El kernel provee el **entorno de ejecución de procesos**: carga los binarios
ejecutables (formato ELF) en memoria, les arma el espacio de direcciones, los
planifica sobre los núcleos disponibles y atiende sus llamadas al sistema. Lo que
habitualmente se llama *runtime*, en cambio, vive en espacio de usuario: el
cargador dinámico (`ld-linux`), la biblioteca estándar de C y, en este proyecto,
el intérprete de Python y NumPy.

### 2.4 Comparación

| | Espacio del kernel | Espacio de usuario |
|---|---|---|
| **Privilegio** | nivel privilegiado del ARM (PL1) | nivel no privilegiado (PL0) |
| **Memoria** | toda la física, más la propia del kernel | solo su espacio virtual, aislado de los demás procesos |
| **Acceso al hardware** | directo | solo a través del kernel (llamadas al sistema, o un mapeo que este autorice) |
| **Interrupciones** | las atiende directamente | no las ve, salvo que un driver se las reenvíe (por ejemplo, UIO) |
| **Consecuencia de un error** | *kernel panic*: cae todo el sistema | muere solo el proceso (`SIGSEGV`, `SIGBUS`) |
| **Lenguaje** | C, con las restricciones del kernel (sin biblioteca estándar) | cualquiera: C, Python, etc. |
| **Ciclo de desarrollo** | compilar contra los encabezados del kernel exacto, cargar el módulo, depurar con `printk` | editar y ejecutar; depuradores y *profilers* estándar |
| **Tareas típicas** | drivers, planificación, gestión de memoria, pila de red | aplicaciones, servicios, análisis de datos |

### 2.5 Drivers, módulos y *device tree*

Los **drivers** son parte del kernel y corren en modo privilegiado. Se compilan
junto con el kernel, ya sea incluidos en la imagen o como **módulos** (archivos
`.ko`) que se cargan en tiempo de ejecución. El kernel es un programa en C como
cualquier otro, y se compila para la arquitectura de destino. En este caso la
compilación es **cruzada**: se compila en una PC x86 (el *host*) para el ARM de la
placa (el *target*).

Lo que es propio de cada placa no son los drivers sino la **descripción del
hardware**. Los periféricos de un SoC no se pueden descubrir solos, como sí ocurre
con un dispositivo PCI o USB. Por eso el kernel recibe al arrancar un **_device
tree_**: una estructura de datos que enumera qué periféricos hay, en qué dirección
y con qué parámetros. Cada nodo declara una cadena `compatible`, y el kernel le
asocia el driver que la reconoce.

En el Zynq esto tiene una consecuencia particular: el contenido de la PL cambia con
cada bitstream, así que la parte del *device tree* que describe la PL se aplica
como un **_overlay_** en el momento de cargarla. El del proyecto es
[`dts/fpga.dtso`](../dts/fpga.dtso); el XADC lo declara
[`dts/pl_patch.dtsi`](../dts/pl_patch.dtsi). Los drivers del Zynq que usa la placa
están en el [apéndice A](#apéndice-a-drivers-del-zynq).

### 2.6 Dónde vive el software del proyecto

La decisión de diseño central de esta capa es que **todo el software del proyecto
corre en espacio de usuario**: no hay driver propio. El acceso a los registros de
la PL se hace mapeando `/dev/mem`, un dispositivo del kernel que representa la
memoria física, dentro del espacio de direcciones del proceso. La llamada `mmap`
sobre `0x4000_0000` le pide al kernel que agregue a la tabla de traducción del
proceso una entrada que apunte a la ventana de la PL, marcada como no cacheable
(por el `O_SYNC`). A partir de ahí, escribir un registro es una escritura común a
memoria que termina en el bus AXI, sin intervención del kernel en cada acceso.

Esta decisión ahorra escribir, compilar y mantener un módulo de kernel, y permite
que todo el software sea Python. Su costo es renunciar a las protecciones que un
driver habría dado:

| Costo | Consecuencia en el proyecto |
|---|---|
| **Requiere privilegios de root** | el software de la placa corre como root |
| **No hay protección de direcciones** | una dirección mal calculada escribe en otro bloque de la PL, o en memoria del kernel. Las funciones de apertura validan una palabra mágica del bloque antes de operar |
| **No hay arbitraje entre procesos** | **un solo proceso puede mapear la PL a la vez**; dos procesos mapeados terminan en errores de bus ([`platform.md`](platform.md) §4.8) |
| **Los errores del bus llegan como señales** | un acceso que la PL no acepta se convierte en `SIGBUS`, que mata al proceso sin *traceback*; en lecturas, en esta placa puede reiniciar el sistema |
| **El acceso tiene reglas de hardware** | solo accesos de 32 bits, alineados y de a uno. Copias en bloque (`memcpy`) generan ráfagas que el esclavo AXI rechaza ([`patrones_memoria_hw.md`](patrones_memoria_hw.md)) |
| **No hay interrupciones** | el software consulta los registros por *polling* |
| **No hay mantenimiento de caché** | la PL escribe en la DDR por los puertos HP, que no son coherentes con las cachés del procesador. La región reservada se mapea no cacheable para no leer datos viejos ([`hw_ring_plumbing.py`](../software/API/tests/placa/hw_ring_plumbing.py)) |

Un driver se justificaría si hiciera falta alguna de las cosas que esta tabla
resigna: atender interrupciones, compartir el hardware entre varios procesos o
aislar al software de usuario de los errores del bus. Ninguna es necesaria con el
reparto de tareas actual (§3.1).

---

## 3. Elección del sistema operativo

### 3.1 Qué le toca al software

La elección del sistema operativo parte de un requerimiento: **cuál es la latencia
de peor caso que el software necesita garantizar**, es decir, cuánto puede tardar
como máximo en reaccionar ante un evento. Esta métrica separa a los sistemas
operativos de tiempo real de los de propósito general, y es decisiva en
aplicaciones donde una respuesta tardía equivale a una falla, como el lazo de
control de un actuador.

En este proyecto, la respuesta se deriva del reparto de tareas entre la lógica
programable (PL) y el sistema de procesamiento (PS): todo lo que ocurre al ritmo
de la señal se implementó en la PL.

| | PL | PS (software) |
|---|---|---|
| **Ritmo** | una muestra cada 8 ns (125 MS/s) | el de la interacción con el usuario y con el disco |
| **Tareas** | muestreo, disparo, discriminación, integración de carga, histograma, escritura de eventos a la DDR | configuración de registros, arranque y parada, lectura del histograma (~1 Hz), vaciado del buffer de eventos, guardado, servicio de la interfaz gráfica por red |
| **Si se atrasa** | se pierde un evento | se consume margen del buffer en DDR; no se pierde ningún evento mientras este no se llene |

Por lo tanto, el software no tiene plazos duros. Lo que se le exige es
**rendimiento promedio**: vaciar el buffer de eventos más rápido de lo que la PL
lo llena. El histograma se acumula en la PL sin intervención de la CPU, y las
demoras del software solo consumen el margen del buffer en DDR. La latencia de
peor caso deja de ser un criterio de selección, y el criterio pasa a ser cuántas
facilidades ofrece el sistema operativo.

### 3.2 Cómo usar los dos núcleos: AMP o SMP

El PS del Zynq-7010 tiene dos núcleos Cortex-A9 a 667 MHz que comparten 512 KB de
caché L2 y la DDR. La coherencia entre sus cachés L1 la mantiene en hardware la
*Snoop Control Unit* (SCU), descripta en [`platform.md`](platform.md) §2.6. El
software se puede repartir entre los dos núcleos de dos maneras:

```
            AMP                                     SMP
  ┌──────────────┬──────────────┐        ┌─────────────────────────────┐
  │ tareas A     │ tareas B     │        │   un conjunto de tareas     │
  ├──────────────┼──────────────┤        ├─────────────────────────────┤
  │ Linux        │ RTOS o       │        │   un kernel (scheduler)     │
  │              │ bare-metal   │        ├──────────────┬──────────────┤
  ├──────────────┼──────────────┤        │   núcleo 0   │   núcleo 1   │
  │   núcleo 0   │   núcleo 1   │        └──────────────┴──────────────┘
  └──────────────┴──────────────┘
```

- **_Asymmetric Multi-Processing_ (AMP).** Cada núcleo ejecuta una imagen de
  software independiente: un sistema operativo completo, un RTOS o un programa
  *bare-metal* sin kernel. Es asimétrico porque los núcleos no cumplen el mismo
  papel: cada uno tiene su propio software y su propio conjunto de tareas. La
  configuración típica en Zynq ejecuta Linux en el núcleo 0, para la red y los
  archivos, y un lazo determinístico (*bare-metal* o FreeRTOS) en el núcleo 1.
  Ambos se comunican por memoria compartida, en Linux mediante el *framework*
  OpenAMP (`remoteproc` y `RPMsg`). El precio es repartir a mano la memoria, las
  interrupciones y los periféricos entre las dos imágenes, mantener dos entornos
  de desarrollo y aceptar que la L2 y la DDR compartidas introducen interferencia
  entre núcleos de todos modos.
- **_Symmetric Multi-Processing_ (SMP).** Un único kernel administra ambos núcleos
  como equivalentes, y su *scheduler* decide en cada momento en qué núcleo corre
  cada tarea. La SCU vuelve natural esta configuración, porque garantiza que los
  dos núcleos vean la misma memoria sin intervención del software.

AMP se justifica cuando se necesita un lazo determinístico **en la CPU**. Como en
este proyecto esa necesidad no existe, la configuración natural es SMP.

### 3.3 Las alternativas

| Opción | Configuración típica en Zynq | Latencia de peor caso | Qué provee | Costo de desarrollo |
|---|---|---|---|---|
| **Standalone (_bare-metal_)** | un núcleo, o AMP | determinística: no hay nada entre el programa y el hardware | drivers básicos de Xilinx (BSP); no hay red, archivos ni procesos | alto: todo se escribe a mano, en C |
| **FreeRTOS** | AMP (también admite SMP) | acotada y garantizada por diseño | *scheduler* por prioridades, colas, semáforos; red y sistema de archivos como bibliotecas aparte | medio-alto |
| **Linux con `PREEMPT_RT`** | SMP | acotada en la práctica, sin garantía formal | todo lo de Linux | medio: en el kernel 5.15 es un parche aparte, que hay que aplicar, compilar y medir |
| **Linux de propósito general** | SMP | sin cota | procesos, memoria virtual, red, sistema de archivos, Python, ssh | bajo |

### 3.4 Decisión

Como los requerimientos sensibles a la latencia se resolvieron en la PL, se eligió
el extremo que maximiza las facilidades: **Linux de propósito general, en
configuración SMP**. En concreto, el sistema operativo que distribuye Red Pitaya,
*Red Pitaya OS 2.00*: un Ubuntu para ARM con el kernel 5.15 de Xilinx
(`linux-xlnx`), que se basa en el kernel *mainline* y le agrega el soporte del
Zynq, sobre el cual Red Pitaya suma su propia capa de software.

No es un requerimiento obligatorio: lo que el proyecto usa del sistema es, en su
mayoría, Linux estándar (§5), y funcionaría sobre cualquier Zynq con Linux. Pero la
imagen llega configurada y arranca sola, lo que evita generar el FSBL, configurar
U-Boot y escribir el *device tree* de la placa.

La misma lógica se repite en las decisiones de más abajo. El software no usa
interrupciones: consulta los registros por *polling*. Una lectura de registro por
`mmap` desde Python tarda 2.3 µs medidos, mientras que despertar a un proceso de
usuario desde una interrupción (vía UIO) se **estima** en 5–20 µs
([`API/arquitectura_adquisicion_software.md`](API/arquitectura_adquisicion_software.md),
Parte 5). Como no hay plazos que cumplir, la opción más simple también resulta la
más rápida.

---

## 4. Servicios del kernel de Linux

| Subsistema | Qué hace | Cómo lo usa el proyecto |
|---|---|---|
| **Procesos y *scheduler*** | crea los procesos e hilos y los reparte entre los dos núcleos | el servidor del MCA, los servicios del sistema y las sesiones de ssh corren en paralelo. Dentro de un proceso de Python, el GIL impide que dos hilos ejecuten Python a la vez; el paralelismo real aparece cuando un hilo espera E/S |
| **Memoria virtual** | da a cada proceso su espacio de direcciones y administra las tablas de la MMU | es el mecanismo por el cual el proceso llega a la PL: el `mmap` de `/dev/mem` es una entrada más en la tabla de traducción |
| **Sistema de archivos virtual (VFS)** | presenta con la misma interfaz los archivos en disco, los dispositivos y los parámetros del kernel | el acceso a la PL (`/dev/mem`), su programación (`/sys/class/fpga_manager`), los puentes AXI (`/sys/class/fpga_bridge`) y la temperatura (IIO) son todos archivos |
| ***Page cache*** | guarda en RAM los datos de disco recientes y difiere las escrituras | una escritura vuelve antes de llegar a la microSD (12.4 MB/s medidos), lo que desacopla al software del disco |
| **Pila de red** | implementa TCP/IP sobre el driver de Ethernet | el servidor del MCA atiende a la interfaz gráfica por TCP; el despliegue se hace por ssh y rsync |
| **Drivers de dispositivo** | traducen las abstracciones anteriores a los periféricos concretos | los del Zynq ([apéndice A](#apéndice-a-drivers-del-zynq)); ninguno propio |

Las rutas concretas que lee y escribe el software están en
[`API/arquitectura_software.md`](API/arquitectura_software.md) §3.

---

## 5. Facilidades del sistema

Las facilidades que el sistema pone a disposición del proyecto provienen de cuatro
fuentes: el **kernel** de Linux, la **distribución** (Ubuntu), el software de
**Xilinx** y el propio de **Red Pitaya**. La distinción no es solo descriptiva: lo
que proviene de Red Pitaya es exactamente lo que habría que reescribir para llevar
el proyecto a otra placa Zynq ([`platform.md`](platform.md) §5).

```
  aplicaciones web · marketplace     JupyterLab     scpi-server        [Red Pitaya]
  librp (C) · binding Python `rp` · rp_overlay                          [Red Pitaya]
  fpgautil · monitor · calib                                    [Xilinx / Red Pitaya]
  Ubuntu · systemd · ssh · rsync · Python 3.10 + NumPy                [distribución]
 ─────────────────────────── kernel 5.15-xilinx ───────────────────────────
  /dev/mem · fpga_manager · fpga_bridge · IIO · reserved-memory              [kernel]
 ─────────────────────────────── PL (bitstream) ───────────────────────────────
                    ▲
       el MCA entra por acá: mmap de /dev/mem sobre 0x4000_0000
```

Leyenda de la última columna: **✓** el MCA la usa · **~** la usa en parte ·
**✗** existe pero no la usa. El porqué de cada veredicto, en detalle, está en
[`platform.md`](platform.md) §4.8.

| Facilidad | Qué aporta | Origen | Uso en el MCA |
|---|---|---|---|
| **`/dev/mem` + `mmap`** | acceso a la memoria física, y por lo tanto a los registros de la PL, desde un proceso de usuario y sin escribir un driver | kernel | ✓ es el único camino a los registros |
| **`fpga_manager` + `fpga_bridge`** (sysfs) | recargar la PL en caliente y bajar/subir los puentes AXI, sin JTAG ni reinicio | kernel (driver `zynq-fpga`) | ✓ lo envuelve [`API/fpga.py`](../software/API/fpga.py) |
| **IIO** + driver `xadc` | temperatura del die y entradas analógicas lentas como archivos, sin lógica en la PL | kernel; el nodo del XADC lo agrega el *device tree* de Red Pitaya | ✓ temperatura, para correlacionar la deriva |
| **`reserved-memory`** | mecanismo estándar del *device tree* para apartar DDR fuera del alcance de Linux | kernel | ✓ el buffer de eventos necesita DDR que el kernel no toque |
| **Consola serie** (micro-USB, 115200 8N1) | acceso a la placa cuando la red no levanta | kernel + `getty` | ✓ |
| **Ubuntu ARM + Python 3.10 + NumPy** | entorno de trabajo completo en la placa, sin compilar nada | distribución | ✓ todo el software del proyecto es Python |
| **`systemd`, ssh, rsync** | servicios que arrancan solos y despliegue por red | distribución | ✓ |
| **nginx** | servidor web de la interfaz de fábrica | distribución | ✗ la interfaz del MCA habla TCP, no HTTP |
| **JupyterLab** | editar y ejecutar Python en la placa, con gráficos | proyecto *upstream*, empaquetado por Red Pitaya | ~ solo como banco de pruebas |
| **`fpgautil`** | programar la PL y aplicar el *overlay* de *device tree* en un solo comando | Xilinx, empaquetado por Red Pitaya | ✓ |
| **Imagen Red Pitaya OS 2.00** | FSBL para este PS7, U-Boot, kernel y *device tree* de esta placa, listos para arrancar | Red Pitaya | ✓ es lo que más trabajo ahorra |
| **Regiones de DDR reservadas** | `buffer@1000000` (2 MB) y `labuf@a000000` (32 MB), ya apartadas en el *device tree* de fábrica | Red Pitaya | ✓ el buffer de eventos usa `labuf`, que toma prestada del analizador lógico |
| **`librp`** + binding Python (`import rp`) | manejo del osciloscopio de fábrica (adquisición, disparo) por *offsets* fijos de registros | Red Pitaya | ✓ en el camino de formas de onda |
| **`monitor`** | leer/escribir registros desde la shell y leer el modelo de placa grabado en la EEPROM | Red Pitaya | ~ solo para identificar el modelo de placa |
| **`rp_overlay`** | cargar los *overlays* de fábrica desde Python | Red Pitaya | ~ solo en código heredado |
| **API de *deep memory* (`rp_AcqAxi*`)** | capturar a DDR por los puertos HP desde la biblioteca | Red Pitaya | ✗ supone el bitstream de fábrica; el MCA escribe a DDR con RTL propio |
| **EEPROM de calibración + `calib`** | ganancia y *offset* de fábrica por canal | Red Pitaya | ✗ el eje de canales del MCA se calibra contra un generador |
| **`scpi-server`** | controlar la placa como instrumento de banco | Red Pitaya | ✗ |
| **Aplicaciones web + *marketplace*** | osciloscopio, analizador de espectro, analizador lógico, etc. | Red Pitaya | ✗ reemplazadas por la interfaz propia del MCA ([`APP/`](APP/README.md)) |
| **Repositorio `RedPitaya-FPGA`** | top, restricciones de pines, *block design* del PS7, PLL y bus de registros con sus 8 *slots* | Red Pitaya | ✓ es la base del diseño de la PL |

Leída de arriba abajo, la tabla muestra que **casi todo lo que el MCA toma es Linux
estándar, y casi todo lo que descarta es propio de Red Pitaya**. Hay dos
excepciones. La primera es `librp`, lo único de Red Pitaya que está en el camino de
medición: como accede a *offsets* fijos de registros, obliga a la PL a conservar el
mapa de registros del osciloscopio de fábrica
([`osc/register_map_osc.md`](osc/register_map_osc.md)). La segunda son `fpgautil` y
`monitor`, lo único de Red Pitaya en la puesta en marcha. Fuera de esas piezas, el
software del proyecto es portable a cualquier Zynq con Linux.

---

## 6. API

Una **API** (*Application Programming Interface*) es el conjunto de funciones,
tipos y reglas con que un programa accede a los servicios de otro componente sin
conocer su implementación. En este proyecto, la API es el paquete de Python
[`software/API/`](../software/API/), y es el contrato entre el hardware —los
registros de cada bloque de la PL— y las aplicaciones que lo usan: los scripts de
medición, el servidor del MCA, la interfaz gráfica y los *notebooks*.

### 6.1 Niveles de la pila

La API no es una sola capa: se organiza en niveles, cada uno apoyado sobre el
anterior. Lo que define los límites no es la conveniencia sino **dónde están las
fronteras físicas**: entre los niveles 1 y 3 hay un bus AXI con reglas propias, y
entre la aplicación y el resto puede haber una red. La figura está en
[`API/figuras/niveles.svg`](API/figuras/niveles.svg).

| # | Nivel | Qué contiene | Corre en |
|---|---|---|---|
| 7 | Aplicación | scripts de medición, *notebooks*, interfaz gráfica | PS o PC |
| 6 | Fuentes y sesión | adquisición y guardado continuo de eventos (`AcquisitionSession`, `EventSource`) | PS |
| 5 | Funciones | `mca_*`, `osciloscope_*`, `multitrigger_*`, `integration_*` | PS |
| 4 | *Handles* | un objeto por bloque abierto: `MCA`, `Osciloscope`, `MultiTrigger`, `RingSource`, `Integration` | PS |
| 3 | Acceso de 32 bits | `w32`, `r32` y la lectura en bloque palabra por palabra | PS |
| 2 | Mapeo | `/dev/mem` + `mmap`, una región por *slot* del bus | PS |
| 1 | Registros | los bloques del bus de sistema | PL |

Dos propiedades de esta estructura merecen destacarse:

- **El nivel 3 es una frontera, no una comodidad.** Todo acceso a la PL pasa por
  dos funciones, `w32` y `r32` ([`API/mca.py:292`](../software/API/mca.py#L292)),
  porque es el único lugar donde se pueden hacer cumplir las reglas del bus:
  accesos de 32 bits, alineados, de a uno (§2.6).
- **La red se inserta en el nivel 4.** El *handle* remoto `MCARemote` es una
  subclase de `MCA` que solo redefine `r32` y `w32` para que viajen por un socket.
  Como las funciones del nivel 5 acceden al hardware únicamente a través del
  *handle*, toda la API del MCA funciona igual desde una PC, sin cambiar una línea.
  Por la misma vía existen *handles* simulados (`FakeMCA`), que permiten probar
  todo lo que está arriba sin la placa.

### 6.2 Convención de nombres

Los nombres de las funciones públicas siguen el patrón
`<módulo>_<operación>_<campo>`, y el nombre dice a qué bloque accede la función y
qué tipo de operación realiza. Los segmentos del nombre no deben confundirse con
los niveles de §6.1.

| Segmento | Qué indica | Valores |
|---|---|---|
| 1 · módulo | a qué bloque del bus accede | `mca_` · `osciloscope_` · `multitrigger_` · `integration_` |
| 2 · operación | qué clase de operación es | `get_` / `set_` (configuración y estado) · `read_` (lectura de datos) · `write_file_` / `save_file_` (guardado) |
| 3 · campo | el registro o el dato concreto | `thr`, `gate_long`, `histogram`, `counters`, … |

Cada tipo de operación tiene una regla propia:

- **Configuración y estado** usan un par `get_`/`set_` por campo de registro:
  `mca_get_thr(h)`, `mca_set_thr(h, 200)`. Cuando varios campos comparten un
  registro, `set_` hace lectura-modificación-escritura, de modo que escribir un
  campo no borra a sus vecinos.
- **Lectura** devuelve siempre un arreglo de NumPy, que es la estructura natural
  del dato: `mca_read_histogram(h)`.
- **Guardado** distingue el formato de texto por defecto, un CSV con la metadata en
  la cabecera (`write_file_`), de los formatos estructurados, `.npz` y `.json`
  (`save_file_`).

Fuera del patrón quedan las funciones de **ciclo de vida**, que no se refieren a un
campo sino al bloque entero: `_open`, `_close`, `_identify`, `_start`, `_stop`,
`_clear`, `_configure`.

```python
from API.mca import mca_open, mca_set_thr, mca_read_acquire, mca_write_file_histogram

h = mca_open()                                   # ciclo de vida: mapea el slot 7 y valida el bloque
mca_set_thr(h, 200)                              # configuración
hist, mapa, contadores = mca_read_acquire(h, 10) # lectura: 10 s de adquisición
mca_write_file_histogram(hist, 'espectro.csv')   # guardado
```

| Módulo | Bloque de la PL | Dirección base |
|---|---|---|
| [`API.mca`](../software/API/mca.py) | analizador multicanal | `0x4070_0000` (*slot* 7) |
| [`API.osciloscope`](../software/API/osciloscope.py) | osciloscopio de fábrica | `0x4010_0000` (*slot* 1) |
| [`API.osciloscope_ring`](../software/API/osciloscope_ring.py) | buffer de eventos en DDR (`event_ring`) | `0x4020_0000` (*slot* 2) |
| [`API.multitrigger`](../software/API/multitrigger.py) | máscaras de disparo, *shield* y *snapshot* | `0x4030_0000` (*slot* 3) — ver aviso |
| [`API.integration`](../software/API/integration.py) | identificación del bitstream y ruteo entre bloques | `0x4060_0000` (*slot* 6) |

El nombre del módulo `osciloscope` conserva la grafía del código (en inglés
correcto, *oscilloscope*).

> ⚠️ **El multitrigger está a medio migrar.** El hardware se mudó al slot 3, pero
> parte de [`API/multitrigger.py`](../software/API/multitrigger.py#L28) todavía
> escribe los offsets `0x210`–`0x24C` sobre el slot 1, donde ya no los decodifica
> nadie, y no lanza excepción. Ver el aviso de [`API/README.md`](API/README.md).

### 6.3 Supuestos de la API

La API se apoya en un conjunto de supuestos que no verifica en cada llamada, por
costo o porque no puede. Son las condiciones bajo las cuales su comportamiento está
garantizado:

1. **Un solo proceso accede a la PL a la vez.** No hay arbitraje entre procesos
   (§2.6). El servidor del MCA lo hace cumplir aceptando un único cliente y
   serializando el acceso al *handle* con un *lock*.
2. **El proceso corre como root**, requisito para mapear `/dev/mem`.
3. **El bitstream cargado es el esperado.** Las funciones de apertura lo comprueban
   una vez, leyendo la palabra mágica de cada bloque (`"MCA1"`, `"EVNT"`,
   `"INTG"`), porque un acceso a un *slot* vacío termina en `SIGBUS`. Después de
   abrir, no se vuelve a comprobar.
4. **La PL no se reprograma con mapeos abiertos.** Reconfigurar la PL con regiones
   mapeadas puede dejar trabado el puerto AXI hasta reiniciar la placa; por eso los
   mapeos se cierran antes de cargar un bitstream.
5. **Todo acceso pasa por el nivel 3.** Escribir o leer el mapeo por otra vía, por
   ejemplo con una copia en bloque de NumPy, viola las reglas del bus.
6. **La exposición la mide el software.** El MCA acumula en forma continua y no
   tiene un registro de tiempo de medición: la duración de una adquisición se
   controla consultando el tiempo vivo que cuenta la PL.

### 6.4 Funciones auxiliares

Además de las funciones por bloque, la API incluye módulos que no acceden a ningún
registro de la PL. Por eso no llevan prefijo de bloque
([`API/decisiones_del_refactor.md`](API/decisiones_del_refactor.md)).

| Módulo | Qué contiene | Accede al hardware |
|---|---|---|
| [`API.analisis`](../software/API/analisis.py) | análisis de espectros: ajuste de picos y resolución, calibración en energía, no linealidad (DNL, INL), figura de mérito de discriminación por forma, tiempo muerto | no |
| [`API.fpga`](../software/API/fpga.py) | puesta en marcha de la PL: verificar que el bitstream corresponda al Zynq de la placa, bajar los puentes AXI, programar, subirlos y comprobar que el bus responde | sí, por sysfs |
| [`API.mca_net`](../software/API/mca_net.py) | protocolo de red del MCA: una línea JSON de control y un bloque binario opcional | no |
| [`API.mca_remote`](../software/API/mca_remote.py) | los *handles* `MCARemote` (el MCA de la placa, por TCP) y `FakeMCA` (simulado) | a través de la red |
| [`API.rigol_dg4162`](../software/API/rigol_dg4162.py) | driver del generador de funciones externo usado en la caracterización | no (instrumento externo) |

Las funciones de análisis son puras: reciben arreglos y devuelven resultados, sin
estado ni acceso al hardware. Esto permite probarlas en la PC contra espectros
guardados, sin la placa.

---

## Apéndice A. Drivers del Zynq

Periféricos del PS del Zynq-7000 que usa la placa y el driver del kernel que los
atiende. Todos forman parte del kernel *mainline*; lo que aporta Red Pitaya es el
*device tree* que los declara. La asignación de pines de cada periférico está en
[`platform.md`](platform.md) §2.8.

> **Pendiente de verificar en la placa.** Los nombres son los de los drivers
> *mainline* para el Zynq-7000; no se contrastaron todavía contra el kernel de RP
> OS 2.00. Para hacerlo: `ls /sys/bus/platform/drivers` y `lsmod` en la placa.

| Periférico | Driver del kernel | Uso en la placa |
|---|---|---|
| Configuración de la PL (PCAP/DevC) | `zynq-fpga` (subsistema `fpga_manager`) | carga del bitstream en caliente |
| Puentes PS–PL | `fpga_bridge` | aislar el bus AXI durante la reconfiguración |
| Ethernet (Cadence GEM) | `macb` | red de 1 Gbit |
| SD/SDIO (Arasan) | `sdhci-of-arasan` | microSD, el disco del sistema |
| UART (Cadence) | `xilinx_uartps` | consola serie |
| I2C (Cadence) | `i2c-cadence`, más `at24` para la EEPROM | EEPROM de calibración y modelo de placa |
| USB (ChipIdea) | `ci_hdrc_usb2` | puerto USB-A host |
| GPIO | `gpio-zynq` | líneas del PS, incluidas las que cruzan por EMIO |
| SPI y QSPI (Cadence) | `spi-cadence`, `spi-zynq-qspi` | conector de expansión y memoria flash |
| CAN | `xilinx_can` | conector de expansión |
| XADC | `xilinx-xadc` (subsistema IIO) | temperatura del die y entradas analógicas lentas |
| DMA (ARM PL330) | `pl330` | DMA general del PS |
| Controlador de interrupciones (ARM GIC) | `irq-gic` | interrupciones de todos los periféricos |
| Timers (Cadence TTC) | `cadence_ttc` | base de tiempo del sistema |
