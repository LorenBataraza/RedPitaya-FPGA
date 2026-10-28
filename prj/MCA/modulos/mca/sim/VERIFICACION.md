# Plan de verificación — mca

DUT principal: `mca_top`

## Cómo se corre

```
make -C modulos/mca/work          # todos los testbenches
make -C modulos/mca/work <tb>     # uno solo
make -C modulos/mca/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/mca/work wave TB=<tb>   # ondas ya grabadas del último batch
```

Las ondas se graban **siempre** en batch (`work/waves/<tb>.wlf`). No se
condiciona el volcado a que haya un error: cuando el chequeo falla, el tiempo
que hay que mirar ya pasó.

## Casos cubiertos

<!-- AUTO:casos -->
<!-- Esta tabla la escribe `modulos/mk/datasheet.py` leyendo los
     testbenches: las escenas numeradas (`// N) ...`) y el nombre de
     cada check(). No editarla a mano. Lo de abajo (casos borde,
     assertions, metas) SI es a mano y no se toca. -->

**328 casos con nombre** en 7 testbenches. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

### [`tb_mca_div_restore`](tb_mca_div_restore.sv) — `mca_div_restore`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Barrido EXHAUSTIVO del camino normal: den en 1..2^D_W-1, num en 0..den-1 | barrido exhaustivo num<den contra division de referencia |
| 2 | den == 0 -> err_o | den=0: err_o alto |
|  |  | den=0: sat_o bajo |
|  |  | den=0: q=0 (no todo unos) |
|  |  | den=0 con num!=0: err_o alto |
|  |  | den=0 con num!=0: q=0 |
| 3 | num >= den -> sat_o, q = 2^Q_W-1. Sin esta guarda num==den envuelve a 0, | num==den: sat_o alto |
|  |  | num==den: q satura a 2^Q_W-1 |
|  |  | num==den: err_o bajo |
|  |  | num>den: sat_o alto |
|  |  | num>den: q satura a 2^Q_W-1 |
|  |  | num>>den: q satura, no envuelve |
| 4 | Casos de valor conocido | num=0: q=0 |
|  |  | num/den=1/2: q=32 |
|  |  | num/den=1/4: q=16 |
|  |  | num/den=3/4: q=48 |
| 5 | Latencia fija = Q_W ciclos, tambien en los casos borde | latencia normal = Q_W ciclos |
|  |  | latencia con den=0 = Q_W ciclos |
|  |  | latencia con saturacion = Q_W |
|  |  | busy_o bajo tras terminar |
|  |  | busy_o sigue bajo sin start |
| 6 | start_i durante busy se ignora (no corrompe la division en curso) | start durante busy se ignora (q sigue siendo 32) |


### [`tb_mca_hist`](tb_mca_hist.sv) — `mca_hist`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Estado inicial: todos los bins en cero | todos los bins arrancan en 0 |
| 2 | Incremento simple y acumulación | 1 incremento en bin 5 -> 1 |
|  |  | bin vecino sin tocar -> 0 |
|  |  | 10 incrementos espaciados -> 10 |
| 3 | FORWARDING: incrementos en ciclos CONSECUTIVOS a la misma dirección | forwarding: 2 incrementos consecutivos -> 2 |
|  |  | forwarding: 3 incrementos consecutivos -> 3 |
|  |  | forwarding: 4 incrementos consecutivos -> 4 |
|  |  | forwarding: 20 incrementos consecutivos -> 20 |
|  |  | alternado A,B x20: bin A -> 10 |
|  |  | alternado A,B x20: bin B -> 10 |
|  |  | 16 direcciones distintas a 1/ciclo -> todos en 1 |
| 4 | Saturación: se queda en 2^CW-1, NO envuelve a 0 | saturacion: se queda en 2^CW-1 (255) |
|  |  | saturacion: sigue en 255 tras otro incremento |
|  |  | full: la bandera se levanto al saturar |
|  |  | full con keep=1: otro bin sigue contando |
|  |  | full con keep=1: nada suprimido |
|  |  | full con keep=0: la acumulacion se congela en TODO el histograma |
|  |  | full con keep=0: los eventos suprimidos se cuentan |
|  |  | full con keep=0: no se confunden con dropped |
|  |  | tras borrar: la bandera de lleno baja |
|  |  | tras borrar: suprimidos a cero |
|  |  | tras borrar: vuelve a contar aunque keep siga en 0 |
| 5 | Barrido de borrado | pre-borrado: bin 15 en 1 |
|  |  | tras el borrado todos los bins en 0 |
| 6 | El puerto de LECTURA sigue vivo durante el barrido | barrido en curso (busy alto) |
|  |  | la lectura responde durante el barrido |
|  |  | busy baja al terminar el barrido |
| 7 | Contador de descartes: eventos que llegan durante el barrido | dropped se resetea con el borrado |
|  |  | dropped cuenta los 5 eventos del barrido |
|  |  | esos eventos NO se contabilizaron en el bin |
| 8 | Los eventos en vuelo al arrancar un borrado se descartan | evento en vuelo al borrar no deja cuenta suelta |


