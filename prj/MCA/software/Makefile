# Makefile del software del MCA: tests, simulaciones Monte-Carlo y campañas.
#
#   make                ayuda
#   make test           TODO lo que corre en una PC (sin placa, sin Rigol)
#   make placa          TODO lo que necesita la Red Pitaya
#   make mc             las simulaciones Monte-Carlo
#   make campana-mca    la campaña de caracterización del MCA (placa + Rigol)
#   make gui-demo       la GUI andando contra un MCA falso, sin placa
#   make gui-placa      la GUI contra la Pitaya de verdad
#   make remoto-e2e-app el e2e de la app con pulsos del Rigol
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

# Estímulo del Rigol (estimulo-*, placa-e2e-app). TASA en pulsos/s y AMP en Vpp
# con la convención de la campaña: base en AMP/2 y pico en AMP, o sea altura de
# pulso AMP/2 -> ~2458 cuentas de ADC con AMP=0.6 en LV.
TASA     ?= 3000
AMP      ?= 0.6
SEGUNDOS ?= 10

# Detección de placa: el módulo `rp` sólo existe en la Red Pitaya. Se mira el
# directorio en vez de importar, para no pagar el import en cada invocación.
EN_PLACA := $(shell test -d /opt/redpitaya/lib/python && echo si)
PITAYA   ?= pitaya
REMOTO   ?= /home/jupyter/RedPitaya/remote_soft

# El bitstream. `make sync` NO lo copia (excluye todo lo que no sea software),
# así que el despliegue de la PL es un objetivo aparte y explícito: recargar la
# PL corta el bus AXI y no es algo que deba pasar como efecto secundario de
# sincronizar unos .py.
BIT_LOCAL  ?= $(RAIZ)/../out/mca_red_pitaya.bit.bin
BIT_REMOTO ?= /root/mca_red_pitaya.bit.bin

# Para los scripts que se invocan sueltos (no vía pytest): pytest resuelve la
# raíz con `pythonpath` de pyproject.toml, pero `python3 campanas/x.py` no.
export PYTHONPATH := $(RAIZ):$(PYTHONPATH)

.DEFAULT_GOAL := help

.PHONY: help test test-api test-app test-mc test-campanas test-modelo \
        test-liviano compat baseline lint \
        mc mc-rapido mc-apilamiento mc-linea-base mc-pico-carga mc-figuras \
        campana-lista campana-mca campana-campana campana-resto campana-formas \
        campana-e2e campana-poisson campana-deriva adquirir \
        graficos-mca graficos-formas graficos-tasa analisis-estimadores \
        placa placa-mem placa-buffer placa-mca placa-diag placa-ring \
        placa-rigol placa-e2e placa-e2e-app placa-preparar placa-cargar \
        estimulo-on estimulo-psd estimulo-off bench exige-placa \
        gui gui-demo gui-placa test-gui exige-gui servidor servidor-falso \
        remoto-servidor remoto-servidor-off remoto-e2e-app \
        remoto-estimulo-on remoto-estimulo-psd remoto-estimulo-off \
        sync sync-dry remoto-test remoto-placa remoto-bench \
        bitstream remoto-preparar remoto-deriva \
        clean clean-pyc distclean

# ------------------------------------------------------------------ ayuda ---
help:              ## esta ayuda
	@echo "software del MCA — objetivos disponibles:"
	@echo ""
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sort | awk 'BEGIN{FS=":.*?## "}{printf "  %-22s %s\n", $$1, $$2}'
	@echo ""
	@echo "  (P) necesita la Red Pitaya      (R) necesita además el Rigol DG4162"
	@echo "  esta máquina es placa: $(if $(EN_PLACA),SÍ,no)"
	@echo "  variables: OUT=$(OUT)"
	@echo "             CH=$(CH)  GEN_CH=$(GEN_CH)  PITAYA=$(PITAYA)  PUERTO=$(PUERTO)"
	@echo "             TASA=$(TASA) Hz  AMP=$(AMP) Vpp  SEGUNDOS=$(SEGUNDOS)"
	@echo ""
	@echo "  los testbenches de RTL (QuestaSim) van aparte:  make -C ../sim"

