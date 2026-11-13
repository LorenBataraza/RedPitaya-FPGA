"""Hilo lector: detecta eventos y copia su ventana al batch.

Es el unico hilo que toca el scope. Tiene dos caminos:

- **Por lote**, si la fuente tiene `read_batch` (`BramSource`): el lazo por evento
  corre en C, sin el GIL, y vuelve con el batch lleno o cada 50 ms como mucho. Aca
  quedan la cola, las estadisticas y los annotators, que corren sobre el rango recien
  llenado. Medido en C (`bench_reader_c.c`): 19.3 us por evento, 2 canales de 32.
- **Por evento**, si no (`FakeSource`, `RingSource`): el lazo de siempre, en Python.
  Era el de `BramSource` hasta la Parte 6, con este presupuesto medido (2 canales,
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

# Sin batch libre, el lazo de C descarta hasta este plazo y vuelve a mirar la cola:
# corto, para tomar el primer batch que el escritor devuelva.
PLAZO_SIN_BATCH_NS = 2_000_000
# Con batch, vuelve como mucho cada esto, para que `stop` responda.
PLAZO_LOTE_NS = 50_000_000


class ReaderThread(threading.Thread):
    """Productor: EventSource -> batches llenos en `full_q`.

    `stats` es un dict compartido (lo lee el escritor para la metadata y, mas
    adelante, el dashboard). Solo este hilo lo escribe.
    """

    def __init__(self, source, free_q, full_q, stats, annotators=(),
                 poll_timeout_s=1.0, name='osc-reader'):
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
            if hasattr(self.source, 'read_batch'):
                self._loop_lotes()
            else:
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
        rearm       = src.rearm
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
                    # ventana (lo caro), pero SI se re-arma: sin eso el buffer
                    # queda congelado, `wait_event` vuelve a disparar con el
                    # MISMO evento y el contador de descartes se dispara con
                    # fantasmas (medido: 14996 "eventos" contra 10251 reales).
                    pending += 1
                    stats['n_dropped'] += 1
                    rearm()
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
            # Re-armar apenas la ventana esta copiada: entre el trigger y esta
            # linea el scope esta ciego, y ese hueco es el dead-time del metodo.
            # Los annotators van DESPUES, con el HW ya adquiriendo de nuevo.
            rearm()
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

    def _loop_lotes(self):
        """El camino por lote: lo de `_loop`, con el lazo por evento en la fuente.

        Lo que cada evento hacia aca (el `gap`, `t_ns`, `wp`, `snap`, la ventana, el
        re-armado) lo hace la fuente; los descartes pendientes los lleva ella, y
        `batch.dropped` suma los que fueron a parar a los `gap` de este batch. Los
        timeouts se cuentan como antes: uno por cada `poll_timeout_s` sin eventos.
        """
        src         = self.source
        annotators  = self.annotators
        free_q      = self.free_q
        full_q      = self.full_q
        stats       = self.stats
        stop        = self.stop_event
        read_batch  = src.read_batch
        pc          = time.perf_counter_ns
        timeout_ns  = self.poll_timeout_ns

        batch = None
        stats['t_start_ns'] = pc()
        t_quieto = stats['t_start_ns']        # desde cuando no llega nada

        while not stop.is_set():
            if batch is None:
                try:
                    batch = free_q.get_nowait()
                    batch.reset()
                except queue.Empty:
                    batch = None

            plazo = PLAZO_LOTE_NS if batch is not None else PLAZO_SIN_BATCH_NS
            i0 = batch.n if batch is not None else 0
            n, descartados, asignados = read_batch(batch, pc() + plazo)
            stats['n_dropped'] += descartados

            if n:
                batch.dropped += asignados
                i1 = i0 + n
                for a in annotators:
                    a.sample_range(batch, i0, i1)
                batch.n = i1
                stats['n_read'] += n
                if batch.n >= batch.capacity:
                    full_q.put(batch)
                    batch = None

            ahora = pc()
            if n or descartados:
                t_quieto = ahora
            elif ahora - t_quieto >= timeout_ns:
                stats['n_timeouts'] += 1
                t_quieto = ahora

        if batch is not None and batch.n:
            full_q.put(batch)
        elif batch is not None:
            free_q.put(batch)
        stats['t_end_ns']    = pc()
        stats['pending_tail'] = src.pending
