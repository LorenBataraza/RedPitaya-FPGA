# Sesión de placa: el experimento de deriva (y lo que hay que re-medir)

Runbook de la primera sesión con el bitstream `v3_features_zoom_discr`. Dos
objetivos en la misma puesta:

1. **Contestar la pregunta abierta**: el corrimiento del centroide, ¿es función
   de la tasa o del tiempo? Es lo que bloquea §17.3 de
   [`resultados_validacion_hw.md`](../resultados_validacion_hw.md) y con eso la
   justificación del conformado trapezoidal.
2. **Re-medir lo que el refactor invalidó**: el throughput y todo FWHM expresado
   en canales.

---

## 0. Antes de tocar nada: la trampa del bitstream

El bitstream nuevo **conserva el magic "MCA1"** del anterior, y `mca_top.sv`
**ignora en silencio las escrituras a direcciones no mapeadas** — el `default`
del decodificador devuelve `32'h0` y no levanta `sys_err`.

Consecuencia concreta: contra el bitstream viejo, `configure(sel_1d=...,
zoom_1d=..., discr=...)` **no falla**. Escribe al vacío, el MCA sigue
histogrameando con lo que tenía, y la campaña sale entera con números
plausibles que no responden a lo que se pidió. Mirando los datos después no hay
manera de darse cuenta.

Por eso hay una sonda explícita. Escribe y relee `R_DISCR_MIN` (0x09C), que sólo
existe en el bitstream nuevo y es **inerte** con el discriminador deshabilitado:

```bash
# desde la PC: copia el .bit.bin, verifica el md5, sincroniza y PROGRAMA la PL
make -C software remoto-preparar

# o, ya estando en la Pitaya:
python3 campanas/preparar_placa.py --cargar      # programa y verifica
python3 campanas/preparar_placa.py               # sólo verifica
```

Tiene que terminar en `PLACA LISTA`, con el eje en **8192 canales** y los 8
registros nuevos verificados uno por uno. Si dice `bus de features: NO`, el
bitstream cargado es el viejo y **no hay que seguir**.

> `make sync` **no** copia el bitstream a propósito: recargar la PL corta el bus
> AXI, y eso no debe pasar como efecto secundario de sincronizar unos `.py`. El
> despliegue es `make bitstream` (copia y verifica md5) o `remoto-preparar`
> (copia, programa y verifica).

---

## 1. El experimento de deriva

### Qué se mide y por qué así

`sweep_rate` barría **en un solo sentido**, de menor a mayor tasa. En esa tabla
"más tasa" y "más tarde" son la misma columna: el +1.28 % publicado admite las
dos lecturas y no hay forma de separarlas *a posteriori*. Es el mismo error que
ya invalidó el +6.45 % (confundido con el ancho de pulso).

La pasada de vuelta lo rompe. Cada tasa se visita dos veces, en `t_ida` y
`t_vuelta`, y **el discriminante no es comparar el primer punto contra el
último** sino regresar la histéresis contra la separación temporal entre las dos
visitas. Con `cen(r,t) = R(r) + D(t)`:

| Si manda… | La histéresis `cen_vuelta − cen_ida` |
|---|---|
| el **tiempo** | crece con `t_vuelta − t_ida`: máxima en la tasa más baja (primera y última visita), **nula en el punto de retorno**. La pendiente ES la deriva, y se puede restar |
| la **tasa** | es ≈ 0 en todos los puntos, incluidos los de separación grande |

Fijarse en la separación temporal en vez de en un par suelto usa los 16 puntos y
hace **falsable** la hipótesis: la deriva pura predice una recta por el origen,
no un número. Una ordenada al origen grande dice que el modelo aditivo no
alcanza.

### Correrlo

```bash
# en la Pitaya (~3 min: 16 tasas x 2 pasadas x 5.4 s por punto)
make -C software campana-deriva OUT=datos/deriva_$(date +%Y%m%d_%H%M%S)

# o desde la PC, con el rsync de vuelta que imprime al terminar
make -C software remoto-deriva OUT=datos/deriva_20260904
```

`run_deriva.py` llama a `mca.exigir_features()` antes de medir, así que no puede
correr contra el bitstream equivocado ni por descuido.

### Leer el resultado

Sale un veredicto explícito, `resumen_deriva.json` y la figura
`deriva_tasa_tiempo.png` (dos paneles: centroide vs tasa con las dos pasadas, y
la histéresis contra la separación temporal).

