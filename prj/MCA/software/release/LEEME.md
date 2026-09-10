# MCA para Red Pitaya — paquete instalable

Un analizador multicanal (MCA) implementado en la PL de una Red Pitaya
STEMlab 125-14, con su driver de Python, un servidor de red y una aplicación
de escritorio que muestra el espectro creciendo en vivo.

Este paquete trae **el bitstream y el software que van juntos**. La versión
exacta y el commit del que salieron están en [`VERSION`](VERSION).

---

## Qué hay acá adentro

```
out/mca_red_pitaya.bit.bin   el bitstream de la PL
software/                    el driver, el servidor, las campañas y los tests
instalar.sh                  el instalador
MANIFIESTO.sha256            checksum de cada fichero
```

---

## Instalación

En la Pitaya, por ssh:

```bash
tar xzf mca-*.tar.gz
cd mca-*/
sudo ./instalar.sh --cargar
```

`--cargar` además **programa la PL** y comprueba que los registros del MCA
respondan. Sin esa bandera el instalador no toca la FPGA: copia el software y
deja la placa como estaba, que es lo que querés si hay una medición corriendo.

El árbol queda en `/opt/mca` (cambialo con `--prefijo`), y una copia del
bitstream en `/root/mca_red_pitaya.bit.bin`, que es donde el software lo busca
por defecto.

**Requisitos:** Red Pitaya OS 2.00 o posterior, `python3` y `numpy`. El
instalador los verifica antes de copiar nada. `matplotlib` y `pytest` son
opcionales y sólo hacen falta para graficar o correr los tests *en la placa*.

Para desinstalar:

```bash
sudo /opt/mca/instalar.sh --desinstalar --confirmar
```

---

## Primer arranque

**1 · ¿Está la PL programada con lo que creo?**

```bash
python3 /opt/mca/software/campanas/preparar_placa.py
```

Contesta las tres cosas que hay que saber antes de gastar una sesión de
laboratorio: si el bitstream cargado es éste, si el eje tiene los canales que
corresponden, y si los registros retienen lo que se les escribe. Un bitstream
viejo **ignora en silencio** las escrituras a direcciones que no mapea, así que
una campaña puede salir entera y con números plausibles sin relación con lo que
se pidió. Esta comprobación es lo que evita eso.

**2 · El servidor, en la placa:**

```bash
sudo python3 /opt/mca/software/app/mca_server.py --port 1001
```

Un solo proceso puede tener `/dev/mem` abierto. Si hay un kernel de Jupyter
vivo que hizo `rp_Init()`, los dos pelean y sale SIGBUS: cerralo antes.

**3 · La aplicación, en la PC:**

La GUI es PyQt5 y **no corre en la placa**: necesita el árbol `software/` en tu
máquina y `pip install PyQt5 matplotlib numpy`.

```bash
python3 app/mcamon.py --host <ip-de-la-pitaya> --port 1001
```

---

## Medir sin la GUI

Todo lo que hace la aplicación se puede hacer desde Python, en la placa o por
red — la clase remota **es** un `MCA`, así que la misma API funciona de los dos
lados:

```python
from API.mca import MCA, mca_set_thr, mca_read_histogram

h = MCA()                       # en la placa
mca_set_thr(h, 317)
hist = mca_read_histogram(h)    # uint32[2^h_aw]
```

```python
from API.mca import mca_set_thr, mca_read_histogram
from API.mca_remote import MCARemote

h = MCARemote.connect('10.73.28.27')   # desde la PC, mismas funciones
```

La geometría del eje **se lee del hardware** (registro `WIDTHS`), nunca se
supone: no hardcodees 8192 ni 16384.

---

## Reglas de la placa

Valen para cualquier código que escribas contra esta API, y el software las
respeta:

1. **Un solo proceso sobre `/dev/mem`.** El servidor acepta un cliente a la vez
   y rechaza el segundo con un error explícito.
2. **Lectura palabra a palabra.** Un slice o un `np.frombuffer` sobre el mapeo
   **reinicia la placa**. No toques `MCA._read_words`.
3. **Escritura por asignación de slice**, nunca `struct.pack_into`.
4. **El bitstream antes que los mapeos.** Reprogramar la PL con handles
   abiertos deja el puerto GP0 trabado y hay que reiniciar la placa.

---

## Documentación

El paquete trae sólo el software. La documentación completa —puesta en marcha
paso a paso, mapa de registros, arquitectura del RTL, protocolo de red— está en
el repositorio, en `prj/MCA/docs/`:

<https://github.com/LorenBataraza/RedPitaya-FPGA/tree/multitrigger/prj/MCA/docs>

Empezá por `puesta_en_marcha.md`.
