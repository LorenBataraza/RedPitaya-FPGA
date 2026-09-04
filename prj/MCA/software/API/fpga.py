#!/usr/bin/env python3
"""Bring-up de la PL: bitstream, puentes AXI y sondeo del bus.

Esto es de PLACA, no del osciloscopio. Vivía en `multitrigger_utils.py` por
accidente histórico — el scope fue lo primero que hubo que arrancar — pero
`load_bitstream()` no tiene nada que ver con adquirir señal, y cargar un
bitstream distinto lo usa igual.

    from API.fpga import load_bitstream, fpga_state, pl_bus_ready

    load_bitstream('/root/mca_red_pitaya.bit.bin')
    assert fpga_state() == 'operating'

Orden que importa: reprogramar la PL con mapeos de /dev/mem abiertos produce el
`external abort ... *pte=40100743` de dmesg y puede dejar el puerto GP0 trabado
hasta reiniciar la placa. Cerrar los mmap ANTES de cargar.
"""

import mmap
import os
import struct
import subprocess
import sys
import time

# Dirección de sondeo por defecto: el registro set_dec del slot 1 (scope). No es
# una dependencia del osciloscopio, es sólo "un registro que sabemos que existe
# y contesta" para preguntarle al bus si está vivo. Se define acá en vez de
# importar SCOPE_PHYS para que este módulo no dependa de API.osciloscope.
_PROBE_PHYS = 0x4010_0000


BITSTREAM_DEFAULT = '/root/red_pitaya_top.bit.bin'
FPGA_STATE        = '/sys/class/fpga_manager/fpga0/state'
FPGA_BRIDGE_DIR   = '/sys/class/fpga_bridge'
# fpgautil vive en el PATH del entorno RP; un shell no interactivo (ssh, cron,
# systemd) no lo tiene, así que se resuelve a mano con fallback absoluto.
FPGAUTIL_PATHS    = ('/opt/redpitaya/bin/fpgautil', '/usr/local/bin/fpgautil')


def fpgautil_bin():
    """Ruta del ejecutable fpgautil (PATH primero, después las conocidas)."""
    import shutil
    return (shutil.which('fpgautil')
            or next((p for p in FPGAUTIL_PATHS if os.path.exists(p)), None))


def fpga_state():
    """Estado del FPGA manager ('operating' = PL programada y corriendo).

    Devuelve None si el sysfs no existe (RP OS viejo / no es una Pitaya): en ese
    caso no se puede saber, y quien lo use NO debe bloquear por las dudas.
    """
    try:
        with open(FPGA_STATE) as f:
            return f.read().strip()
    except OSError:
        return None


def fpga_bridges():
    """Puentes AXI PS-PL expuestos por el kernel (vacío si el DT no los declara)."""
    try:
        return [os.path.join(FPGA_BRIDGE_DIR, d)
                for d in sorted(os.listdir(FPGA_BRIDGE_DIR))]
    except OSError:
        return []


def set_fpga_bridges(enable, verbose=False):
    """Habilita/deshabilita los puentes AXI entre el PS y la PL.

    Hay que BAJARLOS antes de reconfigurar y subirlos después. Si no, una
    transacción del PS puede quedar sin esclavo que la conteste (el bus del
    scope vive en el dominio `adc_clk` y en reset por `adc_rstn`, ver
    red_pitaya_top.sv:227 y :289) y el puente GP0 tira un *external abort*
    → SIGBUS. Peor: el puerto puede quedar TRABADO y seguir abortando aunque
    la PL ya esté bien, hasta reiniciar la placa.

    Devuelve la lista de puentes tocados (vacía si el kernel no los expone).
    """
    done = []
    for b in fpga_bridges():
        try:
            with open(os.path.join(b, 'enable'), 'w') as f:
                f.write('1' if enable else '0')
            done.append(os.path.basename(b))
        except OSError as e:
            print(f'warn: no pude {"subir" if enable else "bajar"} el puente {b}: {e}')
    if verbose and done:
        print(f'  puentes AXI {"habilitados" if enable else "deshabilitados"}: {done}')
    return done


# Lectura de prueba de un registro del scope, para correr en un proceso APARTE.
_PROBE_SRC = (
    'import mmap, os, struct\n'
    'fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)\n'
    'm = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,\n'
    '              mmap.PROT_READ | mmap.PROT_WRITE, offset={phys})\n'
    'print(struct.unpack_from("<I", m, {off})[0])\n'
)


