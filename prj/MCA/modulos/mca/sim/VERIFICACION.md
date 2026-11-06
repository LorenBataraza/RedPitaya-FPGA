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

**206 casos con nombre** en 8 testbenches. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

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


### [`tb_mca_top`](tb_mca_top.sv) — `mca_top`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Identificación | magic = 'MCA2' |
|  |  | CAPS: los dos motores presentes |
|  |  | anchos: H_AW |
|  |  | anchos: H2_AW |
|  |  | anchos: PSD_AW |
|  |  | CAPS del DUT B: 2D ausente |
|  |  | CAPS: trapecio presente (bit 2) |
|  |  | reset: trapecio k y m |
|  |  | reset: trapecio M |
|  |  | reset: ventana de la meseta (ok, sh, lw, off) |
|  |  | reset: banco (umbr_ok, N_FORMAS = 4, n_formas = 1) |
|  |  | reset: FORMA_KM 0 = 0x128 |
|  |  | reset: FORMA_MED 0 = 0x130 |
| 2 | Escritura y relectura de todos los registros RW | RW cfg_baseline |
|  |  | RW cfg_bl_ctrl (holdoff) |
|  |  | RW cfg_bl_ctrl (k) |
|  |  | RW cfg_bl_ctrl (auto) |
|  |  | RW cfg_amp_min |
|  |  | RW cfg_amp_max |
|  |  | RW cfg_amp_src |
|  |  | RW cfg_q_shift |
|  |  | RW cfg_h_shift |
|  |  | RW cfg_h2_shift |
|  |  | RW cfg_dec |
|  |  | RW compuerta larga |
|  |  | RW compuerta corta |
|  |  | RW cfg_n_acc |
|  |  | RW cfg_pre_dly |
|  |  | N_ACC publicado |
|  |  | RW trapecio k |
|  |  | RW trapecio m |
|  |  | RW trapecio M (20 bits) |
|  |  | RW meseta off |
|  |  | RW meseta lw |
|  |  | RW meseta sh |
|  |  | la ventana de la meseta entra en la compuerta |
|  |  | la ventana de la meseta NO entra en la compuerta |
|  |  | alias: 0x128 es FORMA_KM 0 |
|  |  | alias: 0x130 es FORMA_MED 0 |
|  |  | alias: escribir 0x128 escribe FORMA_KM 0 |
|  |  | reservado: +C de la forma 0 lee 0 |
|  |  | reservado: 0x1C0 lee 0 |
|  |  | la ventana y los umbrales no pulsan clr |
|  |  | FORMA_KM 2 pulsa clr |
|  |  | n_formas = 1: el despues de la forma 0 entra (umbr_ok) |
|  |  | n_formas = 2: el de la forma 1 no entra (umbr_ok = 0) |
|  |  | RW n_formas (3 bits) |
|  |  | N_FORMAS es de solo lectura |
|  |  | RW CTRL run |
|  |  | RW CTRL chan_sel |
|  |  | reservados: se leen en cero |
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
|  |  | sin disparo: cnt_total sigue en 3 |
|  |  | estado: bit 3 = vetoed |
|  |  | livetime NO avanza bajo veto |
|  |  | bajo veto: cnt_total sigue en 3 |
|  |  | bajo veto: dos arribos vetados |
|  |  | vetotime avanza |
|  |  | estado: vetoed vuelve a 0 |
|  |  | tras el veto: cnt_total = 4 |
| 7 | El borrado deja el espectro y los contadores en cero | tras borrar: el canal del pico en 0 |
|  |  | tras borrar: cnt_total en 0 |
| 8 | EL TESELADO DEL TIEMPO MUERTO, visto por el BUS, con UNA ranura | teselado: la palabra alta de realtime es 0 |
|  |  | teselado: realtime avanzo |
|  |  | teselado: realtime = veto + win + div + live |
|  |  | una ranura: deadtime (0x078) = t_win + t_div |
|  |  | una ranura: la ventana ocupa la compuerta + 1 |
|  |  | una ranura: la espera de los divisores |
|  |  | ocupacion: t_ocup[0] + t_ocup[1] = realtime |
|  |  | ocupacion: t_ocup[1] = deadtime |
|  |  | arribos: uno |
|  |  | arribos: y abrio ventana |
|  |  | arribos: ninguno bajo veto |
|  |  | periodo: uno |
|  |  | periodo: dura la ventana mas la publicacion |
|  |  | periodo: sin arribos adentro |
|  |  | bus: direccion no mapeada devuelve 0 |
| 9 | VARIAS RANURAS, por el bus | ranuras: cuatro ventanas abiertas |
|  |  | ranuras: dos perdidas con todas midiendo |
|  |  | ranuras: cuatro eventos publicados |
|  |  | ranuras: la cola llego a las cuatro cerradas |
|  |  | ranuras: atribucion (cross = open + active + veto + busy) |
|  |  | ranuras: el teselado sigue cerrando |
|  |  | ranuras: hubo tiempo con las cuatro ocupadas |
|  |  | ranuras: la ocupacion tesela el tiempo sin veto |
|  |  | ranuras: t_ocup[4] > 0 |
|  |  | disparo sostenido: un solo flanco contado |
|  |  | disparo sostenido: UNA sola ventana |
|  |  | retardo: la ventana abrio en el pie (pico 500) |
| 10 | EL TRAPECIO: el pulso que monta sobre la cola de otro mide limpio | trapecio: un evento |
|  |  | trapecio: par a dt = 60, dos eventos |
|  |  | trapecio: par a dt = 30, dos eventos |
|  |  | trapecio: ventana incompleta, F_TRAP = 0 |
| 10 | toma los pares que la forma 0 no puede medir limpio | banco: con la forma 0 descartada, publica la 1 |
|  |  | banco: dt = 60, dos eventos |
|  |  | banco: dt = 60, el primero con la forma 0 |
|  |  | banco: dt = 60, el segundo con la forma 0 |
|  |  | banco: dt = 30, dos eventos |
|  |  | banco: dt = 30, el primero con la forma 1 |
|  |  | banco: dt = 30, el segundo con la forma 1 |
|  |  | banco: dt = 5, dos eventos |
|  |  | banco: dt = 5, el primero marcado (F_FORMA) |
|  |  | banco: dt = 5, el primero marcado (F_TRAP = 0) |
|  |  | banco: dt = 5, el segundo marcado (F_FORMA) |
|  |  | banco: dt = 5, el segundo marcado (F_TRAP = 0) |
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
| `ap_dt_disjuntos` | Los dos casilleros de tiempo muerto (`dt_win`, `dt_div`) no se solapan |
| `ap_puede_abrir_complemento` | …y son el complemento exacto de poder abrir: no hay un estado de bloqueo sin casillero |
| **`ap_suma_relojes`** | **`realtime = vetotime + t_win + t_div + livetime`, en todo ciclo.** Si se agrega una causa de bloqueo y se olvida su reloj, falla |
| **`ap_suma_ocupacion`** | **`Σ t_ocup[j] = realtime − vetotime`**: cada ciclo sin veto suma a exactamente un casillero de ocupación |
| `ap_deadtime_es_ocupacion` | `deadtime` (0x078) es la ocupación de **alguna** ranura: todo menos `t_ocup[0]` |
| `ap_busy_es_ocupacion` | `feat_busy` coincide con haber alguna ranura ocupada |
| `ap_una_ranura` | Con `cfg_n_acc = 1` (y sin cambiarlo desde el `clear`), `deadtime = t_win + t_div`: la arquitectura de una ventana |
| `ap_llenas_no_abre` | Todas las ranuras ocupadas implica no poder abrir |
| `ap_cola_acotada` | La cola de publicación nunca pasa de `N_ACC` |
| **`ap_atribucion_arribos`** | **`cnt_cross = cnt_open + lost_active + lost_busy + lost_veto`.** Ningún disparo se pierde sin quedar atribuido |
| `ap_open_es_win` | Con el disparo como única fuente, cada ventana viene de un disparo |
| `ap_win_vs_total` | Ventanas abiertas y cierres difieren como mucho en las `N_ACC` en vuelo |
| `ap_arribo_libre_abre` | Un arribo con alguna ranura libre y sin veto siempre abre |
| `ap_periodos_acotados` | No hay más períodos muertos que ciclos muertos |
| `ap_ext_acotado_por_periodos` | Los períodos con arribo se cuentan uno por período, no uno por arribo |
| `ap_ext_acotado_por_perdidas` | Cada período con arribo es un disparo perdido por falta de ranura |
| `ap_max_len_acotado` | El período más largo no excede el total |
| `ap_dead_len_congelado` | El largo en curso solo avanza durante el bloqueo |

