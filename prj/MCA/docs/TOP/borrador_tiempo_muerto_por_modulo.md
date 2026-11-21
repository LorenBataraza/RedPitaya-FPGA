<!--
Borrador de la sección «Tiempo Muerto por Módulo» de la nota del vault
«PI - Implementacion TOP (Integracion)». Reemplaza a la sección que la nota tiene
ahora (2026-11-16). Las citas ^[8] a ^[11] siguen a la bibliografía actual de la
nota (1 a 7): al pasarla, sumar las entradas de abajo a su «# Bibliografía».
-->

### Tiempo Muerto por Módulo
El disparo es común a todos los consumidores, pero cada uno tiene su propio tiempo muerto. Un consumidor ocupado no frena a los otros, porque el MT no espera a nadie para volver a disparar. En la Tabla{tm_por_modulo} se presenta, para cada módulo, la causa por la que se pierde un pulso, a cuál de los dos modelos de la Sec{[[PI - Analizador Multicanal#Modelos Fundamentales de Tiempo Muerto]]} responde^[8] y qué contador la registra. Los tiempos muertos propios de cada módulo se explican en sus secciones correspondientes; acá nos interesa cómo se combinan.

| Módulo                  | Causa                                                               | Modelo                                                                                                                                                   | Qué se registra                                                                                                    |
| ----------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Acondicionamiento       | —                                                                   | sin tiempo muerto: una muestra por ciclo y sin bloqueo                                                                                                   | —                                                                                                                  |
| MT, relanzamiento       | fuente con histéresis sin re-armar, o canal enganchado              | paralizable: un pulso que llega antes del re-armado mantiene la señal por encima del nivel de re-armado y lo demora. El enganche dura $D+1$ ciclos fijos | tiempo: $\mathtt{t\_rearm}$                                                                                        |
| MT, escudo hacia el MCA | holdoff del `trigger_shield`                                        | paralizable: cada disparo recarga el contador                                                                                                            | tiempo: $T_\text{veto}$; disparos: $\mathtt{cnt\_lost\_veto}$                                                      |
| MCA                     | ninguna ranura libre: todas midiendo, o alguna esperando publicar   | no paralizable, con $N$ ranuras                                                                                                                          | tiempo: $\mathtt{t\_win}$, $\mathtt{t\_div}$; disparos: $\mathtt{cnt\_lost\_active}$, $\mathtt{cnt\_lost\_busy}$ |
| `event_ring`            | ventana anterior drenándose, o etapa siguiente llena                | no paralizable                                                                                                                                           | disparos: $\mathtt{drop\_busy}$, $\mathtt{drop\_full}$                                                             |
| OSC (BRAM)              | buffer congelado hasta que el PS vuelve a armar la captura          | no paralizable, de duración fijada por el software                                                                                                       | —                                                                                                                  |
Tabla{tm_por_modulo} - Tiempo muerto de cada módulo del datapath: causa, modelo y contador que lo registra.

Las pérdidas se dividen en dos grupos según si el pulso llegó a generar un disparo. Si el disparo existió y el consumidor no lo tomó, la pérdida se **cuenta**. El MCA atribuye cada flanco de disparo a la ranura que abrió o a la causa por la que se perdió, con el mismo orden de prioridad que los relojes,
$$\mathtt{cnt\_cross} = \mathtt{cnt\_open} + \mathtt{cnt\_lost\_veto} + \mathtt{cnt\_lost\_active} + \mathtt{cnt\_lost\_busy}$$
y el `event_ring` cuenta sus descartes por causa. Si la fuente estaba desarmada, en cambio, el pulso no genera flanco y no hay nada que contar: lo único que se puede **medir** es cuánto tiempo estuvo desarmado el disparo, $\mathtt{t\_rearm}$. El submuestreo del diezmador queda fuera de los dos grupos, porque no deja ni un disparo ni un tiempo que registrar.

El MCA es el único consumidor que registra el tiempo muerto del disparo, porque `mca_veto` y `trig_arm` llegan sólo a él. Con esas dos señales y el estado de sus ranuras reparte cada ciclo de la corrida en un único casillero del teselado (Sec{[[PI - Implementacion Multitrigger#Conteo en el MCA]]}),
$$T_\text{real} = T_\text{veto} + \mathtt{t\_win} + \mathtt{t\_div} + \mathtt{t\_rearm} + T_\text{live}$$
Como los casilleros no se solapan, los tiempos muertos del MT y del MCA se suman sin contar dos veces el mismo ciclo. En conclusión resulta:
- **MCA:** $\mathtt{t\_win} + \mathtt{t\_div}$;
- **Del sistema:** $\mathtt{t\_win} + \mathtt{t\_div} + \mathtt{t\_rearm}$ (`deadtime_real_s` en libmca).

El veto no entra en ninguna de las dos sumas. El holdoff del escudo es un tiempo en el que **decidimos** no medir, no uno en el que el sistema no pudo, así que se descuenta del tiempo de la corrida en lugar de contarse como pérdida. Con arribos Poisson y la condición de re-armado del MT (Sec{[[PI - Implementacion Multitrigger#Cuándo mide los pulsos perdidos]]}), la fracción de los pulsos que se pierde es
$$P_\text{perd} = \frac{\mathtt{t\_win} + \mathtt{t\_div} + \mathtt{t\_rearm}}{T_\text{real} - T_\text{veto}}$$
Si la condición no se cumple, $\mathtt{t\_rearm}$ es una cota inferior y $P_\text{perd}$ también.

Medimos estos tiempos en lugar de corregir con un $\tau$ nominal porque la cadena no responde a un único modelo: el relanzamiento es paralizable, las ranuras del MCA forman un sistema no paralizable de $N$ servidores y los dos están en serie. Para tiempos muertos combinados, las fórmulas de un único $\tau$ dejan de valer^[9]^[10]. La medición de tiempos, en cambio, no necesita ningún modelo. Con arribos Poisson, la fracción de pulsos que encuentra al sistema en un estado es igual a la fracción del tiempo que el sistema pasa en ese estado, siempre que el estado no dependa de los arribos futuros (PASTA, *Poisson Arrivals See Time Averages*^[11]). La fracción del tiempo de cada casillero es entonces, directamente, la probabilidad de perder un pulso por esa causa.

El `event_ring` y el OSC no reciben ni `trig_arm` ni `mca_veto`, así que no registran el tiempo muerto del disparo. El MCA registra $\mathtt{t\_rearm}$, y como el ring toma el mismo disparo, ese tiempo vale también para él. El ring separa sus descartes por causa: $\mathtt{drop\_busy}$ cuenta los disparos que llegan mientras se drena la ventana anterior, que es su tiempo muerto propio, y $\mathtt{drop\_full}$, los que llegan cuando la etapa siguiente está llena porque el PS no vacía el anillo, que es tiempo muerto del consumidor (Sec{[[PI - Implementacion OSC#Calculo de Tiempo Muerto y contadores presentes]]}). La captura por BRAM del OSC congela su buffer después de cada disparo hasta que el PS la vuelve a armar (Sec{[[PI - Implementacion OSC#FSM - Finite State Machine de la Captura por BRAM]]}), así que su tiempo muerto lo fija el software y no queda registrado.

Qué módulo domina el tiempo muerto depende de la tasa y de la configuración (largo de la ventana, cantidad de ranuras, histéresis del disparo); las mediciones se presentan en [[PI - Resultados de Merito]]. En la aplicación se presenta por defecto el tiempo muerto total, pero un modo de detalle lo subdivide en sus componentes (Sec{[[PI - Software#Aplicación Desarrollada]]}).

---

Entradas para la «# Bibliografía» de la nota:

8. G. F. Knoll, *Radiation Detection and Measurement*, 4.ª ed. Hoboken, NJ: Wiley, 2010. Cap. 4.
9. J. W. Müller, "Dead-time problems", *Nuclear Instruments and Methods*, vol. 112, pp. 47–57, 1973.
10. J. W. Müller, "Generalized dead times", *Nuclear Instruments and Methods in Physics Research A*, vol. 301, pp. 543–551, 1991.
11. R. W. Wolff, "Poisson Arrivals See Time Averages", *Operations Research*, vol. 30, n.º 2, pp. 223–231, 1982.
