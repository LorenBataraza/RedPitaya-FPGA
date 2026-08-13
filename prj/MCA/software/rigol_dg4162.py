"""
Driver mínimo para Rigol DG4162 (y resto de la serie DG4000), sin
dependencias externas (no requiere pyvisa). Soporta cuatro transportes:

  - USB-TMC vía /dev/usbtmcN (driver del kernel Linux).
  - USB crudo vía pyusb/libusb (`RigolDG4162.usb()`), para cuando el kernel
    no trae el módulo usbtmc — es el caso de la RedPitaya (5.15.0-xilinx).
  - TCP vía socket al puerto SCPI 5555.
  - VXI-11 sobre LAN.

Uso típico desde el notebook:

    from rigol_dg4162 import RigolDG4162

    rg = RigolDG4162.usb()          # o .usbtmc('/dev/usbtmc0') / .tcp(ip)
    print(rg.id)
    rg.reset()
    rg.set_pulse_periodic(ch=1, period_s=100e-6, width_s=200e-9,
                          amp_vpp=1.0, offset_v=0.5)
    rg.output(1, True)
    # ... corre tu test ...
    rg.output(1, False)
    rg.close()

Para sweep de distancia entre pulsos:

    for p in periods:
        rg.set_pulse_period(ch=1, period_s=p)
        # capturás y medís eficiencia
"""

import select
import socket
import time

class _TransportVXI11:
    def __init__(self, host):
        import vxi11
        self.instr = vxi11.Instrument(host)

    def write(self, b):
        self.instr.write(b.decode().strip())

    def read(self, n=4096, timeout=None):
        if timeout is not None:
            self.instr.timeout = timeout
        try:
            return self.instr.read_raw()
        except Exception as e:
            raise TimeoutError(f'VXI-11 read timeout/error: {e}') from e

    def close(self):
        self.instr.close()

