<!-- Prosa a mano del datasheet de `osc_cfg`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_osc_cfg.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es el esclavo de registros del osciloscopio: configura la cadena
de adquisición —umbral, histéresis, decimación, retardo de disparo, ecualizador—
y expone las **aperturas de BRAM** por donde el PS lee las muestras capturadas.
No procesa datos: todo el flujo de muestras pasa por fuera, y lo que este bloque
controla es *dónde se congela* y *cómo se lee*.

Sale de `mt_rp_scope_cfg` quitándole los registros del multitrigger,
que se mudaron al slot 3 ([`mt_cfg`](../datasheet_mt_cfg.md)),
y reorganizando el mapa.

La decisión que explica casi toda su forma: **decodifica dos mapas de
direcciones sobre el mismo banco de registros físicos.**

| Rango | Mapa |
|---|---|
| `0x00000`–`0x00FFF` | **legacy**: los offsets históricos de Red Pitaya |
| `0x01000`–`0x01FFF` | **canónico**: stride uniforme por canal |
| `0x10000`–`0x4FFFF` | aperturas de BRAM, comunes a los dos |

No hay estado duplicado —un solo flop por registro, dos decodificadores para
alcanzarlo—, así que escribir por un mapa y leer por el otro devuelve el mismo
valor y **no se pueden desincronizar**. El mapa legacy existe porque `librp` es
una librería C cerrada que escribe offsets fijos en `0x4010_0000`, y el software
del proyecto la usa en todos lados: hoy son ~80 llamadas a la API `rp`
repartidas en 11 archivos (`run_acquire`, `e2e_espectro`, `mca/sources`, los
benches). Mover los registros sin dejar los viejos rompería todo eso de golpe y
sin posibilidad de parche del lado de Python.

> La cabecera de [`osc_cfg.sv`](../../../modulos/osc/rtl/osc_cfg.sv) dice «111
> llamadas en 14 archivos». Ese número ya no se reproduce —`grep` da ~80 en
> 11—, así que o la migración avanzó o se contó de otra forma. El argumento no
> cambia; el número sí conviene no citarlo como vigente. El parámetro `EN_LEGACY_MAP` lo
compila fuera cuando el software esté migrado, y es el único lugar que hay que
tocar.

Dos cosas que conviene saber antes de tocarlo:

- **Dos offsets legacy pertenecen a lógica que ya se mudó** y `librp` los usa,
  así que se siguen decodificando acá y se mandan al slot 3 ya decodificados
  por canal: `0x004` (SW-trigger) y `0x094` (`trig_dis_clr`).
- **En `0x004` este diseño ya no es el Red Pitaya de fábrica.** El RTL sólo
  honra el valor `1` (SW); un `rp_AcqSetTriggerSrc` con una fuente de flanco
  escribe 2, 3, … y se ignora, porque esas fuentes pasaron al multitrigger. Es
  una divergencia **preexistente**, no la introdujo el refactor.

El otro bloque del módulo, `osc_filter`, es el ecualizador IIR: qué le hace a un
flujo de muestras está medido en [§1.6](#16-transacciones).
