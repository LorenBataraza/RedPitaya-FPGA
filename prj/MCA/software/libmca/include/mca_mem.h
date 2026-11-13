/* Una region de memoria comun, la DDR que escribe la PL: lo que lee el event_ring.
 *
 * No es el bus. El bus (mca_bus.h) son los registros de la PL, y su esclavo solo
 * atiende accesos de 32 bits de a uno: una rafaga reinicia la placa. Esta region es
 * DDR, reservada en el device tree para que la escriba la PL por un puerto HP, y
 * mapeada no cacheable (O_SYNC): los puertos HP no son coherentes con la cache. Ahi
 * se puede copiar de a bloques, y es lo que la hace rapida (docs/event_ring/).
 *
 * Por eso es un tipo aparte, y los accesos son copias: `mca_mem_read` lleva n bytes a
 * memoria del proceso, y `mca_mem_write` los trae (el ring la escribe una sola vez,
 * al configurarse, para borrar los footers de la corrida anterior). Como copiar esta
 * memoria (memcpy, o de a palabras) se decide midiendo en la placa; hoy es memcpy, que
 * es lo que hacia el slice de Python que se midio (64 KB en 296 us).
 *
 * Los backends:
 *
 *   devmem    /dev/mem con O_SYNC: la region reservada, en la placa
 *   file      un fichero comun, mapeado igual: el camino de mmap sin la placa
 *   ptr       memoria de quien llama (un arreglo de numpy en los tests)
 *   callback  la copia la hace una funcion: un modelo, o el puente al simulador
 *
 * `phys` es la direccion fisica de la region: la que el ring escribe en SLOT_BASE.
 * En ptr y callback no hay mapeo, y es la que diga quien llama.
 */
#ifndef MCA_MEM_H
#define MCA_MEM_H

#include <stdint.h>

#include "mca_api.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct mca_mem mca_mem;

/* Copian n bytes desde `off` a dst, o desde src a `off`. 0 si salio bien; otro valor
 * se propaga como MCA_EBACKEND (o como el propio codigo, si es uno de los MCA_E*). */
typedef int (*mca_mem_leer_fn)(void *ctx, uint32_t off, uint32_t n, void *dst);
typedef int (*mca_mem_escribir_fn)(void *ctx, uint32_t off, uint32_t n, const void *src);

/* Devuelve MCA_EOPEN si no hay permiso sobre /dev/mem (hace falta root) o si el mmap
 * falla. `phys` y `size`, multiplos de 8. */
MCA_API int mca_mem_open_devmem(mca_mem **m, uint32_t phys, uint32_t size);
MCA_API int mca_mem_open_file(mca_mem **m, const char *path, uint32_t phys,
                              uint32_t size);
/* `p` tiene que vivir lo mismo que la region: no se copia ni se libera. */
MCA_API int mca_mem_open_ptr(mca_mem **m, void *p, uint32_t phys, uint32_t size);
/* `escribir` puede ser NULL: una region de solo lectura, y mca_mem_write da
 * MCA_ENOSYS. */
MCA_API int mca_mem_open_callback(mca_mem **m, mca_mem_leer_fn leer,
                                  mca_mem_escribir_fn escribir, void *ctx,
                                  uint32_t phys, uint32_t size);
MCA_API void mca_mem_close(mca_mem *m);

/* n bytes desde `off`. `off` y `n` multiplos de 8 (MCA_EALIGN), dentro de la region
 * (MCA_ERANGE). La region son palabras de 64 b: las del slot del ring. */
MCA_API int mca_mem_read(mca_mem *m, uint32_t off, uint32_t n, void *dst);
MCA_API int mca_mem_write(mca_mem *m, uint32_t off, uint32_t n, const void *src);

MCA_API uint32_t mca_mem_size(const mca_mem *m);
MCA_API uint32_t mca_mem_phys(const mca_mem *m);

#ifdef __cplusplus
}
#endif

#endif /* MCA_MEM_H */
