<!-- Prosa a mano del datasheet de `osc_filter`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_osc_filter.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es el **ecualizador** del camino de datos del osciloscopio: una
compensación polo-cero de cuatro coeficientes (`aa`, `bb`, `kk`, `pp`), dos IIR
de primer orden más una etapa de escalado, que procesa una muestra por ciclo de
`adc_clk`. Va entre la calibración y la decimación, dentro de
[`rp_scope_mt_com`](../datasheet_rp_scope_mt_com.md), y su
razón de ser es cancelar la cola del detector: poner un **cero donde el
preamplificador pone su polo**.

Lo que el filtro hace está medido, no descrito: su respuesta al impulso lo
caracteriza entero, y es lo que dibuja
[`osc_c_respuesta.png`](../../osc/figuras/transacciones/osc_c_respuesta.png).

| Coeficientes | Qué sale de un impulso de 4000 cuentas |
|---|---|
| los de **reset** | una sola muestra de 3999 — ganancia 0.99975, que es el redondeo de `kk = 2^24−1` en vez de `2^24` |
| **polo-cero** | una exponencial que arranca en 3943 y tarda 99 ciclos en caer al 1 % |

La latencia medida es **8 ciclos en los dos casos**: el pipeline no depende de
los coeficientes. Con polo-cero el pico viene precedido por un precursor de
hasta 118 cuentas que arranca 4 ciclos antes —el camino directo llega antes que
las dos IIR—, así que medir la latencia por la primera muestra no nula daría 4
y sería una lectura equivocada del mismo dato.

**Tres cosas que conviene saber antes de usarlo.**

- **No está en el bitstream del MCA.** El lazo IIR no cierra timing a 125 MHz y
  es lo que fijaba el camino crítico del diseño, así que los tops del MCA y del
  anillo de eventos lo instancian con `EN_FILT = 0`, que lo saca del camino de
  datos; sólo el top de fábrica
  ([`red_pitaya_top.sv`](../../../rtl/mine/tops/red_pitaya_top.sv)) lo compila
  dentro. Con `EN_FILT = 0` la señal calibrada pasa directo y **también
  desaparecen los ~5 ciclos de latencia del filtro**, pero el corrimiento es
  común al trigger y al buffer, así que siguen alineados.
- **El `tready` de la interfaz AXI-S no frena nada.** El dato llega una muestra
  por ciclo venga de donde venga, así que lo que el bloque hace tiene que
  hacerlo en un ciclo. El puerto existe; el contrato de flujo, no.
- **El bypass no se hace acá.** `cfg_bypass` está atado a `1'b0` en la
  instancia; quien elige entre señal filtrada y señal cruda es `set_filt_byp`,
  un mux de afuera.

El bloque se verifica por **equivalencia secuencial** contra una copia
congelada del filtro anterior al rediseño (`osc_filter_ref.v`), instanciada al
lado del DUT y alimentada con el mismo flujo: no se comparan métricas sino las
dos salidas muestra por muestra, y coinciden en 460 de 460 ciclos dibujados
([`osc_b_cadena.png`](../../osc/figuras/transacciones/osc_b_cadena.png)). Eso vale
**para los coeficientes de esas escenas más los 12 juegos aleatorios del
testbench**, no para todo el espacio; cubrirlo entero con `aa/bb/kk/pp`
simbólicos es uno de los candidatos que discute
[`verificacion_formal.md`](../../verificacion_formal.md).

> **Dos deudas documentadas.** El archivo es Verilog heredado y **no tiene
> cabecera**: todo lo de arriba está reconstruido del código y de la
> simulación, no copiado de un comentario. Y la escena 5 de `tb_osc_filter`,
> que se llama «kk extremos: saturación en la etapa de escalado», escribe
> `25'h1FFFFFF` sobre un `wire signed [24:0]`: ese valor es **−1**, no un
> máximo. La ganancia queda en ≈−2⁻²⁴, la salida colapsa a 0 y las ramas de
> saturación nunca se ejercitan. La escena pasa; lo que dice probar, no.