# --------------------------------------------------- tests que corren en PC --
test: test-api test-app test-mc test-campanas   ## toda la suite offline (PC)
	@echo "OK: suite offline completa"

# Lo mismo SIN las simulaciones Monte-Carlo. La Pitaya tiene 461 MB de RAM y el
# motor de apilamiento llega a ~380 MB de RSS: el OOM killer se lleva el proceso
# a mitad de la corrida. No es un fallo del código —son simulaciones, no tocan
# hardware y su lugar es la PC— así que `remoto-test` corre esto y no `test`.
test-liviano: test-api test-app test-campanas   ## la suite offline sin Monte-Carlo
	@echo "OK: suite offline (sin Monte-Carlo)"

test-api:          ## tests offline de API/ (driver, red, pipeline, análisis)
	$(PYTEST) $(PFLAGS) API/tests

test-app:          ## tests offline de app/ (servidor, cliente remoto, GUI headless)
	$(PYTEST) $(PFLAGS) app/tests

test-mc:           ## tests del motor Monte-Carlo (réplica vectorizada vs RTL)
	$(PYTEST) $(PFLAGS) monte-carlo

test-campanas:     ## tests offline de los drivers de campaña (MCA simulado)
	$(PYTEST) $(PFLAGS) campanas/tests

test-modelo:       ## sólo los modelos de referencia del RTL (estimadores, ring)
	$(PYTEST) $(PFLAGS) API/tests/test_estimadores.py API/tests/test_ring_format.py

compat:            ## el baseline de compatibilidad sigue valiendo (no escribe)
	$(PY) API/tests/test_compat_api.py

baseline:          ## REGENERA el baseline de compatibilidad (revisar el diff!)
	$(PY) API/tests/gen_compat_baseline.py

lint:              ## compila todo y pasa pyflakes si está instalado
	$(PY) -m compileall -q API app campanas monte-carlo *.py
	@command -v pyflakes >/dev/null 2>&1 \
	  && pyflakes API app campanas monte-carlo *.py \
	  || echo "(pyflakes no instalado, salteado)"

# ------------------------------------------------------------- Monte-Carlo ---
mc: mc-apilamiento mc-linea-base mc-pico-carga   ## todas las simulaciones (~15 min)
	@echo "OK: simulaciones Monte-Carlo completas"

mc-rapido:         ## barrido de apilamiento corto, para ver que corre
	$(PY) monte-carlo/montecarlo.py --n-eventos 5000

mc-apilamiento:    ## Monte-Carlo de apilamiento: barrido de tasa (~5 min)
	$(PY) monte-carlo/montecarlo.py

mc-linea-base:     ## Monte-Carlo del seguidor de línea de base
	$(PY) monte-carlo/linea_base.py

mc-pico-carga:     ## Monte-Carlo pico-vs-carga para dobles y triples
	$(PY) monte-carlo/pico_vs_carga.py

mc-figuras:        ## rehace las figuras del MC desde los .npz guardados. DIR=
	$(PY) monte-carlo/graficar.py $(DIR)
	$(PY) monte-carlo/graficar_base.py $(DIR)

# ---------------------------------------------------------------- campañas ---
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

adquirir: exige-placa          ## (P) adquisición continua a chunks. DURACION= THR=
	$(PY) campanas/run_acquire.py --duration $(DURACION) --thr $(THR)

# --- regraficado de campañas ya medidas: NO necesita placa -------------------
graficos-mca:      ## regrafica una campaña del MCA sin placa. DIR=datos/mca_...
	$(PY) campanas/testbench_mca.py --plot-only --outdir $(DIR)

graficos-formas:   ## catálogo de formas de pulso en volts vs microsegundos
	$(PY) campanas/graficar_formas.py

graficos-tasa:     ## tasas medidas contra los tres modelos de tiempo muerto
	$(PY) campanas/plot_modelos_tasa.py

