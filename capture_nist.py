#!/usr/bin/env python3
"""
capture_nist.py — sustained raw capture from the Pico 2 RP2350 TRNG for
NIST SP800-90B entropy assessment. Streams the request/response protocol
continuously, writes raw bytes to disk, reports progress. NO conditioning,
NO processing — raw hardware output only, which is what SP800-90B requires
(it assesses the noise source, not a whitened stream).
"""
import sys, time, serial

PORT = "/dev/ttyACM0"
BAUD = 115200
CHUNK = 32

def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 2_000_000
    outpath = sys.argv[2] if len(sys.argv) > 2 else "/tmp/pico_nist_raw.bin"

    ser = serial.Serial(PORT, BAUD, timeout=3)
    time.sleep(2)  # USB CDC settle
    ser.reset_input_buffer()

    written = 0
    t0 = time.time()
    last_report = t0
    with open(outpath, "wb") as f:
        while written < target:
            ser.write(b"R")
            chunk = ser.read(CHUNK)
            if len(chunk) != CHUNK:
                # strict: a short read means desync/fault — abort, do not
                # silently pad. Production capture must be exact.
                sys.stderr.write(f"\nFAULT: short read ({len(chunk)} bytes) at offset {written}\n")
                ser.close()
                sys.exit(2)
            f.write(chunk)
            written += CHUNK
            now = time.time()
            if now - last_report >= 5:
                rate = written / (now - t0) / 1024
                pct = 100 * written / target
                sys.stderr.write(f"\r{written:,}/{target:,} bytes ({pct:.1f}%) {rate:.1f} KB/s")
                sys.stderr.flush()
                last_report = now

    ser.close()
    dt = time.time() - t0
    sys.stderr.write(f"\nDONE: {written:,} bytes in {dt:.1f}s ({written/dt/1024:.1f} KB/s) -> {outpath}\n")

if __name__ == "__main__":
    main()
