"""Hilo lector: detecta eventos y copia su ventana al batch.

Es el unico hilo que toca el scope. Presupuesto medido por evento (2 canales,
ventana de 32, ver docs/arquitectura_adquisicion_software.md):

    poll de wp_trig      2.3 us
    leer ventana ch0    45.6 us
    leer ventana ch1    45.6 us
    ------------------------------
    total               91.2 us    ->  techo ~11 kev/s

Politica ante backpressure: **descartar y contar, nunca bloquear**. Si se
bloqueara, el dead-time pasaria a depender del disco y dejaria de ser una
constante del hardware, que es justo lo que rompe la estadistica de conteo.
"""

import queue
import threading
import time

from .events import GAP_MAX


class ReaderThread(threading.Thread):
    """Productor: EventSource -> batches llenos en `full_q`.

    `stats` es un dict compartido (lo lee el escritor para la metadata y, mas
    adelante, el dashboard). Solo este hilo lo escribe.
    """

    def __init__(self, source, free_q, full_q, stats, annotators=(),
                 poll_timeout_s=1.0, name='mca-reader'):
        super().__init__(name=name, daemon=True)
        self.source     = source
        self.free_q     = free_q
        self.full_q     = full_q
        self.stats      = stats
        self.annotators = tuple(annotators)
        self.poll_timeout_ns = int(poll_timeout_s * 1e9)
        self.stop_event = threading.Event()
        self.error      = None

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            self._loop()
        except BaseException as exc:            # que no se muera en silencio
            self.error = exc
            self.stats['error'] = repr(exc)
        finally:
            self.full_q.put(None)               # centinela: cierra al escritor

    def _loop(self):
        src         = self.source
        annotators  = self.annotators
        free_q      = self.free_q
        full_q      = self.full_q
        stats       = self.stats
        stop        = self.stop_event
        wait_event  = src.wait_event
        read_into   = src.read_into
        snapshot    = src.snapshot
        pc          = time.perf_counter_ns
        timeout_ns  = self.poll_timeout_ns

        batch   = None
        pending = 0                    # descartes desde el ultimo evento guardado
        stats['t_start_ns'] = pc()

        while not stop.is_set():
            wp = wait_event(pc() + timeout_ns)
            if wp is None:
                # Una fuente finita (FakeSource, un archivo replayed) avisa que
                # no va a haber mas eventos; si no, un timeout es normal y se
                # sigue esperando.
                if getattr(src, 'exhausted', False):
                    stats['exhausted'] = True
                    break
                stats['n_timeouts'] += 1
                continue
            t_ns = pc()

            if batch is None:
                try:
                    batch = free_q.get_nowait()
                except queue.Empty:
                    # Sin destino: se cuenta y se SIGUE poleando. No se lee la
                    # ventana (lo caro), pero no se pierde de vista el stream,
                    # asi que el conteo de descartes es exacto por evento.
                    pending += 1
                    stats['n_dropped'] += 1
                    continue
                batch.reset()

            i = batch.n
            # `gap` satura (uint8): marca DONDE hay un hueco. El total exacto se
            # acumula aparte, en batch.dropped, y va a meta['chunk_dropped'].
            batch.gap[i]   = pending if pending < GAP_MAX else GAP_MAX
            batch.dropped += pending
            pending        = 0
            batch.t_ns[i] = t_ns
            batch.wp[i]   = wp
            batch.snap[i] = snapshot()
            read_into(batch, i, wp)
            for a in annotators:
                a.sample_into(batch, i)

            batch.n = i + 1
            stats['n_read'] += 1
            if batch.n >= batch.capacity:
                full_q.put(batch)
                batch = None

        # Flush del batch parcial: si no, se pierde la cola de la corrida.
        if batch is not None and batch.n:
            full_q.put(batch)
        elif batch is not None:
            free_q.put(batch)
        stats['t_end_ns']    = pc()
        stats['pending_tail'] = pending