analisis-estimadores:  ## compara los estimadores sobre pulsos reales guardados
	$(PY) campanas/analizar_estimadores.py

# ------------------------------------------------------------- en la placa ---
exige-placa:
	@test -n "$(EN_PLACA)" || { \
	  echo "ERROR: esto necesita la Red Pitaya (no está /opt/redpitaya/lib/python)."; \
	  echo "       desde la PC:  make sync && make remoto-placa"; \
	  exit 1; }

placa: placa-mem placa-buffer placa-mca placa-ring  ## (P) toda la batería de placa
	@echo "OK: batería de placa completa"

placa-preparar: exige-placa  ## (P) verifica que el bitstream cargado sea el nuevo
	$(PY) campanas/preparar_placa.py

placa-cargar: exige-placa  ## (P) programa la PL con $(BIT_REMOTO) y verifica
	$(PY) campanas/preparar_placa.py --cargar --bitstream $(BIT_REMOTO)

placa-mem: exige-placa     ## (P) regresión del SIGBUS al escribir /dev/mem
	$(PY) API/tests/placa/test_rw_dev_mem.py

placa-buffer: exige-placa  ## (P) capture_window_np contra el buffer completo
	$(PY) API/tests/placa/test_capture_window_np.py

placa-mca: exige-placa     ## (P) smoke test del bus y los registros del MCA
	$(PY) API/tests/placa/test_mca_hw.py

placa-diag: exige-placa    ## (P) diagnóstico incremental, un paso por invocación
	$(PY) API/tests/placa/diag_mca_hw.py

placa-ring: exige-placa    ## (P) plumbing PL->DDR del event_ring + trigger por SW
	$(PY) API/tests/placa/hw_ring_plumbing.py all
	$(PY) API/tests/placa/hw_ring_swtrig.py

placa-rigol: exige-placa   ## (P,R) camino de datos del MCA con señal real
	$(PY) API/tests/placa/test_mca_datapath.py

placa-e2e: exige-placa     ## (P,R) adquisición end-to-end, deja datos en datos/
	$(PY) API/tests/placa/test_mca_e2e.py

# El único test que cierra el lazo entero: generador -> IN1 -> MCA -> servidor
# -> socket -> MCARemote. Levanta su propio servidor en un puerto de loopback,
# así que no pelea con el del 1001 si hay una GUI conectada.
placa-e2e-app: exige-placa ## (P,R) LA APLICACIÓN contra pulsos reales del Rigol
	$(PY) app/tests/placa/e2e_rigol_app.py --rate $(TASA) --amp $(AMP) \
	  --segundos $(SEGUNDOS) --channel $(CH) --gen-ch $(GEN_CH) \
	  --outdir $(OUT)

# --- el estímulo, suelto: sobrevive al proceso que lo prendió ----------------
estimulo-on: exige-placa   ## (P,R) enciende el tren de pulsos. TASA= AMP=
	$(PY) campanas/estimulo.py on --rate $(TASA) --amp $(AMP) --ch $(GEN_CH)

estimulo-psd: exige-placa  ## (P,R) dos poblaciones (misma altura, distinta cola)
	$(PY) campanas/estimulo.py on --dos-poblaciones --rate $(TASA) \
	  --amp $(AMP) --ch $(GEN_CH)

estimulo-off: exige-placa  ## (P,R) apaga la salida del generador
	$(PY) campanas/estimulo.py off --ch $(GEN_CH)

bench: exige-placa         ## (P) benchmarks de lectura del buffer (no son pass/fail)
	$(PY) API/bench/bench_buffer_read.py
	$(PY) API/bench/bench_read_vs_length.py
	$(PY) API/bench/bench_reader_budget.py

# ------------------------------------------------------------------- la app --
#
# PUERTO: en la placa se corre como root y vale el 1001 por defecto (el de
# mcpha). En una PC de usuario Linux reserva todo lo que está por debajo de
# 1024, así que los objetivos que corren acá usan uno alto.
PUERTO ?= 5001

