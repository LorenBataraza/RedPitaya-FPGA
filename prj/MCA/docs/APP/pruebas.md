# Pruebas de la aplicación

**Código:** [`API/tests/`](../../software/API/tests/) · [`app/tests/`](../../software/app/tests/) · [`app/tests/placa/`](../../software/app/tests/placa/)
**Cómo se corren:** `make test` en la PC · `make placa-e2e-app` en la placa
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
factores; que la ROI ajuste el pico donde el simulador lo puso; que guardar y
recargar dé el mismo array en los tres formatos; que el mapa 2D **sólo se lea
con su pestaña visible**; y que desconectar y volver a conectar funcione.

La pestaña 2D tiene su propia prueba porque aparece o desaparece según lo que
publique `CAPS`, y eso es una decisión que se toma en tiempo de conexión.

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
make placa-e2e-app TASA=4000 SEGUNDOS=8

# desde la PC: sincroniza, corre allá, y trae los datos
make remoto-e2e-app TASA=4000 SEGUNDOS=8 OUT=datos/e2e
```

Y para dejar el generador encendido por fuera de una corrida —mirar el espectro
crecer en la GUI, depurar umbrales a mano—:

```bash
make estimulo-on TASA=3000 AMP=0.6     # tren de pulsos
make estimulo-psd TASA=30000           # dos poblaciones, para el mapa 2D y la FOM
make estimulo-off
```

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
- **`OPS` contra `_OPS`.** La tupla `OPS` de `mca_net.py` es documentación y no
  se importa en ningún lado; si se desincroniza del despacho real, nada lo
  detecta. Es la prueba más barata de las que faltan.
- **El servidor con un cliente lento.** No hay nada que verifique qué pasa si el
  cliente deja de leer a mitad de un envío de 64 KB.

---

## Ver también

[`flujo_de_datos.md`](flujo_de_datos.md), qué hace cada pieza que estas pruebas
ejercitan · [`protocolo.md`](protocolo.md), el contrato que verifica el nivel 1 ·
[`testbenches_escritura_archivos.md`](../testbenches_escritura_archivos.md), la
misma idea para el camino evento→disco del osciloscopio
