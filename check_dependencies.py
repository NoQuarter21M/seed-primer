#!/usr/bin/env python3
"""
check_dependencies.py

Checks whether this machine can run SeedPrimer. Run this BEFORE
transferring the project to an air-gapped or unfamiliar machine,
and again once there, to confirm it will actually run.

Dependencies are split into two categories:
  REQUIRED: the GUI will not run without these.
  OPTIONAL: specific features will be unavailable but the core app runs.

No network code. Safe to run on the air-gapped machine itself.

USAGE
  python3 check_dependencies.py

EXIT CODES
  0 = all required dependencies available, GUI will run
  1 = a required dependency is missing, see remediation notes below
"""

import sys
import platform
import subprocess


def check_cmd(cmd):
    """Return True if a command-line tool is available."""
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def main():
    print("=" * 62)
    print("  SEEDPRIMER DEPENDENCY CHECK")
    print("=" * 62)
    print(f"  Python:   {platform.python_version()}")
    print(f"  Platform: {platform.platform()}")
    print()

    required_ok = True
    optional_notes = []

    # ------------------------------------------------------------------
    # REQUIRED
    # ------------------------------------------------------------------
    print("REQUIRED:")

    # tkinter
    try:
        import tkinter
        print(f"  [OK] tkinter        (Tk {tkinter.TkVersion})")
    except ImportError as e:
        required_ok = False
        print(f"  [!!] tkinter        NOT AVAILABLE -- GUI will not run ({e})")

    # hashlib SHA-256
    try:
        import hashlib
        hashlib.sha256(b"test")
        print("  [OK] hashlib        (SHA-256 + PBKDF2-HMAC-SHA512)")
    except Exception as e:
        required_ok = False
        print(f"  [!!] hashlib        PROBLEM ({e})")

    # math
    try:
        import math
        print("  [OK] math           (stdlib)")
    except Exception as e:
        required_ok = False
        print(f"  [!!] math           PROBLEM ({e})")

    # struct
    try:
        import struct
        print("  [OK] struct         (stdlib)")
    except Exception as e:
        required_ok = False
        print(f"  [!!] struct         PROBLEM ({e})")

    # qr_encoder (project's own from-scratch module, stdlib-only)
    try:
        import qr_encoder
        qr_encoder.build_matrix(b"test", 2, "m")
        print("  [OK] qr_encoder     (from-scratch QR, no external library)")
    except Exception as e:
        required_ok = False
        print(f"  [!!] qr_encoder     PROBLEM ({e})")

    # wordlist
    import os
    wl = os.path.join(os.path.dirname(__file__), "wordlist_english.txt")
    if os.path.isfile(wl):
        with open(wl) as f:
            words = [l.strip() for l in f if l.strip()]
        if len(words) == 2048:
            print(f"  [OK] wordlist       (2048 words, BIP-39 English)")
        else:
            required_ok = False
            print(f"  [!!] wordlist       WRONG LENGTH ({len(words)} words, expected 2048)")
    else:
        required_ok = False
        print(f"  [!!] wordlist       NOT FOUND at {wl}")

    # ------------------------------------------------------------------
    # OPTIONAL
    # ------------------------------------------------------------------
    print()
    print("OPTIONAL:")

    # pyserial -- needed for Pico TRNG injection
    try:
        import serial
        print(f"  [OK] pyserial       (Pico 2 TRNG injection available)")
    except ImportError:
        print(f"  [--] pyserial       NOT AVAILABLE -- Pico TRNG injection disabled")
        optional_notes.append(
            "pyserial: install with 'pip install pyserial' or "
            "'pip install pyserial --break-system-packages'\n"
            "    Required for Pico 2 TRNG hardware entropy injection.\n"
            "    The app runs without it -- Pico section will not appear in settings.")

    # arecord -- needed for Monte Carlo mic source
    if check_cmd("arecord"):
        print(f"  [OK] arecord        (ALSA audio capture, Monte Carlo mic source)")
    else:
        print(f"  [--] arecord        NOT AVAILABLE -- mic source in Monte Carlo disabled")
        optional_notes.append(
            "arecord: install with 'sudo apt install alsa-utils'\n"
            "    Required only for monte_carlo_pico.py --source mic.\n"
            "    Not needed for the main GUI application.")

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    print()
    print("=" * 62)
    if required_ok and not optional_notes:
        print("  RESULT: all dependencies present. SeedPrimer is ready.")
        sys.exit(0)
    elif required_ok:
        print("  RESULT: required dependencies OK. SeedPrimer will run.")
        print("  Optional items missing (see notes below).")
        print()
        for note in optional_notes:
            print(f"  NOTE: {note}")
            print()
        sys.exit(0)
    else:
        print("  RESULT: required dependency missing -- see remediation below.")
        print()
        print("  REMEDIATION (tkinter, on Debian/Ubuntu/Linux Mint):")
        print()
        print("  If you have internet access on this machine:")
        print("    sudo apt install python3-tk")
        print()
        print("  If transferring to an air-gapped machine:")
        print("    1. On a machine WITH internet, same OS version:")
        print("         apt-get install --download-only --reinstall python3-tk")
        print("       (downloads to /var/cache/apt/archives/)")
        print("    2. Copy the .deb file(s) into the offline-packages/ folder")
        print("    3. Transfer the whole SeedPrimer folder via USB")
        print("    4. On the air-gapped machine:")
        print("         sudo dpkg -i offline-packages/python3-tk*.deb")
        sys.exit(1)


if __name__ == "__main__":
    main()
