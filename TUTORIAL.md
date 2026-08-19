# SeedPrimer Tutorial

Step-by-step guide for first-time users. Covers installation, every
input mode, Pico 2 TRNG setup and qualification, and safe handling of
the mnemonic output.

---

## Table of contents

1. [What you need](#1-what-you-need)
2. [Installation](#2-installation)
3. [Running SeedPrimer](#3-running-seedprimer)
4. [Step 1 — Settings](#4-step-1--settings)
5. [Input modes](#5-input-modes)
   - [Cards only (128-bit)](#cards-only-128-bit)
   - [Cards + D6 dice (256-bit)](#cards--d6-dice-256-bit)
   - [D6 dice only](#d6-dice-only)
   - [DnD dice set](#dnd-dice-set)
   - [D8 + D16 × 2](#d8--d16--2)
6. [Step 3 — Statistical analysis](#6-step-3--statistical-analysis)
7. [Step 4 — Hash and mnemonic](#7-step-4--hash-and-mnemonic)
8. [Pico 2 TRNG setup](#8-pico-2-trng-setup)
   - [What you need](#what-you-need-1)
   - [Flashing the firmware](#flashing-the-firmware)
   - [Verifying the firmware](#verifying-the-firmware)
   - [Using the Pico in SeedPrimer](#using-the-pico-in-seedprimer)
   - [Qualifying your Pico (recommended)](#qualifying-your-pico-recommended)
   - [Using an unqualified device](#using-an-unqualified-device)
9. [A critical warning about non-random inputs](#9-a-critical-warning-about-non-random-inputs)
10. [Verifying your seed](#10-verifying-your-seed)
11. [Recording your mnemonic safely](#11-recording-your-mnemonic-safely)
12. [Air-gapped operation](#12-air-gapped-operation)
13. [Frequently asked questions](#13-frequently-asked-questions)

---

## 1. What you need

**Required:**
- A computer running Linux, macOS, or Windows
- Python 3.8 or later
- tkinter (usually bundled with Python — run `python3 -m tkinter` to check)

**Optional (strongly recommended):**
- A Raspberry Pi Pico 2 (RP2350) flashed with the SeedPrimer firmware
- pyserial (`pip install pyserial`)

**Physical entropy source (choose one):**
- A standard 52-card poker deck (riffle-shuffled)
- Standard D6 dice (any quantity from 1 to 12)
- A DnD dice set: D4, D6, D8, D10, D12, D20
- D8 dice plus D16 dice (2 × D16 per throw)

---

## 2. Installation

### Linux / macOS

```bash
# 1. Clone or copy the SeedPrimer folder to your machine
cd /path/to/seed-primer

# 2. Check dependencies
python3 check_dependencies.py

# 3. Install pyserial if you have a Pico (optional)
pip install pyserial
# or, on systems that require it:
pip install pyserial --break-system-packages

# 4. Make the launcher executable
chmod +x run_gui.sh
```

### Windows

```
1. Install Python 3.8+ from python.org (check "Add to PATH")
2. Open Command Prompt in the seed-primer folder
3. python check_dependencies.py
4. pip install pyserial   (if you have a Pico)
5. python seed_primer_gui.py
```

### Air-gapped machines

If the target machine has no internet access:

```bash
# On a machine WITH internet (same OS version):
apt-get install --download-only --reinstall python3-tk
# Downloads to /var/cache/apt/archives/

# Copy the .deb file(s) into seed-primer/offline-packages/
# Transfer the whole seed-primer folder via USB

# On the air-gapped machine:
sudo dpkg -i offline-packages/python3-tk*.deb
python3 check_dependencies.py   # confirm everything is present
```

For pyserial offline install, the wheel file is in `offline-packages/`:
```bash
pip install --no-index --find-links offline-packages pyserial
```

---

## 3. Running SeedPrimer

```bash
./run_gui.sh
# or
python3 seed_primer_gui.py
```

The window opens at the Settings screen. The title bar shows
**SeedPrimer**. The header bar reads "Runs offline. Does not store or
transmit data."

---

## 4. Step 1 — Settings

The settings screen has four sections:

### Entropy source and seed length

Choose your physical input method and word count. Eight modes are
available — see [Section 5](#5-input-modes) for details on each.

**12 words (128-bit):** sufficient for most purposes. The keyspace is
2^128 — computationally unbreakable with any foreseeable hardware.

**24 words (256-bit):** double the entropy. Recommended if you are
protecting large amounts of funds or want the highest available margin.

### Shuffle count (card modes only)

How many riffle shuffles you performed before drawing. The app deducts
entropy based on the Bayer-Diaconis (1992) bound for imperfect mixing.

- **Fewer than 7:** blocked outright — the deck is not sufficiently mixed.
- **7 shuffles:** ~76 bits deducted. Marginal — use 10+.
- **10 shuffles:** ~10 bits deducted. Good.
- **12+ shuffles:** under 3 bits deducted. Excellent.

A standard casino riffle shuffle: split the deck roughly in half, let
the cards fall alternately from each half as you arch them together.
Repeat. Ten shuffles takes about 60 seconds.

### Dice quality (dice modes only)

- **Consumer dice:** standard retail dice. A 5% bias discount is
  applied per roll — more rolls are required to clear the entropy target.
- **Precision / casino-grade:** precision-machined dice with tighter
  tolerances. A 2% discount is applied.

If you are not sure, select Consumer.

### Pico 2 TRNG (optional)

See [Section 8](#8-pico-2-trng-setup) for full setup instructions.

If a Pico 2 is connected:
1. Click **Scan for Pico** — the app probes USB ports for a device
   running the SeedPrimer firmware.
2. On success, the status line turns green and shows the port.
3. The enable checkbox is automatically checked.
4. The scan is valid for 30 seconds. If you spend more time on
   settings, re-scan before clicking Continue.
5. To reset a stale or hung scan, click **Reset** and scan again.

If the Pico is enabled, it is **required**. The app will not proceed
to Step 4 if the Pico fails to respond. If you want to proceed without
it, uncheck the enable checkbox.

### Continue

Click **Continue →** when settings are ready. The app validates your
choices and opens the physical input phase.

---

## 5. Input modes

### Cards only (128-bit)

**What you need:** one standard 52-card poker deck.

**Preparation:**
1. Riffle-shuffle the deck at least 10 times. More is better.
2. Enter your shuffle count in settings.
3. Keep the deck face-down after shuffling — do not look at the order.

**In the app:**
1. Draw cards one at a time from the top of the deck, face up.
2. Click each card in the app as you reveal it. The card grays out
   once entered — each card can only be entered once.
3. The entropy gauge tracks your progress. It turns green when
   27 cards have been entered and the 128-bit target is met.
4. Click **Continue to analysis →**.

**Tips:**
- Enter cards in the exact order you draw them. Do not sort or
  reorder — the randomness is in the draw order, not the card values.
- If you misclick a card, use **Undo last** and re-enter.
- You do not need to draw all 52 cards — 27 is enough for 128-bit.

---

### Cards + D6 dice (256-bit)

**What you need:** one standard 52-card poker deck, plus D6 dice
(any quantity).

**Phase 1 — Cards (52 cards):**
Same as Cards only, but you draw all 52 cards. The gauge reaches 100%
around card 45-48; continue drawing until all 52 are entered.

**Phase 2 — Dice (minimum 20 rolls):**
1. Roll all your D6 dice simultaneously.
2. Click each face value that came up (1 through 6). The app records
   them in groups of 5, shown as `[3 4 5 1 2]  [6 2 1 4 3]`.
3. A minimum of 20 rolls is enforced regardless of the gauge — all
   statistical tests need at least 20 data points to run meaningfully.
4. Continue rolling until both the gauge is green and the minimum
   roll count is met.

**Tips:**
- Roll all dice at once — do not roll one at a time.
- Enter the values in the order you read them (left to right is fine).
- Do not reroll dice you dislike — enter what came up.

---

### D6 dice only

**What you need:** D6 dice (any quantity from 1 to 12).

**128-bit:** minimum 60 rolls (12 groups).
**256-bit:** minimum 120 rolls (24 groups).

**In the app:**
1. Select how many dice you roll per throw using the radio buttons
   (1–12). Default is 5.
2. Roll all selected dice simultaneously.
3. Click each face value. When you have entered all dice for the
   throw, the group commits automatically and appears in the log.
4. The progress tracker shows: groups complete / remaining, and
   rolls in the current group.
5. Use **Undo last roll** to remove the most recent value.
   Use **Undo last group** to remove the last completed group.
6. Continue until the progress tracker shows the minimum is met and
   the gauge is green.

**Tips:**
- More dice per throw means fewer throws needed — 12 dice per throw
  completes a 128-bit session in just 5 throws (60 rolls).
- Roll all dice simultaneously, not sequentially.
- Enter values left to right as they land.

---

### DnD dice set

**What you need:** a standard DnD dice set with D4, D6, D8, D10,
D12, and D20.

**128-bit:** minimum 10 throws.
**256-bit:** minimum 20 throws.

The math: 4×6×8×10×12×20 = 460,800 = 2048×225. Every combination of
dice maps to a perfectly uniform distribution. No values are wasted.

**In the app:**
1. Roll all six dice simultaneously.
2. Click the face value in each column, in order: D4, D6, D8, D10,
   D12, D20.
3. Each column highlights green when a value is selected.
4. The throw commits automatically when all six columns are filled.
5. The D10 face showing "0" or "00" is entered as **0** (meaning 10).
6. The D20 column is split into two sub-columns: 1–10 on the left,
   11–20 on the right.
7. Use **Undo last throw** to remove the most recent throw.
   Use **Clear in-progress throw** to reset the current staging row.

**Important:** the die order is fixed — D4 first, D20 last. Rolling
dice in a different order silently produces a different seed. Keep
the same die in the same column for every throw.

**Tips:**
- Use a dice tray to keep the dice contained.
- Read values left to right: smallest die to largest.

---

### D8 + D16 × 2

**What you need:** one D8 die and two D16 dice.

**128-bit:** 12 throws.
**256-bit:** 24 throws.

The math: 8×16×16 = 2048 exactly. Each throw maps directly to one
BIP-39 word index with perfect uniformity. Zero rejection, zero waste.
This is the only mode where one throw = one word.

**In the app:**
1. Roll the D8 and both D16 dice simultaneously.
2. Enter the D8 value (1–8) in the first box.
3. Enter the first D16 value (1–16) in the second box.
4. Enter the second D16 value (1–16) in the third box.
5. Click **Commit throw**. The throw is validated and added to the log.
6. The log shows each throw as: `[1] D8=3  D16a=12  D16b=7`
7. Use **Undo last throw** to remove the most recent entry.
   Use **Clear entries** to reset the current input boxes.

**Tips:**
- D16 dice are non-standard. If you cannot source them, use the DnD
  mode instead — it achieves the same zero-waste property.
- Enter the two D16 values consistently (e.g. always left die first).
  The order matters — swapping D16a and D16b produces a different word.

---

## 6. Step 3 — Statistical analysis

After physical input, the app runs 14 statistical tests on your raw
draw — before any hashing or whitening. Tests operate on the physical
symbols (card ranks, die faces), not on encoded bits, to avoid
encoding artifacts.

### Reading the results

Each test shows one of three levels:

- **PASS** (green) — no problem detected.
- **BORDERLINE** (orange) — mildly unusual pattern. Not necessarily a
  problem, but worth noting.
- **FLAG** (red) — statistically unlikely pattern for a fair source.

### Tier verdict

The overall session verdict appears at the top:

- **FULL** — all tests pass. Proceed normally.
- **LIMITED** — minor issues. You may proceed but consider re-doing
  the physical input.
- **CAUTION** — notable issues. The app recommends redoing the input.
  You can override and proceed, but this requires an explicit checkbox.
- **STOP** — significant issues detected. Re-do the physical input.
  The Continue button is disabled until you restart.

### False positive rates

These tests will occasionally flag a perfectly good draw by chance.
At the recommended input sizes, false positive rates are:

| Mode | False positive rate |
|---|---|
| Cards only | ~6% |
| Cards + D6 | ~19% |
| D6 only | ~8–9% |
| DnD | ~0% |
| D8+D16×2 | ~0% |

A flag does not mean your draw was bad — it means re-doing it is
prudent. The tests catch realistic mistakes (under-shuffling, dice
bias, unconscious patterns), not a determined adversary.

### Shannon entropy

Shannon entropy is shown for informational purposes only. It does not
contribute to the STOP/CAUTION decision — at the sample sizes used
here, multiple Shannon tests running simultaneously produce too many
false positives to be a reliable gate.

---

## 7. Step 4 — Hash and mnemonic

### What happens

Your physical draw is processed through the pipeline:

```
physical input  ──┐
                  ├── XOR ──► SHA-256 ──► BIP-39 words
Pico TRNG bytes ──┘
```

If the Pico is not enabled, the physical input goes directly to
SHA-256.

### Mnemonic

The mnemonic is hidden by default. Click **Show/Hide** to reveal all
words at once, or click individual numbered buttons to reveal one word
at a time.

**All revealed fields automatically re-mask when the window loses
focus.** Move to another window and the mnemonic hides itself.

The screen warns you that OS-level screenshots cannot be prevented.
Be in a private physical environment before revealing any word.

### SHA-256 entropy

The underlying entropy bytes are shown masked. Click **Show/Hide** to
reveal the hex value for independent verification.

### QR code

A CompactSeedQR code is generated automatically. This encodes the raw
entropy bytes (not the mnemonic words) in a compact format suitable
for air-gap transfer via camera. The QR is shown masked — click
**Show/Hide** to reveal it.

### Key derivation

Below the mnemonic, the app shows:
- Master fingerprint (first 4 bytes of the master public key)
- Extended public keys in BIP44, BIP49, BIP84, and BIP86 formats

These are shown for verification against a second tool (e.g. Ian
Coleman's BIP-39 tool run offline). They cannot be copied — manual
transcription is intentional.

### Entropy quality report (optional)

If enabled in settings, a statistical quality report runs on the
pre-whitening entropy bytes. This is informational — SHA-256 whitening
makes the output look uniform regardless of input quality, so this
report reflects the raw source quality, not the seed quality.

---

## 8. Pico 2 TRNG setup

### What you need

- Raspberry Pi Pico 2 (RP2350 chip — not the original Pico with RP2040)
- A USB cable (USB-A to micro-USB)
- The firmware file: `dice_rng_firmware.uf2` (in this folder)

### Flashing the firmware

1. Hold the **BOOTSEL** button on the Pico 2 while plugging it into
   your computer via USB.
2. The Pico mounts as a USB mass storage device named **RP2350**.
3. Copy `dice_rng_firmware.uf2` onto the RP2350 drive.
4. The Pico flashes automatically and reboots. The drive disappears —
   this is normal.
5. The Pico is now running the SeedPrimer TRNG firmware.

**Verify the firmware SHA-256 before flashing:**
```bash
sha256sum dice_rng_firmware.uf2
# Expected: df39be6a1aa88282edcdc3b4588e2693feeea9b568ff43022190e370f654ae83
```

**Security note:** after flashing, the device cannot be reset to
bootloader by software. The only way to reflash is physical BOOTSEL.
This is intentional — it prevents any software process from silently
wiping the device.

### Verifying the firmware is working

```bash
# Install pyserial if not already installed
pip install pyserial

# On Linux/macOS, find the Pico's port
ls /dev/ttyACM*        # Linux
ls /dev/cu.usbmodem*   # macOS

# Quick test: send R, receive 32 bytes
python3 -c "
import serial, time
with serial.Serial('/dev/ttyACM0', 115200, timeout=3) as s:
    time.sleep(2)
    s.write(b'R')
    chunk = s.read(32)
    print(f'Got {len(chunk)} bytes: {chunk.hex()}')
    print(f'Distinct: {len(set(chunk))}/256')
"
```

You should see 32 bytes of non-zero, non-repeating data. If you see
fewer than 32 bytes or all zeros, the firmware is not running
correctly — reflash and try again.

Alternatively, use SeedPrimer's built-in scan:
1. Open SeedPrimer.
2. In Settings, click **Scan for Pico**.
3. A green status line confirms the device is working.

### Using the Pico in SeedPrimer

1. Plug in the Pico 2 via USB.
2. Open SeedPrimer and go to Settings.
3. Click **Scan for Pico**. The scan takes up to 4 seconds (2 seconds
   per port tested).
4. On success: status turns green, the port is shown, the enable
   checkbox is automatically checked.
5. On failure: status turns red with the reason. Check the USB
   connection and try again.
6. **The scan is valid for 30 seconds.** If you spend more time
   configuring settings, re-scan before clicking Continue.
7. To reset a hung or stale scan, click **Reset** — this clears all
   scan state so you can start fresh.
8. Click **Continue →**. If the Pico is enabled, the app will read
   from it during the hash phase. If the Pico disconnects or fails
   during Step 4, the app stops and sends you back — it does not
   silently proceed without it.

### Qualifying your Pico (recommended)

Qualification tests whether your specific Pico 2 unit produces
genuine high-entropy output. This uses the official NIST SP 800-90B
Entropy Assessment tool.

**Why qualify?** The firmware passes through raw RP2350 TRNG output
with no conditioning. Any individual unit could theoretically have
a defect. Qualification gives you a measured, reproducible entropy
estimate for your specific device.

**The reference device** (the one used during SeedPrimer development)
was assessed at **5.306 bits/byte** (restart test, the conservative
binding figure) and **7.466 bits/byte** (non-IID sequential). Full
results are in `secure-mint-devices/pico2-rp2350/qualification/`.

**Step 1: Capture 2 MB of raw output**

```bash
# From the seed-primer folder
python3 capture_nist.py 2000000 my_pico_raw.bin
# Takes about 40 seconds at ~55 KB/s
```

**Step 2: Install the NIST assessment tool**

```bash
git clone https://github.com/usnistgov/SP800-90B_EntropyAssessment
cd SP800-90B_EntropyAssessment/cpp
make
```

**Step 3: Run non-IID and IID assessments**

```bash
./ea_non_iid -v my_pico_raw.bin 8
./ea_iid -v my_pico_raw.bin 8
```

**Step 4: Interpret results**

Look for `H_original` in the non-IID output — this is the assessed
min-entropy in bits per byte. Reference value: 7.466 bits/byte.

- **Above 7.0 bits/byte:** excellent. Your device is clean.
- **5.0 – 7.0 bits/byte:** acceptable. The conditioning in SHA-256
  covers the gap.
- **Below 5.0 bits/byte:** concerning. Consider replacing the device.
- **Below 3.0 bits/byte:** do not use this device.

**Step 5: Restart test (optional, thorough)**

The restart test requires 1000 genuine cold power-cycles and is the
most demanding track. It requires a power-cycling rig (e.g. a USB hub
with per-port power switching and `uhubctl`). See the reference
qualification at
`secure-mint-devices/pico2-rp2350/qualification/QUALIFICATION.md`
for the full procedure.

### Using an unqualified device

You can use an unqualified Pico 2 — the app does not check
qualification status. However:

- You have no measured entropy estimate for your specific unit.
- You are trusting that the RP2350 TRNG works as documented.
- The XOR independence property still protects you: even if the Pico
  produces weak output, your physical draw covers it. The Pico cannot
  make your seed weaker than the physical draw alone.

Using an unqualified device is not recommended for funds above a
threshold you would be uncomfortable losing. Running the non-IID
assessment (Steps 1–4 above, ~5 minutes) gives you a concrete
entropy estimate and is worth doing.

---

## 9. A critical warning about non-random inputs

**Read this section before generating any seed you intend to use.**

### Statistical tests cannot detect deliberate patterns

The 14 statistical tests in Step 3 catch realistic mistakes: a
deck that was not shuffled enough, dice that were rolled with
unconscious bias, or accidental repetition. They measure the
properties of a sequence — balance, uniformity, independence,
periodicity.

They cannot tell the difference between genuine physical randomness
and a deliberately constructed sequence that happens to have the same
statistical properties. A sequence chosen to pass every test will pass
every test.

**Examples of inputs that may pass all tests but are not random:**

- Memorized sequences (birthdays, phone numbers, patterns)
- Deliberately "spread out" dice rolls (avoiding repeats by choice)
- Digits of pi, e, or other known mathematical constants
- Any sequence you could reconstruct from memory
- Card orders chosen to "look random" rather than physically shuffled

If you enter a sequence you constructed or could reconstruct, the
seed is only as secret as that sequence. Anyone who knows the sequence
and the algorithm can reproduce your seed.

### What the Pico XOR does and does not protect against

The Pico XOR is designed to cover **accidental** physical bias —
a deck shuffled fewer times than ideal, dice with slight mechanical
asymmetry, or unconscious rolling patterns. In these cases, the
Pico's independent randomness fills in the entropy gap.

It does **not** protect against a **deliberately known** physical
input:

**Scenario:** you enter a sequence you know (e.g. always rolling 3s
because you read somewhere that 3 is "random-looking"). The Pico XOR
produces a seed that passes all statistical tests and appears to be a
strong 128-bit seed.

**The implication:** the attacker's search space is now the Pico's
output space — 2^128 possible byte sequences — rather than the
combined space of your physical input plus the Pico. If the Pico is
genuine and uncompromised, 2^128 is still computationally unbreakable.
Your seed is technically secure.

**But:** you have reduced a two-source security argument to a
one-source argument. Without the Pico, a known physical input gives
an attacker your exact seed immediately. With the Pico, they need to
break the Pico's 128-bit output. The Pico is doing all the work —
your physical input contributes nothing.

More importantly: **if the Pico is ever compromised** (its output
known to an attacker), a known physical input means the attacker has
both inputs to the XOR and can reconstruct your seed exactly. The
two-source independence collapses entirely.

### The rule

**Only use SeedPrimer with genuinely physically randomized input.**

- Shuffle a real deck of cards with real riffle shuffles.
- Roll real dice on a flat surface and enter the results as they land.
- Do not adjust, filter, or "improve" the results.
- Do not use memorized sequences, patterns, or numbers you know.

The statistical tests are a safeguard against accidents, not a
certification of randomness. They are a necessary check, not a
sufficient one. The source of the randomness is your responsibility.

---

## 10. Verifying your seed

Before loading funds, verify your seed produces the wallet you expect.
This is the standard verification ceremony. You will need:

- The mnemonic you recorded, or the CompactSeedQR from Step 4
- A SeedSigner device, and/or Sparrow Wallet on an offline machine

### Option A — SeedSigner (hardware verification)

SeedSigner is an open-source, air-gapped signing device. It reads
CompactSeedQR codes directly and derives wallet addresses without
storing anything.

1. In SeedPrimer Step 4, reveal the QR code (click Show/Hide in the
   QR section).
2. On your SeedSigner, select **Scan** and point the camera at the
   QR code on your screen.
3. SeedSigner derives the seed and shows the first receive addresses.
4. Compare the addresses against the xpub-derived addresses shown in
   SeedPrimer's Step 4.

If the addresses match, your mnemonic, QR code, and key derivation
are all consistent. Your seed is correctly recorded.

**What SeedSigner verifies:**
- The QR code decodes to the correct entropy
- The entropy produces the correct BIP-39 mnemonic
- The mnemonic derives the correct master key and addresses

### Option B — Sparrow Wallet (watch-only wallet verification)

Sparrow Wallet can import an extended public key (xpub) and show all
derived addresses without exposing the private key.

1. In SeedPrimer Step 4, note the xpub shown for your preferred
   address type (BIP84 for native SegWit / bc1q addresses is
   recommended for most users).
2. In Sparrow Wallet, go to **File → New Wallet**.
3. Select **Single Signature** → **Native Segwit (P2WPKH)**.
4. In the Keystore section, select **xPub / Watch Only**.
5. Enter the xpub from SeedPrimer.
6. Sparrow derives and displays all receive and change addresses.
7. Cross-reference with the addresses shown in SeedPrimer Step 4.

If the addresses match, Sparrow and SeedPrimer agree on the key
derivation. Your seed is correctly recorded and the derivation path
is correct.

**Running Sparrow offline:**
For maximum security, run Sparrow on an air-gapped machine in
offline mode. Sparrow does not need internet access to derive
addresses from an xpub.

### Option C — Combined verification (most thorough)

Use both SeedSigner and Sparrow:

1. SeedSigner reads the CompactSeedQR and shows addresses.
2. Sparrow imports the xpub and shows the same addresses.
3. All three sources (SeedPrimer, SeedSigner, Sparrow) show the
   same first receive address.

Three independent tools agreeing on the address gives high confidence
that your mnemonic, QR, and xpub are all consistent and correct.

### What to do if addresses do not match

Stop. Do not load funds. Check:

1. Did you record the mnemonic correctly? Re-enter it word by word
   in your verification tool and check for transcription errors.
2. Are you using the same derivation path? SeedPrimer shows BIP44,
   BIP49, BIP84, and BIP86 — make sure Sparrow is set to the same.
3. Did you use a BIP-39 passphrase? If so, you must enter it in the
   verification tool too.

If you cannot reconcile the addresses, generate a new seed before
loading any funds.

---

## 11. Recording your mnemonic safely

**Never photograph or screenshot the mnemonic.** The app cannot
prevent OS-level screenshots — this is your responsibility.

**Recommended recording method:**

1. Prepare a clean sheet of paper and a pen before revealing any word.
2. Reveal one word at a time by clicking individual word buttons.
3. Write it down immediately. Do not type it anywhere.
4. Re-mask the word before revealing the next one.
5. After writing all words, verify by re-reading them against the app
   with the words re-masked — reveal, check, re-mask, next word.
6. Close the app.

**Storage:**

- Write the mnemonic on archival-quality paper (not thermal paper,
  which fades).
- Store in a location protected from fire, flood, and unauthorized
  access.
- Consider stamped metal backup (e.g. CryptoSteel, Bilodeau) for
  durability.
- Never store digitally in plaintext — not in a notes app, email,
  password manager, or cloud storage.
- Never photograph it.

**Verification:**

Before loading funds, verify your mnemonic recovers the expected
wallet using a hardware wallet or an offline tool (e.g. Ian Coleman's
BIP-39 tool, downloaded and run offline). Check that the first receive
address matches.

---

## 12. Air-gapped operation

SeedPrimer is designed to run on a machine that has never been
connected to the internet. Recommended procedure:

1. **On a connected machine:** download SeedPrimer, verify file
   integrity, and prepare the USB transfer.

2. **Transfer via USB:** copy the entire `seed-primer` folder to a
   USB drive. Do not copy anything else onto the same drive.

3. **On the air-gapped machine:** plug in the USB. Copy the folder
   to local storage. Run `python3 check_dependencies.py` to confirm
   everything is available.

4. **Pico:** flash the firmware on a connected machine first. Once
   flashed, the Pico operates offline — it needs no internet access.
   Plug it into the air-gapped machine via USB.

5. **Generate the seed:** run SeedPrimer, complete your session,
   record the mnemonic on paper.

6. **QR transfer:** if you need to move the entropy bytes to another
   device (e.g. a hardware wallet), use the CompactSeedQR displayed
   in Step 4. Show it to the device's camera — no USB or wireless
   transfer needed.

7. **After the session:** close SeedPrimer. The app writes nothing to
   disk — closing it clears all data from memory.

---

## 13. Frequently asked questions

**Q: Which mode should I use?**

For most people: Cards only (128-bit) or Cards + D6 (256-bit). Cards
are the most reliable physical entropy source — well-shuffled, hard
to bias unconsciously, easy to verify. D6-only is fine if you don't
have cards but requires more discipline (60–120 rolls of truly random
dice). DnD and D8+D16×2 are excellent if you have the dice — the
zero-waste math is elegant.

**Q: Do I need the Pico?**

No. SeedPrimer works without it. A well-shuffled card draw or
sufficient dice rolls produce a strong seed on their own. The Pico
adds a second independent source — useful if you want the strongest
possible security guarantee, but not required.

**Q: What if the statistical tests flag my draw?**

Redo the physical input. Under-shuffle the deck more aggressively,
or be more deliberate about randomizing dice throws. A flag on a
genuinely random draw happens occasionally by chance (~6–19% depending
on mode) — but redoing is cheap and removes doubt.

**Q: Can I use this with any BIP-39 wallet?**

Yes. SeedPrimer produces standard BIP-39 mnemonics compatible with
any BIP-39-compliant wallet: hardware wallets (Ledger, Trezor,
Coldcard, Keystone), software wallets (Electrum, Sparrow, Specter),
and any tool that accepts a 12 or 24-word seed phrase.

**Q: Is 12 words enough?**

For personal self-custody: yes. 2^128 possible seeds means a
brute-force attack is computationally impossible with any foreseeable
technology. 24 words (2^256) is preferred by some hardware wallets
and provides extra margin.

**Q: Can I run this online?**

You can, but you should not generate real seeds this way. The tool
produces no network traffic — `grep -r "socket\|urllib\|requests\|http" .`
confirms this — but an online machine may have keyloggers, screen
recorders, or other processes that could capture the mnemonic.
Run on an air-gapped machine for real funds.

**Q: What if I lose my mnemonic?**

The seed cannot be recovered without the mnemonic. SeedPrimer writes
nothing to disk — there is no backup. This is intentional: the only
copy is the one you wrote on paper. Store it safely.

**Q: The app says the Pico scan is stale. What do I do?**

Click **Scan for Pico** again. The scan expires after 30 seconds to
ensure the device is confirmed connected at the moment you proceed.
If the scan hangs, click **Reset** to clear the state, then unplug
and replug the Pico, then scan again.

**Q: Can I verify the output independently?**

Yes. The SHA-256 entropy hex shown in Step 4 is the direct input to
the BIP-39 encoding. You can verify the word list mapping using Ian
Coleman's BIP-39 tool (download and run offline):
`https://iancoleman.io/bip39/` — enter the entropy hex and confirm
the words match.

**Q: Can I verify the output independently?**

Yes — and you should before loading any funds. See
[Section 10](#10-verifying-your-seed) for the full procedure.

Short version:
- **SeedSigner:** scan the CompactSeedQR from Step 4. SeedSigner
  derives the wallet and shows receive addresses. Compare against
  SeedPrimer's displayed addresses.
- **Sparrow Wallet:** import the xpub shown in Step 4 as a watch-only
  wallet. Sparrow shows the same addresses. Compare.
- If all three tools (SeedPrimer, SeedSigner, Sparrow) show the same
  first receive address, your seed is correctly recorded.

**Q: What if I entered non-random inputs deliberately?**

Your seed may be compromised. See
[Section 9](#9-a-critical-warning-about-non-random-inputs).

Short version: statistical tests cannot distinguish genuine randomness
from a deliberate sequence that happens to look random. If you entered
a sequence you know, your seed is only as secret as that sequence.
Generate a new seed using genuinely randomized physical input.
