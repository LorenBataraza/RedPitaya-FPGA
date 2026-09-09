#!/usr/bin/env python3
"""(R) Enciende o apaga el tren de pulsos del Rigol y se va. Corre EN LA PITAYA.

Las campañas manejan el generador dentro de su propia corrida y lo apagan al
terminar. Esto es para cuando el estímulo tiene que sobrevivir al proceso que
lo prendió: mirar el espectro crecer en la GUI, dejar corriendo una medida
larga, o depurar umbrales a mano.

    python3 campanas/estimulo.py on --rate 2000 --amp 0.6
    python3 campanas/estimulo.py on --poisson --rate 30000
    python3 campanas/estimulo.py off

El ancho del pulso y la convención de offset son los de la campaña validada
(`campanas/testbench_mca.py`): tren unipolar positivo, base en amp/2 y pico en
amp, o sea altura de pulso = amp/2.
"""

import argparse
import math
import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import API.rigol_dg4162 as rg                                      # noqa: E402

ANCHO_PULSO_S = 2e-6


def _aplicar(gen, ch, onda, freq, amp_vpp, normalize=True):
    """Sube la forma, la aplica, enciende la salida y ESPERA A QUE ESTÉ.

    El `time.sleep(0.3)` que había acá no alcanza: cargar un arbitrario de
    16384 puntos son decenas de comandos SCPI, y el instrumento los procesa a
    su ritmo. Medido en la placa, la salida seguía emitiendo la forma ANTERIOR
    cuando el proceso ya había terminado — el síntoma es una tasa medida que da
    exactamente la del estímulo previo, y es intermitente, que es lo peor.

    El reemplazo no es un sleep más largo sino un handshake: SCPI es
    secuencial, así que la respuesta a una consulta no llega hasta que el
    instrumento terminó de procesar todo lo anterior. Preguntar la frecuencia
    bloquea hasta que el `APPLy` se aplicó de verdad, y de paso la verifica.
    """
    gen.load_arb(onda, ch=ch, normalize=normalize)
    gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
    gen.output(ch, True)

    leida = float(gen.query(f':SOURce{ch}:FREQuency?'))
    if not math.isclose(leida, freq, rel_tol=1e-3):
        raise RuntimeError(
            f'el generador quedó en {leida:g} Hz y se pidió {freq:g} Hz: la '
            f'forma no se aplicó. Revisá la cola de errores SCPI '
            f'(gen.clear_errors()).')
    return leida


def encender(gen, ch, rate_hz, amp_vpp, ancho_s=ANCHO_PULSO_S):
    onda, freq, info = rg.pulse_train_wave(ancho_s, rate_hz)
    _aplicar(gen, ch, onda, freq, amp_vpp)
    return freq, info


def encender_dos_poblaciones(gen, ch, rate_hz, amp_vpp, ancho_s=ANCHO_PULSO_S,
                             taus=(1.0, 3.0)):
    """Dos poblaciones de MISMA amplitud y distinta cola.

    Es el estímulo que hace medible el eje de forma: las dos caen en el mismo
    canal del espectro 1D y sólo se separan en el mapa 2D por Q_cola/Q_total.
    Sin esto la FOM no tiene dos poblaciones que comparar.

    Va por `pulse_train_wave(tau_choices=...)` y NO por `two_population_wave`,
    que no controla el ancho: ahí cada pulso ocupa su slot entero, o sea 1/tasa
    (333 us a 3 kHz). Con `maxlen` en 4096 muestras (32.8 us) el MCA cierra
    TODOS los pulsos por largo y los cuenta como apilamiento — medido en placa:
    74676 apilados, 0 aceptados.

    `taus` son multiplicadores de la cola de referencia; (1, 3) es el par
    caracterizado, que separa 0.36 en Q_cola/Q_total.
    """
    # `pulse_train_wave` mete tantos pulsos por forma como permita el ciclo de
    # trabajo, y con colas variables exige al menos dos (si no, la "variedad"
    # sería un único valor repetido). n_pulsos ~ 0.5e-3 * tasa con pulsos de
    # 2 us, así que por debajo de ~4 kHz no hay dos poblaciones posibles.
    onda, freq, info = rg.pulse_train_wave(ancho_s, rate_hz, tau_choices=taus)
    _aplicar(gen, ch, onda, freq, amp_vpp)
    return freq, info


