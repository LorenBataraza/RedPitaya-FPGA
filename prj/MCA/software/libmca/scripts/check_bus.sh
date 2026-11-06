#!/bin/sh
# La regla del bus, comprobada sobre el binario de ARM y no sobre la promesa
# de un comentario. Falla (código 1) si:
#
#   1. bus_devmem.o tiene una instrucción que sobre la PL sería una ráfaga, un
#      acceso de 64 b o uno de 1-2 bytes: LDM/STM, LDRD/STRD, VLD/VST (NEON y
#      VFP), LDRB/STRB/LDRH/STRH. Se exceptúan las que operan sobre la pila
#      (`sp`), que es memoria común: el prólogo de una función hace push/pop.
#   2. bus_devmem.o llama a memcpy/memset/memmove.
#   3. la palabra `volatile` aparece en otro fichero de libmca: el acceso de
#      dispositivo vive en UN solo lugar, para que este chequeo alcance.
#   4. el .so pide un símbolo de glibc más nuevo que GLIBC_MAX.
#
#   sh scripts/check_bus.sh OBJDUMP NM bus_devmem.o libmca.so GLIBC_MAX
#
# Ver docs/TOP/bus_sistema_redpitaya.md §7.2-7.4 para el porqué de cada regla.

set -eu

OBJDUMP=$1
NM=$2
OBJ=$3
SO=$4
GLIBC_MAX=$5
RAIZ=$(cd "$(dirname "$0")/.." && pwd)
fallas=0

falla() { printf '  FALLA: %s\n' "$*"; fallas=$((fallas + 1)); }

echo "check-bus: $OBJ"

# --- 1. instrucciones -------------------------------------------------------
# objdump separa con tabs: dirección, mnemónico, operandos. push/pop no se
# listan: son siempre sobre sp.
malas=$("$OBJDUMP" -d --no-show-raw-insn "$OBJ" | awk -F'\t' '
    $2 ~ /^(ldm|stm|ldrd|strd|vld|vst|ldrb|strb|ldrh|strh|ldrsb|ldrsh)/ \
        && $3 !~ /sp/ { print "    " $0 }')
if [ -n "$malas" ]; then
    falla "instrucciones prohibidas sobre memoria que no es la pila:"
    printf '%s\n' "$malas"
else
    echo "  ok: sólo ldr/str de 32 b fuera de la pila"
fi

# --- 2. llamadas a copias en bloque ------------------------------------------
copias=$("$NM" -u "$OBJ" | grep -E 'mem(cpy|set|move)' || true)
if [ -n "$copias" ]; then
    falla "bus_devmem.o llama a: $(echo $copias)"
else
    echo "  ok: sin memcpy/memset/memmove"
fi

# --- 3. volatile en un solo fichero -------------------------------------------
otros=$(grep -lw volatile "$RAIZ"/src/*.c "$RAIZ"/src/*.h "$RAIZ"/include/*.h \
        | grep -v '/bus_devmem\.c$' || true)
if [ -n "$otros" ]; then
    falla "volatile fuera de bus_devmem.c: $(echo $otros)"
else
    echo "  ok: el acceso de dispositivo está sólo en bus_devmem.c"
fi

# --- 4. glibc ----------------------------------------------------------------
max=$("$OBJDUMP" -T "$SO" | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/GLIBC_//' \
      | sort -uV | tail -1)
if [ -n "$max" ] && \
   [ "$(printf '%s\n%s\n' "$max" "$GLIBC_MAX" | sort -V | tail -1)" != "$GLIBC_MAX" ]; then
    falla "el .so pide GLIBC_$max y el máximo tolerado es $GLIBC_MAX"
else
    echo "  ok: glibc pedida $max <= $GLIBC_MAX"
fi

if [ "$fallas" -ne 0 ]; then
    echo "check-bus: $fallas falla(s)"
    exit 1
fi
echo "check-bus: OK"
