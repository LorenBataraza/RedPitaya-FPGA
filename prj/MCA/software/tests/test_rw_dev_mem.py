#!/usr/bin/env python3
"""Regresion: como se puede y como NO se puede escribir un registro del scope.

El mmap de /dev/mem es memoria de DISPOSITIVO (no cacheable). El esclavo AXI de
la PL solo reconoce accesos de 32 bits alineados: cualquier escritura angosta
(de a byte) no completa la transaccion, el puente GP0 tira un *external abort*
y el proceso muere con SIGBUS. En Jupyter eso se ve como "el kernel murio", sin
traceback, y en dmesg como:

    Unhandled fault: external abort on non-linefetch (0x1818) at 0x........
    [........] *pgd=........, *pte=40100743      <- fisica 0x40100xxx = scope

El caso concreto que rompio: `struct.Struct.pack_into(mmap, off, v)` parece
equivalente a la asignacion por slice, pero hace un `memset` de la region antes
de empaquetar, y ese memset sale como stores de a byte -> SIGBUS.

Cada metodo se prueba en un PROCESO HIJO: asi el que muere es el hijo y este
script puede reportar el resultado en vez de llevarse el kernel puesto.

Uso (en la Pitaya, con el bitstream multitrigger cargado):
    python3 test_rw_dev_mem.py
"""
import os
import subprocess
import sys

SCOPE_PHYS = 0x4010_0000
OFF        = 0x240          # OR_MASK ch0: R/W y sin efecto sobre la adquisicion
PATRON     = 0xA5A5_5A5A

CHILD = '''
import mmap, os, struct, sys
metodo = sys.argv[1]
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,
              mmap.PROT_READ | mmap.PROT_WRITE, offset={phys})
U32 = struct.Struct("<I")
orig = U32.unpack_from(m, {off})[0]
try:
    if metodo == "slice":
        m[{off}:{off}+4] = U32.pack({pat})           # el camino bueno
    elif metodo == "pack_into":
        U32.pack_into(m, {off}, {pat})               # memset previo -> SIGBUS
    rb = U32.unpack_from(m, {off})[0]
    print(hex(rb))
finally:
    m[{off}:{off}+4] = U32.pack(orig)                # restaurar siempre
'''.format(phys=hex(SCOPE_PHYS), off=hex(OFF), pat=hex(PATRON))


def run(metodo):
    """(ok, detalle) de escribir con `metodo` en un proceso aparte."""
    r = subprocess.run([sys.executable, '-c', CHILD, metodo],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True, f'readback={r.stdout.strip()}'
    if r.returncode < 0:
        sig = -r.returncode
        return False, f'muerto por señal {sig}' + (' (SIGBUS)' if sig == 7 else '')
    return False, (r.stderr.strip().splitlines() or [''])[-1]


def main():
    if not os.path.exists('/dev/mem'):
        print('SKIP: esto corre en la Pitaya'); return 0

    fails = 0
    print(f'escribiendo {PATRON:#x} en {SCOPE_PHYS + OFF:#x} (OR_MASK ch0)\n')

    ok, det = run('slice')
    print(f'  [{"PASS" if ok else "FAIL"}] slice  m[o:o+4] = pack(v)   -> {det}')
    fails += not ok
    if ok and det != f'readback={PATRON:#x}':
        print('         (readback distinto del patron: ¿bitstream equivocado?)')

    ok, det = run('pack_into')
    # Se ESPERA que falle: si algun dia deja de fallar (kernel/libc distintos),
    # igual no hay que usarlo, pero conviene enterarse.
    print(f'  [{"PASS" if not ok else "WARN"}] pack_into (debe abortar) -> {det}')
    if ok:
        print('         ahora no aborta, pero seguí usando la asignacion por slice')

    print('\nRESULT:', 'PASS' if not fails else 'FAIL')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
