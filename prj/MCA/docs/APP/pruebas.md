# Pruebas de la aplicación

**Código:** [`API/tests/`](../../software/API/tests/) · [`app/tests/`](../../software/app/tests/) · [`app/tests/placa/`](../../software/app/tests/placa/)
**Cómo se corren:** `make verificar` en la PC · `make verificar-placa-app` en la placa
**Qué prueban:** los cuatro niveles de abajo, y en la última sección lo que **no**

Cuatro niveles, cada uno con una pregunta distinta. La utilidad de la lista está
menos en lo que cubre que en la última sección: **lo que ninguna prueba cubre**.

| nivel | dónde | pregunta que contesta |
|---|---|---|
| framing | PC | ¿los bytes llegan enteros y en orden? |
| handle remoto | PC | ¿la API entera funciona por socket? |
| GUI | PC, sin pantalla | ¿los hilos y las señales hacen lo que dicen? |
| end-to-end | placa + Rigol | ¿el número en pantalla es el que inyectó el generador? |

Los tres primeros corren en cualquier máquina, sin placa y sin instrumento, en
menos de 40 segundos entre todos. `pyproject.toml` excluye el directorio
`placa/` de la colección, así que el cuarto no se intenta por accidente en la PC.

---

## 1. El framing — `API/tests/test_mca_net.py`

Ocho pruebas sobre `socket.socketpair()`, sin red real. Lo que prueban es lo que
**rompe en producción y no en una demo**:

| prueba | qué atrapa |
|---|---|
| `payload_grande_llega_entero` | 64 KB es más que un `recv` suelto: si el lector no insiste, acá se ve |
| `dos_mensajes_seguidos_no_se_pisan` | el segundo `recv` tiene que empezar justo después del payload del primero, no en medio |
| `array_es_escribible` | `np.frombuffer` da un array de sólo lectura y la GUI rebinea encima |
| `payload_truncado` | anunciar 1024 B y mandar 10 tiene que dar `ProtocolError`, no un array corto que después se interprete como un espectro vacío |
| `cabecera_ilegible`, `conexion_cerrada` | fallar con diagnóstico en vez de con basura |
| `error_lleva_tipo_y_pista` | que `error`/`hint` sobrevivan el viaje |

---

## 2. El handle remoto — `app/tests/test_mca_remote.py`

Quince pruebas que levantan `mca_server.py --fake` en un puerto de loopback y le
hablan con `MCARemote`.

**Es la prueba que sostiene el diseño.** Si la superficie `mca_*` entera pasa por
socket sin que las funciones sepan que hay una red en el medio, entonces la
abstracción del handle es correcta y la GUI puede escribirse contra `API.mca` y
no contra un protocolo. Cubre los accesores por campo, el read-modify-write de
los registros que empaquetan varios campos, `configure` en bloque, la
adquisición completa, `clear`, la ventana de amplitud, el mapa 2D, la metadata
con el round-trip de los tres formatos de guardado, `acquire` heredado sin
redefinir, las tasas y la exposición, el rechazo del segundo cliente, la
operación inventada y el rechazo de `load_bitstream` en modo fake.

> **La espera al arranque del servidor lee su stdout, no sondea el puerto.** El
> servidor acepta un solo cliente: una conexión de sondeo se gastaría el cupo
> justo antes de la prueba. Cuesta descubrirlo, porque el síntoma es que las
> quince pruebas fallan con `Ocupado`.

---

## 3. La GUI — `app/tests/test_mcamon_gui.py`

Doce pruebas con `QT_QPA_PLATFORM=offscreen`, así que corren en CI y por ssh. No
prueban estética: prueban **el hilo del socket, las señales entre hilos y el
guardado**, que es donde una GUI se rompe de verdad.

Lo que verifican, en orden de interés: que el espectro llegue y **crezca**; que
la exposición **pare sola**; que un valor puesto desde la GUI llegue al hardware
y **vuelva** al spinbox releído; que la ventana de amplitud recorte de verdad y
dibuje sus límites; que el rebin **no pierda cuentas** en ninguno de los siete
factores; que la lista encuentre el pico donde el simulador lo puso y le mida
el FWHM que le corresponde; que guardar y
recargar dé el mismo array en los tres formatos; que el mapa 2D **sólo se lea
con su pestaña visible**; y que desconectar y volver a conectar funcione.

La pestaña 2D tiene su propia prueba porque aparece o desaparece según lo que
publique `CAPS`, y eso es una decisión que se toma en tiempo de conexión. Lo
mismo la de Integración con `has_integracion`, y las de OSC y Multitrigger con
`has_osc` / `has_mtrg`.

Las dos últimas agregan cuatro cosas más: que una captura **viaje como binario y
termine dibujada**, con el trigger exactamente en `t=0` (la muestra `pre`); que
la persistencia acumule y se pueda apagar; que la **marca de captura caiga
dentro del tramo de tasa dibujado**, que es lo que ata los dos gráficos; y que
un campo del OSC se rutee **por bloque y no por nombre** — `thr_ch0` es del
osciloscopio y `thr` del MCA, y si el ruteo fuera por nombre un umbral
terminaría en el bloque equivocado.

