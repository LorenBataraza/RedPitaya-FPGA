#!/usr/bin/env python3
"""Las familias de forma de pulso del catálogo, en VOLTS contra MICROSEGUNDOS.

Corre en la PC, sin placa y sin Rigol.

QUÉ SE GRAFICA, EXACTAMENTE
---------------------------
La onda que se le cargó al generador, reconstruida con las MISMAS funciones
puras que usó la campaña (`rigol_dg4162.shaped_train_wave` con `n_pulses=1`).
No es un dibujo ni una aproximación: es el mismo array.

Lo que NO es: las ondas capturadas por el ADC. La campaña de INL vs forma
(`run_formas.py`) guardó centroides, ganancias, INL y factores de forma, pero no
guardó trazas — así que los pulsos capturados de estas seis familias no existen
en disco. Lo que sí se hace es **anotar sobre cada forma los números medidos en
la placa**, leídos de `formas_inl.npz`, y verificar que la traza graficada
reproduce el factor de forma medido (ver `verificar`). Si eso cierra, lo que se
ve acá es lo que se midió.

POR QUÉ IMPORTAN ESTAS FORMAS
-----------------------------
La campaña mide la misma curva de linealidad con las seis, todas con el MISMO
FWHM y la MISMA altura de pico. Así, cualquier diferencia en la amplitud
reportada es de la cadena de medición y no del estímulo. Y el `factor de forma`
—área/(pico·FWHM)— es **exactamente el cociente Q/pico** que el estudio de
apilamiento (`tests/pile-up/`) usa para discriminar eventos apilados: las dos
campañas miden la misma cantidad por motivos distintos.

    python3 graficar_formas.py                  # a datos/formas_<la más reciente>
    python3 graficar_formas.py --out DIR
    python3 graficar_formas.py --fwhm 4e-6      # otra consigna de ancho
    python3 graficar_formas.py --vpp 1.0
"""
import argparse
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                              # noqa: E402

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..'))          # software/

import rigol_dg4162 as rg                                    # noqa: E402

# --- paleta (docs/mca/figuras/figuras_resolucion.py) -------------------------
SUP    = '#fcfcfb'
TINTA  = '#0b0b0b'
TINTA2 = '#52514e'
MUDO   = '#898781'
GRILLA = '#e1e0d9'
AZUL   = '#2a78d6'
NARAN  = '#eb6834'
ROJO   = '#d03b3b'

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})

# Orden de presentación: de la más asimétrica a la más simétrica. No es
# estético — es el orden en que baja el factor de forma, que es lo que la
# campaña quiere mostrar.
FAMILIAS = ('cr', 'cr_rc', 'cr_rc4', 'triangular', 'trapezoidal', 'bipolar')

COLOR = {'cr': '#d03b3b', 'cr_rc': '#eb6834', 'cr_rc4': '#c9a227',
         'triangular': '#2e8b57', 'trapezoidal': '#2a78d6',
         'bipolar': '#7a5bbd'}

TITULO = {
    'cr':          'CR — una diferenciación',
    'cr_rc':       'CR-RC — semi-gaussiana (referencia)',
    'cr_rc4':      'CR-RC⁴ — cuatro integraciones',
    'triangular':  'triangular — ápice puntiagudo',
    'trapezoidal': 'trapezoidal — techo plano',
    'bipolar':     'bipolar (CR-RC-CR) — lóbulo negativo',
}

ADC_CNT_PER_V = 8192      # jumper LV
THR_CUENTAS   = 100       # cfg_thr de la campaña -> 12.2 mV


def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def construir(fam, fwhm_s, vpp):
    """Una forma de la familia `fam`, en volts contra segundos.

    `n_pulses=1` es lo que hace comparable el conjunto: fija la frecuencia de
    repetición y la tasa de muestreo del ARB, así que entre familias sólo cambia
    la forma. Es la misma llamada que hace la campaña.

    La altura sale de la convención de `load_arb(normalize=True)`: la forma ya
    viene normalizada al pico, así que el pulso mide `vpp/2` de alto — idéntico
    para las seis, por construcción.
    """
    wave, _, info = rg.shaped_train_wave(fam, fwhm_s, 2000.0, n_pulses=1)
    dt = info['dt_s']
    y = np.asarray(wave, dtype=float) * (vpp / 2.0)

    # recortar a la parte con señal, con un poco de aire a los costados
    umbral = 1e-4 * np.abs(y).max()
    nz = np.flatnonzero(np.abs(y) > umbral)
    aire = int(0.12 * (nz[-1] - nz[0] + 1)) + 4
    a, b = max(0, nz[0] - aire), min(y.size, nz[-1] + aire)
    t = (np.arange(a, b) - nz[0]) * dt
    return t, y[a:b], info


