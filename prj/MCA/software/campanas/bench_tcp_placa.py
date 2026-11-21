#!/usr/bin/env python3
"""Cuánto da TCP de la placa a la PC: el techo del ring por red.

Es la Fase 0 de docs/event_ring/salida_por_red.md («El ring por red»): antes de
mandar los slots por un socket, cuánto llega con nada más que el socket en el medio.
La placa no tiene `iperf3` ni `nc`, así que esto corre de los dos lados:

    # en la placa: escucha, manda MB megabytes al primero que se conecte, y sale
    python3 campanas/bench_tcp_placa.py servir --puerto 5099 --mb 1024

    # en la PC: se conecta, recibe y descarta, y dice cuánto tardó
    python3 campanas/bench_tcp_placa.py recibir --host <ip-placa> --puerto 5099

    # o todo desde la PC (lanza el lado de la placa por ssh)
    make bench-tcp-placa

El sentido es el del ring por red: la placa escucha y la PC se conecta, así que no
hace falta abrir nada en el firewall de la PC. La placa manda desde un buffer que ya
está en memoria, con `sendall` de a `--bloque` bytes: es el mejor caso del lado de la
placa (nada que copiar de la DDR). Lo que se mide es la pila TCP del A9 y el enlace.

Imprime una línea JSON por lado, con el tiempo, los MB/s y, en la placa, la velocidad
del enlace (`/sys/class/net/<if>/speed`) y el tiempo de CPU del proceso.
"""

import argparse
import json
import os
import socket
import sys
import time


def velocidad_enlace():
    """{interfaz: Mb/s} de las interfaces con enlace, de /sys/class/net."""
    out = {}
    base = '/sys/class/net'
    try:
        nombres = os.listdir(base)
    except OSError:
        return out
    for n in nombres:
        if n == 'lo':
            continue
        try:
            with open(os.path.join(base, n, 'speed')) as fh:
                v = int(fh.read().strip())
        except (OSError, ValueError):
            continue
        if v > 0:
            out[n] = v
    return out


def servir(puerto, mb, bloque, sndbuf):
    total = mb * 1024 * 1024
    buf = memoryview(os.urandom(bloque))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', puerto))
        s.listen(1)
        print(json.dumps({'lado': 'placa', 'escuchando': puerto}), flush=True)
        c, addr = s.accept()
        with c:
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if sndbuf:
                c.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
            cpu0, t0 = time.process_time(), time.perf_counter()
            enviado = 0
            while enviado < total:
                n = min(len(buf), total - enviado)
                c.sendall(buf[:n])
                enviado += n
            c.shutdown(socket.SHUT_WR)
            c.recv(1)                    # espera que la PC cierre: llegó todo
            t, cpu = time.perf_counter() - t0, time.process_time() - cpu0
    print(json.dumps({'lado': 'placa', 'a': addr[0], 'bytes': enviado,
                      'segundos': round(t, 4), 'MB_s': round(enviado / t / 1e6, 2),
                      'cpu_s': round(cpu, 3), 'bloque': bloque,
                      'sndbuf': c_sndbuf(sndbuf), 'enlace_Mb_s': velocidad_enlace()}),
          flush=True)


def c_sndbuf(pedido):
    return pedido or 'default'


def recibir(host, puerto, bloque, plazo_s=30.0):
    buf = bytearray(bloque)
    vista = memoryview(buf)
    t_fin = time.monotonic() + plazo_s
    while True:                          # el servidor puede tardar en escuchar
        try:
            c = socket.create_connection((host, puerto), timeout=5.0)
            break
        except OSError:
            if time.monotonic() > t_fin:
                raise
            time.sleep(0.2)
    with c:
        c.settimeout(None)
        t0, recibido = time.perf_counter(), 0
        while True:
            n = c.recv_into(vista)
            if n == 0:
                break
            recibido += n
        t = time.perf_counter() - t0
    r = {'lado': 'pc', 'de': host, 'bytes': recibido, 'segundos': round(t, 4),
         'MB_s': round(recibido / t / 1e6, 2), 'enlace_Mb_s': velocidad_enlace()}
    print(json.dumps(r), flush=True)
    return r


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='modo', required=True)
    s = sub.add_parser('servir', help='en la placa: escucha y manda')
    s.add_argument('--puerto', type=int, default=5099)
    s.add_argument('--mb', type=int, default=1024, help='megabytes a mandar')
    s.add_argument('--bloque', type=int, default=1 << 20, help='bytes por sendall')
    s.add_argument('--sndbuf', type=int, default=0, help='SO_SNDBUF; 0 = el del kernel')
    r = sub.add_parser('recibir', help='en la PC: se conecta, recibe y descarta')
    r.add_argument('--host', required=True)
    r.add_argument('--puerto', type=int, default=5099)
    r.add_argument('--bloque', type=int, default=4 << 20, help='bytes por recv_into')
    a = p.parse_args(argv)
    if a.modo == 'servir':
        servir(a.puerto, a.mb, a.bloque, a.sndbuf)
    else:
        recibir(a.host, a.puerto, a.bloque)
    return 0


if __name__ == '__main__':
    sys.exit(main())
