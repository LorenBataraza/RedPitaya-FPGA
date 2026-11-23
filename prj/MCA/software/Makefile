# Makefile del software del MCA: verificación, simulaciones y campañas.
#
#   make                      ayuda
#   make verificar            TODO lo que corre en una PC (sin placa, sin Rigol)
#   make verificar-placa      TODO lo que necesita la Red Pitaya
#   make montecarlo           las simulaciones
#   make campana-mca          la campaña de caracterización del MCA (placa + Rigol)
#   make app                  LA SESIÓN: servidor + generador + GUI, de una
#   make app-demo             la GUI andando contra un MCA falso, sin placa
#   make app-placa            la GUI contra la Pitaya, sin tocar el generador
#   make placa-estado         ¿dónde estoy? ¿responde la placa? ¿qué PL tiene?
#   make release              el paquete instalable: bitstream + software + instalador
#
# Los nombres van por familias, y el prefijo dice de cuál es cada objetivo:
#
#   verificar-*   lo que aprueba o falla          placa-*      despliegue y estado
#   montecarlo-*  simulaciones                    rigol-*      el generador
#   campana-*     medidas sobre hardware          app-*        cliente y servidor
#   graficar-*    reprocesado de lo ya medido     limpiar-*    borrado por categoría
#   release-*     el paquete instalable y su publicación en GitHub
#
# Y el sufijo `-remoto` compone: `verificar-placa-app` corre EN la Pitaya,
# `verificar-placa-app-remoto` sincroniza, lo corre allá por ssh y trae los datos.
#
# "testbench" es ambigua en este proyecto y acá se desambigua: los testbenches
# de RTL (SystemVerilog, QuestaSim) NO están en este fichero. Corren con
# `make -C ../sim`, o `make rtl` desde prj/MCA.

PY     ?= python3
PYTEST ?= $(PY) -m pytest
PFLAGS ?=

RAIZ   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
STAMP  := $(shell date +%Y%m%d_%H%M%S)

# Campañas: dónde guardar y con qué canales.
OUT      ?= datos/mca_$(STAMP)
DIR      ?=
CH       ?= 0
GEN_CH   ?= 1
DURACION ?= 60
THR      ?= 0.2

# Estímulo del Rigol (rigol-*, verificar-placa-app). TASA en pulsos/s y AMP en
# Vpp con la convención de la campaña: base en AMP/2 y pico en AMP, o sea altura
# de pulso AMP/2 -> ~2458 cuentas de ADC con AMP=0.6 en LV.
TASA     ?= 3000
AMP      ?= 0.6
SEGUNDOS ?= 10

# Detección de placa: el módulo `rp` sólo existe en la Red Pitaya. Se mira el
# directorio en vez de importar, para no pagar el import en cada invocación.
#
# OJO con lo que esto significa: contesta "¿soy la placa?", NO "¿hay una placa?".
# Son dos cosas distintas y confundirlas es lo que hacía que un error de
# ubicación pareciera un problema de red. Ver el mensaje de `exige-placa`.
EN_PLACA := $(shell test -d /opt/redpitaya/lib/python && echo si)
PITAYA   ?= pitaya
REMOTO   ?= /home/jupyter/RedPitaya/remote_soft

# La IP se la preguntamos a ssh en vez de repetirla acá: el alias `pitaya` ya la
# tiene y cambia seguido, así que una segunda copia se desactualiza sola.
IP_PITAYA ?= $(shell ssh -G $(PITAYA) 2>/dev/null | awk '/^hostname /{print $$2}')

# Para el mensaje de error de `exige-placa`: qué se pidió, y qué objetivos
# tienen equivalente remoto. El esquema de nombres hace que el de `X` sea
# `X-remoto`, así que la sugerencia se calcula en vez de escribirse a mano —
# que es como antes terminaba sugiriendo el objetivo equivocado.
OBJETIVO := $(firstword $(MAKECMDGOALS))
REMOTOS  := $(shell grep -oE '^[a-z0-9-]+-remoto:' $(RAIZ)/Makefile | tr -d ':')

# El bitstream. `make placa-sync` NO lo copia (excluye todo lo que no sea
# software), así que el despliegue de la PL es un objetivo aparte y explícito:
# recargar la PL corta el bus AXI y no es algo que deba pasar como efecto
# secundario de sincronizar unos .py.
#
# VARIANTE = <Zynq>_<canales>CH y va en el NOMBRE del bitstream, porque el
# .bit.bin no dice para qué placa es (bootgen le quita la cabecera) y cargar
# uno de 7z010 en una 7z020 deja el FPGA manager trabado hasta reiniciar. Hoy
# la única que se sintetiza es Z10_2CH (la STEMlab 125-14 del banco); una
# Z20_4CH necesita otro top, no otro valor acá. La lista de variantes que
# existen es lo que hay en out/: ver `release`.
#
# En la placa, el software busca `/root/mca_red_pitaya.bit.bin` (BIT_ENLACE):
# es un enlace simbólico al .bit.bin con nombre de variante, así los defaults
# no cambian con la placa y un `ls -l /root` dice qué variante está instalada.
VARIANTE   ?= Z10_2CH
BIT_LOCAL  ?= $(RAIZ)/../out/mca_red_pitaya_$(VARIANTE).bit.bin
BIT_REMOTO ?= /root/$(notdir $(BIT_LOCAL))
BIT_ENLACE ?= /root/mca_red_pitaya.bit.bin

# Todos los bitstreams generados, para la release: los del MCA en out/ y los
# de los otros tops en sus subdirectorios (out/v3_event_ring/). El patrón
# `*_Z*_*CH.bit.bin` ES el contrato: un bitstream sin variante en el nombre no
# entra al paquete, porque el instalador no sabría para qué placa es.
#
# Pero out/ también guarda bitstreams viejos archivados en subdirectorios
# (out/mca_6156e5a3/, out/pre_fase12/...) con el MISMO nombre que el vigente.
# Todos van al mismo out/ del paquete, así que el `cp` los pisaba y quedaba el
# último en orden alfabético: el más viejo. Por eso un nombre que ya está en
# out/ gana sobre los de los subdirectorios, y si dos subdirectorios repiten un
# nombre `release` se planta (BITS_REPETIDOS) en vez de elegir uno a ciegas.
BITS_RAIZ  := $(sort $(wildcard $(RAIZ)/../out/*_Z*_*CH.bit.bin))
BITS_SUB   := $(filter-out $(addprefix %/,$(notdir $(BITS_RAIZ))), \
                $(sort $(wildcard $(RAIZ)/../out/*/*_Z*_*CH.bit.bin)))
BITS_TODOS := $(BITS_RAIZ) $(BITS_SUB)
BITS_REPETIDOS := $(shell printf '%s\n' $(notdir $(BITS_SUB)) | sort | uniq -d)

# release-*: el paquete instalable, para quien sólo quiere USAR el sistema y no
# los 300 MB del repo. La versión sale de un fichero y NO de `git describe` a
# propósito: esto es un fork y los tags que ya tiene (`2.07-48`) son de
# RedPitaya. El tag que publica `release-publicar` se deriva de acá y va
# prefijado (`mca-v...`) para que las dos numeraciones no se pisen nunca.
VERSION  ?= $(shell cat $(RAIZ)/../VERSION 2>/dev/null || echo 0.0.0)
PAQUETE  := mca-$(VERSION)
TAG      := mca-v$(VERSION)
DIST     ?= $(RAIZ)/dist
STAGING  := $(DIST)/.staging
GIT_SHA  := $(shell git -C $(RAIZ) rev-parse --short HEAD 2>/dev/null || echo desconocido)
GIT_RAMA := $(shell git -C $(RAIZ) rev-parse --abbrev-ref HEAD 2>/dev/null || echo -)
SUCIO    := $(shell git -C $(RAIZ)/.. status --porcelain 2>/dev/null | head -1)

# `gh` elige el repo mirando los remotos, y acá hay dos: origin (el fork) y
# upstream (RedPitaya). Publicar contra el equivocado no es un error que se
# quiera descubrir después, así que va explícito.
GH_REPO  ?= LorenBataraza/RedPitaya-FPGA
NOTAS    ?= $(DIST)/NOTAS.md

# Dónde se instala en la placa, y dónde se deja el tarball mientras tanto.
# `/opt/mca` es el default porque es una instalación del sistema; para una
# instalación de usuario va algo bajo /home, y ahí `release-instalar-remoto`
# NO usa sudo (ver el comentario del objetivo).
PREFIJO  ?= /opt/mca
DESCARGA ?= /tmp

# PUERTO: el de la GUI y el servidor falso en ESTA máquina. En la placa se corre
# como root y vale el 1001 por defecto (el de mcpha); en una PC de usuario Linux
# reserva todo lo que está por debajo de 1024, así que acá se usa uno alto.
PUERTO       ?= 5001
PUERTO_PLACA ?= 1001

# Para los scripts que se invocan sueltos (no vía pytest): pytest resuelve la
# raíz con `pythonpath` de pyproject.toml, pero `python3 campanas/x.py` no.
export PYTHONPATH := $(RAIZ):$(PYTHONPATH)

.DEFAULT_GOAL := help

.PHONY: help \
        verificar verificar-liviano verificar-api verificar-app verificar-gui \
        verificar-montecarlo verificar-campanas verificar-modelo verificar-libmca \
        libmca libmca-arm \
        verificar-compat verificar-lint baseline-regenerar \
        verificar-placa verificar-placa-mem verificar-placa-buffer \
        verificar-placa-mca verificar-placa-integration verificar-placa-multitrigger \
        verificar-placa-osciloscope \
        verificar-placa-diag verificar-placa-ring verificar-placa-bus \
        verificar-placa-datapath verificar-placa-e2e verificar-placa-app \
        verificar-placa-lazo verificar-placa-ring-app \
        verificar-placa-bitstream \
        verificar-remoto verificar-placa-remoto verificar-placa-app-remoto \
        montecarlo montecarlo-rapido montecarlo-apilamiento montecarlo-apilamiento-mca1 \
        montecarlo-linea-base montecarlo-pico-carga montecarlo-conformado montecarlo-figuras \
        campana-lista campana-mca campana-campana campana-resto campana-formas \
        campana-e2e campana-poisson campana-politicas campana-politicas-remoto \
        campana-etapas-ring campana-etapas-ring-remoto campana-etapas-ring-red \
        campana-etapas-ring-por-red ring-red-recibir ring-red-convertir bench-tcp-placa \
        campana-meritos-pulsos campana-meritos-pulsos-remoto campana-meritos-pulsos-sim \
        campana-fidelidad-osc campana-fidelidad-osc-remoto campana-fidelidad-osc-sim \
        placa-montar-red placa-desmontar-red \
        campana-deriva campana-adquirir \
        campana-adquirir-remoto campana-deriva-remoto \
        graficar-mca graficar-formas graficar-tasa analizar-estimadores \
        rigol-pulsos rigol-psd rigol-poisson rigol-off \
        rigol-pulsos-remoto rigol-psd-remoto rigol-poisson-remoto \
        rigol-off-remoto \
        app app-off app-estimulo \
        app-demo app-gui app-placa app-servidor app-servidor-falso \
        app-servidor-remoto app-servidor-off-remoto \
        placa-estado placa-sync placa-sync-dry placa-bitstream placa-cargar \
        placa-cargar-remoto \
        release release-verificar release-publicar release-instalar-remoto \
        release-limpiar \
        bench bench-remoto bench-api bench-api-remoto bench-escritura \
        bench-escritura-remoto bench-formatos bench-formatos-remoto \
        exige-placa exige-gui \
        limpiar limpiar-pyc limpiar-cache limpiar-simulaciones limpiar-datos \
        limpiar-todo

