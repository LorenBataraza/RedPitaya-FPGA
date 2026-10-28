# El recorrido del usuario — de "me dieron una placa" al dato analizado

Este documento expande el mapa de recorrido (*user journey*) del sistema: **qué
hace un usuario a lo largo del tiempo**, qué tiene que saber en cada paso, qué
lo puede arruinar, y **qué parte de este proyecto hace que ese paso sea barato**.

No es el paso a paso operativo —ese es
[`puesta_en_marcha.md`](puesta_en_marcha.md), que da los comandos—. Acá se
responde otra pregunta: *¿cuánto le cuesta a una persona llegar a un dato
confiable, y dónde se le va el costo?*

**El mapa dibujado** está en
[`figuras/recorrido_del_usuario.tex`](figuras/recorrido_del_usuario.tex)
(`pdflatex recorrido_del_usuario.tex` → lámina apaisada de 34 × 17 cm). Tiene
los mismos carriles que este documento —alto nivel, tareas, detalles,
riesgos—, marca con ★ las actividades que el recorrido original no tenía, y
tacha en gris los riesgos de entonces que hoy están resueltos.

> **La tesis de todo el documento, en una línea.** El recorrido original tenía
> seis pasos y el costo estaba repartido en los **primeros**: bajar, compilar,
> flashear, configurar red. Hoy el paquete instalable, los objetivos del
> Makefile y los scripts de campaña **colapsan esa mitad a tres comandos**, y lo
> que queda caro es la mitad de atrás —decidir si el dato es bueno—, que es
> exactamente donde entra la GUI.

---

## Los tres usuarios, porque no recorren lo mismo

El mapa cambia bastante según quién lo camine, y mezclarlos es lo que hace que
un recorrido parezca más caro de lo que es.

| | **El que mide** | **El que caracteriza** | **El que desarrolla** |
|---|---|---|---|
| Quiere | un espectro de su detector | medir cómo se comporta el MCA | tocar el RTL o la app |
| Baja | la **release**, 1.3 MB | el **clon parcial**, 7.5 MB | el **repo completo**, 303 MB |
| Herramienta principal | la **GUI** (`make app`) | los **scripts de campaña** (`campana-*`) | el repo, Vivado, los tests |
| Sabe Python | no hace falta | sí | sí |
| Sabe Git | **no hace falta** | lo básico | sí |
| Pasos que recorre | 1 → 11 salteando 12 | todos | todos, más la síntesis |

El recorrido de abajo está escrito para **el que mide**, con una nota en cada
paso de qué cambia para los otros dos. Esa es la decisión de diseño que más
mueve el mapa: *el usuario por defecto no es el autor del sistema.*

---

## El recorrido, en tres fases

```
FASE A — PREPARAR            FASE B — MEDIR               FASE C — EXPLOTAR
(una vez por sesión,         (el ciclo que se             (después, y en la PC,
 o por campaña)               repite)                      sin la placa)

0 Conocer la herramienta     6 Configurar la medición     9 Guardar / exportar
1 Montar el equipo           7 Arrancar                  10 Analizar
2 Llegar a la placa          8 Supervisar y diagnosticar 11 Cerrar y dejar traza
3 Conseguir el software        ↑_________________________↓ 12 Automatizar / repetir
4 Dejar listo el hardware        el lazo de realimentación
5 Primera medida de confianza
```

---

## Fase A — Preparar

### 0. Conocer la herramienta antes de tenerla

**Qué hace:** abre la interfaz contra un MCA simulado, en su PC, sin placa ni
señal, y navega las pestañas hasta entender qué va a ver.

```bash
make app-demo      # servidor con MCA falso + GUI, todo en la PC
```

**Por qué es un paso y no un detalle.** En el mapa original este paso no
existía, y por eso *Falta de feedback* aparecía como riesgo recién en el paso 4:
el usuario descubría la interfaz **con el experimento corriendo**, que es el
peor momento posible para aprender dónde está cada control. Poder equivocarse
sin consecuencias, antes de que haya una fuente radiactiva encendida y un
detector estabilizado, mueve el aprendizaje a donde es gratis.

