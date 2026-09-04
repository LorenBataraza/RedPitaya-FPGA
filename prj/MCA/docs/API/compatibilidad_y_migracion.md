# Compatibilidad y migración

Cómo se movió el código sin romper nada, cómo se **verifica** que no se rompió, y
qué falta para retirar la capa de compatibilidad.

---

## 1. Los shims

Los ficheros viejos siguen en `software/` y reexportan desde `API/`. Nadie tuvo
que editar sus imports.

| Shim | Reexporta de | Líneas |
|---|---|---|
| [`mca_utils.py`](../../software/mca_utils.py) | `API.mca` + `API.analisis` | 42 |
| [`multitrigger_utils.py`](../../software/multitrigger_utils.py) | `API.osciloscope` + `API.multitrigger` + `API.fpga` | 93 |
| [`rigol_dg4162.py`](../../software/rigol_dg4162.py) | `API.rigol_dg4162` | 29 |
| [`mca/`](../../software/mca/) | `API.osciloscope_store` (paquete + 7 submódulos) | 127 |

```python
import mca_utils as mu          # sigue funcionando igual
mu.MCA.open(); mu.gauss_fit_peak(...); mu.R_THR
```

**Sin `DeprecationWarning` a propósito**: saltaría en cada corrida en la Pitaya y
sería ruido en la salida de las campañas. La nota de deprecación está en el
docstring de cada shim.

### `MultiTriggerScope` vive en el shim

La clase compone un `Osciloscope` y un `MultiTrigger` **sobre el mismo mapeo** y
delega. Está en `multitrigger_utils.py` y no en `API/` porque es una clase de
compatibilidad, no de la API nueva. Sus métodos se listan explícitamente en vez
de heredarlos todos, para que la superficie que el shim garantiza esté escrita y
no implícita en un MRO.

### Cuatro cosas que hacen falta y no son obvias

Un shim de verdad total necesita más que un `from X import *`:

1. **Los submódulos del paquete.** `from mca.storage import ...` no funciona si
   el shim sólo reexporta en el `__init__`. Hay siete ficheros en `mca/` por eso.
2. **Los nombres privados que otros usan.** `import *` no exporta nada que
   empiece por guion bajo, y `monte-carlo/pileup.py` importa `_fwhm_pts` de
   rigol, más tres tests que llaman `rg._fwhm_pts`. Van importados a mano.
3. **Los imports incidentales.** El módulo original hacía `import ctypes` y
   `_fb_to_np` lo usaba; al trocear el fichero el import se quedó atrás.
4. **Mover un fichero sin dejar shim.** `rigol_dg4162.py` se movió a `API/` y
   rompió todo `import rigol_dg4162 as rg` hasta que se puso el suyo.

Los cuatro pasaron de verdad durante el refactor. Los cuatro los detecta hoy el
test.

---

## 2. El test de compatibilidad

[`API/tests/test_compat_api.py`](../../software/API/tests/test_compat_api.py) compara el
árbol actual contra un **baseline congelado antes de mover nada**
(`API/tests/datos_ref/compat_baseline.json` + `API/tests/datos_ref/compat_golden.npz`, producidos por
[`API/tests/gen_compat_baseline.py`](../../software/API/tests/gen_compat_baseline.py)).

**Corre entero en la PC, sin placa.** Ése es el requisito de diseño: un test de
compatibilidad que necesita la Pitaya no se corre, y si no se corre no sirve.

```bash
cd prj/MCA/software
python API/tests/test_compat_api.py
```

```
A. superficie   4 módulos
B. constantes   79 valores
C. trazas       11 secuencias de registros
D. análisis     125 claves numéricas
E. guardado     round-trip csv/npz/json

OK: 1142 comprobaciones, sin diferencias con el baseline
```

| Bloque | Qué comprueba |
|---|---|
| **A. superficie** | cada nombre público sigue existiendo, con el mismo tipo y la misma firma; los métodos se buscan por el MRO, que es lo que hace un call site; los submódulos siguen importables; los privados que otros usan siguen ahí |
| **B. constantes** | cada `R_*`, `BIT_*`, base y apertura vale **exactamente** lo mismo |
| **C. trazas** | las secuencias de escritura de registros son idénticas, **en orden** |
| **D. análisis** | los helpers puros dan el mismo número, y los que lanzaban siguen lanzando el mismo error |
| **E. guardado** | round-trip csv/npz/json de la capa nueva |

### Cómo funciona sin hardware

Dos piezas:

- **`stub_rp()`** instala un módulo `rp` falso si el de verdad no está.
- **`FakeMmap`**, un `bytearray` que **registra cada escritura de 32 bits en
  orden**. Los drivers reciben el mmap en `__init__`, así que basta construir el
  objeto con esta instancia — no hay que parchear `open()`.

```python
m = FakeMmap(A.MCA_SIZE)
m.poke(A.R_MAGIC, A.MAGIC)
h = A.MCA(m, -1, caps, 14, 8, 8)
h.configure(thr=317, ...)
m.trace()            # [(0x014, 317), (0x018, 91), ...] en orden
```

> El `assert` de tamaño de `FakeMmap` no es decorativo: asignar por slice a un
> `bytearray` fuera de rango **lo redimensiona en silencio**, cosa que un mmap
> real nunca hace. Sin él, un offset equivocado pasaría el test en vez de
> fallarlo.

### El bloque C es el que gana el sueldo