### [`tb_mca_zoom`](tb_mca_zoom.sv) — `mca_zoom`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | z=0: tiene que ser EXACTAMENTE el corrimiento de antes (feat >> 3) | z=0: feat 0x0000 |
|  |  | z=0: feat 0xFFFF |
|  |  | z=0: feat 0x1234 |
|  |  | z=0: feat 0x8000 |
| 2 | Saturacion: fuera de la ventana va a un EXTREMO, nunca envuelve | fuera por arriba satura al ultimo canal |
|  |  | fuera por abajo satura al canal 0 |
|  |  | justo en el borde inferior de la ventana |
|  |  | justo en el borde superior de la ventana |
| 5 | Configuraciones que NO deben ser trampas silenciosas | z > ZMAX se satura a ZMAX |
|  |  | z=0 ignora k (no manda todo al canal 0) |
|  |  | k se enmascara a los z bits utiles |


### [`tb_mca_discriminator`](tb_mca_discriminator.sv) — `mca_discriminator`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Deshabilitado pasa TODO, sin importar min/max ni la feature | deshabilitado: acepta aunque la feature este fuera |
|  |  | deshabilitado: acepta tambien con intervalo externo |
| 2 | Intervalo INTERNO [min,max], bordes INCLUIDOS | interno: 3000 dentro de [2000,4000] |
|  |  | interno: el borde inferior ENTRA |
|  |  | interno: el borde superior ENTRA |
|  |  | interno: justo por debajo del min, rechaza |
|  |  | interno: justo por encima del max, rechaza |
| 3 | Intervalo EXTERNO: el complemento exacto del interno | externo: 3000 dentro del intervalo -> RECHAZA |
|  |  | externo: fuera del intervalo -> acepta |
|  |  | externo: el borde tambien rechaza (complemento exacto) |
| 4 | El SELECTOR elige de verdad. Con la misma ventana, cambiar de ranura | selector: ranura 3 (=3000) entra |
|  |  | selector: ranura 5 (=5000) NO entra |
|  |  | selector: ranura 2 (=2000) NO entra |
|  |  | selector: sigue al contenido de la ranura, no solo al indice |
| 5 | INTERVALO VACIO (min > max). No es un error: el conjunto interno es | vacio: interno con min>max rechaza TODO |
|  |  | vacio: externo con min>max acepta todo |
|  |  | vacio: no depende de que feature se mire |
| 6 | Ventana degenerada de UN valor (min == max) | min==max: acepta exactamente ese valor |
|  |  | min==max: rechaza cualquier otro |
| 7 | Los extremos del rango sin signo, que es el contrato del bus | sin signo: 0xFFFF entra en [0,0xFFFF] |
|  |  | sin signo: 0x0000 tambien |


