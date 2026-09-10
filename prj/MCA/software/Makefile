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
BIT_LOCAL  ?= $(RAIZ)/../out/mca_red_pitaya.bit.bin
BIT_REMOTO ?= /root/mca_red_pitaya.bit.bin

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
        verificar-montecarlo verificar-campanas verificar-modelo \
        verificar-compat verificar-lint baseline-regenerar \
        verificar-placa verificar-placa-mem verificar-placa-buffer \
        verificar-placa-mca verificar-placa-diag verificar-placa-ring \
        verificar-placa-datapath verificar-placa-e2e verificar-placa-app \
        verificar-placa-bitstream \
        verificar-remoto verificar-placa-remoto verificar-placa-app-remoto \
        montecarlo montecarlo-rapido montecarlo-apilamiento \
        montecarlo-linea-base montecarlo-pico-carga montecarlo-figuras \
        campana-lista campana-mca campana-campana campana-resto campana-formas \
        campana-e2e campana-poisson campana-deriva campana-adquirir \
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
        bench bench-remoto exige-placa exige-gui \
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

verificar: verificar-api verificar-app verificar-montecarlo verificar-campanas  ## toda la suite offline (PC)
	@echo "OK: suite offline completa"

# Lo mismo SIN las simulaciones Monte-Carlo. La Pitaya tiene 461 MB de RAM y el
# motor de apilamiento llega a ~380 MB de RSS: el OOM killer se lleva el proceso
# a mitad de la corrida. No es un fallo del código —son simulaciones, no tocan
# hardware y su lugar es la PC— así que `verificar-remoto` corre esto.
verificar-liviano: verificar-api verificar-app verificar-campanas  ## la suite offline sin Monte-Carlo
	@echo "OK: suite offline (sin Monte-Carlo)"

verificar-api:     ## tests offline de API/ (driver, red, pipeline, análisis)
	$(PYTEST) $(PFLAGS) API/tests

verificar-app:     ## tests offline de app/ (servidor, cliente remoto, GUI headless)
	$(PYTEST) $(PFLAGS) app/tests

verificar-montecarlo:  ## tests del motor Monte-Carlo (réplica vectorizada vs RTL)
	$(PYTEST) $(PFLAGS) monte-carlo

verificar-campanas:    ## tests offline de los drivers de campaña (MCA simulado)
	$(PYTEST) $(PFLAGS) campanas/tests

verificar-modelo:  ## sólo los modelos de referencia del RTL (estimadores, ring)
	$(PYTEST) $(PFLAGS) API/tests/test_estimadores.py API/tests/test_ring_format.py

verificar-gui: exige-gui  ## la GUI de punta a punta SIN pantalla (lo que corre en CI)
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

verificar-placa: verificar-placa-mem verificar-placa-buffer verificar-placa-mca verificar-placa-ring  ## (P) toda la batería de placa
	@echo "OK: batería de placa completa"

verificar-placa-mem: exige-placa      ## (P) regresión del SIGBUS al escribir /dev/mem
	$(PY) API/tests/placa/test_rw_dev_mem.py

verificar-placa-buffer: exige-placa   ## (P) capture_window_np contra el buffer completo
	$(PY) API/tests/placa/test_capture_window_np.py

verificar-placa-mca: exige-placa      ## (P) smoke test del bus y los registros del MCA
	$(PY) API/tests/placa/test_mca_hw.py

verificar-placa-diag: exige-placa     ## (P) diagnóstico incremental, un paso por invocación
	$(PY) API/tests/placa/diag_mca_hw.py

verificar-placa-ring: exige-placa     ## (P) plumbing PL->DDR del event_ring + trigger por SW
	$(PY) API/tests/placa/hw_ring_plumbing.py all
	$(PY) API/tests/placa/hw_ring_swtrig.py

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

montecarlo: montecarlo-apilamiento montecarlo-linea-base montecarlo-pico-carga  ## todas las simulaciones (~15 min)
	@echo "OK: simulaciones Monte-Carlo completas"

montecarlo-rapido:       ## barrido de apilamiento corto, para ver que corre
	$(PY) monte-carlo/montecarlo.py --n-eventos 5000

