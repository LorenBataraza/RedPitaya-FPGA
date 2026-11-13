/* El generador de pulsos (gen_pulsos.sv), en el lugar del ASG de Red Pitaya: slot 2,
 * base 0x4021_0000, repartido con el event_ring por sys_bus_split. El doc es
 * docs/gen_eventos/generador_pulsos.md.
 *
 * Cada pulso es un impulso de amplitud A (de una tabla de 1024 que carga el PS) que
 * pasa por dos polos enteros: la caida del preamplificador (DECAE) y una subida
 * opcional (SUBIDA). Los disparos son los de gen_disparos.h. Maneja dos cosas:
 *
 *   asg_dat        la entrada del DAC. Con el lazo digital (digital_loop[0] de HK),
 *                  adc_dat toma el DAC en vez del ADC, antes de la calibracion: el
 *                  osciloscopio, el multitrigger, el MCA y el ring ven los pulsos
 *                  bit a bit. Sin el lazo salen por OUT1/OUT2.
 *   trig_asg_out   la fuente ASG del multitrigger (OR_MASK bit 11).
 *
 * El lazo digital es de housekeeping (slot 0, 0x4000_000C), no del generador, pero
 * este handle es lo unico de libmca que lo usa: gen_pulsos_open mapea tambien esa
 * pagina, y gen_pulsos_set_lazo escribe solo el bit 0.
 *
 *     gen_pulsos_h *g;
 *     if (gen_pulsos_open(&g, GEN_PULSOS_PHYS, GEN_PULSOS_SIZE, 1) != MCA_OK)
 *         fprintf(stderr, "%s\n", gen_pulsos_last_error(NULL));
 *     gen_pulsos_cfg_t cfg;
 *     gen_pulsos_config_default(&cfg);
 *     gen_disparos_umbral_para(200e3, 2, &cfg.disparos.umbral);
 *     cfg.disparos.aleatorio = 1;
 *     cfg.disparos.n = 100000;
 *     gen_pulsos_decae_para(250.0, &cfg.decae);
 *     gen_pulsos_configurar(g, &cfg);          // lo deja apagado
 *     gen_pulsos_cargar_tabla(g, tabla, 1024);
 *     gen_pulsos_set_lazo(g, 1);
 *     ... MCA corriendo, con trap_mq = gen_pulsos_mq(cfg.decae) ...
 *     gen_pulsos_arrancar(g);                  // reinicia el estado y genera
 *     gen_pulsos_esperar(g, plazo, &est);      // hasta N
 *     gen_pulsos_parar(g);
 *     gen_pulsos_set_lazo(g, 0);
 *     gen_pulsos_close(g);
 *
 * Como el resto de libmca: cada funcion devuelve MCA_OK o un MCA_E*, y el detalle
 * queda en gen_pulsos_last_error(). Un handle tiene un solo duenio.
 */
#ifndef GEN_PULSOS_H
#define GEN_PULSOS_H

#include <stddef.h>
#include <stdint.h>

#include "gen_disparos.h"
#include "mca_api.h"
#include "mca_bus.h"
#include "gen_pulsos_regs.h"