exige-gui:
	@$(PY) -c 'import PyQt5, matplotlib' 2>/dev/null || { \
	  echo "ERROR: la GUI necesita PyQt5 y matplotlib en esta máquina."; \
	  echo "       Debian/Ubuntu:  sudo apt install python3-pyqt5 python3-matplotlib"; \
	  echo "       (la placa no los necesita: allá sólo corre el servidor)"; \
	  exit 1; }

gui-demo: exige-gui  ## PROBAR LA GUI sin placa: servidor falso + mcamon conectado
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

test-gui: exige-gui  ## la GUI de punta a punta SIN pantalla (lo que corre en CI)
	$(PYTEST) $(PFLAGS) app/tests/test_mcamon_gui.py

gui:               ## abre mcamon solo. SERVIDOR=host PUERTO=n
	$(PY) app/mcamon.py $(if $(SERVIDOR),--host $(SERVIDOR),) --port $(PUERTO)

servidor: exige-placa   ## (P) levanta mca_server en la placa
	$(PY) app/mca_server.py

servidor-falso:    ## sólo el servidor con MCA falso. PUERTO=n
	$(PY) app/mca_server.py --fake --port $(PUERTO)

# -------------------------------------------------------- PC -> Red Pitaya ---
# SIN --delete, a propósito. La placa tiene ficheros que el repo NO tiene —el
# bitstream cargado, `campana.py`, una docena de `diag_rate*.py`— y un
# --delete los borra sin aviso. Si de verdad querés limpiar lo que sobra,
# mirá primero qué se llevaría:
#
#   make sync-dry
#
# y recién entonces decidilo a mano. Un despliegue no debería poder destruir
# trabajo que sólo vive en el destino.
sync:              ## rsync del árbol a la Pitaya (aditivo: NO borra nada)
	rsync -az \
	  --exclude 'datos/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
	  --exclude '*.ipynb' --exclude '.ipynb_checkpoints/' --exclude '*.npz' \
	  $(RAIZ)/ $(PITAYA):$(REMOTO)/

sync-dry:          ## qué borraría un sync con --delete (no toca nada)
	@echo "ficheros que sólo existen en la placa y un --delete se llevaría:"
	@rsync -az --delete --dry-run --itemize-changes \
	  --exclude 'datos/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
	  --exclude '*.ipynb' --exclude '.ipynb_checkpoints/' --exclude '*.npz' \
	  $(RAIZ)/ $(PITAYA):$(REMOTO)/ | grep '^\*deleting' || echo "  (ninguno)"

# `test-liviano`, no `test`: las simulaciones Monte-Carlo no entran en la RAM
# de la placa (ver el comentario de test-liviano).
remoto-test: sync  ## corre la suite offline EN la Pitaya (sanity del deploy)
	ssh $(PITAYA) 'make -C $(REMOTO) test-liviano'

remoto-placa: sync ## corre la batería de placa EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) placa'

remoto-bench: sync ## corre los benchmarks EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) bench'

remoto-e2e-app: sync ## (R) el e2e de la aplicación EN la Pitaya, y trae los datos
	ssh $(PITAYA) 'make -C $(REMOTO) placa-e2e-app TASA=$(TASA) AMP=$(AMP) \
	  SEGUNDOS=$(SEGUNDOS) CH=$(CH) GEN_CH=$(GEN_CH) OUT=$(OUT)'
	@mkdir -p $(dir $(OUT))
	rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/
	@echo "datos en $(OUT)/"

remoto-estimulo-on: sync  ## (R) enciende el generador EN la Pitaya. TASA= AMP=
	ssh $(PITAYA) 'make -C $(REMOTO) estimulo-on TASA=$(TASA) AMP=$(AMP) GEN_CH=$(GEN_CH)'

remoto-estimulo-psd: sync ## (R) dos poblaciones EN la Pitaya (para el mapa 2D)
	ssh $(PITAYA) 'make -C $(REMOTO) estimulo-psd TASA=$(TASA) AMP=$(AMP) GEN_CH=$(GEN_CH)'

