#!/bin/sh
# instalar.sh — deja el MCA instalado y utilizable en una Red Pitaya.
#
# Va DENTRO del paquete de release, al lado de software/ y out/, y se ejecuta
# desde donde se desempaquetó:
#
#     tar xzf mca-0.1.0.tar.gz
#     cd mca-0.1.0
#     sudo ./instalar.sh --cargar
#
# Lo que hace, en orden: verifica el paquete contra su manifiesto, comprueba
# que esto sea una Pitaya y que estén las dependencias, ELIGE el bitstream de
# esta placa entre los que trae el paquete (por el modelo de la EEPROM: Zynq y
# cantidad de canales, que van en el nombre: mca_red_pitaya_Z10_2CH.bit.bin),
# copia el árbol al prefijo, copia ese bitstream donde los defaults lo buscan
# y —sólo si se lo pide— programa la PL y verifica que respondan los registros.
#
# Lo que NO hace, a propósito: no arranca ningún servicio, no toca la red, no
# instala paquetes de Python, y no reprograma la PL salvo con --cargar. Un
# instalador que reprograma la FPGA solo puede cortarle el bus a una medición
# que está corriendo.
#
# POSIX sh a propósito: la imagen de la placa no garantiza bash.

set -eu

PREFIJO=/opt/mca
BIT_SISTEMA=/root/mca_red_pitaya.bit.bin
VARIANTE=""
CARGAR=no
SIN_BITSTREAM=no
FORZAR=no
DESINSTALAR=no
CONFIRMAR=no

PAQ=$(cd "$(dirname "$0")" && pwd)

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
aviso() { printf '\033[33m%s\033[0m\n' "$*"; }

morir() { rojo "ERROR: $*"; exit 1; }

ayuda() {
    cat <<'FIN'
instalar.sh — instala el MCA en la Red Pitaya

  --prefijo DIR      dónde instalar el árbol      (por defecto /opt/mca)
  --variante Zxx_nCH cuál de los bitstreams del paquete es el de esta placa
                     (p. ej. Z10_2CH). Sin esto se deduce del modelo de la
                     EEPROM, y hace falta root para leerla.
  --bitstream RUTA   enlace para los defaults del software
                     (por defecto /root/mca_red_pitaya.bit.bin)
  --sin-bitstream    no copiar el bitstream fuera del prefijo
  --cargar           además PROGRAMA la PL y verifica los registros
  --forzar           instalar aunque esto no parezca una Red Pitaya
  --desinstalar      borra el prefijo (pide --confirmar)
  --confirmar        sí, borralo de verdad
  -h, --help         esto

Ejemplos:
  sudo ./instalar.sh                  instala, no toca la PL
  sudo ./instalar.sh --cargar         instala y deja la placa lista para medir
  ./instalar.sh --prefijo ~/mca       instalación de usuario, sin sudo
FIN
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefijo)     PREFIJO=$2; shift 2 ;;
        --variante)    VARIANTE=$2; shift 2 ;;
        --bitstream)   BIT_SISTEMA=$2; shift 2 ;;
        --sin-bitstream) SIN_BITSTREAM=si; shift ;;
        --cargar)      CARGAR=si; shift ;;
        --forzar)      FORZAR=si; shift ;;
        --desinstalar) DESINSTALAR=si; shift ;;
        --confirmar)   CONFIRMAR=si; shift ;;
        -h|--help)     ayuda; exit 0 ;;
        *)             morir "opción desconocida: $1  (--help)" ;;
    esac
done

# ------------------------------------------------------------- desinstalar ---
# Enumera antes de borrar, y sin --confirmar no borra nada. El bitstream de
# /root NO se toca: puede ser el que está programado ahora mismo en la PL.
if [ "$DESINSTALAR" = si ]; then
    [ -d "$PREFIJO" ] || { echo "no hay nada instalado en $PREFIJO"; exit 0; }
    echo "se borraría:"
    du -sh "$PREFIJO" | sed 's/^/    /'
    echo "    (el bitstream de $BIT_SISTEMA NO se toca)"
    if [ "$CONFIRMAR" = si ]; then
        rm -rf "$PREFIJO"
        verde "borrado $PREFIJO"
    else
        echo
        echo "NO se borró nada. Para hacerlo de verdad:"
        echo "    $0 --desinstalar --prefijo $PREFIJO --confirmar"
    fi
    exit 0
