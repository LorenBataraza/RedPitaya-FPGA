# Publicar una release

**Código:** [`software/Makefile`](../software/Makefile) (objetivos `release-*`) ·
[`software/release/instalar.sh`](../software/release/instalar.sh)
**Versión:** [`prj/MCA/VERSION`](../VERSION), a mano
**Puesta en marcha del sistema:** [`puesta_en_marcha.md`](puesta_en_marcha.md)

Cómo se arma el paquete instalable y cómo se sube a GitHub. Cada paso dice el
comando, qué tiene que salir, y qué significa si sale otra cosa.

---

## Por qué existe el paquete

El repositorio son **303 MB de clone y 5332 ficheros**: RTL, netlists,
checkpoints de Vivado, IP de Xilinx. Lo que hace falta para *medir* son 1.3 MB.
Quien sólo quiere usar el sistema no tiene por qué bajar el resto.

Pero el argumento fuerte es otro. `mca_top.sv` **ignora en silencio las
escrituras a direcciones que no mapea**, así que un software nuevo contra un
bitstream viejo no falla: mide, y los números son plausibles. La release
garantiza que el `.bit.bin` y el Python que sabe hablarle **salieron del mismo
commit y viajan en el mismo tarball**. Esa es la razón de que exista, y por eso
el bitstream no es opcional en el paquete.

### Las tres vías, y cuándo usar cada una

| Vía | Para quién | Cuánto baja |
|---|---|---|
| **Release** | usar el sistema, sin tocar el código | **1.3 MB** |
| **Clon parcial** | desarrollar *en* la placa, con git y `pull` | 7.5 MB |
| **Clone completo** | trabajar el RTL, sintetizar con Vivado | 303 MB |

El clon parcial, para tenerlo a mano:

```bash
git clone --depth 1 --filter=blob:none --sparse \
    -b multitrigger https://github.com/LorenBataraza/RedPitaya-FPGA.git
cd RedPitaya-FPGA
git sparse-checkout set --no-cone \
    '/prj/MCA/software/**' '/prj/MCA/docs/**' '/prj/MCA/out/mca_red_pitaya.bit.bin'
```

Las tres banderas hacen cosas distintas y las tres importan: `--depth 1` corta
la historia, `--filter=blob:none` evita descargar el contenido de los ficheros
que no vas a materializar, y `--sparse` decide cuáles se materializan. **Sin la
segunda, el filtro de rutas no ahorra descarga**, sólo espacio en disco.

---

## 1 · La versión

Se edita a mano en [`prj/MCA/VERSION`](../VERSION). Una línea:

```
0.1.0
```

De ahí salen el nombre del paquete (`mca-0.1.0.tar.gz`) y el tag
(`mca-v0.1.0`).

> **El prefijo `mca-v` no es cosmético.** Este repositorio es un **fork** de
> RedPitaya y ya trae los tags de ellos: `2.07-48`, `2.00-35`,
> `Release-Apr.2022`. Sin prefijo, la numeración propia se mezcla con la de
> upstream y en un `git tag` no se distingue cuál es cuál. Con prefijo,
> `git tag -l 'mca-v*'` lista exactamente las nuestras.

Criterio para el número, que es el habitual: el tercero para arreglos que no
cambian nada del contrato, el segundo cuando se agregan registros u
operaciones, **el primero cuando cambia el bitstream de forma que el software
viejo ya no sirve** — que es el caso interesante acá.

---

## 2 · Armar el paquete

```console
$ cd prj/MCA/software
$ make release

  /home/…/software/dist/mca-0.1.0.tar.gz   1.3M
  /home/…/software/dist/SHA256SUMS
  /home/…/software/dist/NOTAS.md            (editables antes de publicar)
```

Lo que hay adentro:

```
mca-0.1.0/
  instalar.sh              POSIX sh, sin dependencias
  LEEME.md                 instalación, primer arranque, reglas de la placa
  VERSION                  paquete, commit, rama, fecha, md5 y PARTE del bitstream
  MANIFIESTO.sha256        checksum de cada fichero
  out/mca_red_pitaya.bit.bin
  software/                API/ app/ mca/ campanas/ monte-carlo/ + tests + Makefile
```

> **El campo `parte` no es decorativo.** Dice para qué Zynq se compiló el
> bitstream (`7z010clg400`) y es lo que impide cargarlo en una placa que lleva
> otro. Cargar un bitstream de otro Zynq **no falla y ya**: deja el FPGA manager
> trabado y toda programación posterior falla —incluida la de fábrica— hasta
> reiniciar. `make release` lo lee de la cabecera del `.bit`, porque el
> `.bit.bin` que se carga **no la tiene**: `bootgen` se la quita. Por eso el dato
> tiene que viajar en el paquete; en la placa ya no hay de dónde sacarlo.