**`ap_una_ranura` vale solo si `cfg_n_acc` no cambió desde el último `clear`.**
Los relojes son acumulativos, así que mezclar dos configuraciones en una misma
cuenta no tiene identidad —sin que haya ningún bug—. Se expresa con un flag
`modo_sucio` dentro del módulo de assertions, en vez de dejar una propiedad que
falle en un caso legítimo: una assertion que grita cuando no hay error se termina
desactivando, y entonces ya no protege nada.

### Los `cover property`, y por qué hacen falta

Una propiedad condicionada pasa trivialmente si su condición nunca se dio. Los
once covers aseguran que las ramas de las propiedades de arriba se evaluaron con
contenido:

| Cover | Qué asegura |
|---|---|
| `cp_llenas` / `cp_varias` | Hubo ciclos con todas las ranuras ocupadas, y con dos o más |
| `cp_dt_win` / `cp_dt_div` | Se cargaron los dos casilleros de tiempo muerto |
| `cp_lost_active` / `cp_lost_busy` / `cp_lost_veto` | Las tres causas de pérdida de un disparo |
| `cp_ext` / `cp_periodo` | Períodos muertos, y períodos con un arribo adentro |
| `cp_cola_llena` | La cola de publicación llegó a `N_ACC` |
| `cp_flanco` | Llegaron flancos de trigger de verdad |