#ifdef __cplusplus
extern "C" {
#endif

#define GEN_PULSOS_PHYS   0x40210000u
#define GEN_PULSOS_SIZE   0x2000u       /* los registros y la tabla */
#define GEN_PULSOS_MAGIC  0x50554C31u   /* "PUL1" */

#define GEN_PULSOS_N_TABLA   1024u
#define GEN_PULSOS_AMP_MIN   (-8192)    /* la muestra tiene 14 bits con signo */
#define GEN_PULSOS_AMP_MAX   8191
#define GEN_PULSOS_DECAE_MAX 0xFFFFu
#define GEN_PULSOS_DECAE_RESET 65280u   /* M = 255: tau = 255.5 muestras */
#define GEN_PULSOS_SUBIDA_MAX 7u
#define GEN_PULSOS_RUIDO_SH_MAX 15u

/* Del ciclo de la decision a trig_o, en la cuenta del modelo (g = 0 el ciclo despues
 * de prender en). La primera muestra del pulso sale en dat LAT_DAT ciclos despues de
 * trig_o, con SUBIDA = 0. */
#define GEN_PULSOS_LAT_TRIG 1u
#define GEN_PULSOS_LAT_DAT  5u

#define GEN_PULSOS_CTRL_EN        (1u << 0)
#define GEN_PULSOS_CTRL_ALEATORIO (1u << 1)
#define GEN_PULSOS_CTRL_AMP_ALEAT (1u << 2)
#define GEN_PULSOS_CTRL_OUT1      (1u << 3)
#define GEN_PULSOS_CTRL_OUT2      (1u << 4)
#define GEN_PULSOS_RUIDO_EN       (1u << 8)

/* `salidas` de gen_pulsos_cfg_t: a que canal del DAC va la salida. Para el lazo del
 * canal 0 del ADC, OUT1. */
#define GEN_PULSOS_SAL_OUT1 (1u << 0)
#define GEN_PULSOS_SAL_OUT2 (1u << 1)

/* El lazo digital: housekeeping de Red Pitaya (red_pitaya_hk, slot 0). */
#define GEN_PULSOS_HK_PHYS  0x40000000u
#define GEN_PULSOS_HK_SIZE  0x1000u
#define GEN_PULSOS_HK_LAZO  0x00Cu      /* digital_loop: [0] adc_dat <- DAC, [1] DAC <- adc_dat */

typedef struct gen_pulsos_h gen_pulsos_h;

/* ---- los tipos que cruzan la interfaz ------------------------------------- */

/* Todos los registros de configuracion. Los nombres son los de CFG del modelo
 * (gen_pulsos_model.py), mas `salidas`. */
typedef struct {
    gen_disparos_cfg_t disparos;
    uint32_t amp_aleat;         /* 1: cada pulso sortea su entrada de la tabla */
    uint32_t salidas;           /* GEN_PULSOS_SAL_*: OUT1 para el lazo del canal 0 */
    uint32_t decae;             /* caida por muestra * 2^16: gen_pulsos_decae_para */
    uint32_t subida;            /* polo de subida, tau ~ 2^subida; 0 = sin subida */
    uint32_t amp_n;             /* entradas en uso en orden, 1..1024; 0 = 1024 */
    int32_t  base;              /* sumada a la salida, 14 bits con signo */
    uint32_t ruido;             /* 1: suma el ruido */
    uint32_t ruido_sh;          /* sigma = 147.8 / 2^ruido_sh cuentas */
} gen_pulsos_cfg_t;

/* ---- ciclo de vida -------------------------------------------------------- */

/* Mapea el generador y la pagina de HK (el lazo). Con check_magic,
 * MCA_ENOTPRESENT si el slot 2 no tiene el generador (el bitstream del MCA
 * anterior al 2026-11-09, por ejemplo). */
MCA_API int gen_pulsos_open(gen_pulsos_h **h, uint32_t phys, uint32_t size,
                            int check_magic);

/* Sobre buses ya abiertos: `bus` el del generador y `hk` el de housekeeping (NULL:
 * sin lazo, gen_pulsos_set_lazo da MCA_ENOSYS). Con `propio` / `hk_propio`, close
 * los cierra. Si falla, siguen siendo de quien llama. */
MCA_API int gen_pulsos_open_bus(gen_pulsos_h **h, mca_bus *bus, int propio,
                                mca_bus *hk, int hk_propio, int check_magic);
MCA_API void gen_pulsos_close(gen_pulsos_h *h);

/* El detalle del ultimo error del handle; con NULL, el del ultimo open o el de las
 * funciones sin handle (validar, las cuentas). */
MCA_API const char *gen_pulsos_last_error(const gen_pulsos_h *h);

MCA_API int32_t gen_pulsos_reg_count(void);
MCA_API const mca_reg_t *gen_pulsos_reg_info(int32_t i);
MCA_API size_t gen_pulsos_sizeof(const char *tipo);

MCA_API int gen_pulsos_r32(gen_pulsos_h *h, uint32_t off, uint32_t *v);
MCA_API int gen_pulsos_w32(gen_pulsos_h *h, uint32_t off, uint32_t v);

/* ---- configuracion -------------------------------------------------------- */

/* Los valores de reset, con salidas = OUT1: periodico de 1000 ciclos, sin fin,
 * DECAE 65280, sin subida, la tabla entera en orden, sin base ni ruido. */
MCA_API void gen_pulsos_config_default(gen_pulsos_cfg_t *c);

/* MCA_EINVAL, con el detalle en gen_pulsos_last_error(NULL), si algun campo no entra
 * en su registro o no es lo que hace el RTL (gen_disparos_validar). */
MCA_API int gen_pulsos_validar(const gen_pulsos_cfg_t *c);

/* Apaga el generador (CTRL = 0: la salida y el disparo en cero), valida, escribe
 * todo y lo relee: MCA_EVERIFY si algo no quedo. No lo arranca. Un cambio entra un
 * ciclo despues en el RTL: por eso se configura apagado. */
MCA_API int gen_pulsos_configurar(gen_pulsos_h *h, const gen_pulsos_cfg_t *c);

/* Lo que esta escrito. amp_n 0 se lee como 1024. */
MCA_API int gen_pulsos_leer_config(gen_pulsos_h *h, gen_pulsos_cfg_t *c);

/* Las primeras `n` entradas de la tabla (n <= 1024), y el resto en 0; las relee
 * todas (MCA_EVERIFY). MCA_EINVAL, sin escribir nada, si alguna no entra en 14 bits.
 * Se puede cargar con el generador corriendo, pero la traza ya no es la del
 * modelo. */
MCA_API int gen_pulsos_cargar_tabla(gen_pulsos_h *h, const int16_t *amp, uint32_t n);
MCA_API int gen_pulsos_leer_tabla(gen_pulsos_h *h, int16_t *amp, uint32_t n);

/* ---- control y estado ----------------------------------------------------- */

/* Prende `en`: todo el estado vuelve a cero (los tres xorshift, el periodo, la tabla
 * en orden, los polos, GEN_CNT) y empieza a generar. Si ya estaba prendido, lo apaga
 * y lo vuelve a prender: siempre arranca de cero. */
MCA_API int gen_pulsos_arrancar(gen_pulsos_h *h);

/* Apaga `en`: la salida y el disparo en cero. GEN_CNT y ESTADO quedan. */
MCA_API int gen_pulsos_parar(gen_pulsos_h *h);

MCA_API int gen_pulsos_estado(gen_pulsos_h *h, gen_estado_t *e);

/* Espera que llegue a N (ESTADO[1]), hasta plazo_ns de CLOCK_MONOTONIC
 * (MCA_ETIMEOUT). MCA_EINVAL si N es 0 (no termina nunca) o si esta apagado. `e`
 * puede ser NULL. */
MCA_API int gen_pulsos_esperar(gen_pulsos_h *h, int64_t plazo_ns, gen_estado_t *e);

/* digital_loop[0] de HK: con 1, adc_dat toma el DAC (el generador) en vez del ADC.
 * Conserva digital_loop[1]. MCA_ENOSYS si el handle no tiene HK. */
MCA_API int gen_pulsos_set_lazo(gen_pulsos_h *h, int32_t on);
MCA_API int gen_pulsos_get_lazo(gen_pulsos_h *h, int32_t *on);

/* ---- las cuentas, sin hardware -------------------------------------------- */

/* El DECAE de una caida de tau muestras (8 ns cada una): round(2^16 e^(-1/tau)),
 * en 0..65535. Es `decae_para` del modelo. MCA_EINVAL si tau no es > 0. */
MCA_API int gen_pulsos_decae_para(double tau_muestras, uint32_t *decae);

/* La tau, en muestras, de un DECAE: -1 / ln(DECAE / 2^16). DECAE 0 da 0. */
MCA_API int gen_pulsos_tau(uint32_t decae, double *tau_muestras);

/* La Mq del polo-cero que cancela la caida: round(16 DECAE / (2^16 - DECAE)), la del
 * trapecio (trap_mq) y la del disparo con polo-cero. Exacta: en enteros. */
MCA_API int gen_pulsos_mq(uint32_t decae, uint32_t *mq);

/* El sigma del ruido, en cuentas: 147.8 / 2^sh. */
MCA_API int gen_pulsos_sigma_ruido(uint32_t sh, double *sigma);

/* Las 1024 amplitudes que sortean `valores` con probabilidades `pesos` (n de cada
 * uno) por CDF inversa: la tabla del modo amp_aleat. Es `tabla_cdf` del modelo, con
 * una diferencia: la CDF se normaliza por su ultimo valor y no por la suma de numpy
 * (que suma por pares). Las dos tablas difieren solo si un borde de la CDF cae a
 * menos de 1e-15 de algun (i + 0.5) / 1024. `n_tabla` tiene que ser 1024.
 * MCA_EINVAL si un peso es negativo o no finito, si suman 0, o si un valor
 * redondeado no entra en 14 bits. */
MCA_API int gen_pulsos_tabla_cdf(const double *valores, const double *pesos, uint32_t n,
                                 int16_t *tabla, uint32_t n_tabla);

#ifdef __cplusplus
}
#endif

#endif /* GEN_PULSOS_H */