### La geometría es un parámetro, no una constante

Las pruebas de conexión y de la ventana de amplitud corren con **las dos
geometrías reales**: `h_aw=14` (16384 canales, el bitstream viejo) y `h_aw=13`
(8192, el nuevo), vía `--fake-h-aw` del servidor.

Hasta que lo fueron, toda la suite corría contra 16384 con el número escrito a
mano en las aserciones, y por eso **no podía agarrar** el defecto que motivó
esto: la ventana de aceptación se dibujaba con `amp >> h_shift`, un registro
deprecado que lee 0, en vez de `amp >> (AMP_W − h_aw)`. Con 8192 canales las
líneas caían 8× a la derecha y las de amplitud alta ni se dibujaban.

`test_la_ventana_de_amplitud_cae_en_el_canal_correcto` es la que pone el número:
con `h_aw=13`, `amp_min=1000` tiene que dar el canal **125**. Daba 1000. Se
comprobó que la prueba falla contra el código viejo antes de darla por buena.

Y `test_guardar_y_recargar_desde_la_gui` exige que `h_aw` y el zoom estén en la
metadata: sin ellos un espectro dice "8192 canales" sin decir sobre qué ventana
de amplitud, y su eje es irreconstruible.

---

## 4. El lazo completo — `app/tests/placa/e2e_rigol_app.py`

Veintiún comprobaciones con **pulsos físicos**:

```
Rigol DG4162 ──cable──► IN1 ──► MCA en la PL ──► mca_server ──TCP──► MCARemote
```

Todo lo demás prueba una mitad. `test_mca_remote.py` prueba el protocolo contra
un MCA simulado; `API/tests/placa/test_mca_datapath.py` prueba el camino de
datos sin la aplicación. Acá el estímulo es físico y el cliente habla por
socket, así que si el número que sale es el que inyectó el generador, están bien
las dos mitades **y la costura**.

El servidor se levanta como subproceso en un puerto de loopback y no se usa el
del 1001, por si hay una GUI conectada.

### Los tres grupos de aserciones

**Que la tasa medida sea la inyectada** (tolerancia 5 %). Es la comprobación más
fuerte de todas: liga el contador de aceptados del hardware, el reloj de tiempo
vivo, y la frecuencia que el generador tiene programada. Si falla, algo entre
los tres está mal y no importa qué tan lindo se vea el espectro. La tolerancia
no es más estrecha porque la geometría del arbitrario cuantiza la frecuencia de
repetición: el generador no emite exactamente la tasa pedida.

**Que el pico caiga donde lo pone el generador** (tolerancia 35 % del valor
esperado). El esperado sale de la altura de pulso en volts por la escala del
ADC, desplazada por `h_shift`. La tolerancia es ancha a propósito: no se está
midiendo la calibración del ADC —para eso está la campaña— sino que el eje no
esté ni invertido, ni escalado por un factor grueso, ni saturado. Se acompaña de
comprobaciones más baratas y más específicas: que haya un fotopico y no ruido
plano, que el área del pico sea la mayoría de las cuentas, y que la resolución
sea menor al 15 %, que para un pulser es holgadísimo.

**Que la exposición se respete** (tolerancia 0.5 s sobre el tiempo vivo pedido).
Verifica el hilo vigilante del servidor, que es la pieza que implementa algo que
el hardware no tiene.

Más: que `clear` deje el espectro en cero, que la suma del histograma coincida
con el contador de aceptados, que la tasa instantánea sea estable durante la
corrida, que la metadata tenga las claves suficientes para que el fichero se
entienda solo, y que los ficheros queden escritos.

### Cómo se corre

```bash
# en la placa
make verificar-placa-app TASA=4000 SEGUNDOS=8

# desde la PC: sincroniza, corre allá, y trae los datos
make verificar-placa-app-remoto TASA=4000 SEGUNDOS=8 OUT=datos/e2e
```

Y para dejar el generador encendido por fuera de una corrida —mirar el espectro
crecer en la GUI, depurar umbrales a mano—:

```bash
make rigol-pulsos TASA=3000 AMP=0.6   # tren de pulsos
make rigol-psd TASA=30000             # dos poblaciones, para el mapa 2D y la FOM
make rigol-poisson TASA=30000         # arribos exponenciales
make rigol-off
```

> **El tren periódico es un estímulo benigno y eso sesga lo que se mide.** Con
> arribos deterministas y un servidor sin cola no se pierde nada mientras el
> período supere el tiempo de servicio. Medido en placa a 30 kHz, 6 s: el tren
> periódico entrega 180037 eventos y se aceptan **los 180037**; con Poisson a
> la misma tasa entran 188850 y se registran 168231, o sea un **10.9 % que se
> pierde por fusión de pulsos vecinos**. Ninguna de las dos corridas incrementa
> el contador `pileup`: dos pulsos separados por menos que el ancho no son dos
> eventos apilados para el discriminador, son **uno solo**. La pérdida no
> aparece como un contador, aparece como cuentas que faltan y como un pico
> suma. Es la razón de que `rigol-poisson` exista.