fi

echo "== paquete =="
[ -f "$PAQ/VERSION" ] || morir "no encuentro VERSION: ¿estás dentro del paquete desempaquetado?"
sed 's/^/    /' "$PAQ/VERSION"

# ------------------------------------------------ 1. integridad del paquete ---
# Antes que nada: una descarga truncada instala un árbol a medias que después
# falla en runtime, lejos de acá y sin relación aparente con la instalación.
echo
echo "== integridad =="
if [ ! -f "$PAQ/MANIFIESTO.sha256" ]; then
    aviso "  sin MANIFIESTO.sha256 — no puedo verificar el paquete"
elif command -v sha256sum >/dev/null 2>&1; then
    ( cd "$PAQ" && sha256sum -c --quiet MANIFIESTO.sha256 ) \
        || morir "el paquete está corrupto o incompleto. Bajalo de nuevo."
    verde "  $(wc -l < "$PAQ/MANIFIESTO.sha256") ficheros verificados"
else
    aviso "  no hay sha256sum — salteando la verificación"
fi

# --------------------------------------------------------- 2. el ambiente ---
echo
echo "== ambiente =="

# La pregunta es "¿soy la placa?", no "¿hay una placa en la red?". El módulo
# `rp` y /opt/redpitaya sólo existen en la Pitaya.
if [ -d /opt/redpitaya/lib/python ]; then
    verde "  Red Pitaya            sí"
elif [ "$FORZAR" = si ]; then
    aviso "  Red Pitaya            NO — seguís por --forzar"
else
    rojo  "  Red Pitaya            NO"
    echo
    echo "  Esto no parece una Red Pitaya: no existe /opt/redpitaya/lib/python."
    echo "  El servidor y las campañas necesitan /dev/mem y el módulo rp."
    echo "  Si querés instalarlo igual (para leer datos ya medidos, por ejemplo):"
    echo "      $0 --forzar --prefijo ~/mca --sin-bitstream"
    exit 1
fi

command -v python3 >/dev/null 2>&1 || morir "no hay python3"
echo "  python3               $(python3 -c 'import sys; print(sys.version.split()[0])')"

python3 -c 'import numpy' 2>/dev/null \
    && echo "  numpy                 $(python3 -c 'import numpy; print(numpy.__version__)')" \
    || morir "falta numpy, y es obligatorio.  pip3 install numpy"

# Opcionales: su ausencia no impide medir, sólo recorta qué se puede hacer
# EN la placa. La GUI vive en la PC y no necesita nada de esto acá.
for m in matplotlib pytest; do
    if python3 -c "import $m" 2>/dev/null; then
        echo "  $m$(printf '%*s' $((22 - ${#m})) '')ok"
    else
        aviso "  $m$(printf '%*s' $((22 - ${#m})) '')no (opcional)"
    fi
done

if [ "$(id -u)" != 0 ]; then
    aviso "  usuario               $(id -un) — /dev/mem necesita root"
    echo "                        vas a tener que correr el servidor con sudo"
fi

# ¿Cuál de los bitstreams del paquete es el de ESTA placa? El paquete trae uno
# por variante (Zynq y canales, en el nombre) y acá se elige por el modelo de
# la EEPROM. Se decide siempre, aunque no se vaya a cargar, porque es lo
# primero que alguien necesita saber. Cargar un bitstream de otro Zynq no falla
# y ya: deja el FPGA manager trabado y TODA programación posterior falla
# —incluida la de fábrica— hasta reiniciar.
MODELO=""
for m in /opt/redpitaya/bin/monitor /usr/local/bin/monitor; do
    [ -x "$m" ] && MODELO=$("$m" -f 2>/dev/null | head -1) && break
done
# Sin root, `monitor -f` no puede abrir la EEPROM y escribe "undefined" con
# codigo de salida 0. Tomarlo por un modelo seria peor que no saber.
[ "$MODELO" = undefined ] && MODELO=""
case "$MODELO" in
    z10_*) ZYNQ=Z10 ;;
    z20_*) ZYNQ=Z20 ;;
    *)     ZYNQ="" ;;