# ------------------------------------------------------------------ ayuda ---
help:              ## esta ayuda
	@echo "software del MCA — objetivos disponibles:"
	@echo ""
	@# Se separa el nombre ANTES de ordenar, y con LC_ALL=C. Ordenando la línea
	@# entera, `limpiar:` cae después de `limpiar-todo:` porque el '-' precede al
	@# ':' en ASCII, y el cabeza de cada familia queda al final de los suyos.
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sed 's/:.*## /\t/' | LC_ALL=C sort \
	  | awk -F'\t' '{printf "  %-28s %s\n", $$1, $$2}'
	@echo ""
	@echo "  (P) necesita la Red Pitaya      (R) necesita además el Rigol DG4162"
	@echo "  el sufijo -remoto hace lo mismo, pero EN la placa desde acá"
	@echo ""
	@echo "  esta máquina es la placa: $(if $(EN_PLACA),SÍ,no)   ·   make placa-estado"
	@echo "  variables: OUT=$(OUT)"
	@echo "             CH=$(CH)  GEN_CH=$(GEN_CH)  PITAYA=$(PITAYA)  PUERTO=$(PUERTO)"
	@echo "             TASA=$(TASA) Hz  AMP=$(AMP) Vpp  SEGUNDOS=$(SEGUNDOS)"
	@echo ""
	@echo "  los testbenches de RTL (QuestaSim) van aparte:  make -C ../sim"

# =============================================================================
# verificar-*  ·  lo que aprueba o falla
# =============================================================================

verificar: verificar-libmca verificar-api verificar-app verificar-montecarlo verificar-campanas  ## toda la suite offline (PC)
	@echo "OK: suite offline completa"

# Lo mismo SIN las simulaciones Monte-Carlo. La Pitaya tiene 461 MB de RAM y el
# motor de apilamiento llega a ~380 MB de RSS: el OOM killer se lleva el proceso
# a mitad de la corrida. No es un fallo del código —son simulaciones, no tocan
# hardware y su lugar es la PC— así que `verificar-remoto` corre esto.
verificar-liviano: verificar-libmca verificar-api verificar-app verificar-campanas  ## la suite offline sin Monte-Carlo
	@echo "OK: suite offline (sin Monte-Carlo)"

verificar-api: libmca  ## tests offline de API/ (driver, red, pipeline, análisis)
	$(PYTEST) $(PFLAGS) API/tests

# libmca es la API en C (libmca/Makefile). Los tests de Python la cargan desde
# libmca/build/<arch>/, así que se compila antes de correrlos. En la placa
# `host` ya es ARM y usa el gcc nativo.
libmca:            ## compila libmca para esta máquina (build/<arch>/libmca.so)
	$(MAKE) -s -C libmca host

libmca-arm:        ## compila libmca para la placa, con el cruzado (build/armv7l/)
	$(MAKE) -s -C libmca arm

# check-bus necesita las binutils de ARM: en la PC, el cruzado; en la placa,
# las nativas. Sin ninguna de las dos se saltea y se dice.
verificar-libmca:  ## libmca: tests de C y la regla del bus sobre el binario de ARM
	$(MAKE) -s -C libmca test check-fuente
	@if [ "$$(uname -m)" = armv7l ] || command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; \
	 then $(MAKE) -s -C libmca check-bus; \
	 else echo "(sin binutils de ARM: check-bus salteado)"; fi

verificar-app: libmca  ## tests offline de app/ (servidor, cliente remoto, GUI headless)
	$(PYTEST) $(PFLAGS) app/tests

verificar-montecarlo:  ## tests del motor Monte-Carlo (las réplicas del MCA1 y del MCA2 contra el RTL)
	$(PYTEST) $(PFLAGS) monte-carlo

verificar-campanas: libmca  ## tests offline de los drivers de campaña (MCA simulado)
	$(PYTEST) $(PFLAGS) campanas/tests

verificar-modelo:  ## sólo los modelos de referencia del RTL (estimadores, ring)
	$(PYTEST) $(PFLAGS) API/tests/test_estimadores.py API/tests/test_ring_format.py

verificar-gui: exige-gui libmca  ## la GUI de punta a punta SIN pantalla (lo que corre en CI)
	$(PYTEST) $(PFLAGS) app/tests/test_mcamon_gui.py

verificar-compat:  ## el baseline de compatibilidad sigue valiendo (no escribe)
	$(PY) API/tests/test_compat_api.py

verificar-lint:    ## compila todo y pasa pyflakes si está instalado
	$(PY) -m compileall -q API app campanas monte-carlo *.py
	@command -v pyflakes >/dev/null 2>&1 \
	  && pyflakes API app campanas monte-carlo *.py \
	  || echo "(pyflakes no instalado, salteado)"

# No es `verificar-`: esto ESCRIBE el baseline en vez de comprobarlo.
baseline-regenerar:  ## REGENERA el baseline de compatibilidad (revisar el diff!)
	$(PY) API/tests/gen_compat_baseline.py

# --- las que necesitan la Pitaya --------------------------------------------

verificar-placa: verificar-placa-mem verificar-placa-bus verificar-placa-buffer verificar-placa-mca verificar-placa-integration verificar-placa-multitrigger verificar-placa-osciloscope verificar-placa-ring verificar-placa-generadores  ## (P) toda la batería de placa
	@echo "OK: batería de placa completa"

verificar-placa-mem: exige-placa      ## (P) regresión del SIGBUS al escribir /dev/mem
	$(PY) API/tests/placa/test_rw_dev_mem.py

verificar-placa-bus: exige-placa      ## (P) un registro que cambia mientras se lo lee llega entero (el rdata del CDC)
	$(PY) API/tests/placa/test_bus_lectura_viva.py

verificar-placa-buffer: exige-placa   ## (P) el mismo buffer congelado por rp y por libmca: iguales
	$(PY) API/tests/placa/test_capture_window_np.py

verificar-placa-mca: exige-placa      ## (P) smoke test del bus y los registros del MCA
	$(PY) API/tests/placa/test_mca_hw.py

verificar-placa-integration: exige-placa  ## (P) la región de TOP: C contra Python, y el ruteo
	$(PY) API/tests/placa/test_integration_hw.py

verificar-placa-multitrigger: exige-placa  ## (P) el multitrigger: C contra Python, y armar y desarmar el disparo
	$(PY) API/tests/placa/test_multitrigger_hw.py

verificar-placa-osciloscope: exige-placa  ## (P) el osciloscopio: C contra Python, y la BRAM de un buffer congelado por software
	$(PY) API/tests/placa/test_osciloscope_hw.py

verificar-placa-diag: exige-placa     ## (P) diagnóstico incremental, un paso por invocación
	$(PY) API/tests/placa/diag_mca_hw.py

verificar-placa-ring: exige-placa     ## (P) el event_ring: plumbing PL->DDR, trigger por SW y el lector de C
	$(PY) API/tests/placa/hw_ring_plumbing.py all
	$(PY) API/tests/placa/hw_ring_swtrig.py
	$(PY) API/tests/placa/test_ring_source_placa.py

# Los dos generadores de la FPGA, sin el Rigol: gen_pulsos por el lazo digital contra
# la réplica del MCA (monte-carlo/datos_ref/pulsos_placa_ref.json), y gen_eventos en el
# ring con el patrón. Necesita el bitstream del ring con los generadores (78e26188).
verificar-placa-generadores: exige-placa  ## (P) los dos generadores: gen_pulsos contra la réplica del MCA, gen_eventos en el ring
	$(PY) API/tests/placa/test_generadores_placa.py

verificar-placa-datapath: exige-placa ## (P,R) camino de datos del MCA con señal real
	$(PY) API/tests/placa/test_mca_datapath.py

verificar-placa-e2e: exige-placa      ## (P,R) adquisición end-to-end, deja datos en datos/
	$(PY) API/tests/placa/test_mca_e2e.py

# El único test que cierra el lazo entero: generador -> IN1 -> MCA -> servidor
# -> socket -> MCARemote. Levanta su propio servidor en un puerto de loopback,
# así que no pelea con el del 1001 si hay una GUI conectada.
verificar-placa-app: exige-placa      ## (P,R) LA APLICACIÓN contra pulsos reales del Rigol
	$(PY) app/tests/placa/e2e_rigol_app.py --rate $(TASA) --amp $(AMP) \
	  --segundos $(SEGUNDOS) --channel $(CH) --gen-ch $(GEN_CH) \
	  --outdir $(OUT)

verificar-placa-bitstream: exige-placa  ## (P) comprueba que la PL tenga el bitstream nuevo
	$(PY) campanas/preparar_placa.py

# --- las mismas, lanzadas desde la PC ----------------------------------------

verificar-remoto: placa-sync          ## corre la suite offline EN la Pitaya (sanity del deploy)
	ssh $(PITAYA) 'make -C $(REMOTO) verificar-liviano'

verificar-placa-remoto: placa-sync    ## (P) la batería de placa, EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) verificar-placa'

verificar-placa-app-remoto: placa-sync  ## (R) el e2e de la app EN la Pitaya, y trae los datos
	ssh $(PITAYA) 'make -C $(REMOTO) verificar-placa-app TASA=$(TASA) AMP=$(AMP) \
	  SEGUNDOS=$(SEGUNDOS) CH=$(CH) GEN_CH=$(GEN_CH) OUT=$(OUT)'
	@mkdir -p $(dir $(OUT))
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

# =============================================================================
# montecarlo-*  ·  simulaciones
# =============================================================================

