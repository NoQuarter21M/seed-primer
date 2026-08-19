# SeedPrimer

**Physical-entropy-first BIP-39 seed generation for air-gapped machines.**

SeedPrimer generates BIP-39 mnemonics (12 or 24 words) from physical entropy
sources — playing cards, D6 dice, and DnD dice sets — with optional Raspberry
Pi Pico 2 TRNG hardware injection and a full statistical test suite to audit
your physical draw before committing to a seed.

Designed to run offline on an air-gapped laptop. No network code. No external
dependencies beyond Python 3 and tkinter (pyserial optional, for Pico TRNG).

---

## Input modes

| Mode | Source | Min input | Words | Target |
|---|---|---|---|---|
| Cards only | 27 cards from a shuffled deck | 27 cards | 12 | 128-bit |
| Cards + D6 | Full deck + dice | 52 cards + 20 rolls | 24 | 256-bit |
| D6 only (128-bit) | D6 dice rolls in groups | 60 rolls (12 groups of 5) | 12 | 128-bit |
| D6 only (256-bit) | D6 dice rolls in groups | 120 rolls (24 groups of 5) | 24 | 256-bit |
| DnD (128-bit) | D4/D6/D8/D10/D12/D20 full set | 10 throws | 12 | 128-bit |
| DnD (256-bit) | D4/D6/D8/D10/D12/D20 full set | 20 throws | 24 | 256-bit |

---

## Pipeline

Every session follows the same four phases:

```
Settings → Physical input → Statistical analysis → Hash + mnemonic
```

### 1. Settings

Choose your input mode, dice quality (consumer / precision), and shuffle count
(card modes). The Pico 2 TRNG panel lets you scan for a connected Pico and
enable hardware entropy injection.

**Shuffle quality (card modes):** the entropy deduction for imperfect shuffling
is computed from the Bayer-Diaconis (1992) total variation distance for a
riffle-shuffled deck. At 7 shuffles: ~76 bits lost. At 10 shuffles: ~10 bits
lost. At 12+: under 3 bits. Fewer than 7 shuffles is blocked outright.

### 2. Physical input

Depending on mode:

- **Cards:** click cards in draw order. Each card is clickable once.
  A live entropy gauge tracks discounted bits against the target.
- **D6:** select how many dice you roll per throw (1-12). Click each
  face value. Rolls commit in groups; the progress tracker shows
  groups complete and remaining.
- **DnD:** six columns, one per die. Click one face value per column.
  The throw commits automatically when all six are selected. D10 face
  "0" is entered as 0. D20 is split into two sub-columns (1-10, 11-20)
  for readability.

### 3. Statistical analysis

14 symbol-level tests on your raw physical draw — before whitening.
Tests catch realistic failure modes: weak shuffles, dice bias, human
rolling patterns, and periodicity. Results are shown as PASS /
BORDERLINE / FLAG with explanations.

Shannon entropy is shown informationally for all modes but does not
gate the session — at the sample sizes used here, Shannon compounding
across multiple tests produces unacceptable false-positive rates and
is excluded from the STOP/CAUTION decision.

**False-positive rates (fair input, 5000-trial Monte Carlo):**

| Mode | Effective FP (STOP + CAUTION) |
|---|---|
| Cards only 128-bit | ~6% |
| Cards + D6 256-bit | ~19% |
| D6-only 128-bit | ~8% |
| D6-only 256-bit | ~9% |
| DnD 128-bit | ~0% |
| DnD 256-bit | ~0% |

### 4. Hash + mnemonic

Your physical draw is combined with optional Pico TRNG bytes (XOR,
pre-whitening), then whitened with SHA-256, then encoded as a BIP-39
mnemonic. The mnemonic is shown masked by default with a reveal button.
A QR code (CompactSeedQR format) is generated for air-gap transfer.

---

## Pico 2 TRNG hardware injection

If a Raspberry Pi Pico 2 (RP2350) running the SeedPrimer TRNG firmware
is connected via USB, its output is XOR'd into your raw physical entropy
**before** SHA-256 whitening.