esac
case "$MODELO" in
    *_4ch*) NCH=4 ;;
    *)      NCH=2 ;;
esac

DISPONIBLES=$(cd "$PAQ/out" && ls mca_red_pitaya_Z*_*CH.bit.bin 2>/dev/null \
              | sed -E 's/^mca_red_pitaya_(.*)\.bit\.bin$/\1/' | tr '\n' ' ' | sed 's/ $//')
[ -n "$DISPONIBLES" ] || morir "el paquete no trae ningún bitstream del MCA en out/"

COMPATIBLE=si
if [ -z "$VARIANTE" ]; then
    if [ -n "$ZYNQ" ]; then
        VARIANTE=${ZYNQ}_${NCH}CH
        echo "  placa                 $MODELO -> $VARIANTE"
    elif [ "$(echo $DISPONIBLES | wc -w)" = 1 ]; then
        VARIANTE=$(echo $DISPONIBLES)
        if [ -n "$MODELO" ]; then
            aviso "  placa                 modelo $MODELO no reconocido; el paquete trae sólo $VARIANTE"
        else
            aviso "  placa                 modelo ilegible sin root; el paquete trae sólo $VARIANTE"
            echo  "                        se comprueba de nuevo al programar la PL"
        fi
    else
        rojo  "  placa                 no sé qué bitstream es el de esta placa"
        echo  "                        modelo: ${MODELO:-ilegible sin root}; el paquete trae: $DISPONIBLES"
        echo  "                        elegilo con --variante, o corré con sudo"
        SIN_BITSTREAM=si
        COMPATIBLE=no
    fi
else
    # Elegida a mano: se comprueba contra la placa igual, por si es la otra.
    if [ -n "$ZYNQ" ] && [ "${VARIANTE%%_*}" != "$ZYNQ" ]; then
        COMPATIBLE=no
    fi
fi

if [ -n "$VARIANTE" ]; then
    BIT_PAQ=$PAQ/out/mca_red_pitaya_${VARIANTE}.bit.bin
    [ -f "$BIT_PAQ" ] || morir "el paquete no trae bitstream para $VARIANTE (trae: $DISPONIBLES)"
    if [ "$COMPATIBLE" = si ]; then
        verde "  bitstream             mca_red_pitaya_${VARIANTE}.bit.bin"
    else
        rojo  "  bitstream             mca_red_pitaya_${VARIANTE}.bit.bin, pero esta placa es $MODELO ($ZYNQ)"
    fi
fi

# ------------------------------------------------------------ 3. instalar ---
echo
echo "== instalación =="

mkdir -p "$PREFIJO" 2>/dev/null \
    || morir "no puedo crear $PREFIJO (¿falta sudo?)"
[ -w "$PREFIJO" ] || morir "no puedo escribir en $PREFIJO (¿falta sudo?)"

# El árbol se reemplaza entero en vez de fusionarse: una instalación encima de
# otra más vieja dejaría los .py que la nueva ya no trae, y un import viejo que
# sigue resolviendo es de lo más difícil de diagnosticar. datos/ se conserva
# porque son mediciones, no software.
#
# Y se reemplaza COPIANDO AL LADO Y RENOMBRANDO, no borrando y copiando encima.
# La diferencia importa: borrar primero deja el árbol a medias si algo falla en
# el medio, y falla — un `__pycache__` que quedó de root en un prefijo del
# usuario (pasa apenas alguien corre el software con sudo) no se deja borrar, y
# la instalación anterior queda destruida sin que la nueva llegue a existir.
# Renombrar sólo necesita permiso sobre el directorio padre, así que funciona
# aunque adentro haya ficheros de otro dueño.
NUEVO="$PREFIJO/.nuevo.$$"
VIEJO="$PREFIJO/.viejo.$$"
rm -rf "$NUEVO"
mkdir -p "$NUEVO"
cp -a "$PAQ/software" "$NUEVO/software"
cp -a "$PAQ/out"      "$NUEVO/out"

if [ -d "$PREFIJO/software" ]; then
    echo "  ya había una instalación en $PREFIJO — se reemplaza el software"
    mkdir -p "$VIEJO"
    mv "$PREFIJO/software" "$VIEJO/software"
    [ -d "$PREFIJO/out" ] && mv "$PREFIJO/out" "$VIEJO/out"
