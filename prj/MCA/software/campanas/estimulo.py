#!/usr/bin/env python3
"""(R) Enciende o apaga el tren de pulsos del Rigol y se va. Corre EN LA PITAYA.

Las campañas manejan el generador dentro de su propia corrida y lo apagan al
terminar. Esto es para cuando el estímulo tiene que sobrevivir al proceso que
lo prendió: mirar el espectro crecer en la GUI, dejar corriendo una medida
larga, o depurar umbrales a mano.

    python3 campanas/estimulo.py on --rate 2000 --amp 0.6
    python3 campanas/estimulo.py off

El ancho del pulso y la convención de offset son los de la campaña validada
(`campanas/testbench_mca.py`): tren unipolar positivo, base en amp/2 y pico en
amp, o sea altura de pulso = amp/2.
"""

import argparse
import os
import sys
import time

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import API.rigol_dg4162 as rg                                      # noqa: E402

ANCHO_PULSO_S = 2e-6


def encender(gen, ch, rate_hz, amp_vpp, ancho_s=ANCHO_PULSO_S):
    onda, freq, info = rg.pulse_train_wave(ancho_s, rate_hz)
    gen.load_arb(onda, ch=ch)
    gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
    gen.output(ch, True)
    time.sleep(0.3)
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
    gen.load_arb(onda, ch=ch)
    gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
    gen.output(ch, True)
    time.sleep(0.3)
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
    a = ap.parse_args(argv)

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
        if a.dos_poblaciones:
            freq, info = encender_dos_poblaciones(gen, a.ch, a.rate, a.amp,
                                                  a.ancho, tuple(a.taus))
            print(f'  DOS poblaciones (cola x{a.taus[0]:g} y x{a.taus[1]:g}), '
                  f'{info["n_pulses"]} pulsos/forma de {a.ancho*1e6:g} us, '
                  f'repetición {freq:g} Hz -> {a.rate:g} pulsos/s')
        else:
            freq, info = encender(gen, a.ch, a.rate, a.amp, a.ancho)
            print(f'  {info["n_pulses"]} pulso(s)/forma de {a.ancho * 1e6:g} us, '
                  f'repetición {freq:g} Hz -> {a.rate:g} pulsos/s')
        print(f'  {a.amp:g} Vpp con offset {a.amp / 2:g} V '
              f'(altura de pulso {a.amp / 2:g} V, ~{a.amp / 2 * 8192:.0f} cuentas)')
        print(f'  salida {a.ch} ENCENDIDA — apagar con: '
              f'python3 campanas/estimulo.py off')
        return 0
    finally:
        gen.close()


if __name__ == '__main__':
    sys.exit(main())
