# libmca: la API de hardware en C

Es la API de [`../API/`](../API/) escrita en C, con la forma de
[`rp-api`](https://github.com/RedPitaya/RedPitaya/tree/master/rp-api): un
handle opaco por bloque, y funciones que devuelven `MCA_OK` o un `MCA_E*` y
entregan los resultados por puntero. Python la usa por `ctypes`
([`API/_libmca.py`](../API/_libmca.py), [`API/mca.py`](../API/mca.py)), y no
agrega lógica: sólo traduce tipos y errores.

**Estado:** fase 1 sobre el mapa **"MCA2"** (las ranuras: `n_acc`, `pre_dly`,
el trapecio, `t_ocup`), validada en la placa. El MCA1 ya no lo habla libmca:
`mca_open` lo rechaza diciendo que se use `mca_open(impl='py')` desde Python.
El multitrigger, la región de TOP y los registros del osciloscopio son las
fases siguientes. El diseño y la comparación con las clases de Python están en
[`docs/API/diseno_de_clases.md`](../../docs/API/diseno_de_clases.md) §3 y §4.

```c
#include "mca.h"

mca_h *h;
if (mca_open(&h, MCA_PHYS, MCA_SIZE, 1) != MCA_OK) {
    fprintf(stderr, "%s\n", mca_last_error(NULL));
    return 1;
}
mca_config_t cfg;
mca_config_default(&cfg);
cfg.n_acc = 4;
mca_configure(h, &cfg);   /* todo el estado: sin banco queda una sola forma */
/* el disparo lo arma el multitrigger (API.multitrigger.multitrigger_armar_mca) */
mca_start(h);
/* ... */
uint32_t hist[1 << 14];
mca_stop(h);
mca_read_histogram(h, hist, 1 << 14);
mca_close(h);
```

## Compilar

```bash
make            # build/x86_64/libmca.so: tests de PC y FakeMCA
make arm        # build/armv7l/libmca.so y bench_libmca, con el cruzado
make test       # tests de C del nivel 2
make check-bus  # la regla del bus, sobre el binario de ARM (ver abajo)
make placa-lib  # compila EN la placa, si el cruzado no carga allá
```

Desde `software/`, `make verificar` compila y prueba todo, y `make release`
empaqueta el `.so` de ARM ya chequeado.

## Estructura

| Fichero | Qué es |
|---|---|
| `include/mca_api.h` | códigos de error, versión |
| `include/mca_bus.h` | el nivel 2: `mca_bus` con sus dos backends (devmem y callbacks) |
| `include/mca_regs.h` | mapa de registros y tabla de campos (X-macros) |
| `include/mca.h` | la API del MCA |
| `src/bus_devmem.c` | **el único fichero que toca la PL**: tres funciones, un `ldr`/`str` de 32 b cada una |
| `src/bus_mmap.c` | abrir, mapear y cerrar `/dev/mem` |
| `src/bus_callback.c` | el backend por punteros a función (FakeMCA, tests) |
| `src/mca.c` | la lógica del MCA |
| `scripts/check_bus.sh` | lo que corre `make check-bus` |
| `tests/test_bus.c` | tests del nivel 2 |
| `tests/bench_libmca.c` | la columna `c_puro` de `API/bench/bench_impl.py` |

## La regla del bus, chequeada en el binario

El esclavo AXI de la PL sólo atiende accesos de 32 bits, alineados y de a uno.
Una ráfaga o un acceso de 64 b **reinicia la placa**, y uno de 1 byte da SIGBUS
([`docs/TOP/bus_sistema_redpitaya.md`](../../docs/TOP/bus_sistema_redpitaya.md)
§7.2-7.4). `make check-bus` desensambla `bus_devmem.o` compilado para ARM y
**falla** en estos casos:

- hay un `LDM`/`STM`, `LDRD`/`STRD`, `VLD`/`VST`, o un acceso de 1-2 bytes que
  no sea sobre la pila;
- se llama a `memcpy`/`memset`/`memmove`;
- la palabra `volatile` aparece en otro fichero;
- el `.so` pide un símbolo de glibc más nuevo que `GLIBC_MAX` (2.27 por
  defecto; ajustarlo con `ssh pitaya ldd --version`). Así se detectó que
  `log2()` pedía `GLIBC_2.29`, y por eso `mca.c` usa `frexp`.

## Equivalencia con Python

`API/ref_py/mca2.py` es la implementación Python del MCA2, congelada.
[`API/tests/test_libmca_equivalencia.py`](../API/tests/test_libmca_equivalencia.py)
corre cada función pública de los dos lados, sobre dos modelos de registros
idénticos, y exige las mismas escrituras en el mismo orden (también en los
casos de error), el mismo resultado y la misma excepción. Si se toca `mca.c`,
ése es el test que tiene que seguir pasando.

## Comparar rendimiento

```bash
make bench-api-remoto                          # desde software/: py, c y c_puro en la placa
python3 API/bench/comparar_bench.py DIR        # una corrida
python3 API/bench/comparar_bench.py DIR_A DIR_B  # antes y después
python3 campanas/testbench_mca.py all --impl py  # una campaña, con cada implementación
```