### [`tb_mca_pulse_feature`](tb_mca_pulse_feature.sv) — `mca_pulse_feature`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Pulso rectangular: ventana, q_tot, q_tail, amplitud de pico, psd | rect: cnt_total |
|  |  | rect: cnt_accepted |
|  |  | rect: q_tot = 20*500 |
|  |  | rect: q_tail = 19*500 |
|  |  | rect: amplitud de pico |
|  |  | rect: psd = 60 |
|  |  | rect: psd valido |
|  |  | rect: un solo evento |
|  |  | bus: F_PEAK alineado = 500<<2 |
|  |  | bus: F_INT   = 10000 |
|  |  | bus: F_LEN   = 20 |
|  |  | bus: F_TRISE = 0 |
|  |  | bus: F_PSD   = 62259 |
|  |  | bus: F_INVW  = 3276 |
|  |  | bus: ev_psd son los 6 bits altos de F_PSD |
|  |  | bus: ranura 6 reservada en cero |
|  |  | bus: ranura 15 reservada en cero |
|  |  | ancho inverso: pulso corto  = 6553 |
|  |  | ancho inverso: pulso largo  = 1638 |
|  |  | ancho inverso: mas ancho => menor P/Q |
|  |  | ancho inverso: el pico no cambia con el ancho |
| 2 | Estimador de INTEGRAL: amp = q_tot >> q_shift = 10000>>5 = 312 | integral: amp = 10000>>5 |
| 3 | Pulso por debajo del umbral: no genera evento | bajo umbral: sin eventos |
|  |  | bajo umbral: sin aceptados |
| 4 | Ventana de aceptación de amplitud | amp>max: contado en total |
|  |  | amp>max: rechazado |
|  |  | amp>max: no aceptado |
|  |  | amp<min: rechazado |
|  |  | amp<min: no aceptado |
|  |  | borde min=amp: aceptado |
|  |  | borde min=amp: sin rechazo |
|  |  | borde min=amp+1: rechazado |
|  |  | borde max=amp: aceptado |
|  |  | borde max=amp: sin rechazo |
|  |  | borde max=amp-1: rechazado |
|  |  | saturado, max=FFFF: aceptado |
|  |  | saturado, max=FFFF: amp |
|  |  | saturado, max=FFFE: rechazado |
|  |  | saturado, max=FFFE: no acept. |
|  |  | pico borde min=pico: aceptado |
|  |  | pico borde min=pico+1: rechaz. |
|  |  | veto: sin eventos |
|  |  | veto: no cuenta como perdido |
|  |  | veto a mitad: el pulso termina y se acepta |
|  |  | veto a mitad: q_tot completo = 20*500 |
|  |  | liberar a mitad de pulso: no abre |
|  |  | liberar a mitad de pulso: el siguiente si |
| 5 | APILAMIENTO: la ventana llega a maxlen | apilamiento: cnt_pileup |
|  |  | apilamiento: no aceptado |
|  |  | apilamiento: contado en total |
| 6 | Pulso que NUNCA vuelve a bajar de la histéresis: cierra por maxlen | sin retorno: no queda colgado (busy bajo) |
|  |  | sin retorno: cerro por maxlen |
| 7 | Línea de base FIJA distinta de cero: q_tot usa (muestra - base) | base=200: q_tot = 20*300 |
|  |  | base=200: amp = 300 |
| 8 | Línea de base AUTOMÁTICA: converge al valor DC de la entrada | base auto: converge a ~80 |
|  |  | base auto: congelada durante el pulso |
| 9 | Caso borde PSD: q_tot == 0  -> err del divisor -> cnt_rej_psd | q_tot=0: q_tot leido |
|  |  | q_tot=0: cnt_rej_psd |
|  |  | q_tot=0: evento sin psd valido |
|  |  | q_tot=0: igual entra al espectro 1D |
| 10 | Caso borde PSD: q_tail == q_tot -> guarda psd_inputs_ok | q_tail==q_tot: ambos 5000 (tot) |
|  |  | q_tail==q_tot: ambos 5000 (tail) |
|  |  | q_tail==q_tot: cnt_rej_psd |
|  |  | q_tail==q_tot: psd invalidado (no envuelve a 0) |
| 11 | Dos pulsos SEPARADOS (hueco > latencia del divisor): se cuentan los dos | dos pulsos separados: cnt_total |
|  |  | dos pulsos separados: cnt_accepted |
|  |  | dos pulsos separados: amp del 2do |
|  |  | dos pulsos separados: q_tot del 2do |
|  |  | dos pulsos separados: nada perdido |
|  |  | hueco corto: solo cierra el 1ro |
|  |  | hueco corto: solo se acepta el 1ro |
|  |  | hueco corto: el 2do se cuenta perdido |
|  |  | hueco corto: la amplitud es la del 1ro |
|  |  | tiempo muerto: solo el 1er pulso contado |
|  |  | tiempo muerto: el 2do se contabiliza como perdido |
|  |  | tiempo muerto: amp del 1ro intacta |
|  |  | tiempo muerto: q_tot del 1ro intacto |
| 12 | cfg_run=0 inhibe la detección | run=0: no detecta |
| 13 | COMPUERTAS DE LARGO FIJO (cfg_gate_mode = 1) | compuerta corta que el pulso: q_tot = 10*500 |
|  |  | compuerta: contado en total |
|  |  | la cola del PROPIO pulso no es apilamiento |
|  |  | compuerta corta: el evento se acepta |
|  |  | compuerta larga: q_tot = 20*500 |
|  |  | compuerta larga: q_tail = 16*500 |
|  |  | compuerta larga: NO es apilamiento |
|  |  | compuerta larga: aceptado |
|  |  | compuerta larga: amplitud de pico |
|  |  | misma compuerta, otra amplitud: q_tot = 20*200 |
|  |  | maxlen no actua en modo compuerta: q_tot completo |
|  |  | maxlen no actua en modo compuerta: sin apilamiento |
|  |  | modo 0 ignora gate_long: q_tot = 20*500 |
|  |  | modo 0 ignora gate_short: q_tail = 19*500 |
|  |  | modo 0: sin apilamiento |
|  |  | 2do pulso en la compuerta: contado |
|  |  | 2do pulso en la compuerta: APILAMIENTO |
|  |  | 2do pulso en la compuerta: NO se acepta |
|  |  | bajar sin volver a subir NO es apilamiento |
|  |  | y el evento se acepta |
|  |  | con la carga del unico pulso |
| 14 | TIEMPO MUERTO: los casilleros y la atribucion de arribos | oculto: en S_IDLE sin poder abrir |
|  |  | oculto: puede_abrir en 0 |
|  |  | oculto: 31 ciclos que busy_o no ve |
|  |  | rearm: 60 esta bajo thr_hi pero no re-arma |
|  |  | rearm: 10 esta bajo thr_lo y SI re-arma |
|  |  | rearm: y vuelve a poder abrir |
|  |  | zona bloqueada: 2 arribos en total |
|  |  | zona bloqueada: 1 abrio ventana |
|  |  | zona bloqueada: 1 perdido por rearm |
|  |  | zona bloqueada: ninguno en la ventana |
|  |  | zona bloqueada: ninguno bajo veto |
|  |  | zona bloqueada: la atribucion cierra |
|  |  | en la ventana: 2 arribos |
|  |  | en la ventana: 1 abrio |
|  |  | en la ventana: 1 perdido adentro |
|  |  | en la ventana: ninguno por rearm |
|  |  | en la ventana: la atribucion cierra |
|  |  | veto: 1 arribo |
|  |  | veto: no abrio ventana |
|  |  | veto: contado como vetado |
|  |  | veto: no cuenta como rearm |
|  |  | veto: la atribucion cierra |
|  |  | histeresis: un evento |
|  |  | histeresis: sin tiempo muerto oculto |
|  |  | histeresis: 1 arribo, 1 apertura |
|  |  | histeresis: nada perdido |
| 15 | FASE 2 — RE-ARMADO POR CONTADOR | nivel: UNA sola ventana en 120 muestras |
|  |  | nivel: y el resto es bloqueo oculto |
|  |  | contador: reabre con la senal ARRIBA de thr_lo |
|  |  | contador: el bloqueo oculto queda acotado |
|  |  | contador: los pedazos tienen el largo de la compuerta |
|  |  | contador: un pulso ancho dio VARIOS eventos |
|  |  | rechazo: el holdoff corre igual |
|  |  | rechazo: no reabrio |
|  |  | rechazo: y quedo rechazado |
| 16 | FASE 2 — APERTURA POR TRIGGER EXTERNO | ext: hubo un cruce de thr_hi |
|  |  | ext: pero NO abrio ventana |
|  |  | ext: atribuido a lost_notrig |
|  |  | ext: no llego ningun trigger |
|  |  | ext: la atribucion CIERRA igual |
|  |  | trigger: un flanco contado |
|  |  | trigger: abrio una ventana |
|  |  | trigger: y la cerro |
|  |  | trigger: el cruce fue a cnt_open |
|  |  | trigger: la atribucion cierra |
|  |  | flanco: 5 ciclos en alto = UN flanco |
|  |  | flanco: y UNA sola ventana |
| 17 | FASE 2 — FIFO DE PUBLICACION | bloqueante: una sola ventana |
|  |  | bloqueante: un solo evento |
|  |  | bloqueante: el 2do perdido en busy |
|  |  | bloqueante: sin contrapresion de FIFO |
|  |  | fifo: DOS ventanas |
|  |  | fifo: DOS eventos publicados |
|  |  | fifo: ninguno perdido |
|  |  | fifo: la ocupacion llego a 2 |
|  |  | fifo: vacia al final |
|  |  | fifo: el id publicado es el de la 2da ventana |
|  |  | fifo: la contrapresion se cuenta como tiempo muerto |
|  |  | saturada: la FIFO toco el tope |
|  |  | saturada: hubo eventos publicados |
|  |  | saturada: y contrapresion contada |
|  |  | saturada: la atribucion cierra |


