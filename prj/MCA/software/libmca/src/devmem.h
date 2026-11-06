/* El backend devmem, partido en dos ficheros a proposito:
 *
 *   bus_mmap.c    open + mmap + munmap: arma y libera el struct. Memoria comun.
 *   bus_devmem.c  los TRES accesos a la PL, y nada mas.
 *
 * La particion es lo que hace util a `make check-bus`: revisa bus_devmem.o
 * ENTERO, sin excepciones por funcion. Cuando open y close vivian en el mismo
 * fichero, el compilador cargaba dos campos del struct con un LDRD (memoria
 * comun, inofensivo) y el chequeo no podia distinguirlo de un LDRD sobre la PL
 * sin una lista de funciones exceptuadas, que es justo la clase de disciplina
 * que el chequeo existe para no necesitar.
 *
 * Por lo mismo `regs` es un `void *` aca: el tipo de acceso de dispositivo solo
 * se le da adentro de bus_devmem.c.
 */
#ifndef MCA_DEVMEM_PRIV_H
#define MCA_DEVMEM_PRIV_H

#include <stddef.h>

#include "bus.h"

struct devmem_bus {
    struct mca_bus base;        /* primer miembro: ver bus.h */
    int fd;
    void *map;                  /* lo que devolvio mmap, para el munmap */
    size_t map_len;
    void *regs;                 /* map + (phys - pagina): el offset 0 del slot */
};

#define DM(b) ((struct devmem_bus *)(b))

int dm_r32(mca_bus *b, uint32_t off, uint32_t *val);
int dm_w32(mca_bus *b, uint32_t off, uint32_t val);
int dm_read_words(mca_bus *b, uint32_t off, uint32_t n, uint32_t *dst);

#endif /* MCA_DEVMEM_PRIV_H */