def pl_probe(phys=_PROBE_PHYS, off=0x14):
    """¿Contesta la PL en `phys+off`? Devuelve (ok, detalle).

    La lectura se hace en un **proceso hijo**: si el bus no está listo, el que
    muere con SIGBUS es el hijo y nos enteramos por el returncode, en vez de
    perder el kernel de Jupyter. Es la única forma segura de preguntar
    "¿ya puedo tocar el scope?" después de reconfigurar la PL.
    """
    r = subprocess.run([sys.executable, '-c',
                        _PROBE_SRC.format(phys=hex(phys), off=hex(off))],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True, r.stdout.strip()
    if r.returncode < 0:                      # murió por señal
        sig = -r.returncode
        return False, (f'el hijo murió con señal {sig} '
                       f'({"SIGBUS: la PL no contesta" if sig == 7 else "SIGSEGV"})')
    last = (r.stderr.strip().splitlines() or [''])[-1]
    return False, f'error de entorno (no del bus): {last}'


def pl_bus_ready(phys=_PROBE_PHYS, off=0x14, timeout_s=8.0, interval_s=0.3,
                 verbose=False):
    """Espera a que la PL conteste en el bus, sondeando con `pl_probe`.

    Después de reconfigurar hay una ventana en la que el esclavo no responde
    (el bus del scope está en el dominio adc_clk y en reset por adc_rstn, ver
    red_pitaya_top.sv:227/:289). Medido en esta placa: a los 0.7 s todavía
    abortaba. Acá se espera hasta `timeout_s` en vez de adivinar un sleep.

    Devuelve (ok, detalle, esperado_s). Si el hijo falla por algo que no es el
    bus (p. ej. sin permisos sobre /dev/mem) corta enseguida: reintentar no
    arregla nada.
    """
    t0 = time.time()
    while True:
        ok, det = pl_probe(phys, off)
        el = time.time() - t0
        if ok:
            if verbose:
                print(f'  bus de la PL listo tras {el:.2f} s (leyó {det})')
            return True, det, el
        if det.startswith('error de entorno'):
            return False, det, el
        if el > timeout_s:
            return False, f'{det} (tras {el:.1f} s)', el
        time.sleep(interval_s)


def load_bitstream(path=BITSTREAM_DEFAULT, settle_s=0.2, check=True,
                   bridges=True, wait_bus_s=8.0, verbose=False):
    """Programa la PL con `fpgautil -b` (sin device tree).

    **NUNCA reprogramar con mapeos del scope abiertos.** Mientras la PL se
    reconfigura no hay esclavo que conteste en el bus AXI, y el primer acceso
    posterior a 0x4010_0000 da un *external abort* → SIGBUS → se muere el
    proceso (en Jupyter: "el kernel murió"). En dmesg se ve así:

        Unhandled fault: external abort on non-linefetch (0x1818) at 0x...
        [........] *pgd=........, *pte=40100743      <- física 0x40100xxx

    Para recargar a mitad de sesión usar `MultiTriggerScope.reload_bitstream()`,
    que cierra el mapeo y el rp ANTES de programar y los reabre después.

    `bridges=True` baja los puentes AXI PS-PL mientras dura la reconfiguración
    (lo que `fpgautil -b` a secas NO hace y sí hace el camino del device tree
    overlay). Si el kernel no los expone, avisa: en ese caso reprogramar con el
    sistema vivo puede dejar el puerto GP0 trabado hasta reiniciar la placa.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f'no existe el bitstream {path}')
    exe = fpgautil_bin()
    if exe is None:
        raise FileNotFoundError(
            'no encuentro `fpgautil` (ni en PATH ni en ' + ', '.join(FPGAUTIL_PATHS) + ')')

    have_bridges = bool(fpga_bridges())
    if bridges and not have_bridges:
        print('warn: el kernel no expone /sys/class/fpga_bridge; se reprograma '
              'con los puentes AXI arriba. Si algo accede a la PL en ese '
              'momento, el puerto puede quedar trabado (external abort) hasta '
              'reiniciar la Pitaya.')
    try:
        if bridges and have_bridges:
            set_fpga_bridges(False, verbose=verbose)
        r = subprocess.run([exe, '-b', path], capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            raise RuntimeError(f'fpgautil falló ({r.returncode}): {out}')
        # dar tiempo al PLL (adc_clk) y a que se suelte adc_rstn antes de que
        # alguien toque 0x4010_0000
        time.sleep(settle_s)
    finally:
        if bridges and have_bridges:
            set_fpga_bridges(True, verbose=verbose)
            time.sleep(0.05)

    st = fpga_state()
    if check and st is not None and st != 'operating':
        raise RuntimeError(f'la PL no quedó operativa tras programar (state={st!r}); '
                           'leer el scope ahora daría SIGBUS')

    # `state == operating` NO alcanza: el bus tarda en contestar después de la
    # reconfiguración. Se sondea desde un proceso hijo hasta que responda.
    espera = 0.0
    if wait_bus_s:
        ok, det, espera = pl_bus_ready(timeout_s=wait_bus_s, verbose=verbose)
        if not ok:
            raise RuntimeError(
                f'la PL no contesta en el bus tras programar: {det}. '
                'NO toques el scope desde este kernel (moriría con SIGBUS); '
                'reiniciá la Pitaya.')
    return {'path': path, 'state': st or 'desconocido', 'fpgautil': out,
            'bus_wait_s': espera}