| Lo que necesita | Riesgo que elimina |
|---|---|
| PyQt5 y matplotlib en la PC | aprender la interfaz con la medición corriendo |

*Para el que desarrolla:* el mismo objetivo es el entorno de prueba de la GUI;
`make verificar-gui` la corre entera sin pantalla, que es lo que va en CI.

---

### 1. Montar el equipo

**Qué hace:** conecta la señal al **IN1** por coaxil, decide si la fuente es un
detector real o el generador, y pone la placa en la red.

| | |
|---|---|
| Placa | Red Pitaya STEMlab 125-14 (Zynq 7010), RP OS 2.00 |
| Señal | la fuente —detector o generador— al **IN1**, por coaxil |
| Red | la placa y la PC en la misma red |
| Veto externo (opcional) | DIO0_P del conector E1, 3.3 V |

**Es un paso corto y sin herramienta de por medio**, y por eso es fácil
dibujarlo más chico de lo que es: todo lo que viene después asume que hay señal
en el IN1, y ningún mensaje de error lo dice. `make placa-estado` contesta si la
placa responde y qué bitstream tiene, pero no si llegó la señal; eso lo contesta
recién el paso 5.

> **Si se usa el Rigol DG4162** —que es opcional, y sólo existe para tener señal
> conocida sin depender de un detector— hay un detalle propio de ese
> instrumento: va por **USB a la Pitaya**, no a la PC. Por eso los objetivos
> `rigol-*` llevan el guard `exige-placa` y desde la PC se usan los
> `rigol-*-remoto`. No aplica a quien mide con su propia fuente.

---

### 2. Llegar a la placa

**Qué hace:** define el alias `pitaya` y comprueba que responde.

```bash
ssh pitaya hostname          # tiene que contestar rp-xxxxxx sin pedir password
```

| Tarea | Detalle | Riesgo |
|---|---|---|
| Configurar red | IP de la placa, proxy si lo hay | la IP cambia seguido |
| Clave SSH | `~/.ssh/config.d/pitaya`, `IdentityFile` | pedir password en cada comando |

**Lo que abarata este paso es una convención, no una herramienta**: todo el
proyecto —Makefile, documentación, scripts— habla del **alias** `pitaya` y nunca
de una IP. Cuando la IP cambia (histórico: `.28` → `.37` → `.45` → `.27`) se
edita **un solo campo en un solo archivo**. Sin esa convención, un cambio de IP
es un *find & replace* por el repo, y el costo de un paso de dos minutos se
multiplica por la cantidad de lugares donde el número quedó escrito.

Y hay un comando que contesta el estado entero de un saque, que es al que se
vuelve siempre:

```console
$ make placa-estado
esta máquina  : la PC (no es la placa)
alias ssh     : pitaya -> 10.73.28.27, responde (rp-f08768)
PL            : operating · MCA1 · 8192 canales · mapa 2D sí
servidor      : no hay ninguno corriendo (make app-servidor-remoto)
generador     : Rigol Technologies DG4162
árbol remoto  : al día
```

Cada línea **se degrada sola**: sin ssh, las de abajo dicen que no se pudo
consultar en vez de fallar. Es diagnóstico, no verificación, y por eso sirve
cuando las cosas están mal — que es cuando se lo necesita.

---

### 3. Conseguir el software

**Acá es donde el recorrido original era más caro, y donde más cambió.**

El mapa viejo ponía *Descargar/Compilar* → *Cargar a la SD* como dos tareas con
dos riesgos abajo (*Software muy pesado*, *Uso de Git*). Las dos desaparecen por
completo para el usuario que sólo quiere medir:

```bash
curl -LO .../mca-0.1.0.tar.gz && curl -LO .../SHA256SUMS
sha256sum -c SHA256SUMS
tar xzf mca-0.1.0.tar.gz && cd mca-0.1.0
sudo ./instalar.sh --cargar
```

| Vía | Para quién | Baja | Pide saber Git |
|---|---|---|---|
| **Release** | usar el sistema | **1.3 MB** | **no** |
| Clon parcial | desarrollar *en* la placa | 7.5 MB | sí, un poco |
| Clone completo | tocar el RTL, sintetizar | 303 MB | sí |

