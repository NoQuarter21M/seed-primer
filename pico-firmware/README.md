# Pico 2 TRNG Firmware

Firmware for the Raspberry Pi Pico 2 (RP2350) as a hardware entropy
source for SeedPrimer.

## Files

| File | Purpose |
|---|---|
| `dice_rng_firmware.uf2` | Pre-built firmware binary, ready to flash |
| `main.c` | Full firmware source (52 lines of C, auditable) |

## SHA-256 of firmware binary

```
df39be6a1aa88282edcdc3b4588e2693feeea9b568ff43022190e370f654ae83  dice_rng_firmware.uf2
```

Verify before flashing:
```bash
sha256sum dice_rng_firmware.uf2
```

## Flashing

1. Hold BOOTSEL while plugging the Pico 2 into USB
2. It mounts as a drive named RP2350
3. Copy dice_rng_firmware.uf2 onto the drive
4. The Pico flashes and reboots automatically

## Protocol

- Host sends: single byte `R`
- Device replies: exactly 32 raw bytes of TRNG output
- No headers, no framing, no conditioning

## Build info (for reproducible build)

- Pico SDK: v2.3.0 (commit 98a542c1a62fb549ffb5d66a3e5892b06276b670)
- Board: pico2 (RP2350)
- Toolchain: arm-none-eabi-gcc, ninja, cmake

See TUTORIAL.md for full setup and qualification instructions.