### [`tb_mca_top`](tb_mca_top.sv) — `mca_top`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Identificación | magic = 'MCA1' |
|  |  | CAPS: los dos motores presentes |
|  |  | anchos: H_AW |
|  |  | anchos: H2_AW |
|  |  | anchos: PSD_AW |
|  |  | CAPS del DUT B: 2D ausente |
| 2 | Escritura y relectura de todos los registros RW | RW cfg_thr |
|  |  | RW cfg_hyst |
|  |  | RW cfg_baseline |
|  |  | RW cfg_bl_ctrl (holdoff) |
|  |  | RW cfg_bl_ctrl (k) |
|  |  | RW cfg_bl_ctrl (auto) |
|  |  | RW cfg_maxlen |
|  |  | RW cfg_tail_dly |
|  |  | RW cfg_amp_min |
|  |  | RW cfg_amp_max |
|  |  | RW cfg_amp_src |
|  |  | RW cfg_q_shift |
|  |  | RW cfg_h_shift |
|  |  | RW cfg_h2_shift |
|  |  | RW cfg_dec |
|  |  | RW CTRL run |
|  |  | RW CTRL chan_sel |
| 3 | BARRIDO DE ACK — la regresión importante | barrido de ack: ningun timeout |
|  |  | barrido de ack: sys_err siempre 0 |
| 4 | El mismo barrido en el DUT B, con el motor 2D AUSENTE | motor 2D ausente: sin timeouts de ack |
|  |  | motor 2D ausente: devuelve 0 |
|  |  | motor 2D ausente: sys_err 0 |
| 5 | Lectura DURANTE el barrido de borrado | barrido en curso (clear_busy) |
|  |  | lecturas durante el borrado: sin timeouts |
|  |  | clear_busy baja al terminar |
| 6 | CAMINO DE DATOS COMPLETO: inyectar pulsos y ver el bin correcto | cnt_total = 3 |
|  |  | cnt_accepted = 3 |
|  |  | espectro: todos los demas bins en 0 |
|  |  | espectro: el canal del pico acumulo 3 cuentas |
|  |  | espectro: bin vecino en 0 |
|  |  | ultimo evento: amplitud 200 |
|  |  | realtime avanza |
|  |  | livetime avanza |
|  |  | vetotime en 0 sin veto |
|  |  | estado: bit 3 = vetoed |
|  |  | livetime NO avanza bajo veto |
|  |  | bajo veto: cnt_total sigue en 3 |
|  |  | vetotime avanza |
|  |  | estado: vetoed vuelve a 0 |
|  |  | tras el veto: cnt_total = 4 |
| 7 | El borrado deja el espectro y los contadores en cero | tras borrar: el canal del pico en 0 |
|  |  | tras borrar: cnt_total en 0 |
| 8 | EL TESELADO DEL TIEMPO MUERTO, visto por el BUS | teselado: la palabra alta de realtime es 0 |
|  |  | teselado: realtime avanzo |
|  |  | teselado: realtime = veto+win+div+rearm+live |
|  |  | compat: deadtime (0x078) = t_win + t_div |
|  |  | oculto: t_rearm > 0 |
|  |  | oculto: y supera a la ventana |
|  |  | arribos: hubo al menos uno |
|  |  | arribos: uno abrio ventana |
|  |  | arribos: ninguno bajo veto |
|  |  | periodo: hubo al menos un periodo muerto |
|  |  | periodo: el maximo no excede el total |
|  |  | periodo: los extendidos no superan los periodos |
|  |  | bus: direccion no mapeada devuelve 0 |
| 9 | FASE 2 POR EL BUS: las politicas de ventana y el arbitro | fase2: la palabra de politicas vuelve igual |
|  |  | fase2: el holdoff de re-armado vuelve igual |
|  |  | fase2: PUB_K publicado |
|  |  | fifo: el teselado sigue cerrando |
|  |  | fifo: hubo tiempo de publicacion contado |
|  |  | fifo: deadtime (0x078) = solo t_win |
|  |  | arbitro: la marca de agua llego al tope |
|  |  | arbitro: el id de ventana avanzo |
|  |  | arbitro: se abrieron varias ventanas |
|  |  | arbitro: sin perdidas por falta de trigger |
|  |  | arbitro: ningun trigger externo |
|  |  | arribos: hubo cruces |
|  |  | arribos: los casilleros no exceden los cruces |
|  |  | ext: ninguna ventana sin trigger |
|  |  | ext: el cruce quedo en lost_notrig |
|  |  | ext: ningun flanco de trigger |
|  |  | ext: un solo flanco contado |
|  |  | ext: y UNA sola ventana abierta |
|  |  | ext: la ventana cerro |
|  |  | arribo adentro: contado en lost_active |
|  |  | arribo publicando: contado en lost_busy |
<!-- /AUTO:casos -->

