/* Lo privado comun a los handles de cada bloque: el bus y el detalle del error.
 *
 * Es la misma herencia a la C que `struct mca_bus` en bus.h: `mca_bloque` va como
 * PRIMER miembro de cada handle, y se llama `b`:
 *
 *     struct mca_h { mca_bloque b; uint32_t caps; ... };
 *
 * Asi un puntero al handle es tambien un puntero a la base, y las funciones de aca
 * sirven para todos. NULL significa "todavia no hay handle": el detalle de una
 * apertura que fallo queda en un buffer aparte, por hilo.
 */
#ifndef MCA_BLOQUE_H
#define MCA_BLOQUE_H

#include "mca_bus.h"

#define MCA_LARGO_ERROR 400

typedef struct {
    mca_bus *bus;
    int propio;                 /* el close del handle cierra el bus */
    char error[MCA_LARGO_ERROR];
} mca_bloque;

/* Deja el detalle en `b` (o en el de apertura, con NULL) y devuelve rc. Preserva
 * errno: con MCA_EOPEN el binding arma el OSError con el errno de open()/mmap(). */
int bloque_fallar(mca_bloque *b, int rc, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));

/* mca_bus_open_devmem con el mensaje de error que espera el binding. */
int bloque_abrir_devmem(mca_bus **bus, uint32_t phys, uint32_t size);

void bloque_limpiar_apertura(void);

/* El detalle de `b`, o el de la ultima apertura con NULL. */
const char *bloque_ultimo_error(const mca_bloque *b);

#define TRY(x) do { int rc_ = (x); if (rc_ != MCA_OK) return rc_; } while (0)

/* Al entrar a una funcion publica: rechaza el NULL y borra el detalle anterior. */
#define INICIO(h) do { if ((h) == NULL) return MCA_EINVAL;                  \
                       (h)->b.error[0] = '\0'; } while (0)

#endif /* MCA_BLOQUE_H */
