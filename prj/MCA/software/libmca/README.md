# libmca: la API de hardware en C

Es la API de [`../API/`](../API/) escrita en C, con la forma de
[`rp-api`](https://github.com/RedPitaya/RedPitaya/tree/master/rp-api): un
handle opaco por bloque, y funciones que devuelven `MCA_OK` o un `MCA_E*` y
entregan los resultados por puntero. Python la usa por `ctypes`
([`API/_libmca.py`](../API/_libmca.py), [`API/mca.py`](../API/mca.py)), y no
agrega lógica: sólo traduce tipos y errores.

**Estado:** el MCA sobre el mapa **"MCA2"** (las ranuras: `n_acc`, `pre_dly`,
el trapecio, `t_ocup`), validado en la placa. El MCA1 ya no lo habla libmca:
`mca_open` lo rechaza diciendo que se use `mca_open(impl='py')` desde Python.
La región de TOP (`integration.h`), el multitrigger (`multitrigger.h`) y el osciloscopio
(`osciloscope.h`) están probados contra un modelo de registros y en la placa
(2026-11-07). El lazo por evento del osciloscopio y la calibración de librp
(`osciloscope_lote.h`, 0.7.0) están probados contra un modelo y contra la cuenta de
rp-api, todavía sin correr en la placa. El event_ring (`osciloscope_ring.h`) y su
región de DDR (`mca_mem.h`), desde 0.8.0, están probados contra un modelo del ring,
contra el volcado de DDR del RTL y en la placa (2026-11-09). Los dos generadores de
prueba (`gen_pulsos.h`, `gen_disparos.h` y `osciloscope_ring_gen_*`), desde 0.9.0,
están probados contra un modelo de registros y contra los modelos de Python de los
generadores y en la placa (2026-11-09, con el bitstream del ring). Los modos del
lector del ring para medir la tasa (`osciloscope_ring_medir`), desde 0.10.0, están
probados contra el modelo del ring y en la placa (2026-11-12). El envío del ring por red
(`osciloscope_ring_enviar`, y el código `MCA_EIO`), desde 0.12.0, está probado contra el
modelo del ring, todavía sin correr en la placa. El diseño y la comparación con las clases de Python están en
[`docs/API/libmca.md`](../../docs/API/libmca.md).

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
| `include/mca_api.h`, `src/common.c` | códigos de error y `mca_strerror`, versión, `mca_reg_t` y `mca_field_t` |
| `include/mca_bus.h` | el nivel 2: `mca_bus` con sus backends (devmem, que también abre un fichero común, y callbacks) |
| `src/bus.h`, `src/bus.c` | la tabla `vt` de cada backend, y las funciones públicas del bus: validan alineación y rango y despachan |
| `include/mca_regs.h` | mapa de registros y tabla de campos (X-macros) |
| `include/mca.h` | la API del MCA |
| `include/integration_regs.h`, `include/integration.h` | el mapa y la API de la región de TOP |
| `include/multitrigger_regs.h`, `include/multitrigger.h` | el mapa, la tabla de campos y la API del multitrigger |
| `include/osciloscope_regs.h`, `include/osciloscope.h` | el mapa, la tabla de campos y la API del osciloscopio |
| `include/osciloscope_lote.h` | el lazo por evento (`osciloscope_leer_lote`) y la calibración de librp |
| `include/mca_mem.h` | la región de DDR que escribe la PL: memoria común, se copia de a bloques. Backends devmem, file, ptr y callback |
| `include/osciloscope_ring_regs.h`, `include/osciloscope_ring.h` | el mapa y la API del event_ring: configurar, correr, parar, contadores, el lector por lote, el envío por red (`osciloscope_ring_enviar`) y su generador de eventos (`osciloscope_ring_gen_*`) |
| `include/gen_disparos.h` | el motor de disparos que comparten los dos generadores: su configuración, el umbral por tasa y la predicción de cada disparo. Sin hardware |
| `include/gen_pulsos_regs.h`, `include/gen_pulsos.h` | el mapa y la API del generador de pulsos (`0x4021_0000`): configurar, la tabla, arrancar y esperar, el lazo digital de HK, y las cuentas por τ, Mq y espectro |
| `src/bus_devmem.c` | **el único fichero que toca la PL**: tres funciones, un `ldr`/`str` de 32 b cada una |
| `src/bus_mmap.c`, `src/devmem.h` | abrir, mapear y cerrar `/dev/mem` (o un fichero común) y el struct `devmem_bus`; el mapeo lo usa también `mem.c` |
| `src/bus_callback.c` | el backend por punteros a función (FakeMCA, tests) |
| `src/bloque.h`, `src/bloque.c` | lo común a los handles de cada bloque: el bus y el detalle del error |
| `src/mca.c` | la lógica del MCA |
| `src/integration.c` | la lógica de la región de TOP |
| `src/multitrigger.c` | la lógica del multitrigger |
| `src/osciloscope.c` | la lógica del osciloscopio: la sonda de geometría y la lectura de la BRAM |
| `src/osciloscope_lote.c`, `src/osciloscope_priv.h` | el lazo por evento y la calibración; lo privado que comparten con `osciloscope.c` y `osciloscope_ring.c` |
| `src/mem.c` | la región de DDR. No es la PL: copia con `memcpy` |
| `src/osciloscope_ring.c` | el event_ring: la geometría, configurar (con el borrado de footers), el lector por lote, el envío por red y el generador de eventos |
| `src/gen_disparos.c`, `src/gen_priv.h` | el motor de disparos: las cuentas, y los registros comunes a los dos generadores |
| `src/gen_pulsos.c` | el generador de pulsos |
| `scripts/check_bus.sh` | lo que corre `make check-bus` |
| `tests/test_bus.c` | tests del nivel 2 |
| `tests/bench_libmca.c` | la columna `c_puro` de `API/bench/bench_impl.py` |

`include/mca_api.h` tiene lo común a todos los bloques: los códigos de error, entre
ellos `MCA_ENOKEY` (un índice que no está en la tabla del bloque, el `KeyError` de
Python), `mca_reg_t` y `mca_field_t`.

## Agregar un bloque

Cada bloque de la PL tiene su handle y sus ficheros, con la forma del MCA:

| Fichero | Qué lleva |
|---|---|
| `include/<bloque>_regs.h` | el mapa de registros en X-macros: una sola lista genera el enum de offsets y la tabla exportada |
| `include/<bloque>.h` | la API: handle opaco, `MCA_OK`/`MCA_E*`, resultados por puntero, los mismos nombres que en Python |
| `src/<bloque>.c` | la lógica; el handle lleva `mca_bloque b` como **primer** miembro, y todo acceso pasa por `mca_bus` |
| `API/<bloque>.py` | el binding, que declara sus firmas y traduce errores |
| `API/tests/test_libmca_<bloque>.py` | la tabla de C contra las constantes de Python, y la equivalencia contra `API/ref_py/` |

El `.c` se agrega a `SRC` en el `Makefile`. `check-bus` no cambia: el acceso de
dispositivo sigue sólo en `src/bus_devmem.c`, y la palabra `volatile` en cualquier
otro fichero lo hace fallar.

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

`src/mem.c` usa `memcpy` a propósito, y `check-bus` no lo mira: la región de DDR del
event_ring no es la PL sino memoria común, y no hay ningún esclavo AXI del lado del PS.
Cómo copiar desde ahí se decide midiendo en la placa.

## Equivalencia con Python

`API/ref_py/mca2.py` es la implementación Python del MCA2, congelada.
[`API/tests/test_libmca_equivalencia.py`](../API/tests/test_libmca_equivalencia.py)
corre cada función pública de los dos lados, sobre dos modelos de registros
idénticos, y exige las mismas escrituras en el mismo orden (también en los
casos de error), el mismo resultado y la misma excepción. Si se toca `mca.c`,
ése es el test que tiene que seguir pasando.
[`API/tests/test_libmca_integration.py`](../API/tests/test_libmca_integration.py),
[`test_libmca_multitrigger.py`](../API/tests/test_libmca_multitrigger.py) y
[`test_libmca_osciloscope.py`](../API/tests/test_libmca_osciloscope.py) son lo mismo
para `integration.c`, `multitrigger.c` y `osciloscope.c`, contra
`API/ref_py/integration.py`, `multitrigger2.py` y `osciloscope2.py`.
`osciloscope_lote.c` no tiene referencia en Python (la de antes era `rp`): la
calibración se compara contra
[`API/tests/datos_ref/calib_rp.npy`](../API/tests/datos_ref/generar_calib_rp.py), la
cuenta de rp-api 2.00-35 sobre las 16384 cuentas, y el lazo contra un modelo de la FSM
en [`test_bram_source.py`](../API/tests/test_bram_source.py). `osciloscope_ring.c`
tampoco: [`test_ring_source.py`](../API/tests/test_ring_source.py) lo corre contra un
modelo de `event_ring_top`, contra el volcado de DDR del RTL (`ring_dump.hex`) y por
ficheros comunes. Los generadores no tienen referencia en Python, porque nacieron en C:
[`test_libmca_generadores.py`](../API/tests/test_libmca_generadores.py) corre
`gen_pulsos.c` contra un modelo de los registros de `gen_pulsos.sv`, y las cuentas de
`gen_disparos.c` y `gen_pulsos.c` contra los modelos de Python de los generadores
(`modulos/gen_eventos/modelos/python_model/`): los disparos ciclo por ciclo, el umbral,
el DECAE, la Mq para los 65 536 valores y la tabla. Esos tests se saltean en la placa,
donde `make placa-sync` no copia `modulos/`.

## Comparar rendimiento

```bash
make bench-api-remoto                          # desde software/: py, c y c_puro en la placa
python3 API/bench/comparar_bench.py DIR        # una corrida
python3 API/bench/comparar_bench.py DIR_A DIR_B  # antes y después
python3 campanas/testbench_mca.py all --impl py  # una campaña, con cada implementación
```