| Veredicto | Qué significa | Qué sigue |
|---|---|---|
| **REPRODUCIBLE EN TASA** | ida y vuelta coinciden dentro del ruido: el corrimiento es genuinamente función de la tasa | La cadena digital ya está descartada (§17), así que el sospechoso pasa a ser el **generador** o el **frente analógico** — §17.3, puntos 2 y 3 |
| **DERIVA TEMPORAL** | la histéresis sigue a la separación entre visitas | El +1.28 % es en buena parte artefacto del orden del barrido. Hay que **corregir §17 y el documento de límites**, que lo citan como corrimiento con la tasa |
| **HISTÉRESIS SIN ESTRUCTURA TEMPORAL** | las pasadas no coinciden pero la diferencia no sigue al tiempo | El modelo aditivo no alcanza: deriva no lineal, o la historia de tasas importa. **No concluir desde acá** |

**Lo que este experimento NO puede separar**, y conviene tenerlo presente antes
de leer el número: una deriva causada por el **calor que disipa la propia tasa de
cuentas** es función del tiempo *y* de la tasa a la vez, y aparecería como
histéresis igual que una deriva temporal pura. Distinguir eso pide medir
temperatura, o repetir el barrido con el mismo perfil temporal y otro rango de
tasas.

El análisis está verificado contra verdad de campo en
[`test_deriva_sweep_sim.py`](../../software/campanas/tests/test_deriva_sweep_sim.py):
un MCA simulado con deriva **conocida** en cada uno de los dos regímenes, y el
análisis tiene que recuperar la pendiente (lo hace con 0.0 % de error) y no
inventar deriva cuando no la hay.

---

## 2. Lo que hay que re-medir, y por qué no es defendible el número viejo

| Qué | Por qué cambió | Predicción |
|---|---|---|
| **Throughput** (794 kcps) y `cnt_lost_busy` | el divisor pasó de 6 a 16 ciclos: 390 → 400 ciclos por evento | **−2.5 %**. La etapa de pipeline **no** entra: está aguas abajo de la FSM, agrega latencia y no tiempo muerto |
| **Todo FWHM en canales** | el eje pasó de 16384 a 8192 | se dividen por 2. Las resoluciones en **%** no cambian |

```bash
make -C software campana-resto OUT=datos/...     # incluye sweep_rate con vuelta
make -C software campana-mca-single_peak OUT=datos/...
```

---

## 3. Verificación funcional del refactor

Todavía **no se ejercitó en placa** nada de las fases 1–3: el bus de features, el
zoom, el discriminador y el `full` pegajoso están verificados sólo en simulación
(19 testbenches, ~1500 comprobaciones) y en síntesis.

```bash
make -C software placa-mca       # smoke test del bus y los registros
make -C software placa-rigol     # camino de datos con señal real
make -C software placa-e2e       # espectro HW contra espectro SW
```

Lo mínimo que hay que confirmar con señal, más allá de que corra:

- **el selector de feature mueve el espectro**: `sel_1d=F_PEAK` contra
  `sel_1d=F_INT` sobre el mismo estímulo tienen que dar centroides distintos. Es
  el check que agarró el bug del mux en simulación (una `function` dentro de un
  `assign` continuo no queda sensible a lo que lee del alcance exterior, así que
  el bus se quedaba clavado y **todo el espectro caía en el canal 0**);
- **el zoom anida exacto**: el espectro con `z=1` sobre la mitad correcta tiene
  que ser el de `z=0` con los bines partidos en dos, sin cuentas perdidas;
- **el discriminador cuenta lo que rechaza**: `cnt_rej_discr` tiene que subir
  exactamente lo que baja `accepted`.

---

## 4. Orden sugerido de la sesión

1. `make -C software remoto-preparar` → tiene que decir **PLACA LISTA**
2. `make -C software placa-mca` y `placa-rigol` → el refactor anda con señal
3. `make -C software remoto-deriva OUT=…` → **el experimento** (~3 min)
4. `campana-resto` → throughput y FWHM nuevos
5. Traer los datos y regraficar sin placa:
   `make -C software graficos-mca DIR=datos/…`

Anotar en `resultados_validacion_hw.md` §18.3 los dos números re-medidos, y el
veredicto de la deriva donde corresponda según cuál haya salido.