> **El estímulo de dos poblaciones necesita tasa alta.** `pulse_train_wave` mete
> tantos pulsos por forma como permita el ciclo de trabajo, y con colas
> variables exige al menos dos; con pulsos de 2 µs eso no se cumple por debajo
> de unos 4 kHz. Debajo de eso levanta `ValueError` en vez de devolver una forma
> degenerada con una sola población.

---

## 5. El resto de la red de seguridad

| prueba | dónde | qué demuestra |
|---|---|---|
| `mca_server.py --selftest` | placa | identify + clear + 1 s + espectro completo, con `/proc/uptime` a los lados: si la placa se reinició durante la lectura, el uptime del final es menor |
| `API/tests/placa/diag_mca_hw.py` | placa | el camino de lectura palabra a palabra sigue intacto |
| `API/tests/test_compat_api.py` | PC | que nada público de `API/mca.py` cambió, contra un baseline congelado |

El `--selftest` y `diag_mca_hw.py` comparten una idea que vale la pena copiar en
cualquier prueba nueva sobre esta placa: **medir el uptime antes y después**. El
modo de falla más caro de este hardware no es una excepción, es un reinicio, y
un reinicio no deja traceback.

---

## Lo que ninguna prueba cubre

Esto es lo más útil de este documento.

- **La carga de bitstream.** `fpga.load_bitstream` sólo se prueba en su camino
  de rechazo (modo `--fake`). El camino real —cerrar el mmap, bajar los puentes
  AXI, `fpgautil`, sondear el bus desde un proceso hijo, reabrir— se verificó a
  mano y no hay nada que lo defienda de una regresión. Es, además, la operación
  más delicada del sistema.
- **La reconexión tras caída del servidor.** Que la adquisición sobreviva a
  cerrar la GUI, y que al reconectar `identify` informe `running=True`, está
  implementado y verificado a mano; no hay prueba automática.
- **La recuperación desde un bitstream equivocado**, que es el camino
  `identify → presente:false → cargar bitstream → seguir`.
- **La concurrencia real.** Se prueba que el segundo cliente sea rechazado, pero
  no hay nada que ejercite el lock del servidor bajo contención: en la práctica
  sólo hay un cliente y un hilo vigilante.
- **El driver del slot 6 contra hardware.** La pestaña de Integración tiene su
  prueba, pero el MCA simulado **no simula el slot 6**: la prueba le da
  directamente lo que devolvería `integracion.get`. O sea que está cubierto el
  contrato entre las dos mitades, y no el driver
  ([`API/integration.py`](../../software/API/integration.py)) contra la placa.
  El ruteo de taps nunca se ejercitó desde la aplicación.
- **El RTL del osciloscopio contra hardware, y por la misma razón.** Las
  pestañas de OSC y Multitrigger tienen sus pruebas, pero el simulado
  (`FakeOsc`, `FakeMultiTrigger` de
  [`mca_remote.py`](../../software/API/mca_remote.py)) **no simula el RTL**: no
  hay FSM de captura, ni disparo, ni BRAM. Hay registros que retienen lo escrito
  y formas gaussianas sintéticas. Está cubierto que la captura viaje, que el
  dibujo la alinee en `t=0` y que las casillas armen la máscara que
  corresponde; **no** está cubierto que `capture_window_np` devuelva la ventana
  correcta ni que el shield re-arme.

  > **Ojo con la diferencia contra `FakeMCA`.** Ése sí reproduce los valores de
  > reset del RTL y la aritmética del histograma, así que un desacuerdo contra
  > la placa apunta al hardware. Los del osciloscopio son más flojos a
  > propósito, y no sirven para validar el camino de datos.

- **Las máscaras de bits de `_CAMPOS` contra el RTL.** Están copiadas de
  `modulos/osc/rtl/osc_cfg.sv` —`set_tresh` es DW=14, `set_dec` 17,
  `set_deb_len` 20, `set_filt_byp` 4— pero offline no hay nada que las verifique
  contra el hardware. Eso lo cubre `verificar-placa-mca`, que escribe y relee
  cada registro en la placa. Una máscara de más se manifiesta como readback que
  no coincide con lo escrito, y con eso el anti-eco de la GUI entra en lazo.
- **El descubrimiento por `SLOTS` contra un top que de verdad tenga otra
  topología.** Se prueba que el servidor obedezca una base descubierta distinta
  y que avise, con un slot 6 falso; pero nunca se corrió contra el
  `red_pitaya_top` clásico, que es donde el multitrigger está en otro slot y el
  descubrimiento cambia algo de verdad.
- **El servidor con un cliente lento.** No hay nada que verifique qué pasa si el
  cliente deja de leer a mitad de un envío de 64 KB.

---

## Ver también

[`flujo_de_datos.md`](flujo_de_datos.md), qué hace cada pieza que estas pruebas
ejercitan · [`protocolo.md`](protocolo.md), el contrato que verifica el nivel 1 ·
[`testbenches_escritura_archivos.md`](../testbenches_escritura_archivos.md), la
misma idea para el camino evento→disco del osciloscopio