class _TransportUSBRaw:
    """Transporte USBTMC en espacio de usuario vía pyusb/libusb, sin depender
    del driver de kernel /dev/usbtmcN (que en la RedPitaya no está compilado:
    `modprobe usbtmc` → "Module usbtmc not found"). Implementa el protocolo
    USBTMC/USB488 mínimo sobre los endpoints bulk directamente.

    Notas de implementación (razón de cada una: el DG4162 stallea el bulk-OUT
    — [Errno 32] Pipe error — si no se respetan):

      - NO se llama `set_configuration()` si el device ya está configurado;
        libusb avisa que re-configurar hace perder estado al dispositivo.
      - Se reclama la interfaz explícitamente y se corre la secuencia de
        inicialización USBTMC (INITIATE_CLEAR/CHECK_CLEAR_STATUS), que deja
        los buffers del instrumento limpios aunque haya quedado a mitad de
        una transacción de una sesión anterior.
      - Todo stall se recupera con CLEAR_FEATURE(ENDPOINT_HALT) + reintento.
    """

    # --- USBTMC bulk message IDs ---
    MSG_ID_DEV_DEP_MSG_OUT = 1
    MSG_ID_REQUEST_DEV_DEP_MSG_IN = 2
    MSG_ID_DEV_DEP_MSG_IN = 2

    # --- USBTMC control requests (bmRequestType = 0xA1 iface / 0xA2 endpoint) ---
    INITIATE_ABORT_BULK_IN = 3
    CHECK_ABORT_BULK_IN_STATUS = 4
    INITIATE_CLEAR = 5
    CHECK_CLEAR_STATUS = 6
    GET_CAPABILITIES = 7

    STATUS_SUCCESS = 0x01
    STATUS_PENDING = 0x81

    USBTMC_CLASS = 0xFE      # Application Specific Interface
    USBTMC_SUBCLASS = 0x03   # Test and Measurement Class

    def __init__(self, vid=0x1ab1, pid=0x0641, serial=None):
        # Import diferido: así el módulo sigue importándose en máquinas sin
        # pyusb (la PC de desarrollo), donde solo se usan TCP/VXI-11.
        import usb.core
        import usb.util
        self._usb = usb

        # Si hay más de un instrumento con el mismo VID:PID, filtrar por serial.
        devs = list(usb.core.find(idVendor=vid, idProduct=pid, find_all=True))
        if not devs:
            raise IOError(f'No se encontró dispositivo USB {vid:04x}:{pid:04x}')
        if serial is not None:
            devs = [d for d in devs
                    if usb.util.get_string(d, d.iSerialNumber) == serial]
            if not devs:
                raise IOError(f'Ningún dispositivo {vid:04x}:{pid:04x} con serial {serial}')
        self.dev = devs[0]

        # Configuración activa. Solo se setea si el device NO está configurado:
        # `get_active_configuration()` tira USBError en ese caso.
        try:
            cfg = self.dev.get_active_configuration()
        except usb.core.USBError:
            self.dev.set_configuration()
            cfg = self.dev.get_active_configuration()

        # Buscar la interfaz USBTMC por clase (0xFE/0x03) en vez de asumir (0,0).
        intf = None
        for i in cfg:
            if (i.bInterfaceClass == self.USBTMC_CLASS
                    and i.bInterfaceSubClass == self.USBTMC_SUBCLASS):
                intf = i
                break
        if intf is None:
            raise IOError('El dispositivo no expone una interfaz USBTMC (0xFE/0x03)')
        self.iface_num = intf.bInterfaceNumber

        # En esta Pitaya no hay driver usbtmc en el kernel, pero por robustez
        # se desacopla igual antes de reclamar la interfaz.
        try:
            if self.dev.is_kernel_driver_active(self.iface_num):
                self.dev.detach_kernel_driver(self.iface_num)
        except (NotImplementedError, usb.core.USBError):
            pass

        try:
            usb.util.claim_interface(self.dev, self.iface_num)
        except usb.core.USBError as e:
            if e.errno == 16:  # EBUSY: otro proceso tiene la interfaz tomada
                raise IOError(
                    'La interfaz USBTMC está tomada por otro proceso (típicamente un '
                    'kernel de Jupyter que abrió el instrumento y no llamó a close()). '
                    'Reiniciá ese kernel, o mirá quién la tiene con: '
                    'fuser -v /dev/bus/usb/001/*') from e
            raise

        self.ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
            and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)
        self.ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
            and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)
        if self.ep_out is None or self.ep_in is None:
            raise IOError('No se encontraron endpoints bulk IN/OUT en la interfaz USBTMC')
        self._mps_in = self.ep_in.wMaxPacketSize or 64

        self._btag = 0

        # Inicialización USBTMC: capabilities (informativo, algunos firmwares
        # lo esperan antes del primer bulk) + clear de los buffers.
        self.capabilities = self._get_capabilities()
        self.clear()

    # ---------- helpers de bajo nivel ----------

    def _next_btag(self):
        # bTag cicla 1..255, nunca 0 (0 está reservado por el spec USBTMC).
        self._btag = (self._btag % 255) + 1
        return self._btag

    def _clear_halt(self, ep):
        try:
            self.dev.clear_halt(ep.bEndpointAddress)
        except self._usb.core.USBError:
            pass

    def _get_capabilities(self):
        """GET_CAPABILITIES (0xA1, bRequest=7). Devuelve los 24 bytes crudos o
        None si el instrumento no lo soporta (no es fatal)."""
        try:
            return bytes(self.dev.ctrl_transfer(0xA1, self.GET_CAPABILITIES,
                                                0, self.iface_num, 0x18,
                                                timeout=1000))
        except self._usb.core.USBError:
            return None

    def clear(self):
        """INITIATE_CLEAR + CHECK_CLEAR_STATUS: descarta los buffers de entrada
        y salida del instrumento y deja los endpoints en estado conocido. Es la
        recuperación estándar de un stall (Pipe error)."""
        try:
            r = self.dev.ctrl_transfer(0xA1, self.INITIATE_CLEAR, 0,
                                       self.iface_num, 1, timeout=1000)
        except self._usb.core.USBError:
            self._clear_halt(self.ep_out)
            return False
        if not len(r) or r[0] != self.STATUS_SUCCESS:
            self._clear_halt(self.ep_out)
            return False

        for _ in range(100):
            try:
                r = self.dev.ctrl_transfer(0xA1, self.CHECK_CLEAR_STATUS, 0,
                                           self.iface_num, 2, timeout=1000)
            except self._usb.core.USBError:
                break
            if r[0] != self.STATUS_PENDING:
                break
            # bmClear bit0 = quedan datos en el bulk-IN: hay que drenarlos.
            if len(r) > 1 and (r[1] & 0x01):
                try:
                    self.ep_in.read(self._mps_in, 100)
                except self._usb.core.USBError:
                    pass
            time.sleep(0.01)

        # El spec exige limpiar el halt del bulk-OUT al terminar el CLEAR.
        self._clear_halt(self.ep_out)
        return True

    def _abort_bulk_in(self, btag):
        """INITIATE_ABORT_BULK_IN: cancela una transferencia IN que quedó
        pendiente (típico tras un timeout). Sin esto, el próximo query lee la
        respuesta vieja y todo queda corrido un mensaje."""
        try:
            r = self.dev.ctrl_transfer(0xA2, self.INITIATE_ABORT_BULK_IN, btag,
                                       self.ep_in.bEndpointAddress, 2, timeout=1000)
        except self._usb.core.USBError:
            self._clear_halt(self.ep_in)
            return
        if not len(r) or r[0] != self.STATUS_SUCCESS:
            self._clear_halt(self.ep_in)
            return
        for _ in range(100):
            try:
                self.ep_in.read(self._mps_in, 100)
            except self._usb.core.USBError:
                pass
            try:
                r = self.dev.ctrl_transfer(0xA2, self.CHECK_ABORT_BULK_IN_STATUS, 0,
                                           self.ep_in.bEndpointAddress, 8, timeout=1000)
            except self._usb.core.USBError:
                break
            if r[0] != self.STATUS_PENDING:
                break

    def _bulk_out(self, packet, tmo_ms):
        """Escribe en el bulk-OUT recuperándose de un stall (errno 32) una vez."""
        try:
            return self.ep_out.write(packet, tmo_ms)
        except self._usb.core.USBError as e:
            if e.errno != 32:  # EPIPE == stall; cualquier otra cosa se propaga
                raise
            self._clear_halt(self.ep_out)
            self.clear()
            return self.ep_out.write(packet, tmo_ms)

    def _bulk_in(self, nbytes, tmo_ms):
        try:
            return bytes(self.ep_in.read(nbytes, tmo_ms))
        except self._usb.core.USBError as e:
            if e.errno == 32:
                self._clear_halt(self.ep_in)
            raise

    # ---------- API de transporte ----------

    def write(self, data, timeout=None):
        tmo_ms = 5000 if timeout is None else max(1, int(timeout * 1000))
        btag = self._next_btag()
        header = bytes([
            self.MSG_ID_DEV_DEP_MSG_OUT,
            btag,
            (~btag) & 0xFF,
            0x00,
        ]) + len(data).to_bytes(4, 'little') + bytes([0x01, 0x00, 0x00, 0x00])
        # EOM=1 (bit0 de bmTransferAttributes): este mensaje termina acá.
        packet = header + data
        packet += b'\x00' * ((-len(packet)) % 4)  # alineación a 4 bytes (spec)
        self._bulk_out(packet, tmo_ms)

    def read(self, n=4096, timeout=None):
        tmo_ms = 5000 if timeout is None else max(1, int(timeout * 1000))
        # Buffer múltiplo de wMaxPacketSize: si libusb recibe más de lo que le
        # pedimos, el transfer falla con overflow.
        bufsize = ((n + 12 + self._mps_in - 1) // self._mps_in) * self._mps_in

        out = b''
        while True:
            btag = self._next_btag()
            # REQUEST_DEV_DEP_MSG_IN va por el mismo endpoint bulk OUT.
            req = bytes([
                self.MSG_ID_REQUEST_DEV_DEP_MSG_IN,
                btag,
                (~btag) & 0xFF,
                0x00,
            ]) + n.to_bytes(4, 'little') + bytes([0x00, 0x00, 0x00, 0x00])
            self._bulk_out(req, tmo_ms)

            try:
                resp = self._bulk_in(bufsize, tmo_ms)
            except self._usb.core.USBError as e:
                self._abort_bulk_in(btag)
                raise TimeoutError(f'USBTMC (pyusb) sin respuesta: {e}') from e

            if len(resp) < 12 or resp[0] != self.MSG_ID_DEV_DEP_MSG_IN:
                self.clear()
                raise IOError(f'Respuesta USBTMC inválida ({len(resp)} bytes): {resp[:12]!r}')

            size = int.from_bytes(resp[4:8], 'little')
            eom = bool(resp[8] & 0x01)
            payload = resp[12:12 + size]
            # El mensaje puede venir partido en varios transfers bulk.
            while len(payload) < size:
                try:
                    payload += self._bulk_in(bufsize, tmo_ms)
                except self._usb.core.USBError as e:
                    self._abort_bulk_in(btag)
                    raise TimeoutError(f'USBTMC: mensaje incompleto ({len(payload)}/{size}): {e}') from e
            out += payload[:size]

            if eom or len(out) >= n:
                return out

    def close(self):
        try:
            self._usb.util.release_interface(self.dev, self.iface_num)
        except Exception:
            pass
        self._usb.util.dispose_resources(self.dev)



class _TransportUSBTMC:
    def __init__(self, device='/dev/usbtmc0'):
        self.f = open(device, 'r+b', buffering=0)

    def write(self, b):
        self.f.write(b)

    def read(self, n=4096, timeout=None):
        # select() sobre el fd del USBTMC: si no hay datos en `timeout` segundos
        # devolvemos TimeoutError antes de tocar f.read() (que bloquea sin límite).
        if timeout is not None:
            r, _, _ = select.select([self.f], [], [], timeout)
            if not r:
                raise TimeoutError(f'USBTMC sin respuesta en {timeout}s')
        return self.f.read(n)

    def close(self):
        self.f.close()


class _TransportTCP:
    def __init__(self, host, port=5555, timeout=5):
        self.s = socket.create_connection((host, port), timeout=timeout)

    def write(self, b):
        self.s.sendall(b)

    def read(self, n=4096, timeout=None):
        if timeout is not None:
            self.s.settimeout(timeout)
        try:
            return self.s.recv(n)
        except socket.timeout as e:
            raise TimeoutError(f'TCP sin respuesta en {timeout}s') from e

    def close(self):
        self.s.close()


class RigolDG4162:
    """Cliente SCPI para el Rigol DG4162 (160 MHz AWG). Métodos cubren el flujo
    de generación de pulsos para validación del scope multitrigger."""

    # Timeout default para todos los reads (segundos). Aplica a `query()`,
    # `check_error()`, etc. Si el instrumento no responde en este tiempo se
    # lanza TimeoutError en vez de colgar el proceso.
    DEFAULT_READ_TIMEOUT = 2.0

    def __init__(self, transport, read_timeout=None):
        self._t = transport
        self._read_timeout = read_timeout if read_timeout is not None else self.DEFAULT_READ_TIMEOUT
        self.id = self.query('*IDN?')

    # ---------- factory methods ----------
    @classmethod
    def usb(cls, vid=0x1ab1, pid=0x0641, serial=None):
        """Conexión USB directa vía pyusb/libusb (sin driver de kernel usbtmc).
        Usar cuando /dev/usbtmcN no está disponible."""
        return cls(_TransportUSBRaw(vid=vid, pid=pid, serial=serial))
        
    @classmethod
    def usbtmc(cls, device='/dev/usbtmc0'):
        """Conexión por USB. Probá `ls /dev/usbtmc*` para ver el device disponible."""
        return cls(_TransportUSBTMC(device))

    @classmethod
    def tcp(cls, host, port=5555):
        """Conexión TCP/IP (puerto 5555 SCPI raw, standard en los Rigol DG4000)."""
        return cls(_TransportTCP(host, port))

    @classmethod
    def vxi11(cls, host):
        """Conexión VXI-11 sobre LAN (más robusta que raw TCP en redes con proxy)."""
        return cls(_TransportVXI11(host))
    
    # ---------- SCPI low-level ----------

    def write(self, cmd):
        self._t.write(cmd.encode() + b'\n')

    def query(self, cmd, delay=0.05, timeout=None):
        """Write + read con timeout. Si el instrumento no responde, lanza
        TimeoutError (no se cuelga el proceso). `timeout=None` usa el default
        de la instancia (`self._read_timeout`)."""
        if timeout is None:
            timeout = self._read_timeout
        self.write(cmd)
        time.sleep(delay)
        return self._t.read(timeout=timeout).decode().strip()

    def clear(self):
        """Vacía los buffers de E/S del instrumento y limpia cualquier stall.
        Solo tiene efecto en el transporte USB crudo; en el resto es no-op."""
        clear = getattr(self._t, 'clear', None)
        return clear() if clear is not None else None

    def close(self):
        self._t.close()

    # ---------- alto nivel ----------

    def reset(self, settle_s=1.0, timeout=15.0):
        """*CLS + *RST, esperando a que el instrumento vuelva a responder.

        No se usa *OPC?: sobre USBTMC el DG4000 no lo contesta mientras está
        reseteando (y hay firmwares que directamente no lo implementan), así
        que el read se queda esperando una respuesta que nunca llega. En vez
        de eso se sondea con *IDN?, que responde apenas el reset termina.

        Sobre USBTMC un query sin respuesta es un timeout duro, no una espera:
        cada intento fallido aborta su transferencia bulk-IN pendiente antes
        de reintentar, para no leer una respuesta corrida en el próximo query.
        """
        self.write('*CLS')                     # vacía cola de errores primero
        self.write('*RST')
        time.sleep(settle_s)

        deadline = time.time() + timeout
        last = None
        while True:
            try:
                idn = self.query('*IDN?', timeout=1.0)
                if idn:
                    return idn
            except OSError as e:              # TimeoutError y USBError son OSError
                last = e
                if getattr(e, 'errno', None) == 19:   # ENODEV: se re-enumeró
                    raise IOError(
                        'El instrumento desapareció del bus USB durante el *RST; '
                        'hay que reabrir la conexión con RigolDG4162.usb()') from e
            if time.time() >= deadline:
                raise TimeoutError(
                    f'El Rigol no volvió a responder {timeout:g}s después de *RST'
                    + (f' (último error: {last})' if last else ''))
            self.clear()
            time.sleep(0.3)

    def output(self, ch, on, check_errors=False):
        """Enciende/apaga la salida del canal (ch=1 o 2).
        Con `check_errors=True` se valida la cola SCPI después del comando
        (1 round-trip extra)."""
        self.write(f':OUTPut{ch}:STATe {"ON" if on else "OFF"}')
        if check_errors:
            self.assert_ok(f'output(ch={ch}, on={on})')

    def assert_ok(self, ctx=''):
        """Lee la cola de errores SCPI con :SYSTem:ERRor? y lanza RuntimeError
        si el último comando dejó un error. `ctx` es texto libre para identificar
        qué llamada lo provocó.

        El Rigol responde 0 (o '+0') seguido de la descripción cuando no hay
        error; cualquier otro código numérico indica falla."""
        err = self.check_error()
        # Formato típico: '0,"No error"' o '-221,"Settings conflict"'.
        code = err.split(',', 1)[0].strip().lstrip('+')
        if code != '0':
            raise RuntimeError(f'Rigol SCPI error tras {ctx}: {err}')

    def set_pulse_periodic(self, ch=1, period_s=100e-6, width_s=200e-9,
                            amp_vpp=1.0, offset_v=0.5, check_errors=False):
        """Tren de pulsos PERIÓDICO con `period_s` entre flancos ascendentes.

        Parámetros:
          ch            : canal del Rigol (1 o 2).
          period_s      : período entre pulsos (s). 1/freq.
          width_s       : ancho de cada pulso (s). Tiene que ser < period_s/2.
          amp_vpp       : amplitud pico-pico (V).
          offset_v      : nivel DC del cero del pulso (V). Con amp_vpp=1.0 y
                          offset_v=0.5 el pulso va de 0 V a +1 V.
          check_errors  : si True, valida la cola SCPI después de los comandos.
                          Default False para no pagar el round-trip extra en
                          sweeps; subilo a True cuando estés debugueando.
        """
        if width_s >= period_s / 2:
            raise ValueError(f'width_s ({width_s}) debe ser < period_s/2 ({period_s/2})')
        freq = 1.0 / period_s
        # APPLy:PULSe <freq>,<vpp>,<offset>,<phase>
        self.write(f':SOURce{ch}:APPLy:PULSe {freq},{amp_vpp},{offset_v}')
        self.write(f':SOURce{ch}:PULSe:WIDTh {width_s}')
        # Asegurar burst off (modo continuo)
        self.write(f':SOURce{ch}:BURSt:STATe OFF')
        if check_errors:
            self.assert_ok(f'set_pulse_periodic(ch={ch}, period={period_s}, width={width_s})')

    def set_pulse_period(self, ch=1, period_s=100e-6, check_errors=False):
        """Cambiar SOLO el período de un pulse ya configurado (sweep barato).
        `check_errors=True` valida la cola SCPI después (round-trip extra)."""
        freq = 1.0 / period_s
        self.write(f':SOURce{ch}:FREQuency {freq}')
        if check_errors:
            self.assert_ok(f'set_pulse_period(ch={ch}, period={period_s})')

    def set_pulse_width(self, ch=1, width_s=200e-9, check_errors=False):
        """Cambiar SOLO el ancho del pulso.
        `check_errors=True` valida la cola SCPI después (round-trip extra)."""
        self.write(f':SOURce{ch}:PULSe:WIDTh {width_s}')
        if check_errors:
            self.assert_ok(f'set_pulse_width(ch={ch}, width={width_s})')

    def set_pulse_pair_burst(self, ch=1, gap_s=10e-6, width_s=200e-9,
                              amp_vpp=1.0, offset_v=0.5, burst_period_s=10e-3,
                              check_errors=False):
        """PAR DE PULSOS por burst: dos pulsos separados por `gap_s`, repetidos
        cada `burst_period_s`. Ideal para medir resolución par-pulso (pulse-pair
        resolution): cuán cerca pueden estar dos pulsos seguidos y todavía ser
        registrados como dos eventos distintos.

        Layout temporal por burst:
          |--width--|--(gap-width)--|--width--|--silencio (burst_period - 2*gap)--|
              ↑                          ↑
            pulso 1                   pulso 2  (flanco ascendente separado por gap)

        Parámetros:
          gap_s          : distancia entre los dos flancos ascendentes (s).
          width_s        : ancho de cada pulso.
          burst_period_s : tiempo entre el inicio de un par y el siguiente.
        """
        if width_s >= gap_s:
            raise ValueError(f'width_s ({width_s}) debe ser < gap_s ({gap_s})')
        if burst_period_s <= 2 * gap_s:
            raise ValueError(f'burst_period_s ({burst_period_s}) tiene que ser '
                             f'> 2*gap_s ({2 * gap_s})')
        # gap_s = período del pulse → 1/freq dentro del burst
        freq = 1.0 / gap_s
        self.write(f':SOURce{ch}:APPLy:PULSe {freq},{amp_vpp},{offset_v}')
        self.write(f':SOURce{ch}:PULSe:WIDTh {width_s}')
        self.write(f':SOURce{ch}:BURSt:NCYCles 2')
        self.write(f':SOURce{ch}:BURSt:MODE TRIG')
        self.write(f':SOURce{ch}:BURSt:TRIGger:SOURce INTernal')
        self.write(f':SOURce{ch}:BURSt:INTernal:PERiod {burst_period_s}')
        self.write(f':SOURce{ch}:BURSt:STATe ON')
        if check_errors:
            self.assert_ok(f'set_pulse_pair_burst(ch={ch}, gap={gap_s}, burst_period={burst_period_s})')

    def disable_burst(self, ch=1, check_errors=False):
        self.write(f':SOURce{ch}:BURSt:STATe OFF')
        if check_errors:
            self.assert_ok(f'disable_burst(ch={ch})')

    # ================================================================
    # Forma de onda ARBITRARIA
    #
    # Hace falta para caracterizar el MCA: con pulso rectangular no se puede
    # ni sintetizar un pulso de detector realista, ni generar dos poblaciones
    # con colas distintas (sin las cuales no hay FOM que medir), ni hacer el
    # sliding pulser que mide la DNL.
    #
    # AVISO: estos métodos siguen la guía de programación de la serie DG4000
    # pero NO pudieron probarse contra el instrumento. Verificar con
    # assert_ok() la primera vez que se usen.
    # ================================================================

    ARB_MAX_POINTS = 16384        # memoria de forma arbitraria por canal

    def load_arb(self, samples, ch=1, check_errors=True, normalize=True):
        """Carga una forma de onda normalizada en la memoria volátil del canal.

        `samples` es cualquier secuencia numérica; se re-escala automáticamente
        al rango [-1, 1] que espera el instrumento (la amplitud real la fija
        `set_arb` con amp_vpp). Se manda en trozos porque una sola línea SCPI
        con 16384 números supera el largo de comando admitido.

        `normalize=False` para formas que YA vienen en [-1, 1] con una escala
        elegida a propósito. Hace falta cuando la escala tiene que ser la MISMA
        entre formas distintas: con arribos Poisson el máximo depende de cuánto
        pile-up tocó esa semilla, así que normalizar por el máximo movería la
        altura del pulso individual —y con ella el pico del espectro— de una
        realización a la otra. Ver `poisson_train_wave` (headroom).
        """
        import numpy as _np
        v = _np.asarray(samples, dtype=float).ravel()
        if v.size == 0:
            raise ValueError('la forma de onda está vacía')
        if v.size > self.ARB_MAX_POINTS:
            raise ValueError(f'{v.size} puntos > {self.ARB_MAX_POINTS} '
                             'de memoria arbitraria')
        if normalize:
            peak = _np.abs(v).max()
            if peak > 0:
                v = v / peak
        elif _np.abs(v).max() > 1.0 + 1e-9:
            raise ValueError('con normalize=False la forma tiene que venir en '
                             f'[-1, 1] (máximo {_np.abs(v).max():.3f})')
        v = _np.clip(v, -1.0, 1.0)

        # UN solo comando con todos los puntos.
        #
        # El troceado con `:DATA:CATenate` NO sirve: este firmware (00.01.05)
        # responde -113 "Undefined header; command cannot be found". Verificado
        # contra el instrumento. La forma soportada es mandar la lista completa
        # en un `:DATA VOLATILE,...`, que con 16384 puntos son ~130 KB de
        # comando — el DG4000 los acepta por USBTMC.
        #
        # Se usan 4 decimales en vez de 5 para acortar el comando sin perder
        # resolución útil: el DAC del instrumento es de 14 bits (~6e-5).
        cuerpo = ','.join(f'{x:.4f}' for x in v)
        self.write(f':SOURce{ch}:DATA VOLATILE,{cuerpo}')
        if check_errors:
            self.assert_ok(f'load_arb(ch={ch}, n={v.size})')
        return v.size

    def set_arb(self, ch=1, freq_hz=1e3, amp_vpp=1.0, offset_v=0.0,
                phase_deg=0.0, check_errors=False):
        """Aplica la forma de onda cargada en VOLATILE.

        `freq_hz` es la frecuencia de REPETICIÓN de la forma completa. Si la
        forma contiene N pulsos, la tasa de pulsos es N*freq_hz — es así como
        se llega a tasas altas sin quedarse sin memoria.

        OJO: el instrumento estira la forma COMPLETA sobre 1/freq_hz, así que el
        ancho de cada pulso no es un parámetro sino una consecuencia de cuántos
        puntos ocupa dentro de la forma. Para fijar el ancho en segundos, armar
        la forma con `pulse_train_wave()`, que despeja la frecuencia.
        """
        self.write(f':SOURce{ch}:BURSt:STATe OFF')
        self.write(f':SOURce{ch}:APPLy:USER {freq_hz:g},{amp_vpp:g},'
                   f'{offset_v:g},{phase_deg:g}')
        if check_errors:
            self.assert_ok(f'set_arb(ch={ch}, f={freq_hz})')

    # ================================================================
    # Modulación
    # ================================================================

    def set_am_noise(self, ch=1, depth_pct=100.0, check_errors=True):
        """Modulación AM con la fuente de RUIDO interna.

        Es el camino canónico para el *sliding pulser* de la DNL: hace que la
        amplitud varíe de forma CONTINUA en el tiempo, en vez de repetir un
        conjunto finito de valores como hace una forma arbitraria cíclica (que
        produce líneas discretas en el espectro y una DNL sin sentido).

        `check_errors=True` por default y a propósito: estos comandos NO se
        pudieron probar contra el instrumento, y hay precedente de que la guía
        de programación no coincide con el firmware (`:DATA:CATenate` responde
        -113 "Undefined header"). Si el firmware los rechaza, esto levanta
        RuntimeError y el llamador puede caer a la vía alternativa.
        """
        self.write(f':SOURce{ch}:MOD:STATe ON')
        self.write(f':SOURce{ch}:MOD:TYPE AM')
        self.write(f':SOURce{ch}:AM:SOURce INTernal')
        self.write(f':SOURce{ch}:AM:INTernal:FUNCtion NOISe')
        self.write(f':SOURce{ch}:AM:DEPTh {depth_pct:g}')
        if check_errors:
            self.assert_ok(f'set_am_noise(ch={ch}, depth={depth_pct})')

    def set_mod_off(self, ch=1, check_errors=False):
        """Apaga cualquier modulación del canal."""
        self.write(f':SOURce{ch}:MOD:STATe OFF')
        if check_errors:
            self.assert_ok(f'set_mod_off(ch={ch})')


# ---------- helpers ----------

    def check_error(self):
        """Devuelve el último error SCPI (o '0,\"No error\"' si OK).
        Usa timeout corto: si no responde es síntoma de hang, no demora."""
        return self.query(':SYSTem:ERRor?', timeout=1.0)

    def clear_errors(self, max_n=32):
        """Vacía la COLA de errores SCPI y devuelve los que había.

        Hace falta después de un comando rechazado: la cola es FIFO y guarda
        varios errores, pero `assert_ok` saca uno solo. Si un método escribe 5
        comandos y el firmware rechaza los 5 (p. ej. `set_am_noise` en este
        DG4162, que no soporta modulación por SCPI), quedan 4 errores viejos y
        el PRÓXIMO `assert_ok` los atribuye a un comando que en realidad
        funcionó — medido: `load_arb` fallaba con el -113 de la modulación.
        """
        vistos = []
        for _ in range(max_n):
            try:
                e = self.check_error()
            except Exception:
                break
            if e.strip().startswith('0,'):
                break
            vistos.append(e.strip())
        return vistos

    def drain(self):
        """Vacía cualquier respuesta pendiente en la cola del transporte (sin
        bloquear). Útil si quedó algo de un Ctrl+C anterior y el próximo
        query() lee la respuesta vieja en vez de la nueva."""
        try:
            while True:
                self._t.read(timeout=0.1)
        except TimeoutError:
            return

    def __repr__(self):
        return f'<RigolDG4162 {self.id!r}>'


# ================================================================
# Constructores de forma de onda (numpy puro, sin instrumento)
#
# Se dejan fuera de la clase a propósito: son funciones puras, así que se
# pueden graficar y validar sin tener el Rigol conectado.
# ================================================================

def detector_pulse(n_pts=64, t_rise=4.0, tau=16.0, amplitude=1.0, t0=2.0):
    """Pulso de detector: subida suave y cola exponencial.

    Es la forma que hace falta para que el MCA vea algo parecido a un evento
    real; un rectángulo no ejercita ni el tiempo de subida ni la relación
    Q_cola/Q_total, que es el observable del eje de forma.

    `tau` controla la cola: es el parámetro que separa las dos poblaciones en
    una medición de PSD.
    """
    import numpy as _np
    t = _np.arange(n_pts, dtype=float) - t0
    y = _np.where(t < 0, 0.0,
                  (1.0 - _np.exp(-t / max(t_rise, 1e-6))) * _np.exp(-t / max(tau, 1e-6)))
    peak = y.max()
    return (amplitude * y / peak) if peak > 0 else y


def two_population_wave(n_pulses=64, pts_per_pulse=128, tau_a=12.0, tau_b=40.0,
                        frac_b=0.5, amplitude=1.0, t_rise=4.0, seed=0):
    """Forma con dos poblaciones de pulsos que difieren SÓLO en la cola.

    Misma amplitud, distinto `tau`: es exactamente el estímulo que separa dos
    grupos en el eje de factor de forma sin moverlos en el eje de amplitud, o
    sea el caso que permite medir la FOM de forma limpia.
    """
    import numpy as _np
    rng = _np.random.default_rng(seed)
    out = _np.zeros(n_pulses * pts_per_pulse)
    for k in range(n_pulses):
        tau = tau_b if rng.random() < frac_b else tau_a
        out[k * pts_per_pulse:(k + 1) * pts_per_pulse] = detector_pulse(
            pts_per_pulse, t_rise=t_rise, tau=tau, amplitude=amplitude)
    return out


def sliding_pulser_wave(n_pulses=128, pts_per_pulse=128, tau=16.0,
                        t_rise=4.0, amp_min=0.1, amp_max=1.0, seed=0):
    """Forma con pulsos de amplitud UNIFORMEMENTE aleatoria (sliding pulser).

    Es el estímulo canónico para medir la DNL: si todos los canales tienen el
    mismo ancho, un barrido uniforme de amplitud tiene que llenarlos a todos
    por igual, y la desviación relativa respecto de esa media ES la DNL.
    """
    import numpy as _np
    rng = _np.random.default_rng(seed)
    out = _np.zeros(n_pulses * pts_per_pulse)
    amps = rng.uniform(amp_min, amp_max, n_pulses)
    for k, a in enumerate(amps):
        out[k * pts_per_pulse:(k + 1) * pts_per_pulse] = detector_pulse(
            pts_per_pulse, t_rise=t_rise, tau=tau, amplitude=a)
    return out


# ================================================================
# Tren de pulsos con el ancho fijado EN SEGUNDOS
#
# Los constructores de arriba trabajan en PUNTOS, y el ancho real que sale
# depende de a qué frecuencia se aplique la forma: `set_arb` estira la forma
# completa sobre 1/freq. Con 128 puntos a 2 kHz cada punto dura 3.9 us y un
# pulso de 64 puntos termina durando ~240 us — cuatro ordenes de magnitud mas
# que un pulso de detector. Eso contamina tiempo muerto, apilamiento, `maxlen`
# y par-pulso a la vez.
#
# `pulse_train_wave` invierte la relacion: se le pide el ancho en segundos y la
# tasa en Hz, y devuelve la forma JUNTO CON la frecuencia a la que hay que
# aplicarla.
# ================================================================

ARB_MAX_POINTS = 16384         # memoria de forma arbitraria por canal
ARB_MAX_SRATE  = 500e6         # Sa/s, tasa de muestreo maxima del ARB (DG4000)


def _fwhm_pts(y):
    """Ancho a media altura en puntos, con interpolacion lineal en los cruces."""
    import numpy as _np
    y = _np.asarray(y, dtype=float)
    pk = y.max()
    if pk <= 0:
        return 0.0
    half = 0.5 * pk
    above = _np.flatnonzero(y >= half)
    if above.size == 0:
        return 0.0
    i0, i1 = above[0], above[-1]
    # cruce de subida entre i0-1 e i0
    if i0 > 0 and y[i0] != y[i0 - 1]:
        x0 = i0 - 1 + (half - y[i0 - 1]) / (y[i0] - y[i0 - 1])
    else:
        x0 = float(i0)
    # cruce de bajada entre i1 e i1+1
    if i1 + 1 < y.size and y[i1] != y[i1 + 1]:
        x1 = i1 + (y[i1] - half) / (y[i1] - y[i1 + 1])
    else:
        x1 = float(i1)
    return float(x1 - x0)


def _shape_scale_for_fwhm(fwhm_pts, t_rise_frac, tau_frac, tau_mult=1.0):
    """Escala de la forma que da el FWHM pedido.

    El FWHM es lineal en la escala, asi que alcanza con medirlo UNA vez sobre
    una version sobre-muestreada y despejar. Se hace numericamente en vez de
    con la formula cerrada porque `detector_pulse` normaliza al pico y la
    relacion FWHM/escala depende de t_rise_frac y tau_frac.
    """
    probe_scale = 256.0
    probe = detector_pulse(4096,
                           t_rise=max(t_rise_frac * probe_scale, 1e-6),
                           tau=max(tau_frac * tau_mult * probe_scale, 1e-6),
                           amplitude=1.0, t0=0.0)
    k = _fwhm_pts(probe) / probe_scale
    if k <= 0:
        raise ValueError('forma degenerada: revisá t_rise_frac / tau_frac')
    return fwhm_pts / k


MIN_RISE_PTS = 4               # menos que esto y el flanco queda cuantizado


def pulse_train_wave(width_s, rate_hz, n_pts_max=ARB_MAX_POINTS,
                     t_rise_frac=0.25, tau_frac=0.6, amplitude=1.0,
                     amp_range=None, tau_choices=None, n_pulses=None,
                     pts_per_fwhm=64, srate_max=ARB_MAX_SRATE, seed=0,
                     tail_tol=0.02):
    """Tren de pulsos con FWHM = `width_s` y tasa = `rate_hz`.

    (Con `tau_choices`, `width_s` es el FWHM de la población de referencia: las
    otras comparten el flanco de subida y sólo cambian la cola.)

    Devuelve `(wave, freq_hz, info)`:

      wave    : forma normalizada, lista para `load_arb`
      freq_hz : frecuencia de REPETICIÓN a pasarle a `set_arb`
      info    : dict con la geometría elegida (ver abajo)

    La geometría sale de una sola identidad: el ciclo de trabajo del tren es
    `duty = width_s * rate_hz`, y no depende de cómo se reparta la memoria. Lo
    que sí se elige es `slot_pts`, los puntos que ocupa UN período de
    repetición, porque de ahí salen las tres cosas que limitan:

      tasa de muestreo = slot_pts * rate_hz   <= srate_max
      puntos por pulso = duty * slot_pts      >= los que pida el flanco
      pulsos por forma = n_pts_max // slot_pts

    El reparto por default apunta a `pts_per_fwhm` puntos a lo ancho del pulso y
    mete tantos pulsos como entren con eso, porque **más pulsos por forma es más
    variedad de amplitudes por ciclo** (que es lo que necesitan la DNL y la FOM)
    y la resolución temporal por encima de ~64 puntos no aporta nada. La
    frecuencia de repetición es `rate_hz / n_pulses`.

    El número de pulsos que entran depende del duty, o sea de la tasa: a 2 kHz
    con pulsos de 2 µs el duty es 0.4 % y **entra uno solo**; a 100 kHz entran
    decenas. Si se piden amplitudes o colas variables y sólo entra un pulso,
    esto levanta ValueError en vez de devolver una forma degenerada.

    Parámetros de forma:
      t_rise_frac, tau_frac : subida y cola, en fracciones de la escala del
                              pulso (la escala se despeja para que el FWHM dé
                              `width_s`).
      amplitude             : amplitud de todos los pulsos (normalizada).
      amp_range=(lo,hi)     : si se pasa, cada pulso toma una amplitud uniforme
                              en ese rango — es el *sliding pulser* de la DNL.
      tau_choices=(a,b,...) : si se pasa, cada pulso toma al azar uno de esos
                              multiplicadores de cola — dos poblaciones para la
                              FOM. Combinado con `amp_range` da poblaciones que
                              además se reparten sobre el eje de amplitud, que
                              es lo que hace falta para la FOM vs energía.
      n_pulses              : forzar cuántos pulsos entran en la forma.
      pts_per_fwhm          : puntos objetivo a lo ancho del pulso (default 64).
                              Bajarlo mete más pulsos a costa de resolución.

    Levanta ValueError con un mensaje que dice qué ajustar cuando la
    combinación pedida no entra: es preferible a devolver una forma que en la
    placa se traduce en pulsos de otro ancho.
    """
    import numpy as _np

    if width_s <= 0 or rate_hz <= 0:
        raise ValueError('width_s y rate_hz tienen que ser positivos')
    duty = float(width_s) * float(rate_hz)
    if duty >= 0.5:
        raise ValueError(
            f'duty = width_s*rate_hz = {duty:.3f} >= 0.5: los pulsos se '
            f'solapan. Bajá el ancho o la tasa.')

    # --- geometría ---
    # Cota dura: el flanco necesita MIN_RISE_PTS puntos.
    slot_min = int(_np.ceil(MIN_RISE_PTS / max(t_rise_frac, 1e-9) / duty))
    # Cota superior: memoria y tasa de muestreo del instrumento.
    slot_cap = int(min(n_pts_max, _np.floor(srate_max / rate_hz)))
    if slot_min > slot_cap:
        raise ValueError(
            f'el flanco de subida entraría en {MIN_RISE_PTS * slot_cap / slot_min:.1f} '
            f'puntos (mínimo {MIN_RISE_PTS}): con {width_s*1e6:g} us a '
            f'{rate_hz:g} Hz harían falta {slot_min} puntos por período y el '
            f'instrumento admite {slot_cap} ({srate_max:g} Sa/s, '
            f'{n_pts_max} pts). Subí width_s o bajá rate_hz.')

    if n_pulses is None:
        # Apuntar a pts_per_fwhm puntos por pulso y meter todos los que entren:
        # más pulsos = más variedad de amplitudes por ciclo.
        slot_want = int(_np.ceil(pts_per_fwhm / duty))
        slot_pts  = int(min(max(slot_want, slot_min), slot_cap))
        n_pulses  = max(1, n_pts_max // slot_pts)
    else:
        n_pulses = int(n_pulses)
        if n_pulses < 1:
            raise ValueError('n_pulses tiene que ser >= 1')
        slot_pts = int(min(n_pts_max // n_pulses, slot_cap))
        if slot_pts < slot_min:
            raise ValueError(
                f'con n_pulses={n_pulses} quedan {slot_pts} puntos por período '
                f'y hacen falta {slot_min}. Bajá n_pulses a '
                f'{max(1, n_pts_max // slot_min)} o menos.')

    n_total  = slot_pts * n_pulses
    freq_hz  = rate_hz / n_pulses
    srate    = slot_pts * rate_hz                 # = n_total * freq_hz
    dt_s     = 1.0 / srate
    fwhm_pts = duty * slot_pts                    # = width_s / dt_s
    n_rise   = fwhm_pts * t_rise_frac

    # Pedir variedad con un solo pulso por forma da una forma degenerada: la
    # misma amplitud (o la misma cola) repetida para siempre. Es exactamente el
    # modo de falla que invalidó la DNL de la campaña, así que se rechaza.
    if n_pulses < 2 and (amp_range is not None or tau_choices is not None):
        rate_min = pts_per_fwhm / (width_s * n_pts_max) * 2
        raise ValueError(
            f'sólo entra {n_pulses} pulso por forma, así que amp_range/'
            f'tau_choices darían un valor único repetido (duty={duty:.4f}). '
            f'Subí rate_hz por encima de ~{rate_min:.0f} Hz, subí width_s, o '
            f'bajá pts_per_fwhm.')

    # --- forma ---
    rng   = _np.random.default_rng(seed)
    amps  = (rng.uniform(amp_range[0], amp_range[1], n_pulses)
             if amp_range is not None else _np.full(n_pulses, float(amplitude)))
    taus  = (rng.choice(_np.asarray(tau_choices, dtype=float), n_pulses)
             if tau_choices is not None else _np.ones(n_pulses))

    # La escala se calibra UNA vez, con la cola de referencia (tau_mult=1), y se
    # usa igual para todos los pulsos. O sea: todas las poblaciones comparten el
    # flanco de subida y difieren SÓLO en la cola, que es el caso físico (y el
    # que separa en el eje de forma). Recalibrar por pulso mantendría el FWHM
    # constante encogiendo el resto del pulso, lo que cancela buena parte de la
    # diferencia de cola: medido con tau_choices=(1,3), la separación en
    # Q_cola/Q_total pasaba de 0.36 a 0.05. `width_s` es entonces el FWHM de la
    # población de referencia (tau_mult=1).
    scale = _shape_scale_for_fwhm(fwhm_pts, t_rise_frac, tau_frac, 1.0)

    out = _np.zeros(n_total)
    residual = 0.0
    for k in range(n_pulses):
        p = detector_pulse(slot_pts,
                           t_rise=max(t_rise_frac * scale, 1e-6),
                           tau=max(tau_frac * taus[k] * scale, 1e-6),
                           amplitude=amps[k], t0=0.0)
        residual = max(residual, float(p[-1]) / max(float(p.max()), 1e-12))
        out[k * slot_pts:(k + 1) * slot_pts] = p

    if residual > tail_tol:
        raise ValueError(
            f'la cola todavía vale el {100*residual:.1f}% del pico al terminar '
            f'el período: los pulsos se pisarían. Bajá tau_frac o el duty '
            f'(duty={duty:.3f}).')

    info = dict(n_pts=n_total, n_pulses=n_pulses, slot_pts=slot_pts,
                freq_hz=freq_hz, srate_sa_s=srate, dt_s=dt_s,
                fwhm_pts=fwhm_pts, duty=duty,
                width_s=width_s, rate_hz=rate_hz,
                n_rise_pts=n_rise, tail_residual=residual)
    return out, freq_hz, info


# ================================================================
# Arribos POISSON
#
# Todo el barrido de throughput se hizo con el modo PULSE, que es un tren
# PERIODICO. Con arribos deterministas y un solo servidor sin cola (K=1) el
# sistema no pierde NADA mientras el periodo supere el tiempo de servicio, y
# recien ahi cae en escalones: la eficiencia de 99% a 2 kHz es un artefacto del
# estimulo, no una propiedad del equipo. Una fuente radiactiva entrega arribos
# de Poisson, y ahi la perdida es rho/(1+rho) con rho = lambda*tau -- o sea que
# se pierde algo a CUALQUIER tasa.
#
# Este generador arma la forma arbitraria con arribos exponenciales para poder
# medir esa curva.
# ================================================================


def poisson_train_wave(rate_hz, width_s, n_events=64, n_pts_max=ARB_MAX_POINTS,
                       t_rise_frac=0.25, tau_frac=0.6, amplitude=1.0,
                       amp_range=None, tau_choices=None, headroom=3.0,
                       fixed_n=False, min_rise_pts=MIN_RISE_PTS,
                       srate_max=ARB_MAX_SRATE, seed=0, tail_tol=0.01):
    """Tren de pulsos con arribos de POISSON a tasa `rate_hz` y FWHM `width_s`.

    Devuelve `(wave, freq_hz, info)` igual que `pulse_train_wave`, así se
    aplica con el mismo par `load_arb` + `set_arb` — pero **con
    `normalize=False`** (ver `headroom` abajo).

    Cómo se sortean los arribos
    ---------------------------
    NO se acumulan intervalos exponenciales. Se usa que un proceso de Poisson
    condicionado a `N` eventos en `[0, T)` tiene las `N` posiciones **uniformes
    i.i.d.**: se sortea `N ~ Poisson(rate*T)` y después las posiciones. Es
    exactamente equivalente, y además arregla la costura: el ARB **repite** la
    forma cada `1/freq_hz`, y con posiciones uniformes sobre el círculo el
    empalme no deja un hueco determinista (un `cumsum` de exponenciales sí lo
    deja, y ese hueco fijo se cuela en toda la estadística de intervalos).

    Los pulsos se **suman** (superposición) y la envoltura es circular, así que
    el pile-up ocurre como en un detector real y un pulso que arranca cerca del
    final continúa al principio.

    Geometría y su compromiso
    -------------------------
    `T_ciclo = n_events/rate_hz`, `dt = T_ciclo/n_pts`, o sea

        dt = n_events / (rate_hz * n_pts)

    Con 16384 puntos: a 217 kcps y 64 eventos por ciclo, `dt = 18 ns` y un pulso
    de 2 µs entra holgado. A 400 ev/s el mismo reparto da `dt = 9.8 µs` y el
    pulso tiene que ser MUCHO más ancho. Es memoria contra tasa y no hay forma
    de esquivarlo; lo que sí se puede es bajar `n_events` (más recargas para la
    misma estadística) o subir `width_s`. Para medir *pérdidas* alcanza con que
    `width_s << tau` del sistema; si además se quiere el espectro, el ancho
    importa y conviene quedarse en tasas altas.

    Parámetros propios
    ------------------
      n_events    : eventos MEDIOS por ciclo. Fija la duración del ciclo y por
                    lo tanto `dt`. Más eventos = mejor estadística por
                    realización, peor resolución temporal.
      fixed_n     : `True` fuerza exactamente `n_events` (proceso binomial, sin
                    fluctuación de conteo). Default `False` = Poisson de verdad.
      headroom    : la forma se escala dividiendo por `headroom * amplitud de UN
                    pulso`, no por el máximo de la forma. Así la altura del
                    pulso individual es la misma en todas las realizaciones
                    (`amp_single_rel = 1/headroom`) y el pico del espectro no se
                    mueve con la semilla. Los apilamientos de más de `headroom`
                    pulsos se recortan — se reporta en `frac_clip`.
      min_rise_pts: puntos mínimos del flanco de subida. Bajarlo a 1-2 permite
                    tasas bajas con pulsos angostos a costa de la forma; es
                    válido si sólo se mide temporizado/pérdidas.

    `info` trae lo que hace falta para interpretar y para la meta del .npz:
    `n_events` real, `rate_real`, `dt_s`, `srate_sa_s`, `freq_hz`, `fwhm_pts`,
    `frac_pileup` (medida) y `frac_pileup_teo` (`1-exp(-2*lambda*width)`),
    `gap_min_s`, `amp_single_rel`, `frac_clip`, `jitter_dt_s`, `seed`.
    """
    import numpy as _np

    if rate_hz <= 0 or width_s <= 0:
        raise ValueError('rate_hz y width_s tienen que ser positivos')
    if n_events < 1:
        raise ValueError('n_events tiene que ser >= 1')
    if headroom <= 0:
        raise ValueError('headroom tiene que ser positivo')

    n_pts   = int(n_pts_max)
    T_ciclo = float(n_events) / float(rate_hz)
    dt_s    = T_ciclo / n_pts
    srate   = 1.0 / dt_s
    freq_hz = 1.0 / T_ciclo                      # = rate_hz / n_events

    if srate > srate_max:
        raise ValueError(
            f'harían falta {srate:.3g} Sa/s y el instrumento da {srate_max:.3g}. '
            f'Subí n_events (ahora {n_events}) o bajá rate_hz.')

    fwhm_pts = width_s / dt_s
    n_rise   = fwhm_pts * t_rise_frac
    if n_rise < min_rise_pts:
        width_min = min_rise_pts * dt_s / t_rise_frac
        n_ev_max  = int(_np.floor(t_rise_frac * width_s * rate_hz * n_pts
                                  / min_rise_pts))
        raise ValueError(
            f'el flanco entraría en {n_rise:.1f} puntos (mínimo {min_rise_pts}): '
            f'con {n_events} eventos por ciclo a {rate_hz:g} Hz el paso es '
            f'{dt_s*1e6:.2f} us. Subí width_s a >= {width_min*1e6:.1f} us, bajá '
            f'n_events a <= {max(n_ev_max, 1)}, o bajá min_rise_pts si sólo te '
            f'importa el temporizado.')

    # --- arribos: N ~ Poisson(lambda*T), posiciones uniformes en el circulo ---
    rng = _np.random.default_rng(seed)
    n_arr = int(n_events) if fixed_n else int(rng.poisson(rate_hz * T_ciclo))
    if n_arr < 1:
        raise ValueError(
            f'la realización salió con {n_arr} eventos (media {rate_hz*T_ciclo:.1f}). '
            'Subí n_events o cambiá la semilla.')
    pos = _np.sort(rng.uniform(0.0, n_pts, n_arr))       # en puntos, float
    idx = _np.floor(pos).astype(int) % n_pts             # a la grilla del DAC

    amps = (rng.uniform(amp_range[0], amp_range[1], n_arr)
            if amp_range is not None else _np.full(n_arr, float(amplitude)))
    taus = (rng.choice(_np.asarray(tau_choices, dtype=float), n_arr)
            if tau_choices is not None else _np.ones(n_arr))

    # --- forma de UN pulso, con la escala que da el FWHM pedido ---
    scale = _shape_scale_for_fwhm(fwhm_pts, t_rise_frac, tau_frac, 1.0)
    tau_max = float(_np.max(taus))
    # largo hasta que la cola cae por debajo de tail_tol
    n_pulso = int(min(n_pts, max(int(_np.ceil(tau_frac * tau_max * scale
                                              * _np.log(1.0 / tail_tol))), 8)))

    out = _np.zeros(n_pts)
    for k in range(n_arr):
        p = detector_pulse(n_pulso,
                           t_rise=max(t_rise_frac * scale, 1e-6),
                           tau=max(tau_frac * taus[k] * scale, 1e-6),
                           amplitude=amps[k], t0=0.0)
        # envoltura circular: lo que se pasa del final entra por el principio
        j = (idx[k] + _np.arange(n_pulso)) % n_pts
        _np.add.at(out, j, p)

    # --- escala FIJA (ver headroom): no se normaliza por el maximo ---
    ref = headroom * float(_np.max(amps))
    wave = out / ref
    frac_clip = float(_np.mean(wave > 1.0))
    wave = _np.clip(wave, -1.0, 1.0)

    # --- estadistica de la realizacion ---
    gaps = _np.diff(_np.concatenate([pos, [pos[0] + n_pts]])) * dt_s  # circular
    vecino = _np.minimum(gaps, _np.roll(gaps, 1))          # al vecino mas cercano
    info = dict(
        n_pts=n_pts, n_events=n_arr, n_events_medio=float(n_events),
        rate_hz=float(rate_hz), rate_real=n_arr / T_ciclo,
        width_s=float(width_s), T_ciclo_s=T_ciclo, freq_hz=freq_hz,
        dt_s=dt_s, srate_sa_s=srate, fwhm_pts=fwhm_pts, n_rise_pts=n_rise,
        n_pulso_pts=n_pulso,
        frac_pileup=float(_np.mean(vecino < width_s)),
        frac_pileup_teo=float(1.0 - _np.exp(-2.0 * rate_hz * width_s)),
        gap_min_s=float(gaps.min()), gap_med_s=float(_np.median(gaps)),
        amp_single_rel=float(amplitude / ref), frac_clip=frac_clip,
        jitter_dt_s=dt_s,          # cuantizacion del arribo a la grilla del DAC
        seed=int(seed), fixed_n=bool(fixed_n), headroom=float(headroom),
    )
    return wave, freq_hz, info


def apply_poisson_train(gen, rate_hz, width_s, ch=1, amp_vpp=0.5,
                        offset_v=None, seed=0, check_errors=False, **kw):
    """Arma, sube y aplica un tren Poisson. Devuelve el `info` del generador.

    Es el atajo pensado para el `on_chunk` de `MCA.acquire_chunks`: una semilla
    distinta por trozo hace que el resultado no dependa de qué realización tocó.
    """
    wave, freq_hz, info = poisson_train_wave(rate_hz, width_s, seed=seed, **kw)
    gen.load_arb(wave, ch=ch, normalize=False, check_errors=check_errors)
    gen.set_arb(ch=ch, freq_hz=freq_hz, amp_vpp=amp_vpp,
                offset_v=(amp_vpp / 2 if offset_v is None else offset_v),
                check_errors=check_errors)
    return info
