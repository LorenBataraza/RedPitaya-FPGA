/* Lo privado del bus: la tabla de funciones que cada backend implementa.
 *
 * Es herencia a la C: `struct mca_bus` va como PRIMER miembro de cada backend
 * (`struct devmem_bus`, `struct cb_bus`), asi que un puntero al backend es
 * tambien un puntero a la base, y `vt` dice que funcion corre. Es lo mismo que
 * en Python hacia `FakeMCA(MCA)` al redefinir r32/w32, sin la palabra clave.
 *
 * Las funciones publicas de bus.c validan alineacion y rango antes de llamar a
 * `vt`, de modo que ningun backend tiene que repetirlo.
 */
#ifndef MCA_BUS_PRIV_H
#define MCA_BUS_PRIV_H

#include "mca_bus.h"

struct mca_bus_vt {
    int  (*r32)(mca_bus *b, uint32_t off, uint32_t *val);
    int  (*w32)(mca_bus *b, uint32_t off, uint32_t val);
    int  (*read_words)(mca_bus *b, uint32_t off, uint32_t n, uint32_t *dst);
    void (*close)(mca_bus *b);
};

struct mca_bus {
    const struct mca_bus_vt *vt;
    uint32_t size;          /* bytes accesibles; 0 = sin limite */
};

#endif /* MCA_BUS_PRIV_H */