**El argumento fuerte del paquete no es el tamaño, es el apareamiento.**
`mca_top.sv` **ignora en silencio las escrituras a direcciones que no mapea**:
el `default` del decodificador devuelve `0` y no levanta error. Un software
nuevo contra un bitstream viejo **no falla** — mide, y los números son
plausibles. La release garantiza que el `.bit.bin` y el Python que sabe hablarle
salieron **del mismo commit y viajan en el mismo tarball**.

> Por eso *compilar* desapareció del recorrido del usuario y no es que se haya
> escondido: el bitstream ya viene sintetizado, con su `md5`, su `VARIANTE` y la
> `PARTE` de Zynq para la que se compiló. La síntesis es trabajo del que
> desarrolla, una vez, no de cada persona que quiere medir.

*Para el que caracteriza:* el clon parcial vale la pena porque quiere `git pull`
en la placa. Las tres banderas importan y no son intercambiables: `--depth 1`
corta la historia, `--filter=blob:none` evita **descargar** lo que no va a
materializar, y `--sparse` decide qué se materializa. Sin la segunda, el filtro
de rutas ahorra disco pero no descarga.

---

### 4. Dejar listo el hardware

**Qué hace:** programa la PL y **verifica que quedó programada con lo que
quería**.

```bash
make app-servidor-off-remoto      # que nadie más tenga /dev/mem
make placa-cargar-remoto          # tiene que decir PLACA LISTA
make verificar-placa-remoto       # la batería de hardware
```

Este paso tiene **dos reglas que no son negociables** y que el recorrido
original no mencionaba porque sólo se descubren costando una sesión:

**(a) Un solo proceso sobre `/dev/mem`.** No hay servicios que apagar —ni nginx,
ni el servidor web de Red Pitaya, ni el `scpi-server`—. Lo que rompe son dos
procesos mapeando `/dev/mem` a la vez, y los culpables habituales son un kernel
de Jupyter vivo que haya hecho `rp_Init()` y un `mca_server` de una sesión
anterior. **El síntoma es SIGBUS: el proceso muere sin traceback.** No hay
mensaje que diga qué pasó.

**(b) El bitstream tiene que ser para esta placa.** Cargar uno de otro Zynq
**no falla y ya**: el IDCODE no coincide, el FPGA manager devuelve `-ETIMEDOUT`
y queda trabado; de ahí en adelante falla toda programación posterior, incluida
la de fábrica, y sólo se sale reiniciando. Por eso el instalador **lee el modelo
de la EEPROM** y elige la variante, y por eso la comparación se hace antes de
escribir un solo bit.

**La verificación es el paso que parece opcional y es el que más rinde.** Lee y
reescribe registro por registro, porque es la única forma de distinguir un
bitstream viejo de uno nuevo *desde el software*:

| Si dice… | Qué pasa |
|---|---|
| `PLACA LISTA`, **8192 canales** | todo bien |
| `PLACA LISTA` pero **16384 canales** | está el bitstream **viejo** — no seguir |
| `bus de features: NO` | ídem |
| `NO se programó la PL: este bitstream es para…` | es de otro Zynq; **no se escribió nada** |

> **Por qué este paso justifica existir.** Contra el bitstream viejo, configurar
> los registros nuevos no falla: escribe al vacío, el MCA sigue histogrameando
> con lo que tenía, y **la campaña entera sale con números plausibles que no
> responden a lo que se pidió**. Mirando los datos después no hay forma de darse
> cuenta. Un minuto de verificación contra una campaña inservible.

---

### 5. La primera medida de confianza

**Qué hace:** mide **señal conocida** antes de confiar en señal desconocida.

```bash
make rigol-pulsos-remoto TASA=3000 AMP=0.6     # tren de 2 µs a 3 kHz, 0.6 Vpp
make verificar-placa-datapath                  # mete señal real y la sigue hasta el histograma
```

Y lo que tiene que dar, que es lo que lo convierte en una prueba y no en una
demostración:

