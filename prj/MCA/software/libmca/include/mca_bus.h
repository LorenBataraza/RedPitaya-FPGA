/* El acceso de 32 bits al bus de sistema: el nivel 2 de la pila.
 *
 * Todo lo que libmca lee o escribe en la PL pasa por un `mca_bus`. Hay dos
 * implementaciones, y elegir una es el equivalente en C de lo que en Python
 * se hacia heredando de MCA y redefiniendo r32/w32:
 *
 *   devmem    el real: open("/dev/mem") + mmap, un acceso de 32 bits por vez
 *   callback  los tres accesos los provee quien llama, por punteros a funcion.
 *             Es como FakeMCA enchufa su modelo de registros (escrito en
 *             Python) a la logica de C, y como los tests graban la secuencia
 *             de accesos para compararla con la implementacion de referencia.
 *
 * La regla del bus (docs/TOP/bus_sistema_redpitaya.md §7.2-7.4): el esclavo
 * de la PL solo atiende accesos de 32 bits alineados, de a uno. Una rafaga o un
 * acceso de 1 byte termina en SIGBUS o reinicia la placa. Por eso esta capa
 * verifica alineacion y rango ANTES de llegar a cualquier backend, y el unico
 * fichero que toca memoria de dispositivo es src/bus_devmem.c (lo comprueba
 * `make check-bus`).
 */
#ifndef MCA_BUS_H
#define MCA_BUS_H

#include <stdint.h>
#include "mca_api.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct mca_bus mca_bus;

/* Backend por callbacks. Cada funcion devuelve 0 si salio bien; cualquier otro
 * valor se propaga como MCA_EBACKEND (o como el propio codigo, si es uno de los
 * MCA_E*). `read_words` es opcional: con NULL se hacen n llamadas a r32. */
typedef int (*mca_r32_fn)(void *ctx, uint32_t off, uint32_t *val);
typedef int (*mca_w32_fn)(void *ctx, uint32_t off, uint32_t val);
typedef int (*mca_read_words_fn)(void *ctx, uint32_t off, uint32_t n,
                                 uint32_t *dst);

typedef struct {
    mca_r32_fn        r32;
    mca_w32_fn        w32;
    mca_read_words_fn read_words;
    void             *ctx;
} mca_bus_ops;

/* `phys` es la base del slot (0x4070_0000 para el MCA) y `size` los bytes que
 * se mapean. Devuelve MCA_EOPEN si no hay permiso sobre /dev/mem (hace falta
 * root) o si el mmap falla. */
MCA_API int mca_bus_open_devmem(mca_bus **bus, uint32_t phys, uint32_t size);

/* Lo mismo sobre un fichero comun en vez de /dev/mem. Sirve para probar en la
 * PC el camino de mmap, alineacion y rango sin la placa. */
MCA_API int mca_bus_open_file(mca_bus **bus, const char *path, uint32_t phys,
                              uint32_t size);

/* `size` acota los offsets validos como en devmem; 0 = sin limite. Las ops se
 * copian: `ops` puede liberarse despues de la llamada, `ops->ctx` no. */
MCA_API int mca_bus_open_callback(mca_bus **bus, const mca_bus_ops *ops,
                                  uint32_t size);

MCA_API void mca_bus_close(mca_bus *bus);

MCA_API int mca_bus_r32(mca_bus *bus, uint32_t off, uint32_t *val);
MCA_API int mca_bus_w32(mca_bus *bus, uint32_t off, uint32_t val);

/* n palabras consecutivas desde `off`, DE A UNA. Es la lectura de espectros:
 * nunca un memcpy, que sobre esta memoria emite rafagas (§7.3). */
MCA_API int mca_bus_read_words(mca_bus *bus, uint32_t off, uint32_t n,
                               uint32_t *dst);

/* n lecturas del MISMO registro, una detras de otra, a `dst`. Es para medir el
 * bus: un registro que cambia solo (un contador, un puntero) leido sin pausa
 * muestra si el dato cruza entero el CDC (docs/TOP/bus_sistema_redpitaya.md
 * §6.1). Desde Python, cada mca_bus_r32 cuesta ~19 us en la placa; aca, lo que
 * tarde el bus. */
MCA_API int mca_bus_sondear(mca_bus *bus, uint32_t off, uint32_t n,
                            uint32_t *dst);

/* Bytes accesibles del bus; 0 si no tiene limite. */
MCA_API uint32_t mca_bus_size(const mca_bus *bus);

#ifdef __cplusplus
}
#endif

#endif /* MCA_BUS_H */