## Casos borde conocidos

Lo que hay que probar y todavía no se prueba. Cada línea es deuda de
verificación, no una idea suelta.

| Caso borde | Por qué importa | Cubierto |
|------------|-----------------|----------|
| | | no |

## Assertions

En [`sim/sva/mca_top_sva.sv`](sva/mca_top_sva.sv), sin tocar el RTL
sintetizable. El `bind` está **dentro de [`tb_mca_top.sv`](tb_mca_top.sv)**, no
en un archivo aparte, y el motivo importa: un `bind` en el scope de la unidad de
compilación **no se elabora**. Questa avisa con `(vlog-2650)`, sigue adelante, y
las propiedades no existen — el testbench pasa igual. Así estaba el
`sva/bind_mca.sv` anterior, y no se había notado porque el archivo de
propiedades estaba vacío. Se comprueba con:

```
vsim -c -quiet -work questa tb_mca_top -do "find instances -recursive u_sva; quit -f"
  -> {/tb_mca_top/dut_a/u_sva (mca_top_sva)} {/tb_mca_top/dut_b/u_sva (...)}
```

Si eso devuelve vacío, **ninguna** propiedad está corriendo.

Las propiedades son en su mayoría **invariantes de teselado**: afirman que una
descomposición es exhaustiva, en todo ciclo. Es lo que separa "agregar
contadores" de "poder afirmar que no falta ninguno", y es lo que habría hecho
imposible el bug que motivó el bloque de tiempo muerto.