| Comprobación | Qué esperar |
|---|---|
| `cnt['total']` | ≈ tasa × tiempo (30000 en 10 s a 3 kHz) |
| `accepted == total` | sí, con un tren periódico |
| `livetime + deadtime == realtime` | exacto |
| El histograma | **un** fotopico, no ruido plano |

**Este paso no estaba en el recorrido original y es el que separa un dato de un
número.** Con un detector real, un espectro raro puede ser el detector, la
fuente, el umbral, la línea de base o el bitstream; con el generador, se sabe
qué tiene que salir, así que si no sale, el problema es del sistema de medición
y no de la física. Es el único punto del recorrido donde el usuario **tiene la
respuesta correcta de antemano**.

> **`bl_k` demasiado corto no da menos eventos: da CERO.** El seguidor de línea
> de base persigue el pulso y lo borra antes de que cruce el umbral. La regla es
> τ = 2^k muestras ≥ 100× la duración del pulso. Es el error que más se parece a
> "no hay señal" sin serlo.

---

## Fase B — Medir

Acá empieza el lazo que se repite, y acá es donde la GUI deja de ser una
comodidad y pasa a ser **el instrumento**.

### 6. Configurar la medición

**Antes:** escribir un script de personalización. Eso implicaba saber Python,
conocer el mapa de registros, y —lo caro— saber **cuáles de los 24 parámetros se
pueden tocar sin invalidar lo ya acumulado**. Ese conocimiento vivía en la
cabeza del autor y en la documentación, no en la herramienta.

**Ahora:** la pestaña **MCA** trae los 24 campos agrupados, con readback, y
**cada control marcado con lo que cuesta tocarlo**:

| Marca | Qué significa | Ejemplos |
|---|---|---|
| *(sin marca)* | se cambia con la medición corriendo | `thr`, `hyst`, ventana de amplitud |
| **·** | reinicia la cuenta en curso | `dec`, `channel`, `maxlen`, `tail_dly` |
| **··** | cambia el significado del eje: lo viejo se mezcla con lo nuevo | `sel_1d`, zoom, `amp_src`, `q_shift` |
| **⚠** | mal puesto deja el sistema **sin eventos** | `bl_k`, `bl_auto` |

El criterio es **avisar, no prohibir**: parar la adquisición un instante no es
un problema, esconder un control sí. Y los `··` llevan un botón de borrar al pie
de la pestaña, porque mezclar dos ejes en el mismo histograma no tiene sentido
físico y conviene resolverlo **en el momento en que se produce**, no al
analizar.

**Lo que esto cambia en el recorrido:** un conocimiento que antes se transmitía
por documentación —y por lo tanto se perdía— ahora está **en el punto de uso**.
El usuario no tiene que recordar que `bl_k` puede dejarlo sin eventos: el
control se lo dice mientras lo mira.

> **La interfaz se arma con lo que el hardware tiene, no con lo que se supone.**
> El cliente lee las capacidades al conectarse (bit `CAP_HIST_H_PSD` de `CAPS`,
> banderas `has_osc`, `has_mtrg`) y crea o no cada pestaña. Y el eje **no está
> hardcodeado**: sale del registro `WIDTHS`, que es la única fuente de verdad de
> la geometría. Por eso el mismo binario sirve para el bitstream de 8192 y para
> el de 16384, y por eso "no me aparece la pestaña del mapa 2D" no es un bug.

---

### 7. Arrancar

Un comando levanta las tres cosas —servidor en la placa, estímulo en el
generador, cliente en la PC:

```bash
make app
make app ESTIMULO=psd TASA=30000       # dos poblaciones: llena el mapa 2D
make app ESTIMULO=poisson TASA=30000   # arribos exponenciales, apilamiento realista
make app ESTIMULO=ninguno              # fuente real, no toca el generador
```

```
  servidor   : pitaya:1001
  estímulo   : pulsos a 3000 Hz, 0.6 Vpp por CH1
  cliente    : mcamon -> 10.73.28.27:1001
```

**Lo que estaba repartido en tres tareas del mapa original** —*correr el script
de medición* en la placa, *configurar* el generador, *conectar* el cliente— es
una sola, y las tres cosas quedan en un estado consistente o en ninguno.

---

### 8. Supervisar y diagnosticar — **el paso que antes no existía**

