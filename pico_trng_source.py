"""
pico_trng_source.py

Bridge to the RP2350 (Raspberry Pi Pico 2) hardware TRNG firmware
built for this project. Talks the trivial request/response protocol
implemented in dice_rng_firmware/main.c: send 'R', receive exactly
32 raw bytes from the chip's on-die hardware TRNG.

This module does ONE job: get real bytes off the hardware, with a
minimal sanity check that the connection/firmware is actually alive
and not returning obviously-degenerate output (all-zero, all-same-byte).
It is NOT a substitute for SeedPrimer's own statistical testing
-- those tests run on card/dice draws specifically. This is a
independent hardware source meant to be XORed into the whitened
entropy, per the "combine independent sources" principle: as long as
this source is uniform, XOR-mixing it in cannot make the result worse
than the card/dice source alone, even in the worst case.

No network code. Requires pyserial (already present on this machine).
"""

import serial
import time

DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 115200
CHUNK_BYTES = 32


class PicoTrngError(Exception):
    pass


def _read_chunk(ser: serial.Serial) -> bytes:
    ser.reset_input_buffer()
    ser.write(b"R")
    chunk = ser.read(CHUNK_BYTES)
    if len(chunk) != CHUNK_BYTES:
        raise PicoTrngError(
            f"Expected {CHUNK_BYTES} bytes from Pico TRNG, got {len(chunk)}. "
            "Check the device is flashed with dice_rng_firmware and connected."
        )
    return chunk


def _sanity_check(chunk: bytes):
    """Minimal degeneracy check -- catches a dead/misconfigured/disconnected
    device returning garbage, not a substitute for real statistical testing."""
    if chunk == bytes(CHUNK_BYTES):
        raise PicoTrngError("Pico TRNG returned an all-zero chunk -- treat as untrusted, do not use.")
    if len(set(chunk)) == 1:
        raise PicoTrngError(
            f"Pico TRNG returned a chunk of a single repeated byte (0x{chunk[0]:02x}) "
            "-- treat as untrusted, do not use."
        )


def get_trng_bytes(n_bytes: int, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD) -> bytes:
    """
    Returns exactly n_bytes of raw hardware TRNG output from the Pico,
    requesting 32-byte chunks as needed and concatenating. Raises
    PicoTrngError if the device isn't reachable or returns degenerate
    output on any chunk.
    """
    if n_bytes <= 0:
        raise ValueError("n_bytes must be positive")

    out = bytearray()
    try:
        with serial.Serial(port, baudrate=baud, timeout=3) as ser:
            time.sleep(2)  # let USB CDC settle on first open
            while len(out) < n_bytes:
                chunk = _read_chunk(ser)
                _sanity_check(chunk)
                out += chunk
    except serial.SerialException as e:
        raise PicoTrngError(f"Could not open {port}: {e}") from e

    return bytes(out[:n_bytes])