def factor_forma_calc(t, y, fwhm_nominal):
    """área positiva/(pico·FWHM) sobre la traza graficada.

    Es la MISMA definición de `shaped_train_wave` (rigol_dg4162.py:1292-1296), y
    hay dos detalles que hay que copiar o el número no significa nada:

      - el área es la **positiva**, no la neta. Es la única que ve el integrador
        del RTL, que recorta con `xc = max(x, 0)`. Con las bipolares la
        distinción es todo: su área neta es ~0 por construcción —para eso está
        la segunda diferenciación— así que la neta daría factor de forma nulo.
      - el FWHM es el **nominal**, el de la consigna, no el remedido sobre la
        traza muestreada. El remedido se chequea aparte.

    Es la misma cantidad que el cociente Q/pico del estudio de apilamiento.
    """
    dt = t[1] - t[0]
    pico = float(y.max())
    area_pos = float(y[y > 0].sum()) * dt
    return area_pos / (pico * float(fwhm_nominal)), pico


def fwhm_traza(t, y):
    """FWHM remedido sobre la traza graficada, en segundos."""
    return float(rg._fwhm_pts(y)) * float(t[1] - t[0])


def cargar_medidos(dir_datos):
    """Los números que salieron de la placa. Devuelve {} si no está el archivo."""
    p = os.path.join(dir_datos, 'formas_inl.npz')
    if not os.path.exists(p):
        return {}
    z = np.load(p, allow_pickle=True)
    out = {}
    for fam in z['familias']:
        fam = str(fam)
        d = dict(ok=bool(z[f'ok_{fam}']),
                 factor_forma=float(z[f'factor_forma_{fam}']),
                 area_pos=float(z[f'area_pos_frac_{fam}']))
        if d['ok']:
            d['inl_pct'] = float(z[f'inl_{fam}_pico'])
            d['gain'] = float(z[f'gain_{fam}_pico'])
        out[fam] = d
    return out


# =============================================================================
def fig_familias(formas, med, out, vpp):
    """2x3 paneles: una familia por panel, con sus números medidos encima."""
    # Sin sharex a propósito: las familias difieren en LARGO por un factor 8
    # (la cola de la CR llega a 25 µs, el trapecio termina en 3), así que un eje
    # común aplasta a las compactas contra el margen izquierdo y no se ve la
    # forma, que es lo único que esta figura tiene que mostrar. La comparación
    # directa de anchos la da `familias_superpuestas.png`.
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 6.6))
    thr_V = THR_CUENTAS / ADC_CNT_PER_V

    for ax, fam in zip(axes.ravel(), FAMILIAS):
        t, y, info = formas[fam]
        c = COLOR[fam]
        m = med.get(fam, {})
        us = t * 1e6

        ax.plot(us, y, color=c, lw=1.6)
        ax.axhline(0.0, color=MUDO, lw=0.8)
        ax.axhline(thr_V, color=ROJO, lw=0.9, ls=':')

        # marca del FWHM: la consigna de la campaña, igual para las seis
        pico = y.max()
        cruces = np.flatnonzero(y >= 0.5 * pico)
        ax.annotate('', xy=(us[cruces[0]], 0.5 * pico),
                    xytext=(us[cruces[-1]], 0.5 * pico),
                    arrowprops=dict(arrowstyle='<->', color=TINTA2, lw=1.0))
        ax.text(0.5 * (us[cruces[0]] + us[cruces[-1]]), 0.53 * pico,
                f'FWHM {1e6*fwhm_traza(t, y):.2f} µs', ha='center', va='bottom',
                fontsize=8, color=TINTA2,
                bbox=dict(fc=SUP, ec='none', pad=1.5))

        if fam == 'bipolar':
            neg = y < 0
            ax.fill_between(us, 0, y, where=neg, color=c, alpha=.20, lw=0)

        # anotación: lo MEDIDO en la placa
        ff = m.get('factor_forma')
        txt = f'factor de forma  {ff:.3f}' if ff else ''
        if m.get('ok'):
            txt += f'\nINL {m["inl_pct"]:.2f} % FS'
            txt += f'\nganancia {m["gain"]:.0f} ch/Vpp'
        elif m:
            txt += (f'\nárea positiva {100*m["area_pos"]:.0f} %'
                    f'\nNO MEDIBLE: 50 % cerró por maxlen')
        ax.text(0.97, 0.94, txt, transform=ax.transAxes, ha='right', va='top',
                fontsize=8, color=TINTA2 if m.get('ok') else ROJO,
                linespacing=1.35)

        ax.set_title(TITULO[fam], loc='left', color=TINTA2, fontsize=9.5)
        _limpiar(ax)

    # con autoescala por panel, cada uno lleva su propio par de etiquetas
    for ax in axes.ravel():
        ax.set_xlabel('tiempo [µs]')
    for ax in axes[:, 0]:
        ax.set_ylabel('tensión [V]')

    fig.suptitle(f'Familias de forma de pulso — mismo FWHM y misma altura de '
                 f'pico ({vpp/2:.2f} V).  Punteado rojo: umbral del MCA '
                 f'({1e3*thr_V:.1f} mV).',
                 x=0.008, ha='left', fontsize=10, color=TINTA2)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    p = os.path.join(out, 'familias.png')
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'  familias.png')


