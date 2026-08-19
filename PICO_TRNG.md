# Pico 2 TRNG — What It Does and Why You Can Distrust It

This document explains what the Pico 2 hardware random number generator
does in SeedPrimer, and answers the questions a skeptical user
should ask before trusting any piece of hardware they didn't build
themselves.

The short version: **you don't have to trust it**. The design
guarantees it cannot make your seed weaker. It can only make it
stronger or leave it unchanged.

This guarantee applies identically to all four input modes:
cards only, cards + D6 dice, D6 dice only, and DnD full set.

---

## What the Pico actually does

When you finish your physical input session — drawing cards, rolling
D6 dice, or throwing the DnD set — you have a sequence of physical
events. That sequence is your raw entropy: your unique, unpredictable
input that will become your seed.

Before we turn that into a seed, we need to convert it into clean,
uniform random bytes. Your physical input has structure specific to
its source:

- **Cards:** suits and ranks, values between 1 and 52
- **D6 rolls:** faces between 1 and 6
- **DnD throws:** six different dice (D4/D6/D8/D10/D12/D20),
  each with its own face range

None of these map neatly to the uniform bytes a cryptographic seed
requires. That conversion is called **whitening**, and SHA-256 does it.

Here's where the Pico comes in.

Before we hand your physical input to SHA-256, the Pico 2 — a small
microcontroller plugged into your USB port — generates its own
completely independent stream of random bytes directly from the
electrical noise inside its silicon chip. This is hardware-level
randomness that has nothing to do with your cards, dice, or DnD throws.
It has been independently tested against the NIST SP 800-90B standard
and assessed at 7.466 bits of entropy per byte — essentially the
physical maximum for a binary source.

We take those Pico bytes and XOR them with your raw input sequence.
XOR is a simple bitwise combination — think of it as overlaying two
transparencies, where each bit flips if the corresponding Pico bit is
a 1. The result contains the randomness from both sources
simultaneously. Then we hand that to SHA-256.

---

## The XOR guarantee

XOR has a mathematical property that makes this design trustworthy
even if you distrust the Pico:

> If either input to XOR is truly random and independent of the other,
> the output is truly random — regardless of what the other input
> looks like.

This means:

- If your physical input was perfectly random, the seed is strong. ✓
- If your physical input had subtle bias — not enough shuffles, accidental
  dice patterns, DnD throws that weren't truly independent — the Pico's
  randomness covers it. Still strong. ✓
- If the Pico had a bad day and produced weak output, your physical
  input covers it. Still strong. ✓
- If the Pico produced all zeros, the output equals your physical
  input alone. Same as not having the Pico at all. ✓
- If the Pico produced a sequence an attacker already knows, they
  still don't know your physical input. Still strong. ✓

**The Pico cannot make your seed weaker than your physical input alone.**
The math, not trust, guarantees this.

---

## How this applies to each mode

The guarantee is identical across all input modes. The physical input
changes; the XOR property does not.

### Cards only (128-bit, 27 cards)

Your raw entropy is the draw order of 27 cards from a shuffled deck.
Without Pico: an attacker who knows your shuffle quality and draw order
can find your seed. With Pico: they also need the Pico's 16 bytes —
which they don't have — even if they watched you draw every card.

**Specific risk covered:** weak shuffle (fewer than the recommended 10
riffle shuffles). The Bayer-Diaconis bound shows a 7-shuffle deck is
still meaningfully non-uniform. The Pico XOR covers this entropy gap.

### Cards + D6 dice (256-bit, 52 cards + 20+ rolls)

Your raw entropy is the full card draw order combined with all dice
face values. The physical input is longer and from two mechanisms.
Without Pico: an attacker needs both the card sequence and dice rolls.
With Pico: they additionally need the Pico bytes.

**Specific risk covered:** center bias in dice rolls (tendency to roll
3s and 4s more than 1s and 6s — a known human bias that the
statistical tests catch but cannot fully eliminate). The Pico XOR
covers residual bias the tests miss.

### D6 only (128-bit: 60 rolls, 256-bit: 120 rolls)

Your raw entropy is purely from dice face values. No card draw — the
full entropy budget comes from the dice. This mode is more exposed to
human rolling biases: avoid-repeat patterns, wave sequences, center
bias. The statistical tests catch gross patterns but not subtle ones.
Without Pico: your seed is as strong as your actual rolling behavior,
which may be weaker than you think. With Pico: the Pico covers it.

**Specific risk covered:** all human dice-rolling biases. D6-only is
the mode where the Pico injection has the most practical impact,
because it is the mode most dependent on consistent unbiased rolling
across many throws (60-120).

### DnD full set (128-bit: 10 throws, 256-bit: 20 throws)

Your raw entropy is from six different dice thrown together. Each die
has a different face count (4, 6, 8, 10, 12, 20) and different
mechanical bias characteristics. Fewer throws are needed because the
product of face counts is large (4×6×8×10×12×20 = 460,800 per throw).
Without Pico: your seed depends on the bias of all six dice and your
throwing consistency. With Pico: the Pico covers any bias across all
six dice simultaneously.

**Specific risk covered:** mechanical bias in any of the six dice.
Unlike D6 rolling where you might notice a loaded die, DnD dice are
often cheaper and less balanced. The Pico covers all six at once with
a single hardware source.