**El layout copia el del repositorio a propósito.** Instalado en `/opt/mca`, el
`BIT_LOCAL ?= $(RAIZ)/../out/…` del Makefile resuelve solo, y
`make -C /opt/mca/software verificar-placa` anda sin argumentos.

**Si falta el bitstream** el objetivo se planta antes de armar nada:

```
ERROR: no existe …/out/mca_red_pitaya.bit.bin.
       un paquete sin bitstream no sirve para nada: es justo lo que
       no se puede reconstruir del otro lado. Corré la síntesis.
```

**Si el árbol tiene cambios sin commitear** avisa y sigue: el paquete queda
marcado `<sha>-sucio` en su `VERSION` y sirve para probar acá, pero
`release-publicar` lo va a rechazar.

### Por qué el payload sale del árbol de trabajo

No de `git archive`, por dos cosas que git no tiene: el **bitstream no está
versionado**, y `API/tests/datos_ref/` guarda el `compat_golden.npz` que el
`.gitignore` excluye por patrón. Las exclusiones del `rsync` van **por
categoría** —medidas, salidas de simulación, caches, cuadernos— así que un
fichero nuevo queda incluido por estar donde va, sin tocar esa lista.

---

## 3 · Probarlo antes de publicar

```console
$ make release-verificar

== manifiesto ==
  113 ficheros, ok

== la suite offline, en el paquete ==
87 passed …  33 passed …  14 passed
OK: suite offline (sin Monte-Carlo)

== el instalador ==
  sintaxis ok
  --help ok

OK: el paquete se sostiene solo.
```

Esto **desempaqueta el tarball** en un temporal y corre la suite desde el árbol
desempaquetado, no desde el repo. Es la diferencia que importa: un fichero que
se cayó en las exclusiones del `rsync` se ve exactamente acá y en ningún otro
lado. Si falla la colección de pytest, lo primero a mirar es `testpaths` de
`pyproject.toml` — nombra directorios que tienen que viajar en el paquete.

Y contra la placa, que es la prueba de verdad:

```bash
make release-instalar-remoto              # copia e instala, SIN tocar la PL
ssh pitaya 'sudo /opt/mca/instalar.sh --cargar'
ssh pitaya 'python3 /opt/mca/software/campanas/preparar_placa.py'
```

Tres variables lo redirigen sin editar nada: `PITAYA` (a dónde), `PREFIJO`
(dónde instalar) y `DESCARGA` (dónde deja el tarball mientras tanto). Para una
instalación de usuario, en otra placa:

```bash
make release-instalar-remoto PITAYA=lorenzo@10.73.28.45 \
     PREFIJO=/home/lorenzo/mca DESCARGA=/home/lorenzo
```

> **El `sudo` lo decide el prefijo, y no se pide siempre.** Bajo `/home` no se
> usa: instalar el árbol con sudo en la casa del usuario lo deja perteneciendo a
> root, y después ese usuario no puede ni actualizarlo ni borrarlo. Fuera del
> home sí hace falta. Sin sudo, la copia del bitstream a
> `/root/mca_red_pitaya.bit.bin` no se puede hacer y el instalador lo avisa: el
> bitstream queda igual en `$PREFIJO/out/` y hay que pasarlo con `--bitstream`.

El último tiene que contestar los 8192 canales y los registros nuevos
reteniendo lo escrito. Si contesta 16384, la PL no se reprogramó con el
bitstream del paquete.

Y si la placa es de otro modelo, el segundo comando **no programa nada** y lo
dice:

```
NO se programó la PL: este bitstream es para 7z010clg400 y la placa es una
z20_125_4ch, que lleva un 7z020. Programarla dejaría el FPGA manager trabado
hasta reiniciar.

  La PL quedó COMO ESTABA — no se escribió nada.
```

El resto del paquete queda instalado y sirve igual: el driver, el servidor en
modo `--fake`, las campañas sobre datos ya medidos y los tests.

---

## 4 · Publicar

```bash
make release-publicar                     # muestra qué haría, NO publica
make release-publicar CONFIRMAR=si        # publica de verdad
```

Sin `CONFIRMAR=si` no sube nada: imprime el repo, el tag, los adjuntos y el
fichero de notas, y sale. **Publicar es irreversible en la práctica** —alguien
puede bajar el tarball entre que se sube y se borra— así que la confirmación va
en la línea de comandos y no por stdin, para que siga sirviendo desde un
script.

Con `CONFIRMAR=si`, en orden:

1. `git tag -a mca-v0.1.0 -m "MCA 0.1.0 — bitstream + software"`
2. `git push origin mca-v0.1.0`
3. `gh release create mca-v0.1.0 --repo … --notes-file dist/NOTAS.md` con el
   `.tar.gz` y el `SHA256SUMS` adjuntos

### Las cuatro guardas, y qué significan