| Propiedad | Qué garantiza |
|-----------|---------------|
| `ap_dt_disjuntos` | Los casilleros de tiempo muerto no se solapan |
| `ap_puede_abrir_complemento` | …y son el complemento exacto de poder abrir: no hay un estado de bloqueo sin casillero |
| **`ap_suma_relojes`** | **`realtime = vetotime + t_win + t_div + t_rearm + livetime`, en todo ciclo.** Si se agrega una causa de bloqueo y se olvida su reloj, falla |
| `ap_deadtime_viejo_subestima` | El registro histórico `0x078` nunca excede el total honesto |
| `ap_deadtime_viejo_identidad` | …y con `pub_mode = 0` vale exactamente `t_win + t_div` |
| `ap_deadtime_viejo_fifo` | …mientras con `pub_mode = 1` vale sólo `t_win`: el registro viejo miente **más** en modo FIFO |
| `ap_busy_es_win_o_div` | `feat_busy` coincide con los casilleros que lo componen, según el modo |
| **`ap_contrapresion_es_muerta`** | **El desborde de la FIFO cuenta como tiempo muerto.** Sin esto el bloqueo oculto se habría mudado del Schmitt al árbitro |
| **`ap_atribucion_arribos`** | **`cnt_cross = cnt_open + lost_rearm + lost_active + lost_busy + lost_veto + lost_notrig`.** Ningún pulso se pierde sin quedar atribuido |
| `ap_win_vs_total` | Ventanas abiertas y cierres difieren como mucho en la ventana en vuelo |
| `ap_open_acotado_por_win` | Los cruces que abrieron nunca exceden las ventanas abiertas |
| `ap_arribo_libre_abre` | Un arribo con el módulo libre y sin veto siempre abre (fuente interna) |
| `ap_periodos_acotados` | No hay más períodos muertos que ciclos muertos |
| `ap_ext_acotado_por_periodos` | Los períodos extendidos se cuentan uno por período, no uno por arribo |
| `ap_ext_acotado_por_perdidas` | Cada extensión es un arribo perdido durante el bloqueo |
| `ap_max_len_acotado` | El período más largo no excede el total |
| `ap_dead_len_congelado` | El largo en curso sólo avanza durante el bloqueo |

