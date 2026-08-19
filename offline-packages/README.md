This folder holds offline installable packages for air-gapped machines.

SeedPrimer has no required external dependencies beyond Python's standard
library and tkinter. This folder exists for optional dependencies:

  pyserial: required for Pico 2 TRNG hardware injection
    pip install pyserial
    (or drop the .whl here and install with: pip install --no-index --find-links . pyserial)

  segno-1.6.6-py3-none-any.whl: NOT used. QR generation is implemented
    from scratch in qr_encoder.py. Kept here in case it is needed in future.