def eventos_por_ciclo_max(rate_hz, ancho_s, t_rise_frac=0.25,
                          min_rise_pts=rg.MIN_RISE_PTS,
                          n_pts_max=rg.ARB_MAX_POINTS):
    """Cuántos eventos por ciclo admite `poisson_train_wave` a esta tasa.

    Es la misma cota que la función levanta como ValueError, despejada. Se
    calcula acá para elegir un default que entre, en vez de fallar y mandar al
    usuario a adivinar el número.

    De dónde sale: el ciclo dura `n_eventos/tasa` y se reparte en 16384 puntos,
    así que el paso es `dt = n_eventos/(tasa*16384)`. El flanco de subida ocupa
    `t_rise_frac*ancho/dt` puntos y tiene que ser >= `min_rise_pts`. Despejando:

        n_eventos <= t_rise_frac * ancho * tasa * 16384 / min_rise_pts

    O sea que es LINEAL en la tasa: con pulsos de 2 us hay 6 eventos por ciclo
    a 3 kHz y 61 a 30 kHz. Esa es la restricción real del método — ver
    `encender_poisson`.
    """
    return int(t_rise_frac * ancho_s * rate_hz * n_pts_max / min_rise_pts)


def encender_poisson(gen, ch, rate_hz, amp_vpp, ancho_s=ANCHO_PULSO_S,
                     n_eventos=None, semilla=0, headroom=3.0):
    """Arribos de POISSON en vez de un tren periódico.

    Por qué importa: con arribos deterministas y un solo servidor sin cola
    (K=1) el MCA no pierde NADA mientras el período supere el tiempo de
    servicio, y recién ahí cae en escalones. La eficiencia del 99 % a 2 kHz es
    un artefacto del estímulo. Una fuente radiactiva entrega Poisson, y ahí se
    pierde `rho/(1+rho)` a CUALQUIER tasa. Es el estímulo que hace que el
    apilamiento y el tiempo muerto de la GUI se parezcan a los de una medida
    real.

    LO QUE NO ES: la forma arbitraria **se repite** cada `n_eventos/tasa`. Los
    arribos son Poisson DENTRO del ciclo (posiciones uniformes i.i.d. sobre el
    círculo, que es la construcción equivalente y no deja costura), pero el
    patrón vuelve a empezar. Para el espectro, el apilamiento y las pérdidas da
    igual —son estadísticas de primer y segundo orden dentro del ciclo—; para
    cualquier cosa que mire correlaciones a escalas más largas que el ciclo, no.
    Recargar con otra semilla entre trozos es lo que hace `apply_poisson_train`
    en las campañas.

    Y el ciclo es corto donde uno más querría Poisson: a tasas bajas.
    `eventos_por_ciclo_max` es lineal en la tasa, así que con pulsos de 2 us a
    3 kHz entran 6 eventos por ciclo (2 ms de patrón) y a 30 kHz entran 61
    (2 ms también — el ciclo dura lo mismo, lo que crece es la estadística de
    adentro). Por debajo de ~1 kHz no queda margen ni para un evento y hay que
    ensanchar el pulso.

    `headroom` es el factor por el que se divide la forma: fija la altura del
    pulso individual para que el fotopico NO se mueva con la semilla. Los
    apilamientos de más de `headroom` pulsos se recortan, y eso se reporta.
    """
    n_max = eventos_por_ciclo_max(rate_hz, ancho_s)
    if n_max < 1:
        raise ValueError(
            f'a {rate_hz:g} Hz con pulsos de {ancho_s*1e6:g} us no entra ni un '
            f'evento por ciclo de Poisson (hace falta ancho*tasa >= '
            f'{rg.MIN_RISE_PTS / (0.25 * rg.ARB_MAX_POINTS):.4g}). Subí la tasa '
            f'a >= {rg.MIN_RISE_PTS / (0.25 * rg.ARB_MAX_POINTS) / ancho_s:.0f} '
            f'Hz o ensanchá el pulso con --ancho.')
    if n_eventos is None:
        n_eventos = min(64, n_max)
    elif n_eventos > n_max:
        raise ValueError(
            f'--eventos {n_eventos} no entra: a {rate_hz:g} Hz con pulsos de '
            f'{ancho_s*1e6:g} us el máximo es {n_max}.')

    onda, freq, info = rg.poisson_train_wave(
        rate_hz, ancho_s, n_events=n_eventos, headroom=headroom, seed=semilla)
    # normalize=False a propósito: `poisson_train_wave` ya escaló por
    # `headroom`, y volver a normalizar por el máximo devolvería la dependencia
    # con la semilla que el headroom existe para sacar.
    _aplicar(gen, ch, onda, freq, amp_vpp, normalize=False)
    return freq, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('accion', choices=('on', 'off'))
    ap.add_argument('--rate', type=float, default=2000.0, help='pulsos/s')
    ap.add_argument('--amp', type=float, default=0.6, help='Vpp')
    ap.add_argument('--ancho', type=float, default=ANCHO_PULSO_S,
                    help='FWHM del pulso, s')
    ap.add_argument('--ch', type=int, default=1, help='canal del Rigol')
    ap.add_argument('--dos-poblaciones', action='store_true',
                    help='misma amplitud, dos colas: separa en el mapa 2D')
    ap.add_argument('--taus', type=float, nargs=2, default=(1.0, 3.0),
                    metavar=('TAU_A', 'TAU_B'),
                    help='multiplicadores de cola de las dos poblaciones')
    ap.add_argument('--poisson', action='store_true',
                    help='arribos exponenciales en vez de un tren periódico')
    ap.add_argument('--eventos', type=int, default=None,
                    help='eventos medios por ciclo de Poisson (default: el '
                         'máximo que entre, hasta 64)')
    ap.add_argument('--semilla', type=int, default=0,
                    help='semilla de la realización de Poisson')
    a = ap.parse_args(argv)

    if a.poisson and a.dos_poblaciones:
        ap.error('--poisson y --dos-poblaciones son estímulos distintos: el '
                 'primero varía el TIEMPO de arribo y el segundo la FORMA. '
                 'Para los dos a la vez hace falta pasar tau_choices a '
                 'poisson_train_wave; todavía no está expuesto acá.')

    gen = rg.RigolDG4162.usb()
    try:
        print(gen.id)
        if a.accion == 'off':
            gen.output(a.ch, False)
            print(f'  salida {a.ch} apagada')
            return 0
        # `reset` deja el instrumento en un estado conocido; sin esto, restos de
        # una corrida anterior (burst, modulación) se mezclan con lo que se pide.
        gen.reset()
        if a.poisson:
            freq, info = encender_poisson(gen, a.ch, a.rate, a.amp, a.ancho,
                                          n_eventos=a.eventos,
                                          semilla=a.semilla)
            print(f'  POISSON: {info["n_events"]} eventos en un ciclo de '
                  f'{info["T_ciclo_s"]*1e3:.2f} ms -> {info["rate_real"]:.0f} '
                  f'ev/s (se pidió {a.rate:g})')
            print(f'  apilamiento {100*info["frac_pileup"]:.1f} % medido, '
                  f'{100*info["frac_pileup_teo"]:.1f} % teórico; '
                  f'recorte {100*info["frac_clip"]:.2f} %')
            print(f'  paso del DAC {info["dt_s"]*1e9:.0f} ns = jitter del '
                  f'arribo; el patrón se REPITE cada {info["T_ciclo_s"]*1e3:.2f} ms')
        elif a.dos_poblaciones:
            freq, info = encender_dos_poblaciones(gen, a.ch, a.rate, a.amp,
                                                  a.ancho, tuple(a.taus))
            print(f'  DOS poblaciones (cola x{a.taus[0]:g} y x{a.taus[1]:g}), '
                  f'{info["n_pulses"]} pulsos/forma de {a.ancho*1e6:g} us, '
                  f'repetición {freq:g} Hz -> {a.rate:g} pulsos/s')
        else:
            freq, info = encender(gen, a.ch, a.rate, a.amp, a.ancho)
            print(f'  {info["n_pulses"]} pulso(s)/forma de {a.ancho * 1e6:g} us, '
                  f'repetición {freq:g} Hz -> {a.rate:g} pulsos/s')
        # La altura del pulso NO es amp/2 en Poisson: la forma se escaló por
        # `headroom` para dejar lugar a los apilamientos sin recortarlos, así
        # que un pulso solo llega a amp/2 * amp_single_rel. Reportarlo mal
        # manda a buscar el fotopico donde no está.
        altura = a.amp / 2 * info.get('amp_single_rel', 1.0)
        print(f'  {a.amp:g} Vpp con offset {a.amp / 2:g} V '
              f'(altura de pulso {altura:.4g} V, ~{altura * 8192:.0f} cuentas)')
        print(f'  salida {a.ch} ENCENDIDA — apagar con: '
              f'python3 campanas/estimulo.py off')
        return 0
    finally:
        gen.close()


if __name__ == '__main__':
    sys.exit(main())