montecarlo: montecarlo-apilamiento montecarlo-linea-base montecarlo-pico-carga montecarlo-conformado  ## todas las simulaciones (~35 min)
	@echo "OK: simulaciones Monte-Carlo completas"

montecarlo-rapido:       ## barrido de apilamiento corto, para ver que corre
	$(PY) monte-carlo/montecarlo.py --n-eventos 5000

montecarlo-apilamiento:  ## Monte-Carlo de apilamiento sobre el MCA2: barrido de tasa (~30 min)
	$(PY) monte-carlo/montecarlo.py

montecarlo-apilamiento-mca1:  ## el barrido viejo, sobre la réplica del MCA1 (~5 min)
	$(PY) monte-carlo/montecarlo.py --mapa MCA1

montecarlo-linea-base:   ## Monte-Carlo del seguidor de línea de base
	$(PY) monte-carlo/linea_base.py

montecarlo-pico-carga:   ## Monte-Carlo pico-vs-carga para dobles y triples, con 1 y 4 ranuras
	$(PY) monte-carlo/pico_vs_carga.py

montecarlo-conformado:   ## Monte-Carlo: forma del pulso contra ruido (Nicholson vs ADC, ~30 s)
	$(PY) monte-carlo/conformado.py

montecarlo-figuras:      ## rehace las figuras del MC desde los .npz guardados. DIR=
	$(PY) monte-carlo/graficar.py $(DIR)
	$(PY) monte-carlo/graficar_base.py $(DIR)

# =============================================================================
# campana-*  ·  medidas sobre hardware
# =============================================================================

campana-lista:     ## lista los tests de campaña disponibles
	$(PY) campanas/testbench_mca.py --list

campana-mca: exige-placa       ## (P,R) campaña completa del MCA -> OUT=
	$(PY) campanas/testbench_mca.py all --outdir $(OUT) --channel $(CH) --gen-ch $(GEN_CH)

campana-mca-%: exige-placa     ## (P,R) un test suelto: make campana-mca-sweep_gate
	$(PY) campanas/testbench_mca.py $* --outdir $(OUT) --channel $(CH) --gen-ch $(GEN_CH)

campana-campana: exige-placa   ## (P,R) campaña con bl_k primero (el orden importa)
	$(PY) campanas/run_campana.py $(OUT)

campana-resto: exige-placa     ## (P,R) amplitud, umbral, par-pulso, tasa. OUT=
	$(PY) campanas/run_resto.py $(OUT)
	$(PY) campanas/run_resto2.py $(OUT)

campana-formas: exige-placa    ## (P,R) INL vs familia de forma de pulso (~20 min)
	$(PY) campanas/run_formas.py $(OUT)

campana-deriva: exige-placa    ## (P,R) tasa vs tiempo: el experimento de deriva. OUT=
	$(PY) campanas/run_deriva.py $(OUT)

campana-e2e: exige-placa       ## (P,R) espectro HW contra espectro SW, mismo estímulo
	$(PY) campanas/e2e_espectro.py --acquire --duration 20

campana-poisson: exige-placa   ## (P,R) pérdidas del lector con arribos Poisson
	$(PY) campanas/run_poisson_loss.py

# Las etapas del event_ring (docs/event_ring/generador.md §6): el estímulo es el
# generador de eventos de la FPGA, sin el Rigol. Necesita el bitstream del ring con
# generadores (78e26188 o posterior): `campanas/preparar_placa.py --cargar --bitstream
# /root/event_ring_red_pitaya_Z10_2CH.bit.bin`. ETAPAS= de A, copia, B y C; el resto
# de las opciones (--ventanas, --tasas, --n, --carga, --destino, --margen-mb) va en
# ARGS=. Con --destino /dev/shm/..., --margen-mb 16: tmpfs tiene 231 MB en la placa.
ETAPAS ?= A,B
campana-etapas-ring: exige-placa  ## (P) las etapas del ring con el generador de la FPGA. OUT= ETAPAS= ARGS=
	$(PY) campanas/run_etapas_ring.py $(OUT) --etapas $(ETAPAS) $(ARGS)

campana-etapas-ring-remoto: placa-sync  ## (P) las etapas del ring EN la Pitaya, y trae el JSON. OUT= ETAPAS= ARGS=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-etapas-ring OUT=$(OUT) ETAPAS=$(ETAPAS) ARGS="$(ARGS)"'
	@mkdir -p $(OUT)
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

# Las figuras de mérito del MCA con el generador de pulsos de la FPGA, sin el Rigol: la
# curva m(n) (tasa), la resolución par-pulso (par), la histéresis de la campaña del Rigol
# con el pulser digital (histeresis, ~6 min), el walk con la curva S y la linealidad
# (walk) y la resolución contra el ruido inyectado (ruido); fuentes ASG, polo-cero y
# pendiente. Necesita un bitstream con gen_pulsos (el MCA cce7b66b o el ring 78e26188 en
# adelante). MODO=digital (el lazo) o MODO=analogico (OUT1 → coaxial → IN1, jumper LV:
# mide el canal con la BRAM antes de las etapas). `-sim` corre lo mismo en la PC sobre el
# modelo del generador y la réplica del MCA (en analógico, con un canal de juguete); dos
# corridas se comparan con `campanas/run_meritos_pulsos.py --comparar a.json b.json`.
# MERITOS= las etapas; el resto (--fuentes, --tasas, --dts, --n-acc, --seg,
# --ruidos-sh...) va en ARGS=.
MERITOS ?= tasa,par,histeresis,walk,ruido
MODO ?= digital
campana-meritos-pulsos: exige-placa  ## (P) figuras de mérito del MCA con gen_pulsos. OUT= MERITOS= MODO= ARGS=
	$(PY) campanas/run_meritos_pulsos.py $(OUT) --etapas $(MERITOS) --modo $(MODO) $(ARGS)

campana-meritos-pulsos-remoto: libmca-arm placa-sync  ## (P) las figuras de mérito EN la Pitaya, y trae el JSON. OUT= MERITOS= MODO= ARGS=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-meritos-pulsos OUT=$(OUT) MERITOS=$(MERITOS) MODO=$(MODO) ARGS="$(ARGS)"'
	@mkdir -p $(OUT)
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

campana-meritos-pulsos-sim: libmca  ## la misma campaña sobre la réplica del MCA, en la PC. OUT= MERITOS= MODO= ARGS=
	$(PY) campanas/run_meritos_pulsos.py $(OUT) --simulada --etapas $(MERITOS) --modo $(MODO) $(ARGS)

# La fidelidad de la captura del osciloscopio con gen_pulsos: cada muestra del ring y de
# la BRAM contra el modelo del generador, bit a bit con MODO=digital (el lazo); con
# MODO=analogico (OUT1 → IN1), contra el canal medido (el FIR del piso y la respuesta),
# más la diafonía a IN2. La placa captura (`medir`, necesita el bitstream del ring
# c1875919 o posterior para la ruta ring; ARGS=--rutas bram con el del MCA) y la PC
# compara (`analizar`), porque el modelo vive en modulos/ y no se sincroniza. `-sim`
# recorre el análisis con capturas ideales.
campana-fidelidad-osc: exige-placa  ## (P) captura con gen_pulsos: ring y BRAM. OUT= MODO= ARGS=
	$(PY) campanas/run_fidelidad_osc.py medir $(OUT) --modo $(MODO) $(ARGS)

campana-fidelidad-osc-remoto: libmca-arm placa-sync  ## (P) captura EN la Pitaya, la trae y la compara con el modelo. OUT= MODO= ARGS=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-fidelidad-osc OUT=$(OUT) MODO=$(MODO) ARGS="$(ARGS)"'
	@mkdir -p $(OUT)
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	$(PY) campanas/run_fidelidad_osc.py analizar $(OUT)

campana-fidelidad-osc-sim: libmca  ## la fidelidad con capturas ideales desde el modelo, en la PC. OUT= MODO=
	$(PY) campanas/run_fidelidad_osc.py medir $(OUT) --simulada --modo $(MODO) $(ARGS)
	$(PY) campanas/run_fidelidad_osc.py analizar $(OUT)

# El techo del camino original del osciloscopio, la BRAM, con gen_pulsos y el disparo del
# ASG: el lector de C (libmca) y el lazo original de Python con librp, contra el largo de
# la ventana (techo) y contra la tasa de Poisson (tasa). Docs: resultados_meritos_gen_pulsos.md §3.3.
campana-techo-bram: exige-placa  ## (P) eventos leídos por segundo de la BRAM. OUT= ARGS=
	$(PY) campanas/run_techo_bram.py $(OUT) $(ARGS)

campana-techo-bram-remoto: libmca-arm placa-sync  ## (P) el techo de la BRAM EN la Pitaya, y trae el JSON. OUT= ARGS=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-techo-bram OUT=$(OUT) ARGS="$(ARGS)"'
	@mkdir -p $(OUT)
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

