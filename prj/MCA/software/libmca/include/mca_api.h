/* libmca: la API en C de los bloques que este proyecto agrega a la PL.
 *
 * Tiene la misma forma que rp-api (librp) de Red Pitaya: un handle opaco por
 * bloque, funciones que devuelven un codigo de error y que entregan los
 * resultados por puntero. Desde Python se usa por ctypes (API/_libmca.py); el
 * binding no agrega logica, solo traduce estos codigos a excepciones.
 *
 * Este header tiene lo comun a todos los bloques: los codigos de error y la
 * identificacion de la biblioteca. El acceso al bus esta en mca_bus.h.
 */
#ifndef MCA_API_H
#define MCA_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Se compila con -fvisibility=hidden: solo lo marcado con MCA_API queda en la
 * tabla de simbolos del .so, que es exactamente lo que ctypes puede llamar. */
#define MCA_API __attribute__((visibility("default")))

#define MCA_LIB_VERSION "0.5.0"

/* Cero es exito; todo error es negativo, como en rp-api. El binding de Python
 * traduce cada uno a la excepcion que la API de Python ya lanzaba. */
typedef enum {
    MCA_OK          =   0,
    MCA_EINVAL      =  -1,  /* argumento invalido o fuera de rango            */
    MCA_ENOTPRESENT =  -2,  /* el magic no coincide: el bloque no esta en la PL */
    MCA_ETIMEOUT    =  -3,  /* la PL no termino a tiempo (p. ej. clear_busy)  */
    MCA_ENOSYS      =  -4,  /* el bitstream no tiene esa capacidad (CAPS)     */
    MCA_EALIGN      =  -5,  /* offset que no es multiplo de 4                 */
    MCA_ERANGE      =  -6,  /* offset fuera de la region mapeada              */
    MCA_EOPEN       =  -7,  /* open() o mmap() fallaron: ver errno            */
    MCA_ENOMEM      =  -8,
    MCA_EBACKEND    =  -9,  /* un backend por callbacks devolvio error        */
    MCA_EVERIFY     = -10,  /* la relectura no coincide con lo escrito        */
    MCA_ENOKEY      = -11,  /* un indice que no esta en la tabla del bloque   */
    MCA_E_ULTIMO    = -11,  /* el codigo mas negativo: los de abajo no existen */
} mca_err_t;

MCA_API const char *mca_strerror(int rc);

/* Una fila del mapa de registros de un bloque, como la exporta <bloque>_reg_info. */
typedef struct { const char *nombre; uint32_t offset; } mca_reg_t;

/* Una fila de la tabla de campos de un bloque (<bloque>_field_info). */
typedef struct {
    const char *nombre;
    uint32_t    offset;
    uint32_t    shift;
    uint32_t    mascara;
    int32_t     bandera;        /* 1: set(v) escribe v != 0 */
} mca_field_t;

/* "0.1.0". Va en la metadata de cada medicion (api_impl, libmca_version). */
MCA_API const char *mca_lib_version(void);

/* Compilador y flags con que se armo el .so. Lo registra bench_impl.py: dos
 * corridas solo son comparables si salen de la misma compilacion. */
MCA_API const char *mca_lib_build(void);

#ifdef __cplusplus
}
#endif

#endif /* MCA_API_H */