remoto-estimulo-off:      ## (R) apaga el generador EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) estimulo-off GEN_CH=$(GEN_CH)'

# --------------------------------------------------- la app contra la placa ---
#
# Dos trampas distintas, con dos soluciones distintas:
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
# después de autenticar y el problema desaparece.
#
# El `> /dev/null` del `ssh -f` es lo mismo un nivel más arriba: ese ssh queda
# vivo del lado local y hereda el stdout de make, así que quien lea la salida
# por una tubería (un script, CI) espera para siempre aunque make ya terminó.
#
# El precio es un ssh local vivo mientras dure el servidor; se va solo con
# `remoto-servidor-off`. Si esto tiene que sobrevivir a reinicios, lo que
# corresponde es una unidad de systemd en la placa, no más Makefile.
PUERTO_PLACA ?= 1001

# La IP se la preguntamos a ssh en vez de repetirla acá: el alias `pitaya` ya
# la tiene y cambia seguido, así que una segunda copia se desactualiza sola.
IP_PITAYA ?= $(shell ssh -G $(PITAYA) 2>/dev/null | awk '/^hostname /{print $$2}')

remoto-servidor: sync ## (P) levanta mca_server en la Pitaya y lo deja corriendo
	@ssh $(PITAYA) 'ss -ltn 2>/dev/null | grep -q ":$(PUERTO_PLACA) "' \
	  && echo "ya había un servidor escuchando en el $(PUERTO_PLACA)" \
	  || { ssh -f $(PITAYA) 'cd $(REMOTO) && exec python3 app/mca_server.py \
	         --port $(PUERTO_PLACA) < /dev/null > /tmp/mca_server.log 2>&1' \
	         > /dev/null 2>&1; \
	       sleep 2; ssh $(PITAYA) 'tail -2 /tmp/mca_server.log'; }

remoto-servidor-off:  ## (P) para el mca_server de la Pitaya
	@ssh $(PITAYA) 'pkill -f "[m]ca_server.py" && echo "servidor detenido" \
	   || echo "no había servidor corriendo"'

gui-placa: exige-gui remoto-servidor ## LA GUI contra la Pitaya (levanta el servidor)
	@test -n "$(IP_PITAYA)" || { \
	  echo "ERROR: no pude sacar la IP de '$(PITAYA)' de la config de ssh."; \
	  echo "       pasala a mano:  make gui-placa IP_PITAYA=10.73.28.27"; \
	  exit 1; }
	@echo "mcamon -> $(IP_PITAYA):$(PUERTO_PLACA)  (el servidor queda corriendo"
	@echo " al salir; pararlo con: make remoto-servidor-off)"
	$(PY) app/mcamon.py --host $(IP_PITAYA) --port $(PUERTO_PLACA) --conectar

# --------------------------------------------------- despliegue del bitstream
bitstream:         ## copia el .bit.bin a la Pitaya (SOBREESCRIBE; no lo carga)
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

remoto-preparar: bitstream sync  ## copia bitstream+software, PROGRAMA la PL y verifica
	ssh $(PITAYA) 'make -C $(REMOTO) placa-cargar'

remoto-deriva: sync  ## corre el experimento de deriva EN la Pitaya. OUT=
	ssh $(PITAYA) 'make -C $(REMOTO) campana-deriva OUT=$(OUT)'
	@echo "traé los datos con:  rsync -az $(PITAYA):$(REMOTO)/$(OUT)/ $(OUT)/"

# ---------------------------------------------------------------- limpieza ---
clean-pyc:         ## borra __pycache__ y .pyc
	@find $(RAIZ) -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

clean: clean-pyc   ## limpieza normal (NO toca datos/)
	rm -rf $(RAIZ)/.pytest_cache

distclean: clean   ## además borra las salidas de las simulaciones
	rm -rf $(RAIZ)/monte-carlo/_out_* $(RAIZ)/campanas/tests/_out_*
