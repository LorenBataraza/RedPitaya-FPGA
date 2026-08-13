# Sacar los datos por red en vez de por la SD

## El problema con la SD, en concreto

La expectativa de "SD clase 10 → 100 MB/s" no se cumple, por dos razones
independientes:

1. **La clase de velocidad SD garantiza un mínimo secuencial de escritura de
   10 MB/s.** Los "100 MB/s" del rótulo son el pico de *lectura* del bus UHS-I.
   La escritura sostenida de una tarjeta común está en 10-30 MB/s y cae más
   cuando se agota el caché SLC interno.
2. **El controlador manda sobre la tarjeta.** El SDIO del Zynq-7000 en la Red
   Pitaya corre en modo 4 bits; con reloj de 50 MHz el techo de bus son ~25 MB/s,
   y el throughput real de filesystem típicamente 10-20 MB/s. Poner una tarjeta
   más rápida no mueve la aguja: el cuello está aguas arriba de la tarjeta.

Los 12.4 MB/s medidos de `savez` son sospechosamente parecidos a ese techo.
**Antes de tocar el formato de archivo, correr el diagnóstico**: repetir el
benchmark escribiendo a `/dev/shm` (tmpfs, o sea RAM). Si salta a >100 MB/s, el
formato no es el cuello y cambiarlo no compra nada; si se queda en ~12, entonces
sí el cuello es `savez`.

Por GbE el Zynq 7010 da **~90-110 MB/s reales con TCP**, o sea 5-8× la SD. Con la
ventana default (144 B/evento) eso son ~700 kev/s de techo de transporte: la red
deja de ser el límite.

## Corrección sobre "por si falla la transferencia de paquetes"

TCP ya garantiza entrega o error: la pérdida de paquetes se retransmite sola y no
se ve desde la aplicación. Contra lo que hay que protegerse no es contra paquetes
perdidos sino contra que **el servidor o el enlace se caigan** durante una
corrida. Eso cambia dónde conviene poner la red de contención.

Y la primera línea de contención **ya es el ring de DDR**: con 32 MB reservados y
144 B/evento son ~230 k eventos, es decir **~2.3 s a 100 kev/s**. Una caída de red
más corta que eso no cuesta ni un evento y no toca el disco. El ring y la
robustez ante fallas de red terminan siendo el mismo mecanismo.

## Opciones, y cuál conviene

| | throughput | costo de CPU | complejidad | veredicto |
|---|---|---|---|---|
| **NFS** | ~60-90 MB/s | bajo | monta y listo | **recomendado** |
| socket TCP crudo + daemon en la PC | ~100 MB/s | el más bajo | hay que escribir el daemon | si NFS no alcanza |
| SMB/CIFS | ~40-60 MB/s | medio | media | sin motivo entre dos Linux |
| SSHFS | ~20-40 MB/s | **alto** (AES por software) | baja | **evitar**: se come la CPU que necesita el lector |
| iSCSI / NBD | alto | medio | alta | overkill |

El A9 del 7010 no tiene aceleración de AES, así que SSHFS quema CPU que hace
falta para el lazo de adquisición. Si hace falta cifrar, conviene hacerlo en la
PC sobre el archivo ya recibido, no en vuelo.

## NFS: cómo montarlo

**En la PC** (`/etc/exports`):

```
/datos/pitaya  192.168.1.0/24(rw,async,no_subtree_check,no_root_squash)
```

`async` es lo que más mueve el throughput: el servidor confirma la escritura sin
esperar a que baje a disco. El riesgo es perder lo que estaba en vuelo si la PC
se cae de golpe — aceptable acá, porque la fuente de verdad durante la corrida es
el ring de DDR, no el archivo a medio escribir.

**En la Pitaya**:

```bash
mount -t nfs -o \
  nfsvers=4.1,proto=tcp,wsize=1048576,rsize=1048576,noatime,soft,timeo=50,retrans=2 \
  192.168.1.100:/datos/pitaya /mnt/datos
```

Las opciones que importan:

- `wsize=1048576` — escrituras de 1 MB. Con el default (a veces 32-64 KB) se
  pierde la mitad del ancho de banda en round-trips.
- `noatime` — sin esto, cada escritura arrastra una actualización de metadatos.
- **`soft,timeo=50,retrans=2` en vez de `hard`** — es la decisión menos obvia y
  la más importante. Con `hard` (el default y lo que normalmente se recomienda),
  si el servidor desaparece el `write()` **bloquea para siempre** y el hilo
  escritor queda colgado; en una adquisición eso es fatal. Con `soft`, `write()`
  devuelve `EIO` a los ~10 s y la aplicación puede pasar al respaldo local. Se
  cambia "integridad silenciosa" por "error visible y manejable", que para este
  caso es el trade correcto.

## Cómo escribir, del lado de la aplicación

Tres reglas, en orden de impacto:

1. **Nunca escribir desde el hilo lector.** Ya está resuelto en la estructura
   actual (`mca/reader.py` produce batches, `mca/storage.py` los escribe): el
   jitter de la red no puede propagarse hacia atrás y frenar la captura. Al pasar
   a NFS, mantener esa separación es más importante todavía, porque la varianza
   de latencia de una escritura de red es mucho mayor que la de la SD.
2. **Pocos archivos grandes, no muchos chicos.** Cada archivo nuevo sobre NFS
   cuesta round-trips de metadatos (CREATE, SETATTR, COMMIT). Un archivo por
   batch mata el throughput; conviene uno por bloque de N segundos, en modo
   append.
3. **Escribir binario plano, no `savez`.** El slot ya viene en un formato binario
   fijo desde el RTL (cabecera de 32 B + muestras int16 + footer): el camino más
   rápido es volcar los slots tal cual y guardar la geometría en un `.json` al
   lado. Se ahorra la serialización de numpy y la copia intermedia. Pero **esto
   sólo vale la pena si el diagnóstico de `/dev/shm` mostró que `savez` era el
   cuello** — si el cuello era la SD, cambiar de medio ya resolvió el problema.

## Patrón recomendado: red primaria, local como contención

```
ring DDR (32 MB, ~2.3 s a 100 kev/s)
    │
    ├─► escritor  ──► /mnt/datos (NFS)        camino primario
    │                     │
    │                  EIO / timeout
    │                     ▼
    └────────────► /root/spill/*.bin (SD)     sólo cuando la red falla
```

El archivo local **no** tiene que llevar todo: existe nada más para cubrir el
hueco entre que la red se cae y el ring se llena. A 15 MB/s de SD absorbe
~100 kev/s de la ventana default, que es del orden de la tasa objetivo.

Al reconectar, un proceso aparte sube los `spill` a la PC. Conviene un `sha256`
por archivo para poder verificar la transferencia sin depender de que nadie se
haya equivocado con los cortes.

## Presupuesto de DDR

Sumar la salida por red no compromete el ring: leer del ring (72 MB/s a 500 kev/s)
más copiar hacia los buffers del NIC es del orden del **7 % del ancho útil de la
DDR** (~1.4 GB/s reales sobre un bus de 16 bits). El cuello sigue estando en la
red y en la CPU, no en la memoria.
