# libmca: la API en C de los bloques de la PL. Ver include/mca_api.h.
#
#   make                 = make host
#   make host            build/x86_64/libmca.so   tests de PC y FakeMCA
#   make arm             build/armv7l/libmca.so   cruzado, para la placa
#   make test            compila y corre los tests de C en la PC
#   make check-bus       la regla del bus, comprobada sobre el .so de ARM
#   make bench           build/<arch>/bench_libmca: la columna c_puro del
#                        microbench (API/bench/bench_impl.py)
#   make placa-lib       compila EN la placa por ssh (si el cruzado no carga)
#   make limpiar
#
# Los directorios de build se llaman como `platform.machine()` (x86_64,
# armv7l) porque así los busca API/_libmca.py: el árbol que `make placa-sync`
# copia a la Pitaya lleva los dos, y cada máquina carga el suyo.

HOST_ARCH   := $(shell uname -m)
ARM_ARCH    := armv7l
CC_HOST     ?= gcc
# En la placa las herramientas de ARM son las nativas, sin prefijo de cruzado.
ifneq ($(HOST_ARCH),$(ARM_ARCH))
CC_ARM      ?= arm-linux-gnueabihf-gcc
OBJDUMP_ARM ?= arm-linux-gnueabihf-objdump
NM_ARM      ?= arm-linux-gnueabihf-nm
else
OBJDUMP_ARM ?= objdump
NM_ARM      ?= nm
endif

CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter
# -fno-tree-vectorize: el lazo de read_words NO puede volverse NEON (§7.3 del
#   doc del bus: una ráfaga reinicia la placa). check-bus lo verifica igual.
# -fvisibility=hidden: sólo se exporta lo marcado MCA_API.
CFLAGS_LIB = $(CFLAGS) -fPIC -fvisibility=hidden -fno-tree-vectorize -Iinclude \
             -DMCA_CFLAGS_STR='"$(CFLAGS) -fno-tree-vectorize"'

SRC := src/common.c src/bus.c src/bus_mmap.c src/bus_devmem.c src/bus_callback.c \
       src/mca.c
LDLIBS := -lm
HDR := $(wildcard include/*.h src/*.h)

# glibc más nueva que se tolera en los símbolos del .so de ARM. El cruzado de
# Debian 12 trae 2.36 y la placa puede tener una más vieja: si el .so pide un
# símbolo que la placa no tiene, ctypes no lo carga y la API cae a Python sin
# que nada falle a la vista. 2.27 (Ubuntu 18.04) es el piso conservador;
# ajustarlo con `ssh pitaya ldd --version`.
GLIBC_MAX ?= 2.27

PITAYA ?= pitaya
REMOTO ?= /home/jupyter/RedPitaya/remote_soft

HOST_DIR := build/$(HOST_ARCH)
ARM_DIR  := build/$(ARM_ARCH)
OBJ_HOST := $(SRC:src/%.c=$(HOST_DIR)/obj/%.o)
OBJ_ARM  := $(SRC:src/%.c=$(ARM_DIR)/obj/%.o)

.DEFAULT_GOAL := host
.PHONY: host arm test bench check-bus check-fuente placa-lib limpiar

host: $(HOST_DIR)/libmca.so

$(HOST_DIR)/obj/%.o: src/%.c $(HDR)
	@mkdir -p $(dir $@)
	$(CC_HOST) $(CFLAGS_LIB) -c $< -o $@

$(HOST_DIR)/libmca.so: $(OBJ_HOST)
	$(CC_HOST) -shared -o $@ $^ $(LDLIBS)

test: $(HOST_DIR)/test_bus
	./$(HOST_DIR)/test_bus

$(HOST_DIR)/test_bus: tests/test_bus.c $(OBJ_HOST) $(HDR)
	$(CC_HOST) $(CFLAGS) -Iinclude -o $@ tests/test_bus.c $(OBJ_HOST) $(LDLIBS)

bench: $(HOST_DIR)/bench_libmca

$(HOST_DIR)/bench_libmca: tests/bench_libmca.c $(OBJ_HOST) $(HDR)
	$(CC_HOST) $(CFLAGS) -Iinclude -o $@ tests/bench_libmca.c $(OBJ_HOST) $(LDLIBS)

# En la placa HOST_ARCH ya es armv7l: `make host` ES el build de ARM, con el
# gcc nativo, y no hay cruzado que definir.
ifneq ($(HOST_ARCH),$(ARM_ARCH))
arm: $(ARM_DIR)/libmca.so $(ARM_DIR)/bench_libmca

$(ARM_DIR)/bench_libmca: tests/bench_libmca.c $(OBJ_ARM) $(HDR)
	$(CC_ARM) $(CFLAGS) -Iinclude -o $@ tests/bench_libmca.c $(OBJ_ARM) $(LDLIBS)

$(ARM_DIR)/obj/%.o: src/%.c $(HDR)
	@mkdir -p $(dir $@)
	$(CC_ARM) $(CFLAGS_LIB) -c $< -o $@

$(ARM_DIR)/libmca.so: $(OBJ_ARM)
	$(CC_ARM) -shared -o $@ $^ $(LDLIBS)
else
arm: host bench
endif

check-bus: arm
	sh scripts/check_bus.sh $(OBJDUMP_ARM) $(NM_ARM) $(ARM_DIR)/obj/bus_devmem.o \
	  $(ARM_DIR)/libmca.so $(GLIBC_MAX)

# Sólo la parte de check-bus que no necesita el cruzado: que el acceso de
# dispositivo viva en un único fichero. Corre en cualquier máquina.
check-fuente:
	@otros=$$(grep -lw volatile src/*.c src/*.h include/*.h | grep -v '/bus_devmem\.c$$' || true); \
	 if [ -n "$$otros" ]; then echo "FALLA: volatile fuera de bus_devmem.c: $$otros"; exit 1; fi; \
	 echo "check-fuente: OK"

# Respaldo del cruzado: si el .so de acá no carga en la placa (glibc), se
# compila allá con su propio gcc, que es como ya se compila bench_reader_c.c.
placa-lib:
	rsync -az --exclude build/ ./ $(PITAYA):$(REMOTO)/libmca/
	ssh $(PITAYA) 'make -C $(REMOTO)/libmca host bench'

limpiar:
	rm -rf build