La sección 9 de `tb_mca_top` (la ráfaga con cuatro ranuras) es la que alcanza
los covers de las ranuras al nivel del top: sin ella quedaban en cero, que es el
modo de falla de un `bind` que no se elabora pero con otra cara.

## El trapecio (`mca_trap`)

No lleva assertions propias: su contrato es aritmético y se verifica contra
modelos.

| Qué | Dónde | Resultado |
|---|---|---|
| **bit a bit contra `estimadores.trapecio`**, el modelo de Python | `tb_mca_trap`, vectores de [`vectores/gen_trap.py`](vectores/gen_trap.py) | 28 413 muestras en cuatro formas (polo-cero exacto con apilamiento; líneas de 1000 muestras; `sh = 0`; M y muestras al límite), con 30 % de huecos de `val` y el `clr` entre casos: **0 errores** |
| dentro de las ranuras | `tb_mca_multi` | un modelo del trapecio aparte, con `clr` a mitad de ventana; cubre `F_TRAP` en rango, saturado, negativo e incompleto en los tres DUT que lo tienen |
| de punta a punta | `tb_mca_top` §10 | pulso solo 6313 (teoría 6312.5); par a Δt = 60 ≥ k+m: **6313 y 3787 = 0.6 × 6313**, con el pico del segundo en 901 en vez de 600; a Δt = 30 < k+m, contaminado; ventana fuera de la compuerta, `F_TRAP = 0` |

**Mutaciones**: 14 errores inyectados a mano en `mca_trap`, `mca_slot`,
`mca_window` y `mca_publish`, y `tb_mca_multi` los detectó **todos**: la dirección
de la tercera línea, la máscara de `k + l`, los bits fraccionarios de M, el reset
de `p` con el `clr`, el signo de la saturación, el borde de la ventana, la
latencia, la comprobación de ventana completa, el índice de la máscara corrido
una etapa, la saturación del contador, un corrimiento lógico en vez de
aritmético, el reset de la suma al abrir, la entrada saturada en vez de con signo
y la cadena de retardo de la tercera línea.

## El banco de trapecios (2026-11-03)

`N_FORMAS` trapecios en `mca_window`, una meseta por forma en cada `mca_slot`, y
la elección en `mca_publish` (`F_TRAP` de la forma elegida y `F_FORMA`). Ver
[`pruebas_banco_trapecios.md`](../../../docs/mca/pruebas_banco_trapecios.md) §5.