# La etapa C por la red (docs/event_ring/generador.md §6): la sesión corre en el
# servidor de la placa (las ops ring.*) y escribe en un directorio de la PC montado
# por NFS en la placa; la campaña corre ACÁ y verifica en ese mismo directorio. Hace
# falta: el directorio exportado a la placa (/etc/exports: lo de la PC es con sudo),
# el montaje (`make placa-montar-red`), el bitstream del ring y el servidor
# (`make app-servidor-remoto`). La placa no trae mount.nfs: se monta con las opciones
# del kernel, dando los puertos (mountd fijo en 20048, en /etc/nfs.conf de la PC).
PC_IP    ?= $(shell ip -4 route get $(IP_PITAYA) 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
PC_DIR   ?= $(HOME)/pitaya_red
MONTAJE  ?= /mnt/pc
OPC_NFS  ?= vers=3,proto=tcp,port=2049,mountproto=tcp,mountport=20048,nolock

placa-montar-red:  ## (P) monta PC_DIR de la PC en MONTAJE de la placa, por NFS. PC_IP= PC_DIR= MONTAJE=
	@test -n "$(PC_IP)" || { echo "no pude sacar la IP de esta PC hacia la placa: PC_IP="; exit 1; }
	ssh $(PITAYA) 'mkdir -p $(MONTAJE) && { mountpoint -q $(MONTAJE) || mount -t nfs -o $(OPC_NFS),addr=$(PC_IP) $(PC_IP):$(PC_DIR) $(MONTAJE); } && grep " $(MONTAJE) " /proc/mounts'

placa-desmontar-red:  ## (P) desmonta MONTAJE de la placa
	ssh $(PITAYA) 'if mountpoint -q $(MONTAJE); then umount $(MONTAJE) && echo desmontado; else echo "$(MONTAJE) no estaba montado"; fi'

campana-etapas-ring-red:  ## (P) la etapa C por la red, desde esta PC (servidor + montaje). OUT= ARGS=
	$(PY) campanas/run_etapas_ring.py $(OUT) --etapas C --red $(IP_PITAYA):$(PUERTO_PLACA) --destino $(MONTAJE)/etapas --destino-pc $(PC_DIR)/etapas $(ARGS)

# El ring por red (docs/event_ring/salida_por_red.md): la placa manda los slots por un
# socket desde C (EmisionRing, ring.iniciar destino=red), sin sesión ni archivos allá,
# y esta PC los recibe (API/ring_red.py). No hace falta montar nada: la PC se conecta a
# un puerto de la placa. Hace falta el bitstream del ring y el servidor con libmca
# 0.12.0 o posterior: después de `make libmca-arm placa-sync`, reiniciarlo
# (`make app-servidor-off-remoto app-servidor-remoto`). Para medir el techo, la PC
# tiene que estar cableada a la misma red que la placa: por WiFi o por un ruteo se
# mide el enlace, no la placa. Primero `bench-tcp-placa`, que es el techo de TCP solo.
campana-etapas-ring-por-red:  ## (P) las etapas D0 y D (el ring por red), desde esta PC. OUT= ARGS=
	$(PY) campanas/run_etapas_ring.py $(OUT) --etapas D0,D --red $(IP_PITAYA):$(PUERTO_PLACA) $(ARGS)

RED_DIR ?= $(HOME)/pitaya_red/ring
RED_SEG ?= 10
ring-red-recibir:  ## (P) una corrida del ring por red a RED_DIR, en esta PC. RED_SEG= ARGS= (p. ej. --generador 1e5)
	$(PY) -m API.ring_red recibir --host $(IP_PITAYA) --puerto $(PUERTO_PLACA) --dir $(RED_DIR) --segundos $(RED_SEG) $(ARGS)

ring-red-convertir:  ## los ring_*.bin de RED_DIR a chunk_*.npz y run_summary.json. ARGS=
	$(PY) -m API.ring_red convertir $(RED_DIR) $(ARGS)

TCP_PUERTO ?= 5099
TCP_MB     ?= 1024
bench-tcp-placa:  ## (P) TCP de la placa a esta PC, sin nada más: el techo del ring por red. TCP_MB=
	@ssh $(PITAYA) 'python3 - servir --puerto $(TCP_PUERTO) --mb $(TCP_MB)' \
	   < campanas/bench_tcp_placa.py & \
	 $(PY) campanas/bench_tcp_placa.py recibir --host $(IP_PITAYA) --puerto $(TCP_PUERTO); \
	 wait

# La validación en silicio de las fases 1 y 2. `SOLO=invariantes` corre sólo
# las identidades del teselado, que es lo primero a mirar con un bitstream
# nuevo y tarda segundos; sin SOLO corre las cinco secciones (~5 min).
campana-politicas: exige-placa  ## (P,R) teselado + políticas de ventana en placa. OUT= SOLO=
	$(PY) campanas/run_politicas.py $(OUT) $(if $(SOLO),--solo $(SOLO),)

campana-politicas-remoto: placa-sync  ## (R) la validación de políticas EN la Pitaya, y trae los datos
	ssh $(PITAYA) 'make -C $(REMOTO) campana-politicas OUT=$(OUT) SOLO=$(SOLO)'
	@mkdir -p $(OUT)
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

# `--out $(OUT)` y no el default de run_acquire.py (/home/jupyter/RedPitaya/DATOS):
# escribiendo bajo el árbol del repo, `campana-adquirir-remoto` puede traerse los
# datos con el mismo rsync que el resto de la familia. Fuera del árbol no hay
# forma de recuperarlos sin un comando a mano, y era el único camino de datos del
# proyecto que no tenía vuelta.
campana-adquirir: exige-placa  ## (P) adquisición continua a chunks. DURACION= THR= OUT=
	$(PY) campanas/run_acquire.py --duration $(DURACION) --thr $(THR) --out $(OUT)

campana-adquirir-remoto: placa-sync  ## (P) adquiere EN la Pitaya y trae los chunks. DURACION= THR= OUT=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-adquirir DURACION=$(DURACION) \
	  THR=$(THR) OUT=$(OUT)'
	@mkdir -p $(dir $(OUT))
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

campana-deriva-remoto: placa-sync  ## corre el experimento de deriva EN la Pitaya. OUT=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-deriva OUT=$(OUT)'
	@echo "traé los datos con:  rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/"

# --- reprocesado de lo ya medido: NO necesita placa --------------------------

graficar-mca:      ## regrafica una campaña del MCA sin placa. DIR=datos/mca_...
	$(PY) campanas/testbench_mca.py --plot-only --outdir $(DIR)

graficar-formas:   ## catálogo de formas de pulso en volts vs microsegundos
	$(PY) campanas/graficar_formas.py

graficar-tasa:     ## tasas medidas contra los tres modelos de tiempo muerto
	$(PY) campanas/plot_modelos_tasa.py

analizar-estimadores:  ## compara los estimadores sobre pulsos reales guardados
	$(PY) campanas/analizar_estimadores.py

# =============================================================================
# rigol-*  ·  la salida del generador
# =============================================================================
# Sueltos, para que el estímulo sobreviva al proceso que lo prendió: mirar el
# espectro crecer en la GUI, o depurar umbrales a mano.

rigol-pulsos: exige-placa  ## (P,R) enciende el tren de pulsos. TASA= AMP=
	$(PY) campanas/estimulo.py on --rate $(TASA) --amp $(AMP) --ch $(GEN_CH)

rigol-psd: exige-placa     ## (P,R) dos poblaciones (misma altura, distinta cola)
	$(PY) campanas/estimulo.py on --dos-poblaciones --rate $(TASA) \
	  --amp $(AMP) --ch $(GEN_CH)

# El tren periódico es un estímulo BENIGNO: con arribos deterministas y un solo
# servidor sin cola no se pierde nada mientras el período supere el tiempo de
# servicio. Una fuente real entrega Poisson y ahí se pierde rho/(1+rho) a
# cualquier tasa. Éste es el estímulo con el que el apilamiento y el tiempo
# muerto que muestra la GUI se parecen a los de una medida de verdad.
#
# EVENTOS es el largo del ciclo, y el ciclo SE REPITE: los arribos son Poisson
# adentro, no entre ciclos. Con pulsos de 2 us el máximo entra en ~2 ms de
# patrón a cualquier tasa; por debajo de ~500 Hz no entra ni un evento y hay
# que ensanchar el pulso.
EVENTOS ?=
SEMILLA ?= 0

rigol-poisson: exige-placa  ## (P,R) arribos de POISSON (apilamiento realista). TASA= EVENTOS=
	$(PY) campanas/estimulo.py on --poisson --rate $(TASA) --amp $(AMP) \
	  --ch $(GEN_CH) --semilla $(SEMILLA) $(if $(EVENTOS),--eventos $(EVENTOS),)

rigol-off: exige-placa     ## (P,R) apaga la salida del generador
	$(PY) campanas/estimulo.py off --ch $(GEN_CH)

rigol-pulsos-remoto: placa-sync  ## (R) enciende el generador EN la Pitaya. TASA= AMP=
	ssh $(PITAYA) 'make -C $(REMOTO) rigol-pulsos TASA=$(TASA) AMP=$(AMP) GEN_CH=$(GEN_CH)'

rigol-psd-remoto: placa-sync     ## (R) dos poblaciones EN la Pitaya (para el mapa 2D)
	ssh $(PITAYA) 'make -C $(REMOTO) rigol-psd TASA=$(TASA) AMP=$(AMP) GEN_CH=$(GEN_CH)'

rigol-poisson-remoto: placa-sync  ## (R) arribos de Poisson EN la Pitaya. TASA= EVENTOS=
	ssh $(PITAYA) 'make -C $(REMOTO) rigol-poisson TASA=$(TASA) AMP=$(AMP) \
	  GEN_CH=$(GEN_CH) EVENTOS=$(EVENTOS) SEMILLA=$(SEMILLA)'

rigol-off-remoto:                ## (R) apaga el generador EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) rigol-off GEN_CH=$(GEN_CH)'

# =============================================================================
# app-*  ·  el cliente y el servidor
# =============================================================================

exige-gui:
	@$(PY) -c 'import PyQt5, matplotlib' 2>/dev/null || { \
	  echo ""; \
	  echo "  '$(OBJETIVO)' es la GUI, y necesita PyQt5 y matplotlib en ESTA máquina."; \
	  echo ""; \
	  echo "    Debian/Ubuntu:  sudo apt install python3-pyqt5 python3-matplotlib"; \
	  echo ""; \
	  echo "  La placa NO los necesita: allá sólo corre el servidor (app-servidor),"; \
	  echo "  que no importa ni PyQt5 ni matplotlib."; \
	  echo ""; \
	  exit 1; }

app-demo: exige-gui libmca  ## PROBAR LA GUI sin placa: servidor falso + mcamon conectado
	@echo "servidor falso en 127.0.0.1:$(PUERTO) + mcamon; Ctrl-C o cerrar la ventana para salir"
	@LOG=$$(mktemp); \
	 $(PY) app/mca_server.py --fake --host 127.0.0.1 --port $(PUERTO) >$$LOG 2>&1 & \
	 SRV=$$!; \
	 trap 'kill $$SRV 2>/dev/null; rm -f $$LOG' EXIT INT TERM HUP; \
	 for i in $$(seq 40); do \
	   grep -q escuchando $$LOG && break; \
	   kill -0 $$SRV 2>/dev/null || break; \
	   sleep 0.1; \
	 done; \
	 if ! grep -q escuchando $$LOG; then \
	   echo "el servidor falso no llegó a escuchar:"; cat $$LOG; exit 1; fi; \
	 $(PY) app/mcamon.py --host 127.0.0.1 --port $(PUERTO) --conectar; \
	 echo "--- log del servidor falso ---"; [ -f $$LOG ] && cat $$LOG; true

app-gui:           ## abre mcamon solo. SERVIDOR=host PUERTO=n
	$(PY) app/mcamon.py $(if $(SERVIDOR),--host $(SERVIDOR),) --port $(PUERTO)

app-servidor: exige-placa  ## (P) levanta mca_server en la placa
	$(PY) app/mca_server.py

app-servidor-falso: libmca  ## sólo el servidor con MCA falso. PUERTO=n
	$(PY) app/mca_server.py --fake --port $(PUERTO)

# --- la app contra la placa --------------------------------------------------
#
# Tres trampas distintas, con tres soluciones distintas:
#
# Para PARAR: `pkill -f "[m]ca_server.py"`. pgrep/pkill -f comparan contra la
# línea de comando entera, y la del propio ssh contiene el patrón; con los
# corchetes la expresión regular sigue casando el proceso buscado pero no a sí
# misma. Sin esto, pkill se lleva la sesión de ssh y deja el servidor vivo
# (pasó, y el diagnóstico es confuso: el comando "funciona" y no hace nada).
#
# Para SABER SI YA CORRE no alcanza el truco: el mismo comando que pregunta
# lleva adentro el `app/mca_server.py` con el que arrancaría, o sea una
# aparición SIN corchetes que se casa sola. El guard daba siempre "ya está
# corriendo" y nunca levantaba nada. Se pregunta por el puerto escuchando, que
# es además la condición que de verdad importa.
#
# Y para ARRANCARLO hace falta `ssh -f`. El idioma habitual —`setsid nohup cmd
# </dev/null >log 2>&1 &`— NO alcanza acá: medido en la placa, el servidor
# quedaba con `1 -> pipe` y `2 -> pipe` en /proc/<pid>/fd, o sea reteniendo las
# tuberías de ssh, y ssh no volvía nunca (el `</dev/null` sí se aplicaba: fd 0
# era /dev/null, los otros dos no). Con `-f` ssh se va al fondo del lado local
# después de autenticar y el problema desaparece. El `> /dev/null` del `ssh -f`
# es lo mismo un nivel más arriba: ese ssh queda vivo del lado local y hereda el
# stdout de make, así que quien lea la salida por una tubería espera para
# siempre aunque make ya terminó.
#
# El precio es un ssh local vivo mientras dure el servidor; se va solo con
# `app-servidor-off-remoto`. Si esto tiene que sobrevivir a reinicios, lo que
# corresponde es una unidad de systemd en la placa, no más Makefile.

app-servidor-remoto: placa-sync  ## (P) levanta mca_server en la Pitaya y lo deja corriendo
	@ssh $(PITAYA) 'ss -ltn 2>/dev/null | grep -q ":$(PUERTO_PLACA) "' \
	  && echo "ya había un servidor escuchando en el $(PUERTO_PLACA)" \
	  || { ssh -f $(PITAYA) 'cd $(REMOTO) && exec python3 app/mca_server.py \
	         --port $(PUERTO_PLACA) < /dev/null > /tmp/mca_server.log 2>&1' \
	         > /dev/null 2>&1; \
	       sleep 2; ssh $(PITAYA) 'tail -2 /tmp/mca_server.log'; }

app-servidor-off-remoto:  ## (P) para el mca_server de la Pitaya
	@ssh $(PITAYA) 'pkill -f "[m]ca_server.py" && echo "servidor detenido" \
	   || echo "no había servidor corriendo"'

app-placa: exige-gui app-servidor-remoto  ## servidor + GUI, SIN tocar el generador
	@test -n "$(IP_PITAYA)" || { \
	  echo "ERROR: no pude sacar la IP de '$(PITAYA)' de la config de ssh."; \
	  echo "       pasala a mano:  make app-placa IP_PITAYA=10.73.28.27"; \
	  exit 1; }
	@echo "mcamon -> $(IP_PITAYA):$(PUERTO_PLACA)  (el servidor queda corriendo"
	@echo " al salir; pararlo con: make app-servidor-off-remoto)"
	$(PY) app/mcamon.py --host $(IP_PITAYA) --port $(PUERTO_PLACA) --conectar

# La aplicación con el generador de pulsos por el lazo digital, sin el Rigol. Corre
# EN LA PC contra el servidor del 1001, el mismo camino que la GUI, y deja la placa
# como estaba: generador parado, lazo apagado y disparo desarmado.
verificar-placa-lazo: app-servidor-remoto  ## (P) la app con el generador por el lazo digital, sin el Rigol
	$(PY) app/tests/placa/e2e_lazo_app.py --host $(IP_PITAYA) --port $(PUERTO_PLACA)

# El ring de «OSC settings», con el bitstream del ring cargado (c1875919 o posterior): tres
# corridas desde la pestaña, sin pantalla (el generador con N, Poisson sin fin con el
# ring lleno, el disparo del ADC por el lazo), y que al parar se lea todo lo capturado.
# Borra sus corridas de la placa; con ARGS=--guardar quedan.
verificar-placa-ring-app: app-servidor-remoto  ## (P) el ring de la app contra el bitstream del ring
	$(PY) app/tests/placa/e2e_ring_app.py --host $(IP_PITAYA) --port $(PUERTO_PLACA) \
	  --ssh $(PITAYA) $(ARGS)

# --- la sesión entera --------------------------------------------------------
#
# `app-placa` levanta el servidor y abre la GUI, pero deja el generador como
# estuviera: si nadie inyecta pulsos el espectro se queda plano y lo primero
# que uno hace es abrir otra terminal para prender el Rigol. `app` es las tres
# cosas de una: servidor en la placa, estímulo en el generador, cliente acá.
#
# Se compone de objetivos que ya existen en vez de duplicar sus recetas, así
# que las tres trampas del ssh (ver el bloque de arriba) se resuelven en un
# solo lugar.
#
# ESTIMULO se valida en tiempo de PARSEO y no en la receta: si se valida en la
# receta, un typo hace que primero se sincronice el árbol y se levante el
# servidor, y recién después falle. Se restringe a `app` para que un `make
# help` con ESTIMULO mal puesto no muera.
ESTIMULO ?= pulsos

ifneq ($(filter app,$(MAKECMDGOALS)),)
ifeq ($(filter $(ESTIMULO),pulsos psd poisson ninguno),)
$(error ESTIMULO='$(ESTIMULO)' no existe. Elegí: pulsos | psd | poisson | ninguno)
endif
endif

app-estimulo:
	@case '$(ESTIMULO)' in \
	  ninguno) echo "generador: no se toca (ESTIMULO=ninguno)" ;; \
	  *) $(MAKE) --no-print-directory rigol-$(ESTIMULO)-remoto ;; \
	esac

