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
| `mca.py` | analizador multicanal | `0x4070_0000` |
| `osciloscope.py` | osciloscopio clásico | `0x4010_0000` |
| `multitrigger.py` | máscaras OR, shield, snapshot | `0x4010_0000` (`0x210`–`0x24C`) |
| `osciloscope_ring.py` | event_ring en DDR | `0x4020_0000` |
| `osciloscope_store/` | guardado continuo del flujo de eventos | — |
| `analisis.py` | helpers puros, sin hardware | — |
| `fpga.py` | bring-up de la PL | — |
| `rigol_dg4162.py` | generador externo | — |

## Compatibilidad

`mca_utils.py`, `multitrigger_utils.py`, `rigol_dg4162.py` y el paquete `mca/`
siguen en `software/` como **shims** que reexportan desde acá, así que los ~40
importadores, los notebooks y los scripts que corren en la placa no se tocaron.

```bash
cd prj/MCA/software
python tests/test_compat_api.py   # nada público cambió respecto al baseline
python tests/test_api_mca.py      # accesores por campo, RMW y guardado
```