Este es el agregado más grande al recorrido, y el que vuelve obsoleto el riesgo
*Falta de feedback* que el mapa original ponía en el paso 4.

**El recorrido viejo era abierto:** se arrancaba el script, se esperaba, se
miraba el resultado. Si el umbral estaba mal, si `bl_k` se comía los pulsos, si
el apilamiento arruinaba el fotopico, **se descubría al final** — y la corrida
había que rehacerla entera. Con una fuente que decae y un detector que necesita
estabilizarse, rehacer una corrida no cuesta el tiempo de la corrida: cuesta el
tiempo de volver a las condiciones.

**El recorrido nuevo es cerrado.** Cuatro cosas de la GUI lo cierran:

**(a) El espectro creciendo en vivo.** Ver la forma antes de que la estadística
esté completa es lo que permite abortar a los 30 segundos en vez de a los 30
minutos.

**(b) La lista de picos, no un ajuste de región.** La pestaña del espectro **no
pide una región y ajusta una gaussiana ahí**: lista los picos que hay, con
canal, **FWHM**, resolución en %, cuentas en la cima y área neta. El cambio no
es de presentación: para ajustar una región había que saber **dónde** estaba el
pico, y en un espectro desconocido eso es justamente lo que no se sabe. La lista
contesta *qué hay*. Elegir una fila **centra el eje en ese pico**, y en el
gráfico cada pico lleva una barra horizontal a media altura que **es el FWHM
dibujado**: de un vistazo se ve si el número de la tabla corresponde al pico que
uno está mirando.

> Y el umbral de ruido está **calibrado, no elegido**: se exige que la
> prominencia supere 9.5 veces la fluctuación de conteo del fondo. Ese número
> sale de medir —sobre fondo plano la prominencia del ruido da mediana 0.8 σ,
> percentil 99 unos 5 σ y máximo entre 6 y 8.5 σ, porque el criterio se aplica
> al mayor de ~2000 máximos locales—. Con los 3 σ que uno escribiría, un
> espectro de puro ruido devolvía una docena de picos, todos falsos.

**(c) La pestaña OSC, que es el diagnóstico propiamente dicho.** Con el
histograma solo, un fotopico corrido puede ser el umbral, la línea de base, la
forma del pulso o el apilamiento, y **desde la GUI no hay forma de
distinguirlos**. La pestaña muestra las dos cosas que lo deciden, **atadas en el
tiempo**: arriba la ventana capturada alrededor del trigger en volts contra
microsegundos, con las capturas anteriores en gris (persistencia tipo fósforo,
que es lo que hace visible la dispersión de forma); abajo la tasa instantánea,
con **una marca vertical en el instante de cada captura**.

Leerlas juntas *es* el diagnóstico:

| Lo que se ve | Lo que es |
|---|---|
| tasa que salta + formas apiladas | apilamiento |
| formas limpias + tasa que cae | el umbral |

Y la curva de tasa lleva tres series. Las dos del MCA no cuestan **ninguna
lectura nueva** —ya venían en cada `status`, cada 200 ms, y antes se mostraban
como texto y se tiraban—. La tercera es la tasa de disparos del OSC, y **no es
la misma**: los dos caminos tienen tiempos muertos distintos, y **la distancia
entre las curvas *es* la pérdida del camino lento**. Eso es un número que antes
había que calcular después, offline, cruzando dos archivos.

**(d) La pestaña de mensajes.** Cada operación y cada error con hora. Es lo que
permite reconstruir qué pasó **cuando el síntoma llega tarde y desfigurado**,
que es como llegan casi todos los síntomas de hardware.

> **El costo de todo esto está acotado por diseño.** Un espectro son 64 KB que
> cuestan ~110 ms leídos palabra a palabra en la placa; por eso un hilo es dueño
> del socket y la GUI nunca lo toca —un refresco en el hilo de la interfaz la
> congelaría—. Y la captura de formas (hasta 16384 muestras por canal) **sólo se
> pide con la pestaña visible**: el modo continuo se detiene solo al cambiar de
> pestaña, mismo criterio que el mapa 2D.

---

## Fase C — Explotar

### 9. Guardar y exportar

