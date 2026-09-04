# Decisiones del refactor

Por qué la API quedó como quedó. Igual que
[`decisiones_diseno_mca.md`](../mca/decisiones_diseno_mca.md) para el RTL: lo que
se descartó y por qué, para no volver a discutirlo dentro de seis meses.

---

## 1. El prefijo va en el nombre de la función, no en el import

Se barajaron tres formas de materializar las tres capas:

| Opción | Ejemplo |
|---|---|
| Subpaquetes | `API.mca.cfg.set_thr(h, 200)` |
| Ficheros planos con prefijo | `from API import mca_cfg; mca_cfg.set_thr(...)` |
| **Prefijo en la función** ✔ | `from API.mca import mca_set_thr` |

Ganó la tercera. La razón es que en este árbol **el código se lee fuera de su
contexto de import**: notebooks de una sola celda, scripts de campaña de 2000
líneas, fragmentos pegados en el cuaderno de laboratorio. Con
`mca_set_thr(h, 200)` sabés qué bloque tocás aunque no veas la cabecera; con
`cfg.set_thr(h, 200)` tenés que subir a buscar de qué `cfg` se trata.

Cuesta nombres más largos y algo de repetición. Es un precio que se paga una vez
al escribir y se cobra cada vez que se lee.

### Un fichero plano por módulo

La primera versión partía cada módulo en `regs.py` / `_bus.py` / `cfg.py` /
`read.py`. Se descartó: si el prefijo ya está en el nombre de la función, el
anidamiento no compra nada y obliga a saltar entre cuatro ficheros para seguir
una operación. Los módulos quedaron entre 250 y 820 líneas, comparable a lo que
había. La única excepción es `osciloscope_store/`, que sigue siendo paquete
porque **ya lo era** y es código de hilos, colas y clases, no una superficie
plana de funciones.

---

## 2. El osciloscopio y el multitrigger son dos clases sobre el mismo bloque

`MultiTriggerScope` era **una sola clase sobre un solo mmap** que mezclaba el
osciloscopio original de RedPitaya (umbral, decimación, delay, histéresis,
filtros, calibración, punteros, BRAM) con lo que añadió este proyecto (máscaras
OR `0x240/0x244`, shield `0x210`, snapshot `0x218`).

Se partió en `Osciloscope` y `MultiTrigger`. Comparten slot, no identidad: uno es
hardware heredado y el otro es la contribución del proyecto, y mezclarlos hacía
imposible saber qué era qué al leer.

`MultiTrigger.open(osc=...)` **reutiliza el mapeo del osciloscopio** en vez de
abrir otro. Dos mapeos de la misma región de memoria de dispositivo no dan
problema de coherencia, pero un fd de menos es un fd de menos.

### El precio: la secuencia de armado cruza los dos

`arm_for_adc_trigger` escribía histéresis (`0x20`/`0x24`, osciloscopio) → arm
(`0x00`, osciloscopio) → máscara OR (`0x240`/`0x244`, multitrigger). **Ese orden
es load-bearing** ([por qué](../multitrigger/orden_arm_trigger_captura.md)), y al
partir la clase pasó a ser un punto de fallo nuevo: nada impide reordenarlo, y el
síntoma aparece sólo en la placa y sólo con señal viva.

Se resolvió con `multitrigger_arm(osc, mt, ...)`, que **recibe los dos handles**.
La dependencia queda en la firma en vez de escondida en el `self` de una clase.

Y se le puso una red: el test de compatibilidad congela la **secuencia ordenada
de escrituras** de esa función. Reordenarla falla en la PC, en segundos, con un
diff que señala las líneas movidas:

```
FALLO  [C] la secuencia de escrituras de scope_arm_autorearm cambió
       esperado (pre-refactor)      obtenido
       0x0000 <- 0x00000909         0x0240 <- 0x00000002      <<< DIFIERE
       0x0240 <- 0x00000002         0x0244 <- 0x00000010      <<< DIFIERE
       0x0244 <- 0x00000010         0x0000 <- 0x00000909      <<< DIFIERE
```

---

## 3. `import rp` es perezoso

`multitrigger_utils.py` hacía `import rp` a nivel de módulo. `rp` es la librería
de RedPitaya y **sólo existe en la Pitaya**, así que el fichero entero era
inimportable desde la PC — y con él la configuración, los mapas de registros y
cualquier test offline.

En `API/osciloscope.py` hay un proxy que importa `rp` en el **primer uso** y se
auto-reemplaza en los globals del módulo:

```python
class _RpPerezoso:
    def __getattr__(self, nombre):
        import rp as _real
        globals()['rp'] = _real      # sin coste a partir de acá
        return getattr(_real, nombre)

rp = _RpPerezoso()
```