app: exige-gui app-servidor-remoto app-estimulo  ## LA SESIÓN: servidor + generador + GUI. ESTIMULO= TASA=
	@test -n "$(IP_PITAYA)" || { \
	  echo "ERROR: no pude sacar la IP de '$(PITAYA)' de la config de ssh."; \
	  echo "       pasala a mano:  make app IP_PITAYA=10.73.28.27"; \
	  exit 1; }
	@echo ""
	@echo "  servidor   : $(PITAYA):$(PUERTO_PLACA)"
	@echo "  estímulo   : $(ESTIMULO) a $(TASA) Hz, $(AMP) Vpp por CH$(GEN_CH)"
	@echo "  cliente    : mcamon -> $(IP_PITAYA):$(PUERTO_PLACA)"
	@echo ""
	@echo "  Al cerrar la ventana, el servidor y el generador QUEDAN andando"
	@echo "  (a propósito: una medida larga sobrevive a cerrar la GUI)."
	@echo "  Para cerrar la sesión entera:   make app-off"
	@echo ""
	$(PY) app/mcamon.py --host $(IP_PITAYA) --port $(PUERTO_PLACA) --conectar

# Los dos con `-` porque son independientes: que no haya servidor no es motivo
# para dejar el generador inyectando pulsos, ni al revés.
app-off:  ## cierra la sesión de `app`: apaga el generador y para el servidor
	-@$(MAKE) --no-print-directory rigol-off-remoto
	-@$(MAKE) --no-print-directory app-servidor-off-remoto

# =============================================================================
# placa-*  ·  despliegue y estado de la Pitaya
# =============================================================================

# El guard, y su mensaje.
#
# El de antes decía "esto necesita la Red Pitaya (no está /opt/redpitaya/...)",
# que se lee como "no encuentro la placa" cuando lo que pasa es otra cosa: la
# placa está perfecta y el objetivo corre ALLÁ. Acá se separan las dos
# condiciones, y en el camino de fallo se sondea de verdad — cuesta un segundo
# y ya estamos fallando, así que es barato decir la verdad completa.
exige-placa:
	@test -n "$(EN_PLACA)" || { \
	  echo ""; \
	  echo "  '$(OBJETIVO)' corre EN la Red Pitaya, y esta máquina es la PC."; \
	  echo "  (se reconoce la placa por /opt/redpitaya/lib/python, que acá no existe)"; \
	  echo ""; \
	  H=$$(ssh -o ConnectTimeout=3 -o BatchMode=yes $(PITAYA) hostname 2>/dev/null); \
	  if [ -n "$$H" ]; then \
	    echo "  La placa está bien: $(PITAYA) -> $(IP_PITAYA) responde ($$H)."; \
	  else \
	    echo "  Y además no pude contactarla: 'ssh $(PITAYA)' no responde."; \
	    echo "    La IP vive en ~/.ssh/config.d/$(PITAYA) y cambia seguido."; \
	    echo "    Comprobá con:  ssh $(PITAYA) hostname   ·   o:  make placa-estado"; \
	  fi; \
	  echo ""; \
	  case " $(REMOTOS) " in \
	    *" $(OBJETIVO)-remoto "*) \
	      echo "    desde acá:    make $(OBJETIVO)-remoto" ;; \
	  esac; \
	  echo "    o entrando:   ssh $(PITAYA)   y allá:   make -C $(REMOTO) $(OBJETIVO)"; \
	  echo ""; \
	  exit 1; }

# La sonda del bus va por stdin y no como `python3 -c "..."` dentro del ssh:
# anidar comillas de make, de sh, de ssh y de Python en la misma línea es
# imposible de leer y se rompió a la primera. Por stdin, el fuente viaja tal
# cual y no hay una sola comilla que escapar.
define SONDA_PL
import mmap, os, struct
try:
    estado = open('/sys/class/fpga_manager/fpga0/state').read().strip()
except OSError:
    estado = 'sin fpga_manager'


def leer(fd, base, *offs):
    m = mmap.mmap(fd, 4096, offset=base)
    try:
        return [struct.unpack_from('<I', m, o)[0] for o in offs]
    finally:
        m.close()


