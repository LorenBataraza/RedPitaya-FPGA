/* El backend devmem: abrir, mapear y cerrar. No toca la PL (ver devmem.h). El
 * mapeo lo usa tambien la region de DDR (mem.c). */
#define _DEFAULT_SOURCE         /* MAP_SHARED, sysconf con -std=c11 */

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

#include "devmem.h"

static void dm_close(mca_bus *b)
{
    struct devmem_bus *d = DM(b);
    mapeo_cerrar(d->fd, d->map, d->map_len);
    free(d);
}

static const struct mca_bus_vt devmem_vt = {
    .r32 = dm_r32, .w32 = dm_w32, .read_words = dm_read_words, .close = dm_close,
};

int mapeo_abrir(const char *path, int flags, uint32_t phys, uint32_t size,
                int *fd, void **map, size_t *map_len, void **dir)
{
    *fd = open(path, flags);
    if (*fd < 0)
        return MCA_EOPEN;

    /* mmap exige un offset alineado a pagina. Las bases de slot lo estan
     * (0x40X0_0000), pero se resuelve igual para no depender de eso. */
    long pagina = sysconf(_SC_PAGESIZE);
    off_t base = (off_t)(phys & ~((uint32_t)pagina - 1u));
    size_t delta = (size_t)(phys - (uint32_t)base);
    *map_len = delta + size;
    *map = mmap(NULL, *map_len, PROT_READ | PROT_WRITE, MAP_SHARED, *fd, base);
    if (*map == MAP_FAILED) {
        int e = errno;
        close(*fd);
        errno = e;
        return MCA_EOPEN;
    }
    *dir = (char *)*map + delta;
    return MCA_OK;
}

void mapeo_cerrar(int fd, void *map, size_t map_len)
{
    munmap(map, map_len);
    close(fd);
}

static int abrir(mca_bus **bus, const char *path, int flags, uint32_t phys,
                 uint32_t size)
{
    if (bus == NULL || size == 0 || (phys & 3u) || (size & 3u))
        return MCA_EINVAL;
    *bus = NULL;

    struct devmem_bus *d = calloc(1, sizeof(*d));
    if (d == NULL)
        return MCA_ENOMEM;

    int rc = mapeo_abrir(path, flags, phys, size, &d->fd, &d->map, &d->map_len,
                         &d->regs);
    if (rc != MCA_OK) {
        int e = errno;
        free(d);
        errno = e;
        return rc;
    }
    d->base.vt = &devmem_vt;
    d->base.size = size;
    *bus = &d->base;
    return MCA_OK;
}

int mca_bus_open_devmem(mca_bus **bus, uint32_t phys, uint32_t size)
{
    /* O_SYNC: sin el, el kernel puede mapear la region como cacheable, y un
     * fallo de cache es un relleno de linea en rafaga (§10.1, "Cachear la
     * ventana"). Es el mismo flag que usa la API de Python. */
    return abrir(bus, "/dev/mem", O_RDWR | O_SYNC, phys, size);
}

int mca_bus_open_file(mca_bus **bus, const char *path, uint32_t phys,
                      uint32_t size)
{
    if (path == NULL)
        return MCA_EINVAL;
    return abrir(bus, path, O_RDWR, phys, size);
}
