/* Lo comun a los handles de cada bloque. Ver bloque.h.
 *
 * Nada de este fichero toca memoria de dispositivo.
 */
#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bloque.h"

/* El detalle de un *_open que fallo, cuando todavia no hay handle. */
static _Thread_local char error_apertura[MCA_LARGO_ERROR];

int bloque_fallar(mca_bloque *b, int rc, const char *fmt, ...)
{
    int e = errno;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(b ? b->error : error_apertura, MCA_LARGO_ERROR, fmt, ap);
    va_end(ap);
    errno = e;
    return rc;
}

int bloque_abrir_devmem(mca_bus **bus, uint32_t phys, uint32_t size)
{
    int rc = mca_bus_open_devmem(bus, phys, size);
    if (rc != MCA_OK)
        return bloque_fallar(NULL, rc, "/dev/mem @ 0x%" PRIx32 ": %s", phys,
                             strerror(errno));
    return MCA_OK;
}

void bloque_limpiar_apertura(void)
{
    error_apertura[0] = '\0';
}

const char *bloque_ultimo_error(const mca_bloque *b)
{
    return b ? b->error : error_apertura;
}
