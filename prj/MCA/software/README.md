# Software del MCA

```bash
make help          # todos los objetivos
make test          # la suite offline, en la PC (sin placa, sin Rigol)
make placa         # lo que necesita la Red Pitaya
make mc            # las simulaciones Monte-Carlo
```

Los testbenches de **RTL** van aparte: `make -C ../sim`, o `make rtl` desde
`prj/MCA`. La palabra "testbench" significa dos cosas en este proyecto y los
Makefiles las mantienen separadas: `rtl*` es SystemVerilog en QuestaSim,
`campana-*` son las corridas de caracterización sobre hardware real.

## El árbol

| Directorio | Qué hay |
|---|---|
| [`API/`](API/) | los módulos: driver del MCA, osciloscopio, multitrigger, event_ring, red, análisis |
| [`API/modelo_rtl/`](API/modelo_rtl/) | espejos en software de contratos del RTL — no son tests, los importan siete ficheros y los cita el propio `.sv` |
| [`API/tests/`](API/tests/) | tests **offline** de `API/`: corren en la PC con fakes |
| [`API/tests/placa/`](API/tests/placa/) | los mismos sujetos, pero **necesitan la Red Pitaya** |
| [`API/bench/`](API/bench/) | benchmarks de lectura del buffer: miden, no aprueban ni fallan |
| [`app/`](app/) | la GUI (`mcamon`) y el servidor, con sus tests — documentada en [`docs/APP/`](../docs/APP/) |
| [`monte-carlo/`](monte-carlo/) | **simulaciones**: apilamiento, línea de base, pico-vs-carga |
| [`campanas/`](campanas/) | drivers de campaña: caracterización sobre hardware real, y el regraficado de lo ya medido |
| `datos/` | corridas medidas (no versionado) |

La distinción que más importa es **`monte-carlo/` contra el resto**: ahí adentro
no se prueba código que maneje hardware, se simula física. Un número que sale de
`monte-carlo/` es una predicción; uno que sale de `campanas/` es una medición.

`mca_utils.py`, `multitrigger_utils.py`, `rigol_dg4162.py` y `mca/` siguen en la
raíz como **shims** que reexportan desde `API/`, para no romper los notebooks ni
los scripts ya desplegados en la placa.

## Qué corre dónde

`make test` da lo mismo en la PC y en la Pitaya, y las dos pasan — por eso
`make remoto-test` sirve de sanity check del deploy:

```bash
make sync           # rsync del árbol a la Pitaya
make remoto-test    # la suite offline, allá
make remoto-placa   # la batería que necesita hardware
```

Los tests de placa **no se pueden ni importar** en la PC (hacen `import rp` al
importarse), así que viven en su propio directorio y `pyproject.toml` los saca
de la colección con `norecursedirs`. Un `pytest` pelado en la PC es seguro.

## Compatibilidad

`API/tests/test_compat_api.py` compara la superficie pública actual contra un
baseline congelado antes del refactor: nombres, firmas, valores de constantes,
y las **trazas ordenadas de escritura de registros**. Ese último bloque es el
que gana el sueldo — un `0x240` que se vuelve `0x244` no rompe nada en la PC,
rompe en la placa escribiendo al registro equivocado.

```bash
make compat     # verifica contra el baseline
make baseline   # lo REGENERA (revisar el diff antes de commitear)
```
