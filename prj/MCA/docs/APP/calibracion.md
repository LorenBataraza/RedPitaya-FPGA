# La pestaña «Calibration»: el canal analógico y la base dinámica

En el modo analógico las líneas del MCA se corren con la tasa: con el canal
OUT1 → T 50 Ω → IN1 y la base fija, unos 9 canales a 400 k/s y 18 a 1 M/s
([`resultados_meritos_gen_pulsos.md`](../resultados_meritos_gen_pulsos.md) §2.5). La causa
son los **polos lentos del canal**: la respuesta a un escalón cae una fracción
`caída` = Σd/Σc en algunos µs, cada pulso deja una cola negativa y las colas apiladas
bajan la base. La pestaña mide el canal, ayuda a decidir de dónde es la caída y la
compensa moviendo la base fija con la tasa.

## La ecuación

La base bajo cada pulso queda corrida, en promedio,

$$\Delta b = \text{caída}\cdot\frac{\lambda}{f_s}\cdot\langle A\rangle\cdot\tau$$

con λ la tasa, ⟨A⟩ la amplitud media en IN1 (ADU) y τ la caída de los pulsos (muestras):
λ⟨A⟩τ/f_s es el nivel medio del tren. El trapecio con polo-cero pasa ese error a la
amplitud como (l/τ)·Δb, con l = k + m el largo de la forma. La **base dinámica** escribe
en la base fija del MCA

$$b = b_0 + \kappa\cdot\text{caída}\cdot\frac{\hat\lambda}{f_s}\cdot\frac{\langle F\rangle}{G_F}\cdot\tau$$

| Término | De dónde sale |
|---|---|
| b₀ | la base a tasa cero: el offset de IN1 medido («Set b0 = offset») |
| caída | Σd/Σc del canal, de la medición (la fila elegida en «drop from») |
| λ̂ | los disparos sin veto sobre el tiempo en que pudieron llegar, entre dos pasos: la misma λ̂ del `status`. Cuenta también los perdidos sin ranura, que dejan su cola igual |
| ⟨F⟩ / G_F | la feature media de lo que entró al histograma entre dos pasos, sobre G_F, las cuentas de la feature por ADU de IN1 (`mca.ganancia`) |
| τ | la del polo-cero del trapecio: `trap_mq`/16 + 1/2 |
| κ | un factor de ajuste, 1 por defecto (ver «Check») |

λ̂ y ⟨F⟩ se promedian con una constante de 1 s de tiempo del MCA, y |Δb| se limita a
1000 ADU. Lo corre un hilo del servidor cada 250 ms (`mca-base`), así que sigue aunque la
GUI se desconecte. La ley está en [`API/base_dinamica.py`](../../software/API/base_dinamica.py).

**Qué no corrige.** El corrimiento **medio**: la base bajo un pulso fluctúa con los
vecinos que tuvo, y eso sigue ensanchando la línea. Supone, además, que los pulsos que el
MCA pierde tienen el mismo espectro que los que mide, y que la feature del eje es una
amplitud (con `t_subida` en el eje, ⟨F⟩ no dice nada).

## Cómo se mide el canal

Se captura el mismo estímulo con la BRAM dos veces, disparada por la fuente ASG en el
primer pulso: con el lazo digital (`x`, el generador tal cual) y sin él (`y`, lo que
vuelve por IN1). Como el generador es determinista y el disparo es digital, `x[n]` e
`y[n]` son el mismo instante, y el canal se ajusta por cuadrados mínimos:

$$y[n] = b + \sum_j c_j\,x[n-j] + \sum_i d_i\,(p_i * x)[n]$$

con p_i un pasabajos de un polo de 3.2, 12.8 y 51 µs. Todo está en
[`API/canal.py`](../../software/API/canal.py); las campañas lo usan por
`campanas/canal_analogico.py`, que lo reexporta.

| Medición | Cómo | Qué da |
|---|---|---|
| rápida | a ritmo pleno, la ruta del OSC en `TAP_ADC` (las cuentas que ve el MCA): el piso sin pulsos y un Poisson de escalones de los dos signos | el FIR de 48 taps: ganancia, latencia, corrimiento del ASG, subida, sobrepico, −3 dB; offset y ruido; diafonía a IN2. La caída sale de 65 µs de captura, 1.3 veces el polo más lento: **poco determinada** |
| lenta | cuasi-escalones de ±3000 con τ = 524 µs (el DECAE máximo) cada 131 µs, con **diezmado 8 y promedio** (~0.5 ms por captura), x una vez e y `promedios` veces, en un ajuste | la ganancia de corto plazo y la caída por polo, bien determinadas |
| externa | sin el generador: una cuadrada de afuera en IN1, disparo por software, diezmado 8 | la caída de **IN1 sola** |

Tres detalles de la lenta y la externa:

- **El diezmado va por la ruta nativa del OSC**, porque `TAP_ADC` lo saltea. La
  calibración del RTL escala x e y por igual, así que Σd/Σc no cambia.
- **Los flancos quedan fuera del ajuste.** El diezmado corre libre respecto del arranque
  del generador, así que cada captura tiene su fase: sin la máscara, los flancos meten
  cientos de cuentas (`test_con_los_flancos_adentro_la_lenta_se_arruina`). Lo que se
  ajusta es la ganancia de corto plazo (un tap) y los polos lentos.
- **La externa ajusta también el estado inicial de cada polo**, una columna
  e^(−n/τᵢ) por polo y por captura: la cuadrada viene de antes de la captura. El escalón
  ideal sale de la propia captura (umbral a media altura), así que no hace falta saber
  la amplitud ni la frecuencia; la ganancia, en cambio, no tiene escala y no se muestra.