def get_trng_bulk(n_bytes: int, port: str = DEFAULT_PORT,
                  baud: int = DEFAULT_BAUD) -> bytes:
    """
    Fetch n_bytes from the Pico in one persistent serial session.
    Much faster than repeated get_trng_bytes() calls because the
    2-second USB CDC settle happens only once. Suitable for bulk
    prefetch before a Monte Carlo run.
    Returns exactly n_bytes (may be slightly more, truncated).
    """
    n_chunks = -(-n_bytes // CHUNK_BYTES)  # ceiling division
    out = bytearray()
    try:
        with serial.Serial(port, baudrate=baud, timeout=3) as ser:
            time.sleep(2)
            ser.reset_input_buffer()
            for _ in range(n_chunks):
                ser.write(b"R")
                chunk = ser.read(CHUNK_BYTES)
                if len(chunk) != CHUNK_BYTES:
                    raise PicoTrngError(
                        f"Short read during bulk fetch: got {len(chunk)}/{CHUNK_BYTES}")
                _sanity_check(chunk)
                out += chunk
    except serial.SerialException as e:
        raise PicoTrngError(f"Could not open {port}: {e}") from e
    return bytes(out[:n_bytes])


# Raspberry Pi Foundation USB Vendor ID and Pico CDC Product ID.
# Only devices matching this VID:PID are considered candidates.
# This prevents the port scanner from probing unrelated serial devices.
PICO_VID = 0x2E8A
PICO_PID = 0x0009


def scan_ports() -> list:
    """Return serial ports belonging to a Raspberry Pi Pico (VID:PID 2e8a:0009).
    Uses pyserial's list_ports to filter by VID/PID before probing -- no
    unrelated serial devices are ever opened or probed.
    Falls back to glob-based scan if pyserial list_ports is unavailable."""
    import sys
    try:
        import serial.tools.list_ports
        candidates = [
            p.device for p in serial.tools.list_ports.comports()
            if p.vid == PICO_VID and p.pid == PICO_PID
        ]
        return sorted(candidates)
    except Exception:
        # Fallback: glob-based scan without VID/PID filtering
        import glob
        if sys.platform.startswith("win"):
            return [f"COM{i}" for i in range(1, 257)]
        elif sys.platform.startswith("darwin"):
            return (sorted(glob.glob("/dev/cu.usbmodem*")) +
                    sorted(glob.glob("/dev/tty.usbmodem*")))
        else:
            return sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))


def probe_port(port: str, baud: int = DEFAULT_BAUD) -> tuple:
    """
    Try to get one chunk from the Pico at the given port.
    Returns (ok: bool, message: str, bytes_or_none).
    Uses short timeouts -- intended for quick port scanning only.
    Per-port hard timeout of 2s via threading to prevent hangs on
    devices that open but never respond (e.g. wrong firmware).
    """
    import os, sys, threading

    if not sys.platform.startswith("win") and not os.path.exists(port):
        return False, f"{port}: not found", None

    result = [False, f"{port}: timeout -- no response (wrong firmware?)", None]

    def _try():
        try:
            with serial.Serial(port, baudrate=baud, timeout=0.5) as ser:
                time.sleep(0.1)   # brief settle
                ser.reset_input_buffer()
                ser.write(b"R")
                chunk = ser.read(CHUNK_BYTES)
            if len(chunk) != CHUNK_BYTES:
                result[1] = f"{port}: got {len(chunk)}/{CHUNK_BYTES} bytes -- wrong firmware?"
                return
            if chunk == bytes(CHUNK_BYTES):
                result[1] = f"{port}: all-zero response -- device may be unresponsive"
                return
            if len(set(chunk)) == 1:
                result[1] = f"{port}: degenerate response (single repeated byte)"
                return
            result[0] = True
            result[1] = f"{port}: OK -- {CHUNK_BYTES} bytes, {len(set(chunk))} distinct values"
            result[2] = chunk
        except serial.SerialException as e:
            result[1] = f"{port}: {e}"

    t = threading.Thread(target=_try, daemon=True)
    t.start()
    t.join(timeout=2.0)   # hard 2s cap per port regardless of what the serial layer does
    return tuple(result)


def find_pico() -> tuple:
    """
    Scan all candidate ports and return (port, message, chunk) for the
    first one that responds correctly, or (None, message, None) if none found.
    """
    ports = scan_ports()
    if not ports:
        return None, "No serial ports found (checked ttyACM*, ttyUSB*, cu.usbmodem*, COM*)", None
    msgs = []
    for port in ports:
        ok, msg, chunk = probe_port(port)
        msgs.append(msg)
        if ok:
            return port, msg, chunk
    return None, "Probed: " + "; ".join(msgs), None


def is_available(port: str = DEFAULT_PORT) -> bool:
    """Cheap existence check. Use find_pico() for a real health check."""
    import os
    return os.path.exists(port)
