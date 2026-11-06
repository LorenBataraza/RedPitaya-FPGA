/* El backend por callbacks: los accesos los provee quien llama.
 *
 * No toca la PL. Es el corte por donde entran FakeMCA (su modelo de registros
 * en Python, por ctypes) y el backend que graba de los tests de equivalencia.
 * La logica de mca.c corre identica sobre este backend y sobre devmem: lo
 * unico que cambia es a donde va cada r32/w32.
 */
#include <stdlib.h>

#include "bus.h"

struct cb_bus {
    struct mca_bus base;        /* primer miembro: ver bus.h */
    mca_bus_ops ops;
};

#define CB(b) ((struct cb_bus *)(b))

/* Un codigo propio de libmca se respeta; cualquier otro distinto de cero es
 * un error del backend. */
static int traducir(int rc)
{
    if (rc == 0)
        return MCA_OK;
    if (rc < 0 && rc >= MCA_E_ULTIMO)
        return rc;
    return MCA_EBACKEND;
}

static int cb_r32(mca_bus *b, uint32_t off, uint32_t *val)
{
    return traducir(CB(b)->ops.r32(CB(b)->ops.ctx, off, val));
}

static int cb_w32(mca_bus *b, uint32_t off, uint32_t val)
{
    return traducir(CB(b)->ops.w32(CB(b)->ops.ctx, off, val));
}

static int cb_read_words(mca_bus *b, uint32_t off, uint32_t n, uint32_t *dst)
{
    struct cb_bus *c = CB(b);
    if (c->ops.read_words != NULL)
        return traducir(c->ops.read_words(c->ops.ctx, off, n, dst));
    for (uint32_t i = 0; i < n; i++) {
        int rc = traducir(c->ops.r32(c->ops.ctx, off + 4u * i, &dst[i]));
        if (rc != MCA_OK)
            return rc;
    }
    return MCA_OK;
}

static void cb_close(mca_bus *b)
{
    free(b);
}

static const struct mca_bus_vt callback_vt = {
    .r32 = cb_r32, .w32 = cb_w32, .read_words = cb_read_words, .close = cb_close,
};

int mca_bus_open_callback(mca_bus **bus, const mca_bus_ops *ops, uint32_t size)
{
    if (bus == NULL || ops == NULL || ops->r32 == NULL || ops->w32 == NULL)
        return MCA_EINVAL;
    *bus = NULL;

    struct cb_bus *c = calloc(1, sizeof(*c));
    if (c == NULL)
        return MCA_ENOMEM;
    c->ops = *ops;
    c->base.vt = &callback_vt;
    c->base.size = size;
    *bus = &c->base;
    return MCA_OK;
}