«Repeatability» mide dos veces la rápida y compara IN1 contra √2·σ del piso: una T floja
(como la del 2026-11-14) da cientos de cuentas.

## De dónde es la caída (con tus manos)

El canal medido es OUT1 + cable + carga + IN1. Si la caída es de la salida cargada con
50 Ω, con un sensor en IN1 no existe, y compensarla **agregaría** el error. La tabla
**Origin** junta una fila por conexión, con su rótulo; la nota dice qué concluir.

1. **OUT1 → T (50 Ω) → IN1**, referencia «generator via OUT1»: la de siempre.
2. **OUT1 → IN1 sin el terminador**, la misma referencia. Sin carga el cable resuena en
   12–22 MHz, pero eso no toca la parte lenta, que se mide diezmada.
3. **Una cuadrada del Rigol → T (50 Ω) → IN1**, OUT1 desconectado, referencia «external
   square on IN1»: ~2 kHz (medio período de 250 µs, 5 veces el polo más lento) y
   ~0.5 Vpp.

| Si… | La caída es de… | Con un sensor |
|---|---|---|
| la externa no cae y OUT1 cargado sí | la salida cargada | no hay nada que compensar |
| la externa cae como OUT1 cargado | el front-end de IN1 | la base dinámica con la fila externa |
| la externa cae, pero menos | las dos | la base dinámica con la fila externa |

La fila 2 dice si la caída depende de la carga.

## La base dinámica, paso a paso

1. Medir el canal (fila en Origin) y «Set b0 = offset».
2. **G_F** («Measure»): una línea aislada de 2000 ADU por el **lazo digital** (sin
   cables), con la τ del polo-cero y la base en 0. Corre el MCA con el disparo que esté
   armado y **borra el histograma**. Vale para la configuración del MCA con que se midió
   (la `huella`): si cambia el trapecio o la feature, la pestaña avisa.
3. Elegir la caída en «drop from» y prender «dynamic base». Mientras está prendida,
   «fixed baseline» de «MCA settings» es de sólo lectura: lo que se escriba ahí cambia
   b₀, no la base en uso. Prender el seguidor de base (`bl_auto`) la apaga.
4. **«Check»** (con el cable de la calibración, ~8 s, **borra el histograma**): dos
   líneas del generador por OUT1 a 10 k/s (la referencia) y a la tasa elegida, con la
   base fija y con la dinámica. Como el corrimiento es lineal en κ,
   κ_óptimo = κ·s_fija/(s_fija − s_dinámica); «use κ» lo pone.

## Qué toca cada medición, y qué restaura

| Op | Toca | Al terminar (también si falla) |
|---|---|---|
| `canal.medir` | el generador (config, tabla, lazo), los registros del OSC (umbral, retardo, diezmado, histéresis, promedio, `deb_len`), el shield y las máscaras del MT, la ruta del OSC | todo como estaba; si un canal tenía `we_keep` (el disparo continuo del MCA), la captura se re-arma, armando antes que la máscara |
| `mca.ganancia` | el generador, el lazo, la base y el seguidor, el histograma | todo menos el histograma |
| `base.verificar` | el generador, la base, la base dinámica, el histograma | todo menos el histograma |

No corren con el MCA corriendo ni con una adquisición del ring en curso, ni con el
generador generando.

## Validarla en la placa

En la GUI, con el MCA cce7b66b y el cable OUT1 → T (50 Ω) → IN1:

1. «Measure» dos veces: tiene que dar lo del 2026-11-14 (ganancia 0.95, latencia 14.9,
   subida 11 ns, sobrepico 24 %, −3 dB 52 MHz) y **la misma caída lenta las dos veces**.
2. Las tres conexiones de Origin.
3. G_F, la base dinámica y «Check» a 400 k/s: el corrimiento tiene que bajar de −9.3 a
   menos de ±2 canales con el κ ajustado.

Y la etapa `tasa` entera en analógico, contra la base fija y el seguidor de la corrida
del 2026-11-14:

```bash
make campana-meritos-pulsos-remoto OUT=datos/meritos_<fecha>_analogico_dinamica \
     MERITOS=tasa MODO=analogico ARGS="--base-tasa dinamica --caida -0.073 --kappa 1"
```

`--caida` es la de la medición lenta de la pestaña (`--calibracion cal.json` la lee del
archivo, si está en la placa). La campaña corre en la placa sin el servidor: su lazo de
la ley está en `PlacaReal.correr`. **Ceba** la ley con el estímulo (la tasa pedida y la
amplitud media de la tabla por la ganancia del canal), así el espectro no junta el
transitorio del promedio, y saca G_F de su propia referencia, porque la configuración
del MCA es la de la campaña.

## Sin placa

- `API/tests/test_canal.py`: la lenta y la externa recuperan la caída de un canal
  sintético con fases de diezmado distintas; `CapturaBram` sobre los fakes de registros
  deja todo como estaba, también si falla.
- `API/tests/test_base_dinamica.py`: la ley, el suavizado, el Clear, los topes, el
  cebado, y un lazo cerrado contra una planta de juguete (con la base fija la línea queda
  11 canales abajo; con la dinámica, a menos de 1).
- `app/tests/test_calibracion.py` (las ops contra `mca_server.py --fake`, con el canal
  falso de `API/canal_falso.py`) y `app/tests/test_calibracion_gui.py` (la pestaña).
- `campanas/tests/test_meritos_pulsos.py`: `--base-tasa dinamica`, G_F y el cebado, y el
  lazo de `PlacaReal` con un MCA de mentira.

## Estado

Hecho y probado sin placa el 2026-11-15. Falta todo lo de «Validarla en la placa».