| Qué | Dónde | Resultado |
|---|---|---|
| `mca_trap` con las líneas en LUT y el reset sin `clr` | `tb_mca_trap` (`dut` y `dut_lut`), más los 10 casos de `banco_vectores_trap.py` con `+NCASOS=10` | 0 errores en las dos memorias. El caso de reset sin `clr` **falla con el reset viejo de `kl`** (en cero) y pasa con el nuevo (en todo unos) |
| la regla de elección y las N mesetas | `tb_mca_multi`, con 4 DUT: (N_ACC, EN_PSD, N_FORMAS) = (4,1,4), (1,1,1), (3,1,2), (2,0,0) | cobertura completa en seis semillas: cada forma elegida, el marcado, y la forma elegida **justo** en su umbral de antes y en el de después |
| los registros y el banco por el bus | `tb_mca_top` §1, §2 y §10b | reset de `0x134` y de los cuatro bloques, el alias `0x128`/`0x180`, el `clr` solo con k, m o M, `umbr_ok`. Con dos formas: a Δt = 60 se elige la forma 0; a 30 la 1, limpia (6312 y 3787); a 5, los dos marcados |
| invariantes | SVA `ap_forma_valida`, `ap_marcado_sin_altura` | `F_FORMA` ∈ {0..n_formas−1, 0xFFFF} y marcado ⇒ `F_TRAP` = 0, en todos los eventos |
| de punta a punta, con el polo-cero | `tb_banco_e2e.sv` y `banco_e2e.py` | sobre un tren de Poisson, `F_TRAP` bit a bit en 21 966 de 21 966 eventos, y la misma clase que el modelo en el 99.95–100 % de los pulsos |

**Mutaciones del banco**: 13 inyectadas en `mca_publish`, `mca_window` y
`mca_slot`, con `tb_mca_multi` corriendo 300 000 ciclos:

- **Detectadas, 12:**
  - `≤` por `<` en cada umbral;
  - `dt_prev` y `dt_next` cruzados;
  - la prioridad al revés;
  - el marcado sin poner `F_TRAP` en cero;
  - `n_formas` ignorado;
  - la ventana, el `lw`, la salida, el `sh` y el `l` de otra forma;
  - la elección registrada en el ciclo equivocado.
- **No detectada, 1, y es equivalente:** sacar la saturación de `n_formas`, que
  el lazo ya acota.

Las de ventana se detectaban con 2 o 3 errores en 300 000 ciclos, porque con
formas al azar `F_TRAP` casi siempre salía en cero. Con el sorteo de un "banco
realista" (formas que se acortan a la mitad, ventanas dentro de la compuerta, el
M de una cola típica) pasaron a 16–33.

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

Las assertions prueban las invariantes **en el modelo**. Que valgan en el
silicio, leídas por el bus de verdad, es otra afirmación y necesita la placa.

### Estado al 2026-10-30 — el bitstream de las ranuras ("MCA2")

[`software/API/tests/placa/test_mca2_placa.py`](../../../software/API/tests/placa/test_mca2_placa.py),
corrido en la placa (`rp-f08768`, 10.73.28.30) con el Rigol en IN1: **349 PASS,
0 FAIL**. Es autónomo (habla los registros "MCA2" a mano) porque `API/mca.py`
todavía es el de "MCA1".

| Etapa | Qué mide | Resultado |
|---|---|---|
| `regs` | identificación, 17 registros escribibles, 11 reservados en cero, barrido del bus, borrado, relojes en reposo | 42 / 42 |
| `periodico` | tren de 2 kHz: disparos sin pérdida, las cinco identidades por AXI con pulsos de verdad, la ley de Little | ocupación por ventana **403.00 = gate + 19** ciclos; espectro con 1 ranura contra 4: pico **1149.84 contra 1149.85**, ancho 1.37 contra 1.38 |
| | `F_TRISE` contra `cfg_pre_dly` | pendiente **0.9989**; la latencia del disparo con este pulso es ~14 ciclos (conviene `pre_dly` 16, no el 11 del reset) |
| | `F_DTPREV` contra el período del generador | 99.98 % en el canal del período |
| `par` | pares a 1.6 µs | con 1 ranura el segundo es `lost_active` y toda ventana queda marcada; con 2 y 4 se miden los dos, `F_DTPREV`/`F_DTNEXT` = 200 ± 3 muestras y `F_SOLAPE` mitad "adentro", mitad "otra abierta" |
| `poisson` | 30, 100 y 250 kev/s, dos semillas, 1 a 4 ranuras | la pérdida medida coincide con una simulación M/D/N/N **sobre el mismo patrón de arribos**, reconstruido de la semilla del generador: 37.36 contra 37.00 %, 7.63 contra 7.05 %, 1.05 contra 1.01 %; la ocupación `t_ocup[j]` a ±0.01 por casillero. Erlang B la sobreestima (41.8, 13.1 %) porque el disparo funde los pulsos a menos de ~0.5 µs y el proceso de disparos queda más regular que Poisson |