try:
    fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
    magic, caps, w, n_acc = leer(fd, 0x40700000, 0x000, 0x004, 0x008, 0x11C)
    canales = 1 << (w & 0xFF)
    if magic == 0x4D434132:
        mapa = ('%d x %d' % (1 << ((w >> 8) & 0xFF), 1 << ((w >> 16) & 0xFF))
                if caps & 2 else 'no')
        pl = 'MCA2 · %d ranuras · %d canales · mapa 2D %s · trapecio %s' % (
            n_acc, canales, mapa, 'sí' if caps & 4 else 'no')
    elif magic == 0x4D434131:
        pl = 'MCA1 (el mapa anterior; la API pide MCA2) · %d canales · mapa 2D %s' % (
            canales, 'sí' if caps & 2 else 'no')
    else:
        pl = 'sin MCA en el slot 7 (magic %#010x)' % magic
    ring = leer(fd, 0x40200000, 0x50)[0] == 0x45564E54
    pl += ' · ring en el slot 2: %s' % ('sí' if ring else 'no')
except Exception as e:
    pl = 'no se pudo leer el bus (%s)' % type(e).__name__
print('%s · %s' % (estado, pl))
endef
export SONDA_PL

# Lo que uno averigua a mano antes de una sesión, de una sola vez. Cada línea se
# degrada sola: sin ssh, las de abajo dicen que no se pudo consultar en vez de
# fallar. Es lo que hay que correr cuando algo no anda.
placa-estado:      ## ¿dónde estoy? ¿responde la placa? ¿qué PL tiene? ¿hay servidor?
	@echo "esta máquina  : $(if $(EN_PLACA),la Red Pitaya,la PC (no es la placa))"
	@H=$$(ssh -o ConnectTimeout=3 -o BatchMode=yes $(PITAYA) hostname 2>/dev/null); \
	 if [ -z "$$H" ]; then \
	   echo "alias ssh     : $(PITAYA) -> $(IP_PITAYA), NO responde"; \
	   echo "                la IP está en ~/.ssh/config.d/$(PITAYA) y cambia seguido"; \
	   echo "PL            : no se pudo consultar (sin ssh)"; \
	   echo "servidor      : no se pudo consultar (sin ssh)"; \
	   echo "generador     : no se pudo consultar (sin ssh)"; \
	   echo "árbol remoto  : no se pudo consultar (sin ssh)"; \
	   exit 0; \
	 fi; \
	 echo "alias ssh     : $(PITAYA) -> $(IP_PITAYA), responde ($$H)"; \
	 printf '%s' "$$SONDA_PL" | ssh $(PITAYA) python3 - \
	   | sed 's/^/PL            : /'; \
	 ssh $(PITAYA) 'ss -ltn 2>/dev/null | grep -q ":$(PUERTO_PLACA) " \
	     && echo "escuchando en el $(PUERTO_PLACA)" \
	     || echo "no hay ninguno corriendo (make app-servidor-remoto)"' \
	   | sed 's/^/servidor      : /'; \
	 ssh $(PITAYA) 'lsusb 2>/dev/null | grep -oE "Rigol.*" | head -1 \
	     || echo "no se ve el Rigol por USB"' \
	   | sed 's/^/generador     : /'; \
	 N=$$(rsync -azn --itemize-changes \
	    --exclude 'datos/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
	    --exclude '*.ipynb' --exclude '.ipynb_checkpoints/' --exclude '*.npz' \
	    $(RAIZ)/ $(PITAYA):$(REMOTO)/ 2>/dev/null | grep -c '^[<>]'); \
	 if [ "$$N" = "0" ]; then echo "árbol remoto  : al día"; \
	 else echo "árbol remoto  : $$N ficheros por sincronizar (make placa-sync)"; fi

# SIN --delete, a propósito. La placa tiene ficheros que el repo NO tiene —el
# bitstream cargado, `campana.py`, una docena de `diag_rate*.py`— y un --delete
# los borra sin aviso. Si de verdad querés limpiar lo que sobra, mirá primero
# qué se llevaría con `make placa-sync-dry` y recién entonces decidilo a mano.
# Un despliegue no debería poder destruir trabajo que sólo vive en el destino.
placa-sync:        ## rsync del árbol a la Pitaya (aditivo: NO borra nada)
	rsync -az \
	  --exclude 'datos/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
	  --exclude '*.ipynb' --exclude '.ipynb_checkpoints/' --exclude '*.npz' \
	  $(RAIZ)/ $(PITAYA):$(REMOTO)/

placa-sync-dry:    ## qué borraría un sync con --delete (no toca nada)
	@echo "ficheros que sólo existen en la placa y un --delete se llevaría:"
	@rsync -az --delete --dry-run --itemize-changes \
	  --exclude 'datos/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
	  --exclude '*.ipynb' --exclude '.ipynb_checkpoints/' --exclude '*.npz' \
	  $(RAIZ)/ $(PITAYA):$(REMOTO)/ | grep '^\*deleting' || echo "  (ninguno)"

placa-bitstream:   ## copia el .bit.bin a la Pitaya (SOBREESCRIBE; no lo carga)
	@test -f $(BIT_LOCAL) || { \
	  echo "ERROR: no existe $(BIT_LOCAL)."; \
	  echo "       corré la síntesis primero (make -C ../.. o el flujo de Vivado)."; \
	  exit 1; }
	@echo "copiando $(BIT_LOCAL)"
	@echo "     ->  $(PITAYA):$(BIT_REMOTO)   (sobreescribe el que haya)"
	scp $(BIT_LOCAL) $(PITAYA):$(BIT_REMOTO)
	@# Verificar la copia: un .bit.bin truncado programa la PL con basura, y el
	@# síntoma sería un MCA que no contesta o que contesta cualquier cosa.
	@L=$$(md5sum $(BIT_LOCAL) | cut -d' ' -f1); \
	 R=$$(ssh $(PITAYA) "md5sum $(BIT_REMOTO)" | cut -d' ' -f1); \
	 if [ "$$L" = "$$R" ]; then echo "md5 coincide: $$L"; \
	 else echo "ERROR: md5 distinto (local $$L, remoto $$R)"; exit 1; fi
	@# El nombre estable que buscan los defaults apunta al de la variante.
	ssh $(PITAYA) "ln -sfn $(BIT_REMOTO) $(BIT_ENLACE)"
	@echo "$(BIT_ENLACE) -> $(BIT_REMOTO)"

placa-cargar: exige-placa  ## (P) programa la PL con $(BIT_REMOTO) y verifica
	$(PY) campanas/preparar_placa.py --cargar --bitstream $(BIT_REMOTO)

placa-cargar-remoto: placa-bitstream placa-sync  ## copia bitstream+software, PROGRAMA la PL y verifica
	ssh $(PITAYA) 'make -C $(REMOTO) placa-cargar'

# =============================================================================
# release-*  ·  el paquete instalable
# =============================================================================
#
# Para quien sólo quiere USAR el sistema. El repo son ~300 MB de clone y 5000
# ficheros de RTL, netlists y checkpoints de Vivado; lo que hace falta para
# medir son ~2 MB. El paquete los junta y —esto es lo importante— los junta
# APAREADOS: el bitstream y el software que sabe hablarle salen del mismo
# commit y viajan en el mismo tarball. Un bitstream viejo no falla, ignora en
# silencio las escrituras a registros que no mapea.
#
#   make release              arma dist/mca-<v>.tar.gz
#   make release-verificar    lo desempaqueta y corre la suite offline ADENTRO
#   make release-publicar     lo sube a GitHub como release (pide CONFIRMAR=si)
#
# La versión se edita a mano en prj/MCA/VERSION. El procedimiento completo,
# incluida la parte de GitHub, está en docs/publicar_release.md.

