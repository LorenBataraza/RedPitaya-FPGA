/* Lo comun a todos los bloques: mensajes de error e identificacion. */
#include "mca_api.h"

/* El Makefile pasa los CFLAGS como cadena; si se compila a mano, queda vacia. */
#ifndef MCA_CFLAGS_STR
#define MCA_CFLAGS_STR ""
#endif

const char *mca_strerror(int rc)
{
    switch (rc) {
    case MCA_OK:          return "ok";
    case MCA_EINVAL:      return "argumento invalido";
    case MCA_ENOTPRESENT: return "el bloque no esta en el bitstream cargado (magic)";
    case MCA_ETIMEOUT:    return "la PL no termino a tiempo";
    case MCA_ENOSYS:      return "el bitstream no tiene esa capacidad (CAPS)";
    case MCA_EALIGN:      return "offset no alineado a 32 bits";
    case MCA_ERANGE:      return "offset fuera de la region mapeada";
    case MCA_EOPEN:       return "no se pudo abrir o mapear (ver errno; /dev/mem pide root)";
    case MCA_ENOMEM:      return "sin memoria";
    case MCA_EBACKEND:    return "el backend devolvio error";
    case MCA_EVERIFY:     return "la relectura no coincide con lo escrito";
    case MCA_ENOKEY:      return "indice fuera de la tabla del bloque";
    default:              return "codigo de error desconocido";
    }
}

const char *mca_lib_version(void)
{
    return MCA_LIB_VERSION;
}

const char *mca_lib_build(void)
{
    return "gcc " __VERSION__ " | " MCA_CFLAGS_STR;
}