| Se planta con | Qué pasó | Qué hacer |
|---|---|---|
| `falta gh` | no está el CLI de GitHub | instalarlo, o [publicar a mano](#5--publicar-a-mano) |
| `gh no está autenticado` | falta el token | `gh auth login` |
| `hay cambios sin commitear` | el árbol está sucio | commitear primero — ver abajo |
| `el tag mca-v0.1.0 ya existe` | esa versión ya se publicó | subir el número en `VERSION` |

> **Por qué se rechaza un árbol sucio.** Una release apunta a un commit. Si hay
> cambios sin commitear, el tarball contiene código que ese commit no tiene, y
> el tag miente sobre qué hay adentro. Dentro de seis meses, cuando alguien
> quiera reconstruir qué versión midió unos datos, el tag es lo único que queda.

### `--repo` explícito, y por qué

Hay **dos remotos**: `origin` (el fork) y `upstream` (RedPitaya). `gh` elige el
repositorio mirando los remotos, y publicar contra el equivocado no es un error
que se quiera descubrir después. Por eso el objetivo pasa `--repo` a mano; si
cambiás de fork, se sobreescribe:

```bash
make release-publicar CONFIRMAR=si GH_REPO=otro/repo
```

### Las notas

`make release` regenera `dist/NOTAS.md` en cada corrida, con las tres líneas de
instalación y los requisitos. Si las editás, **publicá antes de volver a armar**
o pasá las tuyas:

```bash
make release-publicar CONFIRMAR=si NOTAS=mis_notas.md
```

---

## 5 · Publicar a mano

Si no hay `gh`, es lo mismo en tres pasos:

```bash
cd prj/MCA/software && make release        # el tarball igual sale de acá
git tag -a mca-v0.1.0 -m "MCA 0.1.0 — bitstream + software"
git push origin mca-v0.1.0
```

Y después, en la web: **Releases → Draft a new release**, elegir el tag
`mca-v0.1.0` que acabás de empujar (no crear uno nuevo desde ahí), pegar el
contenido de `dist/NOTAS.md`, y adjuntar los **dos** ficheros —
`mca-0.1.0.tar.gz` y `SHA256SUMS`.

Adjuntar el `SHA256SUMS` no es ceremonia: es lo que le permite a quien la baja
distinguir una descarga truncada de un bitstream corrupto, que si no se
manifiesta como una PL programada con basura.

---

## 6 · Del otro lado

Lo que corre quien la baja, en la Pitaya:

```bash
curl -LO https://github.com/LorenBataraza/RedPitaya-FPGA/releases/download/mca-v0.1.0/mca-0.1.0.tar.gz
curl -LO https://github.com/LorenBataraza/RedPitaya-FPGA/releases/download/mca-v0.1.0/SHA256SUMS
sha256sum -c SHA256SUMS
tar xzf mca-0.1.0.tar.gz && cd mca-0.1.0
sudo ./instalar.sh --cargar
```

El instalador, antes de copiar un solo fichero: verifica el manifiesto,
comprueba que esto sea una Red Pitaya, y que estén `python3` y `numpy`
(`matplotlib` y `pytest` los reporta como opcionales). Después reemplaza el
árbol **entero** conservando `datos/`, y copia el bitstream a
`/root/mca_red_pitaya.bit.bin`, que es donde los defaults lo buscan.

**Sin `--cargar` no toca la PL.** Reprogramar la FPGA corta el bus AXI y no
puede pasar como efecto secundario de instalar unos ficheros: si hay una
medición corriendo, se pierde.

Para desinstalar:

```bash
sudo /opt/mca/instalar.sh --desinstalar --confirmar
```

---

## 7 · Si hay que retirar una release

```bash
gh release delete mca-v0.1.0 --repo LorenBataraza/RedPitaya-FPGA
git push --delete origin mca-v0.1.0
```

**Pero pensalo dos veces.** Entre que se publicó y ahora, alguien puede haberla
bajado e instalado, y ese alguien va a tener una placa corriendo una versión
que ya no existe en ningún lado — imposible de reconstruir y de diagnosticar.

La salida correcta casi siempre es **publicar `0.1.1`**, no reescribir `0.1.0`.
Borrar se justifica en la ventana de minutos posterior a publicar algo roto, y
en poco más.

---

## Lista de control

Antes de `make release-publicar CONFIRMAR=si`:

1. `prj/MCA/VERSION` subido, y el tag que sale de ahí todavía no existe.
2. El árbol está limpio y **pusheado**: el tag no sirve si el commit no está en
   el remoto.
3. `make release-verificar` pasa — la suite corre **dentro** del paquete.
4. El bitstream del paquete es el que querés publicar: `md5` en el `VERSION` de
   adentro del tarball, y `preparar_placa.py` verde en la placa contra él.
5. `dist/NOTAS.md` dice lo que tiene que decir.

---

## Ver también

[`puesta_en_marcha.md`](puesta_en_marcha.md), el paso a paso del sistema ·
[`APP/README.md`](APP/README.md), la aplicación ·
[`../software/README.md`](../software/README.md), el mapa del árbol
