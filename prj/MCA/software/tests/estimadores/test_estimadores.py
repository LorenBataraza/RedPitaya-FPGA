#!/usr/bin/env python3
"""Tests de los estimadores. Corren en la PC, sin placa y sin datos.

El test que importa es el PRIMERO: la replica en NumPy tiene que dar los
MISMOS numeros exactos que ya verifica el testbench de RTL
(sim/tb_mca_pulse_feature.sv) sobre los mismos estimulos. Si eso pasa, la
replica esta midiendo lo mismo que el hardware y el resto del analisis
offline es confiable. Si no, no.

    python3 test_estimadores.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import estimadores as es

FAILS = []


def check(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(name)


def checkv(name, got, exp):
    check(name, got == exp, f'(obtenido {got}, esperado {exp})')


def rect(v, n, lo=0, pre=3, post=3):
    """Pulso rectangular de n muestras de valor v, con base a los costados."""
    return np.array([lo] * pre + [v] * n + [lo] * post, dtype=np.int64)


# ------------------------------------------------------------------ 1

def test_contra_el_testbench_de_rtl():
    print('\n[1] la replica reproduce los valores EXACTOS de tb_mca_pulse_feature.sv')

    # Escenario 1 del TB (:127-143): 20 muestras de 500 sobre base 0,
    # thr=100, hyst=50, tail_dly=1  ->  q_tot=10000, q_tail=9500, psd=60
    ev = es.segmentar_rtl(rect(500, 20), baseline=0, thr=100, hyst=50,
                          maxlen=1000, tail_dly=1)
    check('un solo evento', len(ev) == 1, f'({len(ev)})')
    e = ev[0]
    checkv('rect: q_tot = 20*500', e.q_tot, 10000)
    checkv('rect: q_tail = 19*500', e.q_tail, 9500)
    checkv('rect: amplitud de pico', e.pico, 500)
    checkv('rect: cerro por histeresis', e.motivo, 'hyst')
    psd, ok = es.psd_rtl(e.q_tail, e.q_tot, psd_aw=6)
    checkv('rect: psd = 60', psd, 60)
    check('rect: psd valido', ok)

    # Escenario 7 del TB (:207-217): base fija 200, pulso de 500 -> x=300
    ev = es.segmentar_rtl(rect(500, 20, lo=200), baseline=200, thr=100,
                          hyst=50, maxlen=1000, tail_dly=1)
    checkv('base=200: q_tot = 20*300', ev[0].q_tot, 6000)
    checkv('base=200: amp = 300', ev[0].pico, 300)

    # Escenario 3 del TB (:158-162): bajo umbral -> ningun evento
    ev = es.segmentar_rtl(rect(50, 20), baseline=0, thr=100, hyst=50,
                          maxlen=1000, tail_dly=1)
    checkv('bajo umbral: sin eventos', len(ev), 0)

    # Escenario 5 del TB (:187-193): apilamiento, cierra por maxlen
    ev = es.segmentar_rtl(rect(500, 30), baseline=0, thr=100, hyst=50,
                          maxlen=10, tail_dly=1)
    checkv('apilamiento: un evento', len(ev), 1)
    checkv('apilamiento: cerro por maxlen', ev[0].motivo, 'maxlen')

    # Escenario 10 del TB (:255-265): q_tail == q_tot -> psd invalido
    psd, ok = es.psd_rtl(5000, 5000, psd_aw=6)
    check('q_tail==q_tot: psd invalidado (no envuelve a 0)', not ok)
    psd, ok = es.psd_rtl(0, 0, psd_aw=6)
    check('q_tot=0: psd invalidado', not ok)


# ------------------------------------------------------------------ 2

def test_semantica_fina():
    print('\n[2] los detalles del RTL que costaron bugs')

    # La muestra que CIERRA no se acumula (TB :99-105).
    ev = es.segmentar_rtl(np.array([0, 0, 500, 500, 40, 0]), thr=100, hyst=50,
                          maxlen=100, tail_dly=1)
    checkv('la muestra de cierre no se acumula', ev[0].q_tot, 1000)

    # Clamp a >=0 antes de acumular: un undershoot NO resta de q_tot (:133).
    ev = es.segmentar_rtl(np.array([0, 0, 500, 500, -300, 40, 0]), thr=100,
                          hyst=50, maxlen=100, tail_dly=1)
    checkv('undershoot no resta de q_tot', ev[0].q_tot, 1000)

    # Pico ESTRICTO: en una meseta gana la PRIMERA ocurrencia (:319).
    ev = es.segmentar_rtl(np.array([0, 0, 500, 500, 500, 40, 0]), thr=100,
                          hyst=50, maxlen=100, tail_dly=1)
    checkv('meseta: t_pico es la PRIMERA ocurrencia', ev[0].t_pico, 0)

    # ...y si sube despues, el pico se actualiza.
    ev = es.segmentar_rtl(np.array([0, 0, 300, 700, 500, 40, 0]), thr=100,
                          hyst=50, maxlen=100, tail_dly=1)
    checkv('pico posterior actualiza t_pico', ev[0].t_pico, 1)
    checkv('pico posterior actualiza el valor', ev[0].pico, 700)

    # Re-armado: dos pulsos separados son dos eventos.
    x = np.concatenate([rect(500, 10), rect(300, 10)])
    ev = es.segmentar_rtl(x, thr=100, hyst=50, maxlen=100, tail_dly=1)
    checkv('dos pulsos separados: dos eventos', len(ev), 2)
    checkv('el segundo tiene su propia amplitud', ev[1].pico, 300)

    # Truncado: el array se acaba con el pulso abierto.
    ev = es.segmentar_rtl(np.array([0, 0, 500, 500, 500]), thr=100, hyst=50,
                          maxlen=100, tail_dly=1)
    checkv('pulso sin cerrar -> fin_ventana', ev[0].motivo, 'fin_ventana')
    check('pulso sin cerrar -> cerrado=False', not ev[0].cerrado)


# ------------------------------------------------------------------ 3

def test_compuertas_fijas():
    print('\n[3] compuertas de largo fijo')

    # Rectangulo de 20 muestras: compuerta larga de 30 toma las 20;
    # compuerta corta de 5 toma 5.
    g = es.integral_gates(rect(500, 20, post=20), thr=100, hyst=50,
                          corta=5, larga=30)
    checkv('un disparo', len(g), 1)
    checkv('compuerta larga (30) toma las 20 muestras', g[0]['q_tot'], 10000)
    checkv('compuerta corta (5) toma 5 muestras', g[0]['q_corta'], 2500)
    checkv('la cola es la diferencia', g[0]['q_tail'], 7500)

    # EL PUNTO DE TODO ESTO: con una COLA EXPONENCIAL el cruce de cierre cae en
    # una pendiente suave, asi que el ruido corre el punto donde la ventana se
    # cierra y el largo tiembla. Es el candidato (a) del diagnostico. Con un
    # rectangulo no se ve (el flanco de bajada es instantaneo): hay que usar la
    # forma real.
    t = np.arange(300, dtype=float)
    base = np.where(t < 20, 0.0, 500 * np.exp(-(t - 20) / 60.0))
    rng = np.random.default_rng(0)
    largos, cargas = [], []
    for _ in range(200):
        x = (base + rng.normal(0, 8, base.size)).astype(np.int64)
        ev = es.segmentar_rtl(x, thr=100, hyst=50, maxlen=1000, tail_dly=1)
        if ev and ev[0].cerrado:
            largos.append(ev[0].largo)
            cargas.append(ev[0].q_tot)
    check('la ventana por histeresis varia de largo con el ruido',
          np.std(largos) > 0.5, f'(sigma {np.std(largos):.2f} muestras)')

    # Y ese temblor se traduce en varianza de la carga. La compuerta fija, no.
    cargas_fijo = []
    for _ in range(200):
        x = (base + rng.normal(0, 8, base.size)).astype(np.int64)
        g = es.integral_gates(x, thr=100, hyst=50, corta=30, larga=200)
        if g and not g[0]['truncado']:
            cargas_fijo.append(g[0]['q_tot'])
    r_h = es.resolucion(cargas)
    r_f = es.resolucion(cargas_fijo)
    check('la compuerta fija da MENOS dispersion de carga que la histeresis',
          r_f['res_pct'] < r_h['res_pct'],
          f'(fija {r_f["res_pct"]:.3f}% contra histeresis {r_h["res_pct"]:.3f}%)')


# ------------------------------------------------------------------ 4

def test_trapecio():
    print('\n[4] conformado trapezoidal (Jordanov-Knoll)')

    # Entrada canonica: escalon con cola exponencial de constante tau.
    n, tau, A = 4000, 200.0, 1000.0
    t = np.arange(n, dtype=float)
    v = np.where(t < 500, 0.0, A * np.exp(-(t - 500) / tau))

    k, m = 100, 50
    M = tau                       # constante correcta -> cancela el polo
    s = es.trapecio(v, k, m, M)

    # La meseta va de k a k+m despues del escalon.
    i0 = 500
    meseta = s[i0 + k + 5: i0 + k + m - 5]
    check('la meseta es plana con M correcto',
          np.std(meseta) / np.mean(meseta) < 0.01,
          f'(ondulacion {100*np.std(meseta)/np.mean(meseta):.3f}%)')

    # Altura teorica de la meseta para una exponencial: k*M*A (con M en
    # muestras y la recursion tal como esta escrita).
    alt = es.altura_meseta(s, i0, k, m)
    check('la altura de la meseta es proporcional a la amplitud', alt > 0,
          f'({alt:.3e})')
    s2 = es.trapecio(2 * v, k, m, M)
    alt2 = es.altura_meseta(s2, i0, k, m)
    check('doble amplitud -> doble meseta', abs(alt2 / alt - 2.0) < 1e-6,
          f'(razon {alt2/alt:.6f})')

    # LA TRAMPA: con una entrada REAL la carga no se colecta instantaneamente,
    # y la meseta solo existe si m > tiempo de coleccion. Con m menor no hay
    # meseta y lo que se muestrea es el flanco: da un numero, y es malo.
    # (Este test existe porque el analisis daba 1.6 % hasta que se corrigio;
    # con la meseta bien ubicada da 0.21 %.)
    check('sin coleccion instantanea, m > t_col tiene meseta',
          es.meseta_ventana(i_disparo=13, i_pico=101, k=128, m=160) is not None)
    check('m <= t_col: NO hay meseta (y hay que decirlo, no devolver basura)',
          es.meseta_ventana(i_disparo=13, i_pico=101, k=128, m=64) is None)
    checkv('la meseta arranca en i_pico+k, no en i_disparo+k',
           es.meseta_ventana(13, 101, 128, 160)[0], 101 + 128)
    checkv('y termina en i_disparo+k+m',
           es.meseta_ventana(13, 101, 128, 160)[1], 13 + 128 + 160)
    check('altura_meseta devuelve nan si no hay meseta',
          np.isnan(es.altura_meseta(s, 13, 128, 64, i_pico=101)))

    # Con M MAL la salida no vuelve a cero: queda un residuo (o se dispara).
    s_mal = es.trapecio(v, k, m, M=tau / 4)
    cola_ok  = abs(s[i0 + 3 * (k + m):][:200].mean())
    cola_mal = abs(s_mal[i0 + 3 * (k + m):][:200].mean())
    check('con M correcto la salida vuelve cerca de cero',
          cola_ok < 0.02 * alt, f'({cola_ok:.3e} contra meseta {alt:.3e})')
    check('con M mal queda residuo (no hay cancelacion de polo)',
          cola_mal > 5 * max(cola_ok, 1e-12),
          f'({cola_mal:.3e} contra {cola_ok:.3e})')


# ------------------------------------------------------------------ 5

def test_resolucion():
    print('\n[5] la metrica de resolucion')
    rng = np.random.default_rng(1)
    v = rng.normal(1000, 10, 20000)          # 1% sigma -> 2.355% FWHM
    r = es.resolucion(v)
    check('recupera la resolucion de una gaussiana conocida',
          abs(r['res_pct'] - 2.355) < 0.1, f'({r["res_pct"]:.3f}%, esperado 2.355%)')
    check('media correcta', abs(r['media'] - 1000) < 1)


def main():
    test_contra_el_testbench_de_rtl()
    test_semantica_fina()
    test_compuertas_fijas()
    test_trapecio()
    test_resolucion()
    print('\nRESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