montecarlo-apilamiento:  ## Monte-Carlo de apilamiento: barrido de tasa (~5 min)
	$(PY) monte-carlo/montecarlo.py

montecarlo-linea-base:   ## Monte-Carlo del seguidor de línea de base
	$(PY) monte-carlo/linea_base.py

montecarlo-pico-carga:   ## Monte-Carlo pico-vs-carga para dobles y triples
	$(PY) monte-carlo/pico_vs_carga.py

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

app-demo: exige-gui  ## PROBAR LA GUI sin placa: servidor falso + mcamon conectado
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

app-servidor-falso:  ## sólo el servidor con MCA falso. PUERTO=n
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
try:
    fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(fd, 4096, offset=0x40700000)
    magic = struct.unpack_from('<I', m, 0)[0]
    w = struct.unpack_from('<I', m, 8)[0]
    caps = struct.unpack_from('<I', m, 4)[0]
    if magic == 0x4D434131:
        pl = 'MCA1 · %d canales · mapa 2D %s' % (
            1 << (w & 0xFF), 'sí' if caps & 2 else 'no')
    else:
        pl = 'sin MCA en el slot 7 (magic %#010x)' % magic
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

release: ## arma el paquete instalable en dist/. Versión en ../VERSION
	@test -f $(BIT_LOCAL) || { \
	  echo "ERROR: no existe $(BIT_LOCAL)."; \
	  echo "       un paquete sin bitstream no sirve para nada: es justo lo que"; \
	  echo "       no se puede reconstruir del otro lado. Corré la síntesis."; \
	  exit 1; }
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
	@cp $(BIT_LOCAL) $(STAGING)/$(PAQUETE)/out/
	@cp $(RAIZ)/release/LEEME.md $(STAGING)/$(PAQUETE)/
	@install -m 755 $(RAIZ)/release/instalar.sh $(STAGING)/$(PAQUETE)/
	@# VERSION viaja DENTRO del paquete: cuando dentro de seis meses una placa
	@# dé un número raro, la pregunta va a ser "¿qué tiene instalado?", y la
	@# respuesta tiene que estar en la placa y no en la memoria de nadie.
	@{ echo "paquete    $(PAQUETE)"; \
	   echo "commit     $(GIT_SHA)$(if $(SUCIO),-sucio) (rama $(GIT_RAMA))"; \
	   echo "armado     $$(date -Iseconds)"; \
	   echo "bitstream  mca_red_pitaya.bit.bin"; \
	   echo "           $$(stat -c%s $(BIT_LOCAL)) bytes"; \
	   echo "           md5 $$(md5sum $(BIT_LOCAL) | cut -d' ' -f1)"; \
	   echo "eje         $$(grep -oP 'H_AW_ESPERADO = \K[0-9]+' $(RAIZ)/campanas/preparar_placa.py) bits de histograma esperados"; \
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
	   echo "antes de copiar nada; sin \`--cargar\` no toca la PL."; \
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

release-instalar-remoto: ## copia el paquete a la Pitaya y lo instala (NO carga la PL)
	@test -f $(DIST)/$(PAQUETE).tar.gz || { \
	  echo "ERROR: no hay $(DIST)/$(PAQUETE).tar.gz — corré 'make release'"; exit 1; }
	scp $(DIST)/$(PAQUETE).tar.gz $(PITAYA):/tmp/
	@# Sin --cargar: reprogramar la PL corta el bus AXI, y eso no puede pasar
	@# como efecto secundario de un despliegue. Va aparte y explícito.
	ssh $(PITAYA) 'cd /tmp && rm -rf $(PAQUETE) && tar xzf $(PAQUETE).tar.gz \
	   && cd $(PAQUETE) && sudo ./instalar.sh'
	@echo ""
	@echo "  instalado, sin tocar la PL. Para programarla:"
	@echo "    ssh $(PITAYA) 'sudo /opt/mca/instalar.sh --cargar'"

# Publicar es irreversible en la práctica —alguien puede haber bajado el
# tarball entre que se sube y se borra— así que pide confirmación explícita y
# rechaza todo lo que haría el paquete no reproducible.
release-publicar:  ## sube dist/ a GitHub como release $(TAG). Pide CONFIRMAR=si
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