La etapa `trapecio` (bitstream con `mca_trap`) usa pulsos de preamplificador del
Rigol (subida de 10 ns, cola de 2 µs) en una forma con un **par** (a1 y
a2 = 0.6 a1 a 1 µs) y **los mismos dos pulsos aislados**; el discriminador por
`F_DTPREV` separa el segundo del par de su referencia aislada, con la misma forma
cargada. k = 64, m = 48 (k + m = 112 muestras < 125):

| M | segundo del par | a2 aislado | error |
|---|---|---|---|
| 239.5 | 2398.03 | 2382.75 | +0.64 % |
| 244.5 | 2414.44 | 2422.28 | −0.32 % |
| 249.5 (nominal, τ = 2 µs) | 2430.84 | 2461.87 | −1.26 % |
| 259.5 | 2463.92 | 2541.13 | −3.04 % |
| **242.8 (ajustado)** | **2409.05 ± 0.98** | **2409.08 ± 1.02** | **−0.001 %** |

**El polo-cero hay que ajustarlo en el hardware.** El error es lineal en M y
cruza cero en M = 242.8: la cola que llega al ADC es de 1.946 µs, no los 2 µs
programados (la cadena Rigol → entrada de la placa la acorta un 2.7 %). Con M
ajustado, el segundo pulso —que llega sobre el 61 % de la cola del primero— mide
lo mismo que aislado; su pico, en cambio, da el doble (canal 2461 contra 1204). A
Δt = 0.5 µs < k + m el segundo se contamina (+66 %), como tiene que ser. La
primera carga de una forma después del `reset` del generador a veces no sale
(se midió ~1 MHz de disparos espurios): la etapa verifica la tasa de cada forma
y la recarga.

### Estado al 2026-10-22 — el bitstream "MCA1" (histórico)

La campaña era
[`campanas/run_politicas.py`](../../../software/campanas/run_politicas.py)
(`make -C software campana-politicas-remoto`), con cinco secciones:
`invariantes`, `barrido`, `politicas`, `rearm_dly` y `distribucion`. Las
políticas que medía (re-armado, modo de publicación) ya no existen.

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

### El bitstream con el trapecio no cierra timing — y no es el MCA

Con `mca_trap` el diseño pasa a 69 % de LUT (12 188), 5 DSP y 26.5 BRAM. El
dominio del MCA (`pll_adc_clk`) cierra con **+0.023 ns**, pero el build falla en
`clk_fpga_3`: **−0.383 ns** en un camino interno del `axi_protocol_converter_0`
que lleva el AXI-lite del PS al XADC, a 200 MHz. Es IP del block design, no RTL
del proyecto; con las ranuras ya cerraba por +0.003 ns, y el script de build
documenta que "cada tanto queda del otro lado". Se probaron cinco
implementaciones desde el mismo `post_synth.dcp` y ninguna cierra:

| Implementación | WNS `clk_fpga_3` |
|---|---|
| la del build (y `phys_opt` post-route) | −0.383 ns |
| `place_design -directive ExtraTimingOpt` | −0.154 ns |
| ExtraTimingOpt + `phys_opt`/`route` AggressiveExplore | −0.123 ns |
| Pblock del convertidor | −0.214 ns |
| Pblock del convertidor y el XADC + lo anterior | −0.243 ns |
| `AltSpreadLogic_high` + AggressiveExplore | −0.040 ns |

El camino es lógica real (8 niveles con un sumador de 12 bits) a 200 MHz en un
7z010 grado −1: compacto o no, vive en el límite. El arreglo de fondo es de
plataforma: en `prj/MCA/ip/systemZ10.tcl` el XADC, el convertidor, el register
slice y `M_AXI_GP1` comparten `FCLK_CLK3` (200 MHz), que existe para la
referencia de los IDELAY; pasarlos a `FCLK_CLK0` (125 MHz) les da 3 ns más.

**Hecho el 2026-10-30** en `prj/MCA/ip/systemZ10.tcl` (y `dts/pl_patch.dtsi` a
fclk0). Falta rearmar el bitstream para confirmar que cierra.

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