release: libmca-arm  ## arma el paquete instalable en dist/. Versión en ../VERSION
	@# libmca va en el árbol (software/libmca/build/armv7l/), que es donde la busca
	@# API/_libmca.py. Se chequea ANTES de empaquetar: un .so que hace una
	@# ráfaga sobre la PL reinicia la placa, y uno que pide una glibc más nueva
	@# que la de la placa no carga y deja la API cayendo a Python.
	@$(MAKE) -s -C libmca check-bus
	@test -f $(BIT_LOCAL) || { \
	  echo "ERROR: no existe $(BIT_LOCAL)."; \
	  echo "       un paquete sin bitstream no sirve para nada: es justo lo que"; \
	  echo "       no se puede reconstruir del otro lado. Corré la síntesis."; \
	  exit 1; }
	@if [ -n "$(BITS_REPETIDOS)" ]; then \
	   echo "ERROR: más de un subdirectorio de out/ trae $(BITS_REPETIDOS)."; \
	   echo "       el paquete los copia todos al mismo out/ y uno pisaría al otro."; \
	   echo "       dejá el vigente en out/ (gana sobre los subdirectorios) o"; \
	   echo "       renombrá los archivados."; \
	   exit 1; fi
	@# Van TODOS los bitstreams generados, no sólo el de la variante del banco:
	@# el paquete es uno por versión y el instalador elige el de su placa. Pero
	@# "todos los que hay en out/" incluye los que quedaron de una síntesis
	@# vieja, y un bitstream anterior al commit rompe justo la garantía del
	@# paquete (bitstream y software del mismo commit). Se avisa por mtime; el
	@# que sobra se borra de out/ o se vuelve a sintetizar.
	@echo "bitstreams:"; \
	 C=$$(git -C $(RAIZ) log -1 --format=%ct 2>/dev/null || echo 0); \
	 for b in $(BITS_TODOS); do \
	   if [ $$(stat -c%Y $$b) -lt $$C ]; then \
	     echo "  $$(basename $$b)   AVISO: es ANTERIOR al commit $(GIT_SHA); ¿es el último?"; \
	   else echo "  $$(basename $$b)"; fi; \
	 done
	@if [ -n "$(SUCIO)" ]; then \
	   echo ""; \
	   echo "  AVISO: hay cambios sin commitear en el árbol."; \
	   echo "         el paquete queda marcado '$(GIT_SHA)-sucio' y NO es"; \
	   echo "         reproducible desde el repo. Sirve para probarlo acá;"; \
	   echo "         make release-publicar lo va a rechazar."; \
	   echo ""; \
	 fi
	@rm -rf $(STAGING)
	@mkdir -p $(STAGING)/$(PAQUETE)/out
	@# El payload sale del ÁRBOL DE TRABAJO y no de `git archive`, por dos cosas
	@# que git no tiene: el bitstream no está versionado, y datos_ref/ guarda un
	@# .npz que el .gitignore del repo excluye por patrón. Las exclusiones van
	@# por categoría —medidas, salidas de simulación, caches, cuadernos— así que
	@# un fichero nuevo queda incluido por estar donde va, sin tocar esta lista.
	@rsync -a --include 'compat_golden.npz' \
	  --exclude 'datos/' --exclude 'jupyters_viejos/' \
	  --exclude 'release/' --exclude 'dist/' --exclude '_out_*/' \
	  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '*.pyc' \
	  --exclude '*.ipynb' --exclude '.ipynb_checkpoints/' --exclude '*.npz' \
	  $(RAIZ)/ $(STAGING)/$(PAQUETE)/software/
	@cp $(BITS_TODOS) $(STAGING)/$(PAQUETE)/out/
	@# El golden model de gen_pulsos vive en modulos/, fuera de software/, y lo
	@# importan los modos --simulada de run_meritos_pulsos y run_fidelidad_osc
	@# (por _RAIZ/../modulos/...). Va en la misma ruta relativa del repo.
	@mkdir -p $(STAGING)/$(PAQUETE)/modulos/gen_eventos/modelos
	@rsync -a --exclude '__pycache__/' \
	  $(RAIZ)/../modulos/gen_eventos/modelos/python_model \
	  $(STAGING)/$(PAQUETE)/modulos/gen_eventos/modelos/
	@cp $(RAIZ)/release/LEEME.md $(STAGING)/$(PAQUETE)/
	@install -m 755 $(RAIZ)/release/instalar.sh $(STAGING)/$(PAQUETE)/
	@# VERSION viaja DENTRO del paquete: cuando dentro de seis meses una placa
	@# dé un número raro, la pregunta va a ser "¿qué tiene instalado?", y la
	@# respuesta tiene que estar en la placa y no en la memoria de nadie.
	@# Un bloque por bitstream. `parte` es el Zynq para el que se compiló, y es
	@# el campo que impide repetir el incidente de cargar un bitstream de 7z010
	@# en una placa 7z020: el FPGA manager queda trabado y falla toda
	@# programación posterior hasta reiniciar. Se lee del `.bit` porque el
	@# `.bit.bin` NO lleva la cabecera; viaja acá justamente porque en la placa
	@# ya no hay de dónde sacarla. `variante` es lo mismo dicho por el nombre.
	@{ echo "paquete    $(PAQUETE)"; \
	   echo "commit     $(GIT_SHA)$(if $(SUCIO),-sucio) (rama $(GIT_RAMA))"; \
	   echo "armado     $$(date -Iseconds)"; \
	   echo "eje        $$(grep -oP 'H_AW_ESPERADO = \K[0-9]+' $(RAIZ)/campanas/preparar_placa.py) bits de histograma esperados"; \
	   for b in $(BITS_TODOS); do \
	     n=$$(basename $$b); \
	     echo "bitstream  $$n"; \
	     echo "           $$(stat -c%s $$b) bytes"; \
	     echo "           md5 $$(md5sum $$b | cut -d' ' -f1)"; \
	     echo "variante   $$(echo $$n | sed -E 's/.*_(Z[0-9]+_[0-9]+CH)\.bit\.bin$$/\1/')"; \
	     echo "parte      $$(PYTHONPATH=$(RAIZ) $(PY) -c \
	         'from API.fpga import parte_del_bitstream as p; print(p("'$${b%.bin}'") or "desconocida")')"; \
	   done; \
	 } > $(STAGING)/$(PAQUETE)/VERSION
	@# Un manifiesto de todo el contenido, que el instalador verifica antes de
	@# copiar nada. Una descarga truncada instala un árbol a medias que falla
	@# después, lejos de acá y sin relación aparente con la instalación.
	@cd $(STAGING)/$(PAQUETE) && find . -type f ! -name MANIFIESTO.sha256 \
	  | LC_ALL=C sort | xargs sha256sum > MANIFIESTO.sha256
	@mkdir -p $(DIST)
	@tar czf $(DIST)/$(PAQUETE).tar.gz -C $(STAGING) $(PAQUETE)
	@cd $(DIST) && sha256sum $(PAQUETE).tar.gz > SHA256SUMS
	@$(MAKE) --no-print-directory _release-notas
	@rm -rf $(STAGING)
	@echo ""
	@echo "  $(DIST)/$(PAQUETE).tar.gz   $$(du -h $(DIST)/$(PAQUETE).tar.gz | cut -f1)"
	@echo "  $(DIST)/SHA256SUMS"
	@echo "  $(DIST)/NOTAS.md            (editables antes de publicar)"
	@echo ""
	@echo "  probalo:   make release-verificar"
	@echo "  instalalo: make release-instalar-remoto"
	@echo "  publicalo: make release-publicar CONFIRMAR=si"

# Las notas de la release, con lo mínimo que hay que saber para instalarla. Se
# regeneran en cada `make release`, así que si las editás, publicá antes de
# volver a armar — o pasá NOTAS=<fichero> a release-publicar.
_release-notas:
	@{ echo "## MCA para Red Pitaya — $(PAQUETE)"; \
	   echo ""; \
	   echo "Bitstream y software apareados, salidos del commit \`$(GIT_SHA)\`"; \
	   echo "(rama \`$(GIT_RAMA)\`)."; \
	   echo ""; \
	   echo '```bash'; \
	   echo "curl -LO https://github.com/$(GH_REPO)/releases/download/$(TAG)/$(PAQUETE).tar.gz"; \
	   echo "tar xzf $(PAQUETE).tar.gz && cd $(PAQUETE)"; \
	   echo "sudo ./instalar.sh --cargar"; \
	   echo '```'; \
	   echo ""; \
	   echo "Requiere Red Pitaya OS 2.00+, \`python3\` y \`numpy\`. El instalador"; \
	   echo "verifica el paquete contra su manifiesto y comprueba las dependencias"; \
	   echo "antes de copiar nada; sin \`--cargar\` no toca la PL. \`h5py\` es opcional:"; \
	   echo "hace falta para guardar los eventos del osciloscopio en LH5."; \
	   echo ""; \
	   echo "La documentación no va en el paquete:"; \
	   echo "[\`prj/MCA/docs/\`](https://github.com/$(GH_REPO)/tree/$(GIT_RAMA)/prj/MCA/docs)."; \
	 } > $(DIST)/NOTAS.md

release-verificar: ## desempaqueta el paquete y corre la suite offline ADENTRO
	@test -f $(DIST)/$(PAQUETE).tar.gz || { \
	  echo "ERROR: no hay $(DIST)/$(PAQUETE).tar.gz — corré 'make release'"; exit 1; }
	@# Contra el tarball y no contra staging/: lo que hay que demostrar es que
	@# lo que se publica alcanza para correr, no que el árbol de acá alcanza.
	@# Un fichero olvidado en las exclusiones se ve exactamente así.
	@T=$$(mktemp -d) && trap "rm -rf $$T" EXIT && \
	 tar xzf $(DIST)/$(PAQUETE).tar.gz -C $$T && \
	 echo "== manifiesto ==" && \
	 ( cd $$T/$(PAQUETE) && sha256sum -c --quiet MANIFIESTO.sha256 ) && \
	 echo "  $$(wc -l < $$T/$(PAQUETE)/MANIFIESTO.sha256) ficheros, ok" && \
	 echo "" && echo "== la suite offline, en el paquete ==" && \
	 $(MAKE) --no-print-directory -C $$T/$(PAQUETE)/software verificar-liviano && \
	 echo "" && echo "== el instalador ==" && \
	 sh -n $$T/$(PAQUETE)/instalar.sh && echo "  sintaxis ok" && \
	 $$T/$(PAQUETE)/instalar.sh --help > /dev/null && echo "  --help ok" && \
	 echo "" && echo "OK: el paquete se sostiene solo."

release-instalar-remoto: ## copia el paquete a la Pitaya y lo instala. PITAYA= PREFIJO=
	@test -f $(DIST)/$(PAQUETE).tar.gz || { \
	  echo "ERROR: no hay $(DIST)/$(PAQUETE).tar.gz — corré 'make release'"; exit 1; }
	@echo "  destino  $(PITAYA):$(PREFIJO)"
	scp $(DIST)/$(PAQUETE).tar.gz $(PITAYA):$(DESCARGA)/
	@# Sin --cargar: reprogramar la PL corta el bus AXI, y eso no puede pasar
	@# como efecto secundario de un despliegue. Va aparte y explícito.
	@#
	@# El sudo se decide por el prefijo y no se pide siempre: instalar bajo el
	@# home del usuario CON sudo deja un árbol de root en su casa, que después
	@# no puede ni actualizar ni borrar. Fuera del home, en cambio, hace falta.
	ssh $(PITAYA) 'cd $(DESCARGA) && rm -rf $(PAQUETE) && tar xzf $(PAQUETE).tar.gz \
	   && cd $(PAQUETE) && $(if $(filter /home/%,$(PREFIJO)),,sudo )./instalar.sh --prefijo $(PREFIJO)'
	@echo ""
	@echo "  instalado en $(PREFIJO), SIN tocar la PL. Para comprobar la placa:"
	@echo "    ssh $(PITAYA) 'python3 $(PREFIJO)/software/campanas/preparar_placa.py'"
	@echo "  y para programarla (corta el bus AXI):"
	@echo "    ssh $(PITAYA) 'sudo $(PREFIJO)/instalar.sh --prefijo $(PREFIJO) --cargar'"

# Publicar es irreversible en la práctica —alguien puede haber bajado el
# tarball entre que se sube y se borra— así que pide confirmación explícita y
# rechaza todo lo que haría el paquete no reproducible.
release-publicar:  ## sube dist/ a GitHub como release mca-v<versión>. Pide CONFIRMAR=si
	@command -v gh >/dev/null || { \
	  echo "ERROR: falta gh (https://cli.github.com). Alternativa a mano en"; \
	  echo "       docs/publicar_release.md"; exit 1; }
	@gh auth status >/dev/null 2>&1 || { \
	  echo "ERROR: gh no está autenticado.  gh auth login"; exit 1; }
	@test -f $(DIST)/$(PAQUETE).tar.gz || { \
	  echo "ERROR: no hay $(DIST)/$(PAQUETE).tar.gz — corré 'make release'"; exit 1; }
	@if [ -n "$(SUCIO)" ]; then \
	   echo "ERROR: hay cambios sin commitear."; \
	   echo "       una release apunta a un commit; si el árbol no está limpio,"; \
	   echo "       el tag miente sobre qué hay adentro del tarball."; \
	   git -C $(RAIZ)/.. status --porcelain | head -10 | sed 's/^/       /'; \
	   exit 1; fi
	@if git rev-parse -q --verify refs/tags/$(TAG) >/dev/null; then \
	   echo "ERROR: el tag $(TAG) ya existe."; \
	   echo "       subí la versión en prj/MCA/VERSION y volvé a armar."; \
	   exit 1; fi
	@echo "  repo      $(GH_REPO)"
	@echo "  tag       $(TAG)      -> commit $(GIT_SHA) ($(GIT_RAMA))"
	@echo "  adjuntos  $(PAQUETE).tar.gz  ·  SHA256SUMS"
	@echo "  notas     $(NOTAS)"
	@if [ "$(CONFIRMAR)" != "si" ]; then \
	   echo ""; \
	   echo "  NO se publicó nada. Revisá las notas y después:"; \
	   echo "    make release-publicar CONFIRMAR=si"; \
	   exit 0; fi; \
	 git tag -a $(TAG) -m "MCA $(VERSION) — bitstream + software" && \
	 git push origin $(TAG) && \
	 gh release create $(TAG) --repo $(GH_REPO) \
	   --title "MCA $(VERSION)" --notes-file $(NOTAS) \
	   $(DIST)/$(PAQUETE).tar.gz $(DIST)/SHA256SUMS && \
	 echo "" && \
	 echo "  publicado: https://github.com/$(GH_REPO)/releases/tag/$(TAG)"

