# Fase 0 — validación del camino PL → DDR

Valida el *plumbing* (device tree, mapeo, coherencia de cache, throughput) y el
formato del slot **antes** de confiar en el ring para tomar datos.

## Qué corre dónde

| archivo | dónde | necesita placa |
|---|---|---|
| `ring_format.py` | módulo | no — es la definición del layout del lado software |
| `test_ring_format.py` | PC | **no** |
| `hw_ring_plumbing.py` | Red Pitaya, como root | sí |
| `ring_dump.hex` | generado por la simulación | no |

## Tests offline (PC)

```bash
cd prj/MCA/software/tests/fase0
python3 -m pytest test_ring_format.py -v
```

El test que más vale es `test_contra_volcado_de_simulacion`. `ring_dump.hex` lo
escribe el testbench de integración (`prj/MCA/sim/tb_event_ring_top.sv`) con el
contenido real de la DDR después de una corrida con wrap, y el test lo decodifica
con **el mismo `ring_format.py` que va a usar el lector**. Un error de
endianness, de intercalado de canales o de posición del footer se cae acá, en
segundos y sin placa.

Para regenerar el volcado tras tocar el RTL:

```bash
cd prj/MCA/sim && make tb_event_ring_top
```

El TB inyecta una rampa donde `ch1 = -ch0` muestra a muestra: es una firma que no
se satisface por casualidad si el de-intercalado está mal.

## Validación en la placa

```bash
# en la Red Pitaya
python3 hw_ring_plumbing.py dt        # ¿existe la región reservada?
python3 hw_ring_plumbing.py regs      # ¿responde el slot 2? ¿se congela la geometría?
python3 hw_ring_plumbing.py bw        # throughput DDR vs el baseline de BRAM/GP0
python3 hw_ring_plumbing.py capture   # corrida corta + decodificación de slots
python3 hw_ring_plumbing.py all
```

### Antes de correrlo: reservar la región de DDR

El PL escribe por HP2 sin pasar por la MMU ni por la cache, así que Linux no
puede estar usando esa memoria. En el device tree:

```dts
reserved-memory {
    #address-cells = <1>; #size-cells = <1>; ranges;
    event_ring: buffer@1e000000 {
        no-map;
        reg = <0x1e000000 0x02000000>;   /* 32 MB */
    };
};
```

Y ajustar `DDR_PHYS` / `DDR_SIZE` en `hw_ring_plumbing.py` si se usa otra
dirección. El paso `dt` compara la RAM que ve Linux contra los 512 MB de la
placa: si no bajó, la reserva no tomó efecto.

### Coherencia de cache

Los puertos HP **no son coherentes** con L1/L2. El script mapea con `O_SYNC` (no
cacheable), que es lo simple y correcto. Es más lento que cacheable con
invalidación explícita, pero sigue siendo mucho más rápido que leer la BRAM por
GP0 — y esa diferencia es justamente lo que mide el paso `bw`.

### Qué número mirar

El baseline del camino viejo es **~45.6 µs por llamada y por canal**
(`rp_AcqGetDataPosV` sobre BRAM), con ~35 µs de overhead fijo, o sea **~0.57 MB/s
de payload útil**. Si leer un slot de 512 B de DDR no queda bien por debajo de
eso, hay algo mal en el mapeo y no tiene sentido seguir con la Fase 1.

## Notas de acceso a `/dev/mem`

Dos reglas que ya costaron caro en este proyecto y siguen valiendo acá:

- **Escritura**: asignación por slice, nunca `struct.pack_into`. `pack_into` hace
  un `memset` previo que sale como stores de a byte → external abort → SIGBUS.
- **Lectura de registros**: `unpack_from` de a 32 b alineados.

La restricción de *no* leer en bulk aplicaba a la **BRAM por GP0** (un slice
grande reinicia la placa, ver `docs/TOP/bus_sistema_redpitaya.md`). Sobre la región
de DDR **sí** se puede hacer `np.frombuffer` de a bloques: es memoria normal, no
un esclavo AXI de 32 b. Ésa es, precisamente, la ganancia.
