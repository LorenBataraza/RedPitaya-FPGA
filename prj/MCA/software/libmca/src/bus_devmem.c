/* Los accesos a la PL. EL UNICO FICHERO QUE TOCA MEMORIA DE DISPOSITIVO.
 *
 * Todo acceso es un `volatile uint32_t` alineado, de a una palabra: un `ldr` o
 * un `str` por transaccion. Es el mismo acceso que hace bench_reader_c.c, que
 * esta medido en placa (0.235 us por palabra) y es seguro.
 *
 * Lo que NO puede aparecer aca, y por que (docs/TOP/bus_sistema_redpitaya.md):
 *
 *   memcpy, NEON, LDM/LDRD   rafagas o accesos de 64 b: axi4_slave.sv los
 *                            rechaza y la placa SE REINICIA (§7.3)
 *   accesos de 1 o 2 bytes   el de 1 byte tambien se rechaza: SIGBUS (§7.4)
 *
 * `make check-bus` desensambla este objeto compilado para ARM y falla si
 * encuentra alguna de esas instrucciones. Por eso aca no hay nada mas que los
 * tres accesos: abrir y cerrar el mapeo esta en bus_mmap.c (ver devmem.h).
 * Ademas se compila con -fno-tree-vectorize, para que el lazo de
 * dm_read_words no se convierta en NEON.
 */
#include "devmem.h"

int dm_r32(mca_bus *b, uint32_t off, uint32_t *val)
{
    volatile uint32_t *r = DM(b)->regs;
    *val = r[off >> 2];                         /* un ldr de 32 b */
    return MCA_OK;
}

int dm_w32(mca_bus *b, uint32_t off, uint32_t val)
{
    volatile uint32_t *r = DM(b)->regs;
    r[off >> 2] = val;                          /* un str de 32 b */
    return MCA_OK;
}

int dm_read_words(mca_bus *b, uint32_t off, uint32_t n, uint32_t *dst)
{
    volatile uint32_t *p = (volatile uint32_t *)DM(b)->regs + (off >> 2);
    /* volatile obliga a una carga por iteracion, en orden y sin fusionarlas.
     * NO reemplazar por memcpy: ver la cabecera. */
    for (uint32_t i = 0; i < n; i++)
        dst[i] = p[i];
    return MCA_OK;
}