---

## The security proposition stated plainly

For all modes, the Pico XOR changes the attacker's problem from:

> "Break the physical input quality plus SHA-256"

to:

> "Break the physical input quality AND the Pico's 128-bit hardware
> randomness, plus SHA-256"

An attacker needs both. The two sources are physically independent —
different silicon, different physical mechanism (digital TRNG noise vs.
shuffled cards or rolled dice), different time of acquisition. There
is no single point of failure.

This is the value proposition of the Pico injection: not a statistical
improvement to the output (SHA-256 already makes the output look
uniform), but a structural improvement to the security argument.

---

## Adversarial questions

### "How do I know the Pico isn't compromised? It's a cheap chip from
a factory I've never seen."

You don't have to know. See the XOR guarantee above. A completely
compromised Pico — one producing zeros, ones, or a known sequence —
reduces your seed to the strength of your physical input alone. That's
the same security you'd have without the Pico. It cannot go below that.

### "What if the Pico firmware was backdoored and is sending my seed
somewhere?"

The Pico 2 has no WiFi, no Bluetooth, no network connection of any
kind. The only channel it has is the USB cable to your laptop. The
firmware source code is in this repository and is auditable. If you
want to verify the binary matches the source, the build instructions
are in `../secure-mint-devices/pico2-rp2350/`.

**The Pico is stateless and stores nothing.** The firmware is 52 lines
of C. The full protocol is: host sends one byte `R`, Pico replies with
256 raw TRNG bytes, loop. No flash writes. No session state. No memory
of prior requests. The output buffer is stack-allocated and exists only
for the duration of one response. Unplug the Pico and nothing is
retained — there is nothing to retain. Read it yourself:
`secure-mint-devices/pico2-rp2350/firmware/main.c`.

More importantly: the Pico never sees your seed. It never sees your
cards, dice, or DnD throws. It produces bytes before your physical
input is processed. Those bytes go into the XOR before SHA-256 runs.
The Pico has no visibility into the final seed.

### "What if the Pico is producing predictable output and an attacker
knows its sequence in advance?"

Then your seed falls back to the strength of your physical input alone.
For cards: ~2^216 possibilities before SHA-256. For dice: depends on
the number of rolls. For DnD: ~18.8 bits per throw before SHA-256.
That is the same security you would have without the Pico at all. The
Pico cannot reduce your security below that floor.

### "The NIST qualification could be fabricated or tested incorrectly."

The qualification data is in `../secure-mint-devices/pico2-rp2350/`.
The raw sample files are there. The NIST SP 800-90B assessment tool
that produced the results is open source at
github.com/usnistgov/SP800-90B_EntropyAssessment. You can download it,
feed it the same raw data, and reproduce every number yourself. The
assessed min-entropy is 7.466 bits/byte. The health floor is 4.24
bits/byte — if a live sample drops below that, the firmware rejects it.

### "I'd rather just use my physical input and not introduce hardware
I don't control."

That is a completely valid choice. Don't scan for the Pico in settings
and don't enable it. Your physical input alone — cards, D6 rolls, or
DnD throws — with proper execution produces a strong seed. The Pico
is an optional layer. We built it so it cannot hurt you if you don't
trust it, and can only help if you do.

### "What if the USB cable itself is an attack vector?"

A malicious cable that injects crafted bytes would need to know your
physical input in advance to produce bytes that weaken the XOR. It
doesn't — your physical session hasn't happened yet when the Pico
produces its bytes. A cable that reads the Pico's output gives an
attacker knowledge of one XOR input, not the result. They still don't
know your card/dice sequence.

If the cable disrupts the connection entirely, the application falls
back to your physical input alone and shows you a warning. It never
silently degrades.

---

## The one honest concession

If an attacker simultaneously:

1. Compromised the Pico firmware to produce a known sequence, AND
2. Had full knowledge of your physical input (watched every card and
   every die), AND
3. Broke SHA-256

...they could reconstruct your seed.

At that point you have larger problems. SHA-256 breaking is an
extinction-level event for essentially all digital security. And
someone with full knowledge of your physical session was in the room
with you.

The threat model here is realistic attackers with realistic
capabilities. Against those, the Pico adds genuine defense in depth
at the cost of plugging in a $15 USB device.

---

## Summary table

| Scenario | Without Pico | With Pico |
|---|---|---|
| Good physical input, good Pico | Strong | Strong |
| Biased/weak physical input, good Pico | Weaker | Strong |
| Good physical input, bad/compromised Pico | Strong | Strong |
| Bad physical input, bad Pico | Weaker | Weaker (same as no Pico) |
| Pico read fails | Strong | Strong (fallback) |

This table is identical for all four input modes. The physical source
changes; the XOR guarantee does not.

---

## Qualification record

- **Device:** Raspberry Pi Pico 2 (RP2350)
- **Assessed min-entropy:** 7.466 bits/byte (non-IID), 7.302 (IID)
- **Standard:** NIST SP 800-90B
- **Health floor:** 4.24 bits/byte (80% of validated baseline)
- **Full record:** `../secure-mint-devices/pico2-rp2350/qualification.json`
- **Firmware:** `../secure-mint-devices/pico2-rp2350/firmware/`


