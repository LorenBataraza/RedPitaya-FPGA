#!/usr/bin/env python3
"""`buscar_picos`: encontrar los picos del espectro y medirles el FWHM.

Reemplaza al ajuste gaussiano sobre una región elegida a mano. La diferencia de
fondo es qué se le pide al usuario: antes, *dónde mirar*; ahora, nada.

Las pruebas usan espectros SINTÉTICOS con picos de posición y ancho conocidos,
así que hay verdad contra la que comparar — que es lo que no se puede hacer con
un espectro medido. Semilla fija: un test que falla una de cada veinte corridas
no es un test.
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import numpy as np                                                 # noqa: E402

from API.analisis import buscar_picos                              # noqa: E402

FWHM_POR_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))


def _espectro(n, picos, fondo=0.0, semilla=0):
    """Histograma de Poisson con gaussianas de (centro, sigma, altura)."""
    x = np.arange(n, dtype=float)
    limpio = np.full(n, float(fondo))
    for c, s, a in picos:
        limpio += a * np.exp(-0.5 * ((x - c) / s) ** 2)
    return np.random.default_rng(semilla).poisson(limpio).astype(np.uint32)


# =============================================================================
# Lo que tiene que encontrar
# =============================================================================

def test_encuentra_los_tres_picos_donde_estan():
    esp = _espectro(8192, [(1200, 18, 4000), (3000, 25, 9000),
                           (5600, 30, 2500)], fondo=40.0)
    picos = buscar_picos(esp)
    assert len(picos) == 3, f'encontró {len(picos)}: {[p["canal"] for p in picos]}'
    for hallado, esperado in zip(picos, (1200, 3000, 5600)):
        assert abs(hallado['canal'] - esperado) < 2.0, hallado


def test_el_fwhm_da_el_ancho_verdadero():
    """La razón de ser de la lista. Tolerancia del 3 %: el error medido está
    por debajo del 1 %, y el margen absorbe la estadística de conteo."""
    esp = _espectro(8192, [(1200, 18, 4000), (3000, 25, 9000),
                           (5600, 30, 2500)], fondo=40.0)
    for hallado, sigma in zip(buscar_picos(esp), (18, 25, 30)):
        teorico = FWHM_POR_SIGMA * sigma
        error = abs(hallado['fwhm'] - teorico) / teorico
        assert error < 0.03, (f"canal {hallado['canal']:.0f}: FWHM "
                              f"{hallado['fwhm']:.2f} contra {teorico:.2f}")


def test_devuelve_la_lista_ordenada_por_canal():
    """Por canal y NO por altura: con el orden por altura las filas saltan de
    lugar entre refrescos mientras la medida crece."""
    esp = _espectro(8192, [(1200, 18, 9000), (3000, 25, 2000),
                           (5600, 30, 5000)], fondo=40.0)
    canales = [p['canal'] for p in buscar_picos(esp)]
    assert canales == sorted(canales)


def test_un_pico_chico_sobre_un_fondo_alto_se_ve():
    """El criterio es la prominencia y no la altura: la altura sola no
    distingue un hombro real de un rizo sobre el fotopico."""
    esp = _espectro(4000, [(2000, 20, 150)], fondo=500.0)
    picos = buscar_picos(esp)
    assert len(picos) == 1, [p['canal'] for p in picos]
    assert abs(picos[0]['canal'] - 2000) < 3.0


def test_el_fondo_local_no_ensancha_el_pico():
    """El FWHM se mide desde la base local, no desde cero. Midiendo desde cero
    el mismo pico da sistemáticamente más ancho cuanto más alto el continuo."""
    anchos = []
    for fondo in (0.0, 2000.0):
        esp = _espectro(4000, [(2000, 20, 6000)], fondo=fondo)
        picos = buscar_picos(esp)
        assert len(picos) == 1, f'fondo {fondo}: {len(picos)} picos'
        anchos.append(picos[0]['fwhm'])
    teorico = FWHM_POR_SIGMA * 20
    for ancho in anchos:
        assert abs(ancho - teorico) / teorico < 0.05, anchos


# =============================================================================
# Lo que NO tiene que encontrar
# =============================================================================

def test_un_fondo_plano_no_tiene_picos():
    """El que motivó calibrar el umbral. Un espectro de puro ruido de Poisson
    devolvía una docena de picos, todos falsos: el corte RELATIVO no tiene
    defensa contra un espectro sin ningún pico, porque la fracción de una
    prominencia de ruido sigue siendo ruido."""
    for semilla in range(6):
        esp = _espectro(8192, [], fondo=1000.0, semilla=semilla)
        picos = buscar_picos(esp)
        assert picos == [], f'semilla {semilla}: {[p["canal"] for p in picos]}'


def test_un_espectro_vacio_no_rompe():
    assert buscar_picos(np.zeros(1000, dtype=np.uint32)) == []
    assert buscar_picos(np.zeros(0, dtype=np.uint32)) == []
    assert buscar_picos(np.array([5], dtype=np.uint32)) == []


def test_n_max_acota_la_lista():
    picos_sim = [(500 + 700 * i, 20, 5000) for i in range(10)]
    esp = _espectro(8192, picos_sim, fondo=30.0)
    assert len(buscar_picos(esp)) == 10
    acotado = buscar_picos(esp, n_max=4)
    assert len(acotado) == 4
    # Se queda con los MÁS PROMINENTES y después ordena por canal.
    assert [p['canal'] for p in acotado] == sorted(p['canal'] for p in acotado)


def test_subir_la_prominencia_deja_solo_los_grandes():
    esp = _espectro(8192, [(1200, 18, 400), (3000, 25, 9000)], fondo=30.0)
    assert len(buscar_picos(esp, prominencia_rel=0.01)) == 2
    assert len(buscar_picos(esp, prominencia_rel=0.20)) == 1


# =============================================================================
# El FWHM que no está definido
# =============================================================================

def test_dos_picos_que_no_se_separan_se_reportan_como_uno_ancho():
    """Y no como dos, que sería inventar una resolución que la medida no tiene.

    Con separación 90 y sigma 40 las dos gaussianas suman una curva de una sola
    joroba: el valle ni siquiera existe. Lo correcto es una entrada con el ancho
    de la mezcla — un FWHM muy mayor que el de los picos vecinos es la señal de
    que ahí hay un doblete sin resolver.
    """
    esp = _espectro(4000, [(2000, 40, 5000), (2090, 40, 5000)], fondo=10.0)
    picos = buscar_picos(esp)
    assert len(picos) == 1, [p['canal'] for p in picos]
    solo = FWHM_POR_SIGMA * 40
    assert picos[0]['fwhm'] > 1.5 * solo, (picos[0]['fwhm'], solo)
    assert 1990 < picos[0]['canal'] < 2100


def test_dos_picos_que_si_se_separan_se_reportan_como_dos():
    esp = _espectro(4000, [(1800, 20, 6000), (2200, 20, 6000)], fondo=10.0)
    picos = buscar_picos(esp)
    assert len(picos) == 2, [p['canal'] for p in picos]
    assert abs(picos[0]['canal'] - 1800) < 3
    assert abs(picos[1]['canal'] - 2200) < 3


def test_un_pico_contra_el_borde_del_eje_se_marca_truncado():
    """Medio pico contra el canal 0: no hay flanco izquierdo que cruzar."""
    esp = _espectro(2000, [(5, 25, 8000)], fondo=10.0)
    picos = buscar_picos(esp)
    if picos:                       # puede quedar por debajo del corte, y está bien
        assert picos[0]['truncado']
        assert np.isnan(picos[0]['fwhm'])


def test_el_ruido_de_la_ladera_no_trunca_un_pico_medible():
    """La regresión de la primera versión: cortar el paseo ante CUALQUIER subida
    parecía razonable y era incorrecto. En un histograma de Poisson la ladera
    sube y baja todo el tiempo, y un solo rizo declaraba truncado un pico
    perfectamente medible — el tercero de este espectro daba nan."""
    esp = _espectro(8192, [(1200, 18, 4000), (3000, 25, 9000),
                           (5600, 30, 2500)], fondo=40.0)
    picos = buscar_picos(esp)
    assert not any(p['truncado'] for p in picos), \
        [(p['canal'], p['truncado']) for p in picos]
    assert all(np.isfinite(p['fwhm']) for p in picos)


# =============================================================================
# Los otros campos
# =============================================================================

def test_la_resolucion_es_fwhm_sobre_centroide():
    esp = _espectro(8192, [(3000, 25, 9000)], fondo=20.0)
    p = buscar_picos(esp)[0]
    assert abs(p['resolucion_pct'] - 100.0 * p['fwhm'] / p['canal']) < 1e-9


def test_el_area_no_cuenta_el_fondo():
    """El área es neta: sobre un continuo alto, sumar en crudo daría un número
    dominado por el fondo y no por el pico."""
    sin_fondo = buscar_picos(_espectro(4000, [(2000, 20, 6000)], fondo=0.0))[0]
    con_fondo = buscar_picos(_espectro(4000, [(2000, 20, 6000)],
                                       fondo=2000.0))[0]
    assert abs(con_fondo['area'] - sin_fondo['area']) / sin_fondo['area'] < 0.15


def test_el_centroide_sale_de_las_cuentas_crudas_no_del_suavizado():
    """El máximo del suavizado sirve para ENCONTRAR el pico, no para ubicarlo:
    un centroide con resolución de canal entero no serviría para calibrar."""
    esp = _espectro(8192, [(3000.5, 25, 20000)], fondo=10.0)
    p = buscar_picos(esp)[0]
    assert p['canal'] != float(p['canal_pico'])
    assert abs(p['canal'] - 3000.5) < 1.0