**Antes:** el mapa original tenía *Copiar/Ejecutar comando* como tarea, con
*uso de línea de comandos en Linux* como detalle. El usuario tenía que saber
`scp` o `rsync`, y saber **dónde** el script había dejado los archivos.

**Ahora, dos caminos, y ninguno pide la terminal:**

**Desde la GUI**, botón de guardado en la pestaña del espectro. Lo que lo hace
barato no es el botón: es que **el cliente reusa el guardado de la placa tal
cual**. `MCARemote` hereda de `class MCA` y sólo redefine `r32`/`w32` y las
lecturas en bloque, así que la superficie `mca_*` entera funciona por red sin
tocar una línea. **Un archivo escrito desde la GUI es indistinguible de uno
escrito en la placa**, y `mca_load_file()` los relee igual. No hay dos formatos,
ni un conversor, ni una fuente de confusión sobre cuál es el bueno.

**Desde un comando**, cuando los datos son formas de onda y no un histograma:

```bash
make campana-adquirir-remoto DURACION=60 THR=0.2 OUT=datos/adq_prueba
```

Ese objetivo **corre en la placa y trae los datos a la PC al terminar**. Es el
colapso de dos pasos del mapa original —*arrancar la medición* y *exportar los
datos*— en uno.

> **El zoom viaja en la metadata, y eso es parte del guardado.** Hasta que
> `mca_get_config` lo releyó, un espectro guardado con zoom decía "8192 canales"
> sin decir **sobre qué ventana de amplitud**: su eje era irreconstruible. Un
> archivo cuyo eje no se puede reconstruir no es un dato, es una imagen de un
> dato. Los archivos anteriores a ese arreglo no lo traen y la GUI **avisa al
> abrirlos**.

---

### 10. Analizar

**Qué hace:** trabaja los datos en la PC, **sin la placa**, con la misma API.

```python
from API.osciloscope_store import load_chunk
arrays, meta = load_chunk('datos/adq_prueba/Data_.../chunk_000000.npz')
print(arrays['wave_V'].shape)      # ya convertido a volts
```

```bash
make analizar-estimadores     # compara los estimadores sobre pulsos reales
make graficar-formas          # catálogo de formas en volts vs microsegundos
make graficar-mca DIR=datos/mca_...   # regrafica una campaña entera sin placa
```

**Lo que abarata este paso es que el análisis no necesita hardware.** El riesgo
que el mapa original ponía acá —*tomar en cuenta nuevos datos*, *uso de
librerías*— se reduce porque los archivos llegan **con las unidades puestas**
(`wave_V` ya en volts, escala 8192 cuentas/V) y con su metadata, en vez de
llegar como enteros crudos que hay que saber interpretar. Y porque el
regraficado de una campaña ya medida es un objetivo del Makefile, no un
cuaderno que hay que reconstruir.

---

### 11. Cerrar la sesión y dejar trazabilidad

```bash
make app-off       # apaga el generador y para el servidor
```

**Cerrar la ventana NO cierra la medición, y es a propósito:** una medida larga
tiene que sobrevivir a que se cierre la GUI, y al reconectar el servidor informa
que la adquisición sigue corriendo. Separar "dejar de mirar" de "dejar de medir"
es una decisión, no un olvido.

**La trazabilidad es la parte que no se siente como un paso y se extraña a los
seis meses.** La release ata, en un solo `VERSION`: el número de paquete, el
commit, la rama, la fecha, y por bitstream su `md5`, su `VARIANTE` y su `PARTE`.
Un tag `mca-v0.1.0` es lo único que queda cuando alguien pregunta con qué
versión se midieron unos datos.

> Por eso `release-publicar` **rechaza un árbol sucio**: si hay cambios sin
> commitear, el tarball contiene código que ese commit no tiene, y el tag miente
> sobre qué hay adentro. Y por eso el prefijo `mca-v` no es cosmético — este
> repositorio es un **fork** de RedPitaya y ya trae los tags de ellos
> (`2.07-48`, `Release-Apr.2022`); sin prefijo, la numeración propia se mezcla
> con la de upstream y en un `git tag` no se distingue cuál es cuál.