**Las dos identidades de compatibilidad valen sólo si `pub_mode` no cambió desde
el último `clear`.** Los relojes son acumulativos, así que mezclar dos modos en
una misma cuenta no tiene identidad — sin que haya ningún bug. Se expresa con un
flag `modo_sucio` dentro del módulo de assertions, en vez de dejar una propiedad
que falle en un caso legítimo: una assertion que grita cuando no hay error se
termina desactivando, y entonces ya no protege nada.

### Los `cover property`, y por qué hacen falta

Quince, y no son decorativos: una propiedad condicionada por modo pasa
trivialmente si ese modo nunca se ejercitó. Estado (ucdb combinado de los 6 TB,
`make cov`):

| Cover | Hits | Qué asegura |
|---|---|---|
| `cp_rearm` | 33291 | Se ejercitó el bloqueo por re-armado |
| `cp_oculto` | 30974 | …con `busy` bajo: el caso que el diseño anterior no veía |
| `cp_lost_rearm` | 4 | Arribos perdidos esperando el re-armado |
| `cp_lost_active` | 2 | Arribos dentro de la ventana |
| `cp_lost_busy` | 2 | Arribos sin lugar donde publicar |
| `cp_ext` / `cp_periodo` | 7 / 56 | Períodos muertos y extensiones |
| `cp_trig_ext` | 1005 | Fuente de apertura externa seleccionada |
| `cp_trig_ambos` | 1180 | Fuente mixta |
| `cp_trig_flanco` | 4 | Flancos de trigger recibidos de verdad |
| `cp_notrig` | 4 | Cruces libres que no abrieron por falta de trigger |
| `cp_rearm_cnt` | 3144 | Re-armado por contador |
| `cp_pub_fifo` | 3144 | Publicación por FIFO |
| `cp_win_sin_cruce` | 39 | Ventana abierta **sin** cruce de `thr`: el caso que obligó a separar `cnt_win` de `cnt_open` |
| **`cp_contrapresion`** | **108** | **La FIFO se llenó de verdad.** En cero, el casillero nuevo del teselado estaría sin probar |

> **Tres de estos covers leían CERO hasta que se los fue a buscar.** `cp_trig_*`
> y `cp_notrig` sólo se ejercitaban en `tb_mca_pulse_feature`, que **no tiene el
> bind** de assertions; y `cp_lost_active`/`cp_lost_busy`, que existen desde la
> fase 1, nunca se habían ejercitado en `tb_mca_top` —el único TB con las
> propiedades puestas—, así que esas ramas de `ap_atribucion_arribos` jamás se
> habían evaluado con contenido. Es el mismo modo de falla que el `bind` que no
> se elaboraba: algo que el flujo daba por verificado y no lo estaba. Los casos
> que faltaban están ahora en `tb_mca_top` test 9.

Estado: **17 propiedades × 2 instancias, 0 fallas** en `tb_mca_top`, y **15 de 15
covers alcanzados**.

> **`make cov` no funcionaba, y por la misma razón que el `bind`.** Los
> testbenches terminan con `$finish`, que por defecto **sale** del simulador: el
> `coverage save` del `-do` nunca se ejecutaba, `cov/` quedaba vacío y el
> `vcover merge` fallaba con *"All files were empty"*. Se arregla con
> `-onfinish stop`, que ahora está en `module.mk` dentro de la rama `ifdef COV`
> para no tocar en nada el flujo normal.

## Metas de cobertura

| Métrica | Meta | Actual |
|---------|------|--------|
| statements | 100% | |
| branches | 100% | |
| toggle | 90% | |
| covergroups funcionales | 100% | |

