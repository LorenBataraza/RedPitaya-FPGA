<!-- Prosa a mano del datasheet de `mt_rp_scope_cfg`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mt_rp_scope_cfg.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

> **Este bloque ya no se instancia en ningún top.** Está en el repo como
> referencia del diseño anterior a la separación en regiones, y esta página
> existe para que el lector que lo encuentre sepa en un renglón por qué no
> tiene que tocarlo. Su reemplazo son **dos** esclavos con slot propio:
> [`osc_cfg`](../datasheet_osc_cfg.md) (slot 1) y
> [`mt_cfg`](../datasheet_mt_cfg.md) (slot 3).

**Qué hace.** Es el esclavo de registros del scope en su forma **monolítica**:
el `rp_scope_cfg` de Red Pitaya con los registros del multitrigger agregados
adentro —la máscara de fuentes de 32 b por canal en `0x240 + 4·ch` y la
configuración del escudo en `0x210`—, y con un
[`trigger_shield`](../datasheet_trigger_shield.md) instanciado en su cuerpo. El
resto del mapa es idéntico al original.

Por qué se partió: tener la configuración del scope y la del multitrigger en el
mismo esclavo hacía que **cualquier** registro nuevo del multitrigger tuviera
que entrar en la ventana de direcciones del slot 1, que es la que `librp`
escribe con offsets fijos. Separar en slots deja crecer el multitrigger sin
tocar el mapa que el software cerrado ya usa, y el mapa histórico está
documentado en
[`register_map_mt_rp_scope_cfg.md`](../../osc/register_map_mt_rp_scope_cfg.md).

**El bug que la separación arregló —y que acá sigue estando.** Las aperturas de
BRAM sacan su `sys_ack` de `bram_ack_i[i]`, y
[`rp_scope_mt_com`](../datasheet_rp_scope_mt_com.md) ata
`bram_ack[2]` y `bram_ack[3]` a cero para los canales que no se construyen:
cualquier lectura en `0x4013_0000`–`0x4014_FFFF` **no hacía ack nunca** y
dejaba el CDC del slot desincronizado, o sea el slot muerto hasta el próximo
reset (ver [`bus_sistema_redpitaya.md`](../../TOP/bus_sistema_redpitaya.md) §7.1).
En `osc_cfg` el ack sale de un shift register incondicional, a los 4 ciclos y
para cualquier dirección; para los canales que sí existen el timing es
**idéntico**, porque `rp_acq_bram` ya generaba su ack como `sys_en` retrasado 4
ciclos. Se arregla el cuelgue sin cambiar una sola lectura buena.

Se conserva sin corregir a propósito: es el estado de las cosas contra el que
se compara, y tocarlo haría perder la referencia sin ganar nada — no está en
ningún bitstream.
