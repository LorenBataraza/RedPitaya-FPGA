/* Las funciones publicas del bus: validan y despachan al backend.
 *
 * La validacion vive aca y no en cada backend porque la regla es del bus, no
 * de la implementacion: un offset desalineado es un error contra la placa y
 * contra el modelo simulado por igual, y conviene que FakeMCA lo rechace igual
 * que la PL lo haria.
 */
#include <stddef.h>

#include "bus.h"

static int chequear(const mca_bus *b, uint32_t off, uint32_t n_palabras)
{
    if (b == NULL)
        return MCA_EINVAL;
    if (off & 3u)
        return MCA_EALIGN;
    if (b->size != 0) {
        /* En 64 bits para que off + 4n no de la vuelta. */
        uint64_t fin = (uint64_t)off + 4ull * (uint64_t)n_palabras;
        if (fin > b->size)
            return MCA_ERANGE;
    }
    return MCA_OK;
}

int mca_bus_r32(mca_bus *b, uint32_t off, uint32_t *val)
{
    int rc = chequear(b, off, 1);
    if (rc != MCA_OK)
        return rc;
    if (val == NULL)
        return MCA_EINVAL;
    return b->vt->r32(b, off, val);
}

int mca_bus_w32(mca_bus *b, uint32_t off, uint32_t val)
{
    int rc = chequear(b, off, 1);
    if (rc != MCA_OK)
        return rc;
    return b->vt->w32(b, off, val);
}

int mca_bus_read_words(mca_bus *b, uint32_t off, uint32_t n, uint32_t *dst)
{
    int rc = chequear(b, off, n);
    if (rc != MCA_OK)
        return rc;
    if (dst == NULL && n != 0)
        return MCA_EINVAL;
    return b->vt->read_words(b, off, n, dst);
}

uint32_t mca_bus_size(const mca_bus *b)
{
    return b ? b->size : 0;
}

void mca_bus_close(mca_bus *b)
{
    if (b != NULL)
        b->vt->close(b);
}