Así los cuerpos que llaman `rp.rp_AcqGetDataPosV(...)` quedaron **verbatim** —no
hubo que reescribir cada llamada— y el error, si falta la librería, sale donde se
usa y no donde se importa.

Efecto colateral bueno: `tests/fase0/test_ring_source.py` metía un
`multitrigger_utils` falso en `sys.modules` para poder correr en la PC. Ese stub
ya no hace falta, y además **hacía daño**: se quedaba para todo el proceso, así
que cualquier otro test del mismo `pytest` veía el módulo falso en vez del real.

Esta es la **única desviación intencionada** de la superficie pública, y el test
la registra explícitamente en vez de ignorarla en silencio.

---

## 4. El análisis no lleva prefijo

`gauss_fit_peak`, `dnl`, `fom`, `deadtime_fit`, `axis_calibration`,
`linearize_spectrum`… viven en `API/analisis.py` **con los nombres que ya
tenían**.

No son cfg/read/store, no pegan a ningún bloque del bus y no tocan hardware:
`mca_analisis_gauss_fit_peak()` sería un prefijo que miente sobre lo que la
función hace. Además se usan como `mu.gauss_fit_peak` en una quincena de sitios,
incluidas las figuras de [`docs/mca/figuras/`](../mca/figuras/), que importan
desde fuera del árbol de `software/`.

**Las tres capas gobiernan la API de hardware.** Que sea una excepción declarada
es mejor que una regla que se dobla sin decirlo.

---

## 5. `fpga.py` está en la raíz de `API/`, no dentro del osciloscopio

`load_bitstream`, `pl_probe`, `fpga_bridges`, `fpga_state` vivían en
`multitrigger_utils.py` porque el scope fue lo primero que hubo que arrancar.
Pero cargar un bitstream no tiene nada que ver con adquirir señal, y un
bitstream distinto usa esas mismas funciones.

`pl_probe` sondeaba `SCOPE_PHYS + 0x14`. En `API/fpga.py` esa dirección es una
constante propia con su explicación:

```python
# Dirección de sondeo por defecto: el registro set_dec del slot 1 (scope). No es
# una dependencia del osciloscopio, es sólo "un registro que sabemos que existe
# y contesta" para preguntarle al bus si está vivo.
_PROBE_PHYS = 0x4010_0000
```

Así `API.fpga` no depende de `API.osciloscope`, que es lo correcto: el bring-up
es anterior a que exista un osciloscopio al que hablarle.

---

## 6. Los `set_` hacen read-modify-write

Cinco campos comparten registro con otros: `bl_auto`/`bl_k`/`bl_holdoff` en
`0x020`, `amp_src`/`q_shift` en `0x038`, `gate_short`/`gate_long` en `0x04C`, y
`channel` con `run` en `0x00C`.

Un `mca_set_bl_k(h, 13)` que escribiera la palabra entera dejaría `bl_holdoff` en
cero. En la placa eso cambia el comportamiento del seguidor de línea de base
**sin que nada falle ni avise** — el peor tipo de bug.

Antes de escribirlo se verificó en el RTL que esos registros **releen lo
escrito** (`mca_top.sv:340,346,351` devuelven el valor con ceros en los huecos),
que es lo que hace seguro el read-modify-write. Lo cubre
[`test_api_mca.py::test_rmw_no_pisa_campos_vecinos`](../../software/tests/test_api_mca.py).

---

## 7. Se nombraron los offsets del scope

`multitrigger_utils.py` **no tenía ninguna constante de offset**: cada dirección
era un literal hex inline (`self.w32(0x240, mask)`). Extraerlos a constantes
`R_*` fue la parte más mecánica del refactor y la más peligrosa: un `0x240` que
se vuelve `0x244` no rompe nada en la PC, rompe escribiendo al registro
equivocado en la placa.

Por eso el test de compatibilidad congela **el valor de cada constante**, no sólo
su existencia. Es el chequeo que atrapa ese typo.

---

## 8. Se movió el fichero, no el trabajo de los demás

Ninguno de los ~40 ficheros que importan estos módulos se editó, ni los
notebooks, ni los scripts que ya corren en la placa. `API/` vive **dentro** de
`software/`, que es donde ya apuntan todos los `sys.path.insert`, y los ficheros
viejos siguen ahí como shims que reexportan.

Retirar los shims y migrar los call sites es un paso posterior, deliberadamente
separado: mezclarlo con el movimiento habría hecho imposible saber si un fallo en
la placa venía del refactor o de la migración. Ver
[`compatibilidad_y_migracion.md`](compatibilidad_y_migracion.md).
