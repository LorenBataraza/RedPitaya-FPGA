/* Lo privado que comparten gen_pulsos.c y osciloscope_ring.c: los registros del
 * motor de disparos, que en los dos generadores son los mismos y en el mismo
 * orden desde una base (0x000 en gen_pulsos, 0x100 en el ring).
 */
#ifndef MCA_GEN_PRIV_H
#define MCA_GEN_PRIV_H

#include "bloque.h"
#include "gen_disparos.h"

/* Los offsets desde la base del motor. */
#define GEN_OFF_CTRL     0x00u
#define GEN_OFF_PERIODO  0x04u
#define GEN_OFF_UMBRAL   0x08u
#define GEN_OFF_DT_MIN   0x0Cu
#define GEN_OFF_N        0x10u
#define GEN_OFF_SEMILLA  0x14u
#define GEN_OFF_GEN_CNT  0x18u
#define GEN_OFF_ESTADO   0x1Cu
#define GEN_OFF_MAGIC    0x20u

/* gen_disparos_validar con el detalle en `b` (NULL: el buffer sin handle). */
int gen_disparos_validar_en(mca_bloque *b, const gen_disparos_cfg_t *c);

/* Escribe los cinco registros de datos del motor (no CTRL) y los relee:
 * MCA_EVERIFY con el detalle en `b` si alguno no quedo. */
int gen_disparos_escribir(mca_bloque *b, uint32_t base, const gen_disparos_cfg_t *c);

/* Los lee, con aleatorio = 0: ese bit es de CTRL, y lo pone quien llama. */
int gen_disparos_leer(mca_bloque *b, uint32_t base, gen_disparos_cfg_t *c);

int gen_estado_leer(mca_bloque *b, uint32_t base, gen_estado_t *e);

/* Escribe y relee un registro: MCA_EVERIFY si no quedo `esperado`. */
int gen_poner(mca_bloque *b, uint32_t off, const char *nombre, uint32_t v,
              uint32_t esperado);

#endif /* MCA_GEN_PRIV_H */