---

### 12. Automatizar: los scripts de campaña

El paso que recorre **el que caracteriza**, y donde la API deja de ser una
biblioteca y pasa a ser la herramienta principal.

Una campaña de caracterización es, a mano, un recorrido entero por cada punto
medido: configurar, arrancar, esperar, leer, guardar, cambiar un parámetro,
repetir. Con 6 valores de `bl_k`, 4 anchos de pulso y varias tasas, el recorrido
de la Fase B se camina **decenas de veces** — y cada repetición es una
oportunidad de equivocarse en un parámetro y no enterarse.

```bash
make campana-campana OUT=datos/mca_...   # bl_k primero (el orden importa)
make campana-formas                      # INL vs familia de forma de pulso
make campana-deriva-remoto OUT=...       # tasa vs tiempo, corre allá
make campana-poisson                     # pérdidas del lector con arribos Poisson
```

**Lo que los scripts aportan, y que no es "ahorrar tecleo":**

| Aporte | Por qué importa |
|---|---|
| **El orden queda codificado** | `run_campana.py` corre `sweep_baseline_k` **primero**: la constante del seguidor depende de cuánto dura el pulso, y medirla después sería calibrar con un valor que ya se usó. El orden es física, y vive en el script |
| **El punto de trabajo se deriva, no se elige** | se toma `k_min + 2`, porque el mínimo es **el borde** donde el seguidor empieza a comerse el pulso, no un punto de trabajo |
| **Sin `input()`** | todo por argumentos, para poder correr como servicio o desde el Makefile |
| **Guarda por chunks, no todo al final** | un corte de luz cuesta el último chunk, no la corrida entera |
| **Escritura atómica** (`.tmp` + `rename`) | **nunca hay un `.npz` a medias**, aunque se corte la luz |
| **Ctrl-C corta limpio** | cierra el chunk en curso y escribe el resumen; no pierde más que lo que estaba en vuelo |
| **Corta sola si el disco baja de 200 MB** | y lo dice, en vez de morir escribiendo |
| **Re-arma por hardware** | `auto_rearm=True` + `trigger_shield` re-arman en ~24 ns, contra los ~65 µs de piso del `rp_AcqStop`/`rp_AcqStart` por evento |
| **Tabla de progreso cada medio segundo** | evento, tasa, descartes, chunks, cola libre — el mismo lazo de realimentación de la GUI, en la terminal |

Esa última tabla merece su propia lectura, porque es el equivalente en consola
de la pestaña OSC:

| Columna | Qué mirar |
|---|---|
| Tasa | tiene que seguir al generador |
| Descartes | si sube, el lector no da abasto (*backpressure*) |
| Cola libre | si llega a cero, el escritor a disco es el cuello de botella |

**Y el `--fake`**, que es la versión del paso 0 para los scripts: `run_acquire.py
--duration 30 --fake` recorre el flujo entero sin hardware. El mismo principio
—equivocarse donde es gratis— aplicado al camino automatizado.

> **La validación cruzada que cierra el círculo.** `campana-e2e` corre los dos
> caminos sobre **el mismo estímulo y al mismo tiempo**: el pipeline de
> adquisición guarda las formas y de ahí sale un histograma calculado por
> software; el MCA histogramea en la FPGA. Si coinciden, el camino de datos está
> bien de punta a punta. Pero hay que comparar **centroide y ancho, NO áreas**:
> el pipeline de software arrastra ~683 µs de tiempo muerto por evento (leer
> 1024 muestras por el bus) mientras el MCA vive en los microsegundos, así que ve
> muchísimos más eventos. Las **cuentas** no tienen por qué parecerse; la
> **forma** sí.

---

## Transversal — cuando algo no anda

No es un paso del recorrido: es una rama que sale de cualquiera de ellos, y el
mapa debería dibujarla como tal. Siempre empieza igual:

