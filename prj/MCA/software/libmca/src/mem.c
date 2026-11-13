/* La region de DDR. Ver include/mca_mem.h.
 *
 * NO es memoria de dispositivo: es DDR, que la PL escribe por un puerto HP. La regla
 * del bus (de a 32 bits, sin rafagas) es la del esclavo AXI de la PL, y aca no hay
 * ninguno: por eso se copia con memcpy, como hacia el slice de Python sobre el mismo
 * mapeo, medido en la placa. El orden entre la lectura del footer y la de los datos lo
 * pone quien lee (osciloscope_ring.c), con una barrera.
 */
#define _DEFAULT_SOURCE         /* MAP_SHARED, sysconf con -std=c11 */

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>

#include "devmem.h"
#include "mca_mem.h"

#define TRY_MEM(x) do { int rc_ = (x); if (rc_ != MCA_OK) return rc_; } while (0)

struct mca_mem {
    uint32_t phys, size;
    uint8_t *dir;               /* ptr, file y devmem: se copia desde y hacia aca */
    mca_mem_leer_fn leer;       /* callback */
    mca_mem_escribir_fn escribir;
    void *ctx;
    int fd;                     /* file y devmem; -1 si no hay mapeo */
    void *map;
    size_t map_len;
};

static int nueva(mca_mem **m, uint32_t phys, uint32_t size, mca_mem **n)
{
    if (m == NULL)
        return MCA_EINVAL;
    *m = NULL;
    if (size == 0 || (size & 7u) || (phys & 7u))
        return MCA_EINVAL;
    *n = calloc(1, sizeof(**n));
    if (*n == NULL)
        return MCA_ENOMEM;
    (*n)->phys = phys;
    (*n)->size = size;
    (*n)->fd = -1;
    return MCA_OK;
}

static int mapear(mca_mem **m, const char *path, int flags, uint32_t phys,
                  uint32_t size)
{
    mca_mem *n;
    int rc = nueva(m, phys, size, &n);
    if (rc != MCA_OK)
        return rc;
    void *dir;
    rc = mapeo_abrir(path, flags, phys, size, &n->fd, &n->map, &n->map_len, &dir);
    if (rc != MCA_OK) {
        int e = errno;
        free(n);
        errno = e;
        return rc;
    }
    n->dir = dir;
    *m = n;
    return MCA_OK;
}

int mca_mem_open_devmem(mca_mem **m, uint32_t phys, uint32_t size)
{
    /* O_SYNC: no cacheable. Los puertos HP no son coherentes con L1/L2, y una linea
     * de cache vieja seria un slot viejo con el footer nuevo. */
    return mapear(m, "/dev/mem", O_RDWR | O_SYNC, phys, size);
}

int mca_mem_open_file(mca_mem **m, const char *path, uint32_t phys, uint32_t size)
{
    if (path == NULL)
        return MCA_EINVAL;
    return mapear(m, path, O_RDWR, phys, size);
}

int mca_mem_open_ptr(mca_mem **m, void *p, uint32_t phys, uint32_t size)
{
    if (p == NULL)
        return MCA_EINVAL;
    mca_mem *n;
    int rc = nueva(m, phys, size, &n);
    if (rc != MCA_OK)
        return rc;
    n->dir = p;
    *m = n;
    return MCA_OK;
}

int mca_mem_open_callback(mca_mem **m, mca_mem_leer_fn leer,
                          mca_mem_escribir_fn escribir, void *ctx, uint32_t phys,
                          uint32_t size)
{
    if (leer == NULL)
        return MCA_EINVAL;
    mca_mem *n;
    int rc = nueva(m, phys, size, &n);
    if (rc != MCA_OK)
        return rc;
    n->leer = leer;
    n->escribir = escribir;
    n->ctx = ctx;
    *m = n;
    return MCA_OK;
}

void mca_mem_close(mca_mem *m)
{
    if (m == NULL)
        return;
    if (m->fd >= 0)
        mapeo_cerrar(m->fd, m->map, m->map_len);
    free(m);
}

static int validar(const mca_mem *m, uint32_t off, uint32_t n, const void *p)
{
    if (m == NULL || (p == NULL && n != 0))
        return MCA_EINVAL;
    if ((off & 7u) || (n & 7u))
        return MCA_EALIGN;
    if (off > m->size || n > m->size - off)
        return MCA_ERANGE;
    return MCA_OK;
}

static int de_callback(int rc)
{
    if (rc == MCA_OK)
        return MCA_OK;
    return (rc < 0 && rc >= MCA_E_ULTIMO) ? rc : MCA_EBACKEND;
}

int mca_mem_read(mca_mem *m, uint32_t off, uint32_t n, void *dst)
{
    TRY_MEM(validar(m, off, n, dst));
    if (n == 0)
        return MCA_OK;
    if (m->leer != NULL)
        return de_callback(m->leer(m->ctx, off, n, dst));
    memcpy(dst, m->dir + off, n);
    return MCA_OK;
}

int mca_mem_write(mca_mem *m, uint32_t off, uint32_t n, const void *src)
{
    TRY_MEM(validar(m, off, n, src));
    if (n == 0)
        return MCA_OK;
    if (m->leer != NULL) {
        if (m->escribir == NULL)
            return MCA_ENOSYS;
        return de_callback(m->escribir(m->ctx, off, n, src));
    }
    memcpy(m->dir + off, src, n);
    return MCA_OK;
}

uint32_t mca_mem_size(const mca_mem *m)
{
    return m ? m->size : 0;
}

uint32_t mca_mem_phys(const mca_mem *m)
{
    return m ? m->phys : 0;
}