fi

mv "$NUEVO/software" "$PREFIJO/software"
mv "$NUEVO/out"      "$PREFIJO/out"
rmdir "$NUEVO"

# Las mediciones vuelven al árbol nuevo: son datos, no software.
if [ -d "$VIEJO/software/datos" ]; then
    echo "  (se conserva $PREFIJO/software/datos)"
    mv "$VIEJO/software/datos" "$PREFIJO/software/datos"
fi

cp -a "$PAQ/VERSION" "$PAQ/LEEME.md" "$PAQ/instalar.sh" "$PREFIJO/"
if [ -f "$PAQ/MANIFIESTO.sha256" ]; then
    cp -a "$PAQ/MANIFIESTO.sha256" "$PREFIJO/"
fi

# Recién ahora se borra lo viejo, cuando lo nuevo ya está en su lugar. Si esto
# falla, la instalación está completa igual: es basura, no un problema.
if [ -d "$VIEJO" ]; then
    rm -rf "$VIEJO" 2>/dev/null || \
        aviso "  no pude borrar $VIEJO (¿ficheros de root?): borralo a mano"
fi

verde "  árbol                 $PREFIJO/software"
verde "  bitstreams            $PREFIJO/out/  ($DISPONIBLES)"

# La copia en /root existe para que los defaults del software funcionen sin
# argumentos: tanto mca_server.py como preparar_placa.py buscan el bitstream
# en $BIT_SISTEMA. Se copia CON el nombre de la variante y el nombre estable
# es un enlace a esa copia: así un `ls -l /root` dice qué placa cree el
# software que es ésta. Es 1 MB duplicado a cambio de que nada tenga que pasar
# --bitstream.
if [ "$SIN_BITSTREAM" = no ] && [ -n "$VARIANTE" ] && [ "$COMPATIBLE" = si ]; then
    BIT_ROOT=$(dirname "$BIT_SISTEMA")/mca_red_pitaya_${VARIANTE}.bit.bin
    if cp "$BIT_PAQ" "$BIT_ROOT" 2>/dev/null && ln -sfn "$BIT_ROOT" "$BIT_SISTEMA" 2>/dev/null; then
        verde "  copia para defaults   $BIT_SISTEMA -> $BIT_ROOT"
    else
        aviso "  no pude escribir $BIT_SISTEMA (¿falta sudo?)"
        aviso "  vas a tener que pasar --bitstream $PREFIJO/out/mca_red_pitaya_${VARIANTE}.bit.bin"
    fi
fi

# ---------------------------------------------------- 4. programar la PL ---
if [ "$CARGAR" = si ]; then
    echo
    echo "== programar la PL =="
    [ "$(id -u)" = 0 ] || morir "--cargar necesita root (/dev/mem y /dev/xdevcfg)"
    if [ "$COMPATIBLE" = no ] || [ -z "$VARIANTE" ]; then
        morir "no hay un bitstream de este paquete que sea para esta placa
       (modelo ${MODELO:-ilegible}; elegido: ${VARIANTE:-ninguno}; trae: $DISPONIBLES).
       NO se programó nada: cargar uno de otro Zynq dejaría el FPGA manager
       trabado y toda programación posterior fallaría hasta reiniciar.
       El resto del paquete quedó instalado y sirve igual."
    fi
    echo "  esto CORTA el bus AXI: cualquier medición en curso se pierde."
    python3 "$PREFIJO/software/campanas/preparar_placa.py" \
        --cargar --bitstream "$PREFIJO/out/mca_red_pitaya_${VARIANTE}.bit.bin"
fi

# -------------------------------------------------------------- 5. cómo ---
cat <<FIN

$(verde "listo.")

  comprobar que la PL responde y el eje es el que creés:
      python3 $PREFIJO/software/campanas/preparar_placa.py

  levantar el servidor para la aplicación de la PC:
      sudo python3 $PREFIJO/software/app/mca_server.py --port 1001

  y desde la PC:
      make app-gui SERVIDOR=$(hostname -I 2>/dev/null | awk '{print $1}') PUERTO=1001

  la puesta en marcha completa está en $PREFIJO/LEEME.md
FIN