def fig_superpuestas(formas, med, out, vpp, fwhm_s):
    """Las seis juntas, y las seis como las ve el integrador del RTL."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.4), sharex=True)
    thr_V = THR_CUENTAS / ADC_CNT_PER_V

    for fam in FAMILIAS:
        t, y, _ = formas[fam]
        ff = med.get(fam, {}).get('factor_forma')
        et = f'{fam}' + (f'  ({ff:.3f})' if ff else '')
        a1.plot(t * 1e6, y, color=COLOR[fam], lw=1.5, label=et)
        # lo que ve el acumulador de carga: xc = max(x, 0)
        a2.plot(t * 1e6, np.maximum(y, 0.0), color=COLOR[fam], lw=1.5)

    for ax in (a1, a2):
        ax.axhline(0.0, color=MUDO, lw=0.8)
        ax.axhline(thr_V, color=ROJO, lw=0.9, ls=':')
        ax.set_xlabel('tiempo [µs]')
        ax.set_ylabel('tensión [V]')
        # 8 FWHM: cubre el lóbulo negativo de la bipolar y la cola de la CR
        # hasta bien debajo del umbral. Más allá el eje lo domina la cola y las
        # formas compactas quedan ilegibles.
        ax.set_xlim(-0.5e6 * fwhm_s, 8e6 * fwhm_s)
        _limpiar(ax)

    a1.set_title('(a) el estímulo — sólo cambia la forma',
                 loc='left', color=TINTA2)
    a2.set_title('(b) lo que integra el RTL: xc = max(x, 0)',
                 loc='left', color=TINTA2)
    a1.legend(fontsize=8, title='familia (factor de forma)',
              title_fontsize=8, loc='upper right')

    # señalar el lóbulo que se pierde
    t, y, _ = formas['bipolar']
    neg = y < 0
    if neg.any():
        a1.fill_between(t * 1e6, 0, y, where=neg, color=COLOR['bipolar'],
                        alpha=.22, lw=0)
        i = int(np.argmin(y))
        a1.annotate('la bipolar pierde este lóbulo\nal recortar (área 50 %)',
                    xy=(t[i] * 1e6, y[i]),
                    xytext=(t[i] * 1e6 + 2.2e6 * fwhm_s, y[i] * 0.80),
                    fontsize=8, color=ROJO, va='center',
                    arrowprops=dict(arrowstyle='->', color=ROJO, lw=1.0))

    fig.tight_layout()
    p = os.path.join(out, 'familias_superpuestas.png')
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'  familias_superpuestas.png')


# =============================================================================
def verificar(formas, med, fwhm_s):
    """El chequeo que hace que las figuras signifiquen algo.

    Dos cosas, y las dos tienen que cerrar:
      1. el FWHM de la traza graficada sigue la consigna (el eje de tiempo está
         bien escalado y no es decorativo);
      2. el factor de forma recalculado sobre esa traza coincide con el que se
         MIDIÓ en la placa. Si no, lo que se grafica no es lo que se midió.
    """
    print(f'\n  {"familia":<12} {"FWHM [µs]":>10} {"ff calc":>9} '
          f'{"ff medido":>10} {"dif":>8}')
    peor_ff = peor_fwhm = 0.0
    for fam in FAMILIAS:
        t, y, info = formas[fam]
        ff, _ = factor_forma_calc(t, y, fwhm_s)
        fwhm = fwhm_traza(t, y)
        e_fwhm = abs(fwhm - fwhm_s) / fwhm_s
        peor_fwhm = max(peor_fwhm, e_fwhm)
        ffm = med.get(fam, {}).get('factor_forma')
        if ffm:
            d = abs(ff - ffm) / ffm
            peor_ff = max(peor_ff, d)
            print(f'  {fam:<12} {1e6*fwhm:10.3f} {ff:9.4f} {ffm:10.4f} '
                  f'{100*d:7.2f} %')
        else:
            print(f'  {fam:<12} {1e6*fwhm:10.3f} {ff:9.4f} {"—":>10} {"—":>8}')

    # El FWHM remedido admite un poco más de tolerancia que el factor de forma
    # por una razón concreta y no por comodidad: la triangular tiene el ápice
    # puntiagudo, así que al muestrearla en la grilla del ARB el máximo cae
    # entre dos muestras y el ancho a media altura sale ~0.7 % más grande. Es
    # cuantización del generador, y es justamente el efecto que la campaña
    # quería aislar comparándola contra el trapecio.
    ok_f = peor_fwhm < 0.015
    print(f'\n  [{"PASS" if ok_f else "FAIL"}] el FWHM graficado sigue la '
          f'consigna de {1e6*fwhm_s:g} µs (peor desvío {100*peor_fwhm:.2f} %)')

    # El factor de forma medido se tomó con la consigna de la campaña (2 µs), y
    # el de la TRIANGULAR depende de ella: su valor exacto es 1.0000, pero al
    # muestrear el ápice en la grilla del ARB sale inflado, y cuánto depende de
    # cuántas muestras entran en el ancho (65 a 2 µs, 131 a 4 µs). O sea que a
    # otro ancho la comparación contra el número medido deja de ser válida —no
    # porque el gráfico esté mal, sino porque el estímulo es otro—. Se informa
    # igual, pero sólo se exige coincidencia a la consigna de la campaña.
    campana = abs(fwhm_s - 2e-6) < 1e-9
    ok_ff = peor_ff < 0.005
    if campana:
        print(f'  [{"PASS" if ok_ff else "FAIL"}] el factor de forma graficado '
              f'= el medido en placa (peor desvío {100*peor_ff:.2f} %)')
    else:
        ok_ff = True
        print(f'  [nota] a {1e6*fwhm_s:g} µs el ARB remuestrea el ápice, así que '
              f'el factor de forma\n         de la triangular se aparta del '
              f'medido a 2 µs (desvío {100*peor_ff:.2f} %). Es esperado.')
    return ok_f and ok_ff


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=None,
                    help='dónde dejar los PNG (por defecto, el dir de la campaña)')
    ap.add_argument('--datos', default=None,
                    help='dir con formas_inl.npz (por defecto, el más reciente)')
    ap.add_argument('--fwhm', type=float, default=2e-6, help='FWHM en segundos')
    ap.add_argument('--vpp', type=float, default=0.5,
                    help='amplitud pico a pico de la consigna del generador')
    a = ap.parse_args()

    datos = a.datos
    if datos is None:
        c = sorted(glob.glob(os.path.join(_AQUI, '..', '..', 'datos',
                                          'formas_*')))
        datos = c[-1] if c else None
    med = cargar_medidos(datos) if datos else {}
    out = a.out or datos or _AQUI
    os.makedirs(out, exist_ok=True)

    print(f'=== familias de forma ===')
    print(f'consigna: FWHM {1e6*a.fwhm:g} µs, {a.vpp} Vpp '
          f'(altura de pico {a.vpp/2:.3f} V)')
    print(f'medidos:  {os.path.relpath(datos) if med else "(no encontrados)"}')

    formas = {f: construir(f, a.fwhm, a.vpp) for f in FAMILIAS}
    ok = verificar(formas, med, a.fwhm)

    print(f'\nfiguras en {os.path.relpath(out)}:')
    fig_familias(formas, med, out, a.vpp)
    fig_superpuestas(formas, med, out, a.vpp, a.fwhm)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