Las metas son del código del módulo (`files.f`), no del RTL del repo raíz que
arrastre por `extra.f`.

## Lo que la simulación no cubre: la validación en placa

Las 17 assertions prueban las invariantes **en el modelo**. Que valgan en el
silicio, leídas por el bus de verdad, es otra afirmación y necesita la placa.
La campaña que lo hace es
[`campanas/run_politicas.py`](../../../software/campanas/run_politicas.py)
(`make -C software campana-politicas-remoto`), con cinco secciones:
`invariantes`, `barrido`, `politicas`, `rearm_dly` y `distribucion`.

### Estado al 2026-10-22

Corrido en la placa (`rp-f08768`, 10.73.28.30) con el bitstream de las fases
1-2 cargado:

| qué | resultado |
|---|---|
| los 7 registros nuevos existen y hacen round-trip | **OK** — las 4 combinaciones de `trig_src`/`rearm_mode`/`pub_mode`/`rearm_dly` |
| `PUB_K` leído del hardware | **2** — la FIFO se sintetizó con los dos lugares |
| teselado `realtime == veto+win+div+rearm+live` por AXI | cerró **exacto**: 375 397 848 == 375 397 848, diferencia 0 |

**Y ese último OK no vale como validación todavía.** La corrida tenía
`cross = 0`: el generador estaba con la salida apagada, así que el MCA no vio un
solo pulso y las cinco identidades cerraron con `0 == 0`. Seis OK que no
probaban nada. Dos arreglos, y el segundo es el que importa:

1. `rg.apply_poisson_train` sube la forma pero **no enciende la salida** (lo
   hace el llamador), y `tb.connect()` arranca con un `gen.reset()` que la
   apaga. La campaña ahora tiene una sola puerta de entrada al estímulo,
   `estimulo()`, que enciende.
2. **`invariantes` ahora exige que el estímulo haya llegado** —`cross > 0`,
   `windows > 0`, `t_win > 0`, `t_rearm > 0`— y es el primer chequeo de la
   lista. Una identidad de la forma `a == b + c` cierra sola con la entrada
   muerta; sin este guard la campaña informa éxito sobre una corrida vacía.

Lo que queda pendiente de placa, entonces: las cinco secciones con señal real.
Falta medir el teselado con los casilleros cargados, el barrido que muestra
`deadtime_real` monótono contra `deadtime_cnt` que no lo es, las cuatro
políticas sobre el mismo estímulo, el codo de `rearm_dly` y la discriminación
paralizable/no paralizable por `E[L]/tau`.

> **Nota sobre comparar contra la tabla de `figuras_trigger.py`.** El criterio
> de aceptación del plan era reproducir 11.0 / 25.6 / 52.2 / 85.7 % de bloqueo
> real. Esa tabla sale de correr la FSM sobre señal sintetizada con cola de
> 5.9 µs sobre `thr_lo`; el Rigol entrega pulsos de ~2 µs de FWHM, con otra cola
> y por lo tanto otro τ. Los porcentajes no tienen por qué coincidir y decir
> que "reproduce la tabla" sería comparar dos estímulos distintos. Lo que sí se
> contrasta es la forma (monotonía) y el τ medido contra el que predice la
> configuración.

### Síntesis: el build completo no dice lo mismo que el OOC

El OOC de `mca_top` aislado deja WNS en 0.070 ns y el camino crítico en
`cfg_amp_max → max_q`, sin degradación atribuible a la fase 2. **El build
completo post-route dice otra cosa**, y es el que decide:

| build | WNS | camino crítico |
|---|---|---|
| HEAD, antes de las fases 1-2 | 0.050 ns | fuera del MCA (`i_scope`) |
| con las fases 1 y 2 | **0.006 ns** | `i_mca/dat_q[7]` → `i_mca/i_feat/q_tot[14]/R` |

El camino es `dat_q → x → (x>=thr_hi) → disparo → open_pulse → q_tot/R`: el de
la apertura, que es el que la fase 2 tuvo que tocar para multiplexar la fuente
de disparo. El análisis completo y las tres palancas para recuperar slack están
en [`docs/datasheet/datasheet_mca_top.md`](../../../docs/datasheet/datasheet_mca_top.md),
sección 1.5.