Verifica sin hardware las dos cosas que más pueden romperse al trocear los
drivers: escribir al **registro** equivocado y escribir en el **orden**
equivocado. Cuando falla, el diff señala la línea:

```
FALLO  [C] la secuencia de escrituras de scope_arm_autorearm cambió
       esperado (pre-refactor)      obtenido
       0x0244 <- 0x00000010         0x0240 <- 0x00000010      <<< DIFIERE
```

### Está validado por inyección de fallos

Un test que pasa trivialmente no prueba nada. Se comprobó que cada bloque muerde,
inyectando fallos realistas en copias del árbol:

| Fallo inyectado | Lo caza |
|---|---|
| `0x244` → `0x240` al extraer literales | C (+ el propio assert de readback del driver) |
| `arm` movido después de la máscara OR | C, con diff posicional |
| `R_TAIL_DLY` `0x02C` → `0x02D` | B y C |
| Firma de `gauss_fit_peak` cambiada | A y D |
| `ADC_CNT_PER_V` 8192 → 8191 | B y D |

### Desviaciones intencionadas

El test lleva una lista explícita de cambios de superficie decididos a propósito,
cada uno con su motivo. Hoy tiene **una**: `multitrigger_utils.rp`, que era un
módulo y ahora es el proxy perezoso ([por qué](decisiones_del_refactor.md#3-import-rp-es-perezoso)).
Lo que no esté en esa lista falla. Es un registro que se lee en el diff del
commit, no una alfombra.

---

## 3. Regenerar el baseline

**Regenerarlo desde el árbol ya refactorizado anula el sentido del test.** Si
hace falta —porque se amplió lo que se congela, o porque un cambio de API es
deliberado— se regenera desde un worktree en el commit pre-refactor:

**Ojo con las rutas:** en el worktree pre-refactor el generador vive en
`software/tests/` y escribe los dos ficheros ahí al lado; en el árbol de hoy
vive en `software/API/tests/` y los escribe en `software/API/tests/datos_ref/`.
El generador siempre escribe *relativo a sí mismo*, así que hay que copiarlo a
la ruta vieja, correrlo allá, y traer el resultado a la ruta nueva.

```bash
git worktree add --detach /tmp/pre_refactor <commit-pre-refactor>
VIEJO=/tmp/pre_refactor/prj/MCA/software

# el generador de HOY, corriendo sobre el arbol de ANTES
cp prj/MCA/software/API/tests/gen_compat_baseline.py $VIEJO/tests/
cd $VIEJO && python3 tests/gen_compat_baseline.py     # deja los .json/.npz en tests/

# y de vuelta a donde los busca el test actual
cd - && cp $VIEJO/tests/compat_baseline.json $VIEJO/tests/compat_golden.npz \
          prj/MCA/software/API/tests/datos_ref/
git worktree remove --force /tmp/pre_refactor
```

El diff de `compat_baseline.json` en el commit **es** el registro de qué cambió
de la API pública, y hay que revisarlo como tal.

> `compat_golden.npz` está versionado a pesar del `*.npz` del `.gitignore`
> (hay una negación explícita): es dato de referencia, no salida de medición.
> Sin versionarlo, el test no corre en un clon limpio.

---

## 4. Qué falta: retirar los shims

El refactor se paró **a propósito** antes de migrar los call sites. Mezclar el
movimiento con la migración habría hecho imposible saber si un fallo en la placa
venía de uno o de la otra.

Orden sugerido para el segundo paso, cuando el primero esté verificado en la
Pitaya:

1. Migrar los importadores a `from API.<modulo> import ...`, un módulo por
   commit, corriendo el test entre medias.
2. Migrar los notebooks (son siete).
3. Actualizar las reglas de ruta de `.claude/settings.json`, que mencionan
   `remote_soft/mca/mca_utils.py` y `remote_soft/mca/testbench_mca.py`.
4. Borrar los shims y regenerar el baseline, con el diff del JSON como acta de
   lo que se retiró.

Hasta el paso 4 el test sigue siendo la red. Después de él, deja de comparar
contra el árbol viejo y pasa a ser un test de regresión de la API nueva —
momento en que conviene renombrarlo.

---

## 5. Cobertura de los tests

| Test | Qué cubre | Placa |
|---|---|---|
| [`test_compat_api.py`](../../software/API/tests/test_compat_api.py) | que la superficie **vieja** no cambió | no |
| [`test_api_mca.py`](../../software/API/tests/test_api_mca.py) | lo que el refactor **añadió**: accesores por campo, RMW, metadata, guardado | no |
| [`API/tests/placa/`](../../software/API/tests/placa/) | formato del ring y `RingSource` | no |
| `API/tests/placa/diag_mca_hw.py` | camino de lectura completo del MCA | **sí** |
| `API/tests/placa/test_mca_hw.py`, `testbench_mca.py` | campañas de caracterización | **sí** |

Los tres primeros corren juntos:

```bash
python -m pytest API/tests/test_api_mca.py API/tests/test_compat_api.py API/tests/placa/ -q
```

El chequeo que sólo puede hacerse en la placa es
[`diag_mca_hw.py`](../../software/API/tests/placa/diag_mca_hw.py): si lee el espectro
completo sin colgarse, confirma que la lectura palabra a palabra sobrevivió el
movimiento sin que nadie la "optimizara" a un slice — que en esta placa no da
SIGBUS sino que **reinicia el sistema**.
