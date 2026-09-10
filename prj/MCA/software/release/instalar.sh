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
# que esto sea una Pitaya y que estén las dependencias, copia el árbol al
# prefijo, copia el bitstream donde los defaults lo buscan y —sólo si se lo
# pide— programa la PL y verifica que respondan los registros.
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
  --bitstream RUTA   copia del bitstream para los defaults del software
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
if [ -d "$PREFIJO/software" ]; then
    echo "  ya había una instalación en $PREFIJO — se reemplaza el software"
    if [ -d "$PREFIJO/software/datos" ]; then
        echo "  (se conserva $PREFIJO/software/datos)"
        mv "$PREFIJO/software/datos" "$PREFIJO/.datos.tmp"
    fi
    rm -rf "$PREFIJO/software"
fi

rm -rf "$PREFIJO/out"
cp -a "$PAQ/software" "$PREFIJO/software"
cp -a "$PAQ/out"      "$PREFIJO/out"
cp -a "$PAQ/VERSION" "$PAQ/LEEME.md" "$PAQ/instalar.sh" "$PREFIJO/"
if [ -f "$PAQ/MANIFIESTO.sha256" ]; then
    cp -a "$PAQ/MANIFIESTO.sha256" "$PREFIJO/"
fi
if [ -d "$PREFIJO/.datos.tmp" ]; then
    mv "$PREFIJO/.datos.tmp" "$PREFIJO/software/datos"
fi

verde "  árbol                 $PREFIJO/software"
verde "  bitstream             $PREFIJO/out/mca_red_pitaya.bit.bin"

# La copia en /root existe para que los defaults del software funcionen sin
# argumentos: tanto mca_server.py como preparar_placa.py buscan el bitstream
# ahí. Es 1 MB duplicado a cambio de que nada tenga que pasar --bitstream.
if [ "$SIN_BITSTREAM" = no ]; then
    if cp "$PAQ/out/mca_red_pitaya.bit.bin" "$BIT_SISTEMA" 2>/dev/null; then
        verde "  copia para defaults   $BIT_SISTEMA"
    else
        aviso "  no pude escribir $BIT_SISTEMA (¿falta sudo?)"
        aviso "  vas a tener que pasar --bitstream $PREFIJO/out/mca_red_pitaya.bit.bin"
    fi
fi

# ---------------------------------------------------- 4. programar la PL ---
if [ "$CARGAR" = si ]; then
    echo
    echo "== programar la PL =="
    [ "$(id -u)" = 0 ] || morir "--cargar necesita root (/dev/mem y /dev/xdevcfg)"
    echo "  esto CORTA el bus AXI: cualquier medición en curso se pierde."
    python3 "$PREFIJO/software/campanas/preparar_placa.py" \
        --cargar --bitstream "$PREFIJO/out/mca_red_pitaya.bit.bin"
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