The XOR independence property means: if either input is uniform and
independent, the output is uniform — regardless of the other input.
This means:

- A weak physical draw + good Pico = strong seed
- A good physical draw + compromised Pico = still strong seed
- The Pico can never make your seed weaker than the physical draw alone

The Pico is optional. The app runs without it; the Pico panel simply
does not appear if no device is found.

**Qualification:** Pico 2 (RP2350) assessed at 7.466 bits/byte non-IID
under NIST SP 800-90B. Full qualification record in
`../secure-mint-devices/pico2-rp2350/qualification.json`.

See [PICO_TRNG.md](PICO_TRNG.md) for the full adversarial explainer,
including per-mode analysis and skeptical Q&A.

---

## Wordlist

Uses the official BIP-39 English wordlist (2048 words).

SHA-256: `2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda`

Verify against the official source:
```
https://github.com/trezor/python-mnemonic/blob/master/src/mnemonic/wordlist/english.txt
```

---

## Installation

**Requirements:** Python 3.8+, tkinter (usually bundled with Python).

**Optional:** pyserial (for Pico 2 TRNG injection).

```bash
# Check all dependencies
python3 check_dependencies.py

# Install pyserial if you have a Pico (optional)
pip install pyserial

# Run
./run_gui.sh
# or
python3 entropy_mix_gui.py
```

**Air-gapped machines:** copy the entire folder via USB. Run
`check_dependencies.py` on the target machine to confirm everything is
available. If tkinter is missing, see the remediation steps it prints.

---

## Files

| File | Purpose |
|---|---|
| `entropy_mix_gui.py` | Main GUI application |
| `entropy_mix_core.py` | Core logic: encoding, tests, whitening, BIP-39 |
| `pico_trng_source.py` | Pico TRNG interface: scan, probe, bulk fetch |
| `qr_encoder.py` | From-scratch QR generation (no external library) |
| `wordlist_english.txt` | Official BIP-39 English wordlist |
| `check_dependencies.py` | Dependency checker for new/air-gapped machines |
| `test_bip39_checksum.py` | BIP-39 checksum correctness test (27 PASS) |
| `dev_test_harness.py` | Dev-only: batch testing across all six modes |
| `monte_carlo_pico.py` | Pipeline Monte Carlo test with real Pico TRNG |
| `capture_nist.py` | NIST SP 800-90B raw capture tool for Pico |
| `PICO_TRNG.md` | Pico TRNG explainer and adversarial Q&A |
| `HARDENING.md` | Testing and hardening record (dated, append-only) |
| `ADVERSARIAL_NOTES.md` | Statistical test suite adversarial test results |

---

## Testing

```bash
# BIP-39 checksum correctness (all six modes, known vectors, edge cases)
python3 test_bip39_checksum.py

# Statistical test false-positive rates (all six modes, 1000 trials each)
python3 dev_test_harness.py --all-modes 1000

# Monte Carlo pipeline test with real Pico (requires Pico connected)
python3 monte_carlo_pico.py --trials 1000 --source mic --no-xor
```

See [HARDENING.md](HARDENING.md) for the full testing record including
Monte Carlo results with real hardware (H1essential mic + Pico 2,
n=1000 and n=10000, bias 0%/30%/70% — all conditions PASS).

---

## Security notes

- **No CSPRNG in the seed path.** Physical entropy sources only.
  The Pico TRNG is the only software-adjacent entropy source, and it
  is optional and XOR'd (cannot reduce security below physical draw alone).
- **No network code.** Verified: `grep -r "socket\|urllib\|requests\|http" .`
- **No disk writes of entropy or mnemonic data.** Everything stays in
  process memory and is cleared on restart.
- **Deterministic pipeline.** Same physical input always produces the
  same mnemonic (given the same Pico bytes, if used). This is by design
  — it allows independent verification of the implementation.

---

## Credits

See [CREDITS.md](CREDITS.md).

Developed by **NoQuarter21M** in collaboration with **Claude** (Anthropic).