release-limpiar:   ## borra dist/
	@rm -rf $(DIST)
	@echo "  dist/ borrado"

# =============================================================================
# bench  ·  miden, no aprueban ni fallan
# =============================================================================

bench: exige-placa  ## (P) benchmarks de lectura del buffer (no son pass/fail)
	$(PY) API/bench/bench_buffer_read.py
	$(PY) API/bench/bench_read_vs_length.py
	$(PY) API/bench/bench_reader_budget.py

bench-remoto: placa-sync  ## (P) los benchmarks, EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) bench'

# El microbench de la API: cada operación en py (la referencia congelada), c
# (libmca por ctypes) y c_puro. Ver API/bench/bench_impl.py. DESTRUCTIVO=1 mide
# además clear/configure/acquire y BORRA el histograma.
#
# En la placa no hay .git: el commit se calcula acá y viaja en MCA_COMMIT, que
# es lo que permite saber después qué código se midió.
BENCH_OUT ?= datos/bench_impl_$(STAMP)
COMMIT    := $(shell git -C $(RAIZ) rev-parse --short HEAD 2>/dev/null)$(shell \
               git -C $(RAIZ) diff --quiet HEAD -- . 2>/dev/null || echo -sucio)

bench-api: exige-placa libmca  ## (P) microbench de la API, py contra c. BENCH_OUT= DESTRUCTIVO=
	$(PY) API/bench/bench_impl.py --out $(BENCH_OUT) $(if $(DESTRUCTIVO),--destructivo,)
	$(PY) API/bench/comparar_bench.py $(BENCH_OUT)

bench-api-remoto: libmca-arm placa-sync  ## (P) el microbench EN la Pitaya, y trae los datos
	ssh $(PITAYA) 'MCA_COMMIT=$(COMMIT) make -C $(REMOTO) bench-api \
	  BENCH_OUT=$(BENCH_OUT) DESTRUCTIVO=$(DESTRUCTIVO)'
	@mkdir -p $(BENCH_OUT)
	rsync -az $(PITAYA):$(REMOTO)/$(BENCH_OUT)/ $(BENCH_OUT)/
	$(PY) API/bench/comparar_bench.py $(BENCH_OUT)

# El mismo microbench SIN PL: el MCA es un fichero en /dev/shm y `c` usa el
# backend devmem de libmca sobre él. Mide el binding sin el costo del bus, con
# cualquier bitstream cargado (o ninguno). Es el que hay que correr al tocar
# API/mca.py o API/_libmca.py: comparar con comparar_bench.py A B.
BENCH_SHM ?= datos/bench_shm_$(STAMP)

# Cuánto cuesta escribir un lote, en .npz y en .lh5, y si frena al lector. No toca la
# PL: es la comprobación de que h5py sirve en la placa. Sale con 1 si falta h5py.
BENCH_DIR ?= datos/bench_escritura

bench-escritura:  ## escribir un lote: .npz contra .lh5, sin PL. BENCH_DIR=
	$(PY) API/bench/bench_escritura.py --dir $(BENCH_DIR)

bench-escritura-remoto: placa-sync  ## lo mismo EN la Pitaya, sobre su disco (no toca la PL)
	ssh $(PITAYA) 'make -C $(REMOTO) bench-escritura BENCH_DIR=$(BENCH_DIR)'

# .npz contra LH5 para elegir por lo que se hace con los archivos: escribir una corrida
# (sin y con compresión) y leerla entera, sólo las columnas, unos pocos eventos y con
# el lector oficial. Ventanas de 32, 256 y 2048 muestras, la del ring. No toca la PL.
BENCH_FMT_DIR ?= datos/bench_formatos
BENCH_FMT_ARGS ?=

bench-formatos:  ## .npz contra LH5: escribir y leer una corrida, sin PL. BENCH_FMT_DIR=
	@mkdir -p $(BENCH_FMT_DIR)
	$(PY) API/bench/bench_formatos.py --dir $(BENCH_FMT_DIR)/tmp \
	  --json $(BENCH_FMT_DIR)/$(shell hostname)_$(STAMP).json $(BENCH_FMT_ARGS)
	@rm -rf $(BENCH_FMT_DIR)/tmp

bench-formatos-remoto: placa-sync  ## lo mismo EN la Pitaya, sobre su disco (no toca la PL)
	ssh $(PITAYA) 'make -C $(REMOTO) bench-formatos BENCH_FMT_DIR=$(BENCH_FMT_DIR) BENCH_FMT_ARGS="$(BENCH_FMT_ARGS)"'

bench-api-shm: libmca  ## microbench del binding sin PL (fichero en /dev/shm). BENCH_SHM=
	$(PY) API/bench/bench_impl.py --shm --out $(BENCH_SHM)
	$(PY) API/bench/comparar_bench.py $(BENCH_SHM)

bench-api-shm-remoto: libmca-arm placa-sync  ## el microbench sin PL EN la Pitaya (no toca la PL), y trae los datos
	ssh $(PITAYA) 'MCA_COMMIT=$(COMMIT) make -C $(REMOTO) bench-api-shm \
	  BENCH_SHM=$(BENCH_SHM)'
	@mkdir -p $(BENCH_SHM)
	rsync -az $(PITAYA):$(REMOTO)/$(BENCH_SHM)/ $(BENCH_SHM)/
	$(PY) API/bench/comparar_bench.py $(BENCH_SHM)

# La columna `remoto`: las funciones de la API desde la PC, por la op `call`,
# contra el mca_server de la Pitaya (lo levanta app-servidor-remoto si no
# estaba; queda corriendo). Es lo que ve la GUI por cada acción.
BENCH_RED ?= datos/bench_remoto_$(STAMP)

bench-api-red: app-servidor-remoto  ## (P) cuánto cuesta cada función por red (op call), medido desde la PC
	$(PY) API/bench/bench_impl.py --remoto $(IP_PITAYA):$(PUERTO_PLACA) \
	  --out $(BENCH_RED) $(if $(DESTRUCTIVO),--destructivo,)
	$(PY) API/bench/comparar_bench.py $(BENCH_RED)

# =============================================================================
# limpiar-*  ·  borrado, por categoría
# =============================================================================
#
# `limpiar` a secas es seguro: sólo toca lo que se regenera solo. Lo que borra
# medidas pide confirmación explícita, y la pide en la línea de comandos
# (CONFIRMAR=si) y no por stdin, para que siga sirviendo desde un script.

limpiar-pyc:       ## borra __pycache__ y .pyc
	@find $(RAIZ) -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "  __pycache__ borrado"

limpiar-cache: limpiar-pyc  ## además borra .pytest_cache
	@rm -rf $(RAIZ)/.pytest_cache
	@echo "  .pytest_cache borrado"

limpiar-simulaciones:  ## borra las salidas de las simulaciones (se regeneran)
	@rm -rf $(RAIZ)/monte-carlo/_out_* $(RAIZ)/campanas/tests/_out_*
	@echo "  salidas de simulación borradas"

limpiar: limpiar-cache  ## limpieza normal: lo que se regenera solo. NO toca datos/
	@echo "OK: limpieza normal (datos/ y simulaciones intactos)"

# datos/ son campañas MEDIDAS en placa: 100+ MB de los que casi nada está
# versionado. Rehacerlas es volver a montar el experimento con el generador, así
# que esto no puede pasar por descuido.
limpiar-datos:     ## BORRA datos/ (campañas medidas). Pide CONFIRMAR=si
	@if [ ! -d $(RAIZ)/datos ]; then echo "  no hay datos/ que borrar"; else \
	  echo "  se borraría datos/ — campañas medidas en placa, NO versionadas:"; \
	  du -sh $(RAIZ)/datos | sed 's/^/    /'; \
	  echo "    $$(ls $(RAIZ)/datos | wc -l) entradas"; \
	  if [ "$(CONFIRMAR)" = "si" ]; then \
	    rm -rf $(RAIZ)/datos; echo "  datos/ BORRADO."; \
	  else \
	    echo ""; \
	    echo "  NO se borró nada. Para hacerlo de verdad:"; \
	    echo "    make limpiar-datos CONFIRMAR=si"; \
	  fi; fi

# SIN prerequisitos a propósito: un objetivo que pide confirmación no puede
# destruir la mitad antes de preguntar. Sin CONFIRMAR=si esto no borra NADA,
# sólo lista. Con CONFIRMAR=si borra todo de una.
limpiar-todo:      ## TODO lo regenerable, datos/ incluido. Pide CONFIRMAR=si
	@echo "  se borraría:"
	@echo "    __pycache__/ y .pytest_cache/           se regeneran solos"
	@echo "    monte-carlo/_out_*  campanas/tests/_out_*   (make montecarlo, ~15 min)"
	@if [ -d $(RAIZ)/datos ]; then \
	   echo "    datos/   campañas MEDIDAS en placa, NO versionadas:"; \
	   du -sh $(RAIZ)/datos | sed 's/^/        /'; \
	   echo "        $$(ls $(RAIZ)/datos | wc -l) entradas — rehacerlas es volver a"; \
	   echo "        montar el experimento con el generador"; \
	 fi
	@if [ "$(CONFIRMAR)" = "si" ]; then \
	   $(MAKE) --no-print-directory limpiar-cache limpiar-simulaciones; \
	   rm -rf $(RAIZ)/datos; \
	   echo "  BORRADO TODO, datos/ incluido."; \
	 else \
	   echo ""; \
	   echo "  NO se borró nada. Para hacerlo de verdad:"; \
	   echo "    make limpiar-todo CONFIRMAR=si"; \
	   echo "  Para borrar sólo lo que se regenera solo:  make limpiar"; \
	 fi