```bash
make placa-estado
```

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `esto necesita la Red Pitaya` | se pidió un objetivo `(P)` desde la PC | usar el `-remoto`; el mensaje dice cuál |
| `es la GUI, y necesita PyQt5` | falta el paquete en la PC | `sudo apt install python3-pyqt5 python3-matplotlib` |
| `ssh pitaya` no responde | la IP cambió | actualizar `HostName` |
| `Ocupado: ya hay un cliente` | otra GUI o un proceso colgado | `make app-servidor-off-remoto` |
| `PermissionError` en el bind | puerto < 1024 sin root | `PUERTO=5001` (ya es el default en la PC) |
| El proceso muere **sin traceback** | SIGBUS: la PL sin programar, u otro proceso en `/dev/mem` | reiniciar la placa |
| `MCANotPresent` al abrir | está el bitstream del scope: el slot 7 es un stub | cargar el del MCA |
| 0 eventos con señal buena | `bl_k` corto: el seguidor se come el pulso | subirlo |
| Números plausibles sin relación con lo pedido | bitstream viejo | verificar (§4) |

**La observación de diseño:** casi todos estos mensajes **nombran la acción
correctiva**. Un error que dice "esto necesita la Red Pitaya, usá
`verificar-placa-remoto`" cuesta diez segundos; el mismo error como un traceback
de Python cuesta una búsqueda en la documentación, y eso —repetido— es la mitad
del costo real de usar una herramienta nueva.

---

## El antes y el ahora, en una tabla

Para redibujar el mapa, esto es lo que cambió de carril:

| Paso del mapa original | Antes costaba | Hoy | Qué lo movió |
|---|---|---|---|
| Obtener herramientas | descargar 303 MB, compilar, saber Git | `curl` + `tar`, 1.3 MB, **sin Git** | la **release** |
| Cargar a la SD / flashear | software de flasheo, conocimiento especializado | `sudo ./instalar.sh --cargar` | el **instalador** (elige el bitstream por EEPROM) |
| Conexión a la placa | IP, proxy, obtener la IP del dispositivo | un alias ssh, un campo | la **convención `pitaya`** |
| *(no existía)* | — | **verificar que la PL es la que se cree** | `placa-cargar-remoto` + `verificar-placa-*` |
| Personalizar la adquisición | escribir un script, saber el register map | pestaña MCA, 24 campos con readback y marcas | la **GUI** |
| Correr script de medición | línea de comandos, un script por caso | `make app` / `campana-*` | **Makefile + API** |
| *(no existía)* | — | **supervisar y diagnosticar en vivo** | la **GUI** (espectro, picos, OSC, mensajes) |
| Copiar/ejecutar comando | `scp`, saber dónde quedaron los archivos | botón de guardar, o `-remoto` que los trae | **GUI + Makefile** |
| Trabajar los datos | librerías, interpretar enteros crudos | `.npz` con unidades y metadata, `graficar-*` | la **API** |

Y los riesgos del mapa original, uno por uno:

| Riesgo original | Estado |
|---|---|
| *Software muy pesado* | **resuelto** — 1.3 MB |
| *Uso de Git* | **resuelto** para el que mide; sigue para el que desarrolla |
| *Falta de feedback* | **resuelto** — es el aporte central de la GUI (§8) |
| *Tomar en cuenta nuevos datos* | **mitigado** — unidades y metadata en el archivo |
| *(nuevo)* **Bitstream viejo midiendo plausible** | mitigado por verificación obligatoria (§4) |
| *(nuevo)* **Dos procesos sobre `/dev/mem`** | mitigado por `placa-estado` y el servidor de un cliente |
| *(nuevo)* **Bitstream de otro Zynq** | mitigado por comparación antes de escribir |

Los tres riesgos nuevos no aparecieron: **estaban y no se veían**. Un mapa de
recorrido honesto los dibuja, porque son los que cuestan una sesión entera y los
que no tienen mensaje de error propio.

---

## Ver también

[`puesta_en_marcha.md`](puesta_en_marcha.md), el paso a paso con los comandos ·
[`publicar_release.md`](publicar_release.md), el paquete y por qué existe ·
[`APP/README.md`](APP/README.md), la aplicación en detalle ·
[`API/guia_de_uso.md`](API/guia_de_uso.md), las recetas por tema ·
[`mca/sesion_placa_deriva.md`](mca/sesion_placa_deriva.md), un recorrido real de
campaña, de punta a punta
