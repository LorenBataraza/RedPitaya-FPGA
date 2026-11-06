# API del software de adquisición

**Documentación completa:** [`prj/MCA/docs/API/`](../../docs/API/)

| Documento | Qué contiene |
|---|---|
| [README](../../docs/API/README.md) | nomenclatura, estructura, mapa de módulos a bloques del bus |
| [Referencia](../../docs/API/referencia_api.md) | todas las funciones, con el registro al que pega cada una |
| [Guía de uso](../../docs/API/guia_de_uso.md) | recetas completas y errores frecuentes |
| [Decisiones](../../docs/API/decisiones_del_refactor.md) | por qué la API quedó así |
| [Compatibilidad](../../docs/API/compatibilidad_y_migracion.md) | los shims, el test, y qué falta para retirarlos |

---

## El contrato de nombres, en corto

`<módulo>_<capa>_<campo>`

| Capa | Qué dice | Valores |
|---|---|---|
| 1 · módulo | a qué bloque del bus pega | `mca_` · `osciloscope_` · `osciloscope_ring_` · `multitrigger_` |
| 2 · tipo de API | qué clase de operación es | cfg/status *sin infijo* · `read_` · `write_file_` / `save_file_` |
| 3 · campo | el registro o la operación concreta | `thr`, `gate_long`, `histogram`, … |

```python
from API.mca import mca_open, mca_set_thr, mca_read_histogram

h = mca_open()
mca_set_thr(h, 200)
hist = mca_read_histogram(h)
```

`API.analisis` es la excepción deliberada: sus funciones (`gauss_fit_peak`,
`dnl`, `fom`, …) no son cfg/read/store, no tocan hardware y conservan sus
nombres. Las tres capas gobiernan la API de *hardware*.

## Ficheros

| Fichero | Bloque | Base |
|---|---|---|
| `mca.py` | analizador multicanal con ranuras ("MCA2") | `0x4070_0000` |
| `osciloscope.py` | osciloscopio clásico | `0x4010_0000` |
| `multitrigger.py` | máscaras OR, shield, snapshot; la región propia (pendiente) y el disparo del MCA2 (`multitrigger_armar_mca`) | `0x4010_0000` (`0x210`–`0x24C`), `0x4030_0000` |
| `osciloscope_ring.py` | event_ring en DDR | `0x4020_0000` |
| `osciloscope_store/` | guardado continuo del flujo de eventos | — |
| `analisis.py` | helpers puros, sin hardware | — |
| `fpga.py` | bring-up de la PL | — |
| `rigol_dg4162.py` | generador externo | — |
| `_libmca.py` | carga de [`libmca`](../libmca/) (la API en C) y su `Bus` | — |
| `_despacho.py` | el decorador `@_api`: cada llamada va a C, a la referencia o a la red | — |
| `ref_py/` | la implementación Python **congelada**: base de benchmarks y de la equivalencia. `mca2.py` es la del MCA2; `mca.py`, la del MCA1 | — |

**El MCA está en C** desde la fase 1 de libmca: cada `mca_*` es una llamada por
ctypes a la función homónima de `libmca/include/mca.h`, que habla el mapa
"MCA2". `mca_open(impl='py')` abre la implementación Python para comparar (y
es la única que abre el bitstream MCA1). **Sin el disparo del multitrigger
armado el MCA2 no mide**: `multitrigger_armar_mca(osc, mtr)`. Ver
[`docs/API/diseno_de_clases.md`](../../docs/API/diseno_de_clases.md) §3 y §4.

## Compatibilidad

`mca_utils.py`, `multitrigger_utils.py`, `rigol_dg4162.py` y el paquete `mca/`
siguen en `software/` como **shims** que reexportan desde acá, así que los ~40
importadores, los notebooks y los scripts que corren en la placa no se tocaron.

```bash
cd prj/MCA/software
python API/tests/test_compat_api.py   # nada público cambió respecto al baseline
python API/tests/test_api_mca.py      # accesores por campo, RMW y guardado
```
