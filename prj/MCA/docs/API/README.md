# API del software de adquisición

**Código:** [`prj/MCA/software/API/`](../../software/API/)
**Contrato de nombres:** las tres capas de abajo
**Tests:** [`tests/test_compat_api.py`](../../software/tests/test_compat_api.py) · [`tests/test_api_mca.py`](../../software/tests/test_api_mca.py) — los dos corren en la PC, sin placa

Antes, el software estaba organizado por *fichero histórico*: `mca_utils.py`
mezclaba el driver del MCA con los helpers de análisis, `multitrigger_utils.py`
mezclaba el osciloscopio, el multitrigger y el bring-up de la FPGA, y el paquete
`mca/` no era del MCA sino el pipeline de guardado del osciloscopio. Cada script
nuevo tenía que adivinar dónde vivía cada cosa.

Ahora está organizado por **bloque del bus** y por **tipo de operación**, y el
nombre de la función dice las dos cosas.

---

## Documentos

| Documento | Qué contiene |
|---|---|
| [`referencia_api.md`](referencia_api.md) | Todas las funciones por módulo, con el registro al que pega cada una |
| [`guia_de_uso.md`](guia_de_uso.md) | Recetas completas: espectro, captura de eventos, guardado, armado |
| [`decisiones_del_refactor.md`](decisiones_del_refactor.md) | Por qué dos clases sobre el mismo bloque, por qué el import perezoso, por qué el análisis no lleva prefijo |
| [`compatibilidad_y_migracion.md`](compatibilidad_y_migracion.md) | Los shims, cómo se verifica que nada se rompió y cómo retirarlos |

---

## Las tres capas del nombre

`<módulo>_<capa>_<campo>`

| Capa | Qué dice | Valores |
|---|---|---|
| 1 · módulo | a qué bloque del bus pega | `mca_` · `osciloscope_` · `osciloscope_ring_` · `multitrigger_` |
| 2 · tipo de API | qué clase de operación es | cfg/status *sin infijo* · `read_` · `write_file_` / `save_file_` |
| 3 · campo | el registro o la operación concreta | `thr`, `gate_long`, `histogram`, … |

```python
from API.mca import mca_open, mca_set_thr, mca_read_histogram

h = mca_open()          # capa 1 + ciclo de vida
mca_set_thr(h, 200)     # capa 1 + capa 2 (cfg, sin infijo) + capa 3
hist = mca_read_histogram(h)
```

**Configuración y estatus** no llevan infijo de capa 2: son `mca_get_thr(h)` y
`mca_set_thr(h, 200)`, un par por campo de registro.

**Lectura** devuelve siempre `numpy`, que es la estructura natural del dato.
Convertir a otra representación es trabajo de la capa de guardado, no de la de
lectura.

**Guardado** distingue el formato de texto por defecto (`write_file_`) de los
formatos estructurados (`save_file_`).

---

## Módulos y bloques del bus

| Módulo | Bloque | Base | Registros |
|---|---|---|---|
| [`API.mca`](../../software/API/mca.py) | analizador multicanal | `0x4070_0000` (slot 7) | [mapa](../mca/register_map_mca.md) |
| [`API.osciloscope`](../../software/API/osciloscope.py) | osciloscopio clásico | `0x4010_0000` (slot 1) | [mapa](../multitrigger/register_map_multitrigger_rp_scope_cfg.md) |
| [`API.multitrigger`](../../software/API/multitrigger.py) | máscaras OR, shield, snapshot | `0x4010_0000` (slot 1, `0x210`–`0x24C`) | [mapa](../multitrigger/register_map_multitrigger_rp_scope_cfg.md) |
| [`API.osciloscope_ring`](../../software/API/osciloscope_ring.py) | event_ring en DDR | `0x4020_0000` (slot 2) | [mapa](../event_ring/diseno_y_register_map.md) |
| [`API.osciloscope_store`](../../software/API/osciloscope_store/) | guardado continuo del flujo de eventos | — | [arquitectura](../multitrigger/arquitectura_adquisicion_software.md) |
| [`API.analisis`](../../software/API/analisis.py) | helpers puros, sin hardware | — | — |
| [`API.fpga`](../../software/API/fpga.py) | bring-up de la PL | — | — |
| [`API.rigol_dg4162`](../../software/API/rigol_dg4162.py) | generador externo | — | — |

> **El osciloscopio y el multitrigger comparten slot pero son dos módulos.**
> `osciloscope_` cubre lo que ya existía en el diseño original de RedPitaya
> (umbral, decimación, delay, histéresis, filtros, calibración, punteros de
> escritura, BRAM); `multitrigger_` cubre lo que **añadió este proyecto**. Son
> dos APIs sobre el mismo bloque físico, no dos bloques.

---

## Dónde encaja cada cosa

```
software/
├── API/                    ← la API
│   ├── mca.py
│   ├── osciloscope.py
│   ├── osciloscope_ring.py
│   ├── osciloscope_store/  ← el antiguo paquete mca/
│   ├── multitrigger.py
│   ├── analisis.py
│   ├── fpga.py
│   └── rigol_dg4162.py
│
├── mca_utils.py            ← SHIM, reexporta de API/
├── multitrigger_utils.py   ← SHIM
├── rigol_dg4162.py         ← SHIM
├── mca/                    ← SHIM (paquete + 7 submódulos)
│
├── testbench_mca.py        ← campañas de caracterización (no son API)
├── testbench_multitrigger.py
└── tests/
```

`API/` vive **dentro** de `software/` a propósito: los ~40 ficheros del árbol ya
hacen `sys.path.insert(0, <dir de software>)`, así que `import API.mca` funciona
sin tocar ninguno, y el rsync de deploy a la Pitaya
([`flujo_sync_notebooks_pitaya.md`](../flujo_sync_notebooks_pitaya.md)) sigue
siendo el mismo comando.

La separación **driver / caracterización** se mantiene igual que antes: en `API/`
va el acceso al hardware y los helpers puros; las campañas de medida siguen en
`testbench_mca.py` y `testbench_multitrigger.py`.
