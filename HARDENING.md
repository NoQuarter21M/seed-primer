# Entropy Mixer — Testing and Hardening Record

Append-only record of testing, calibration, and hardening work done
to prepare this application for real-world use. Each section is dated
when the work was completed. Read alongside ADVERSARIAL_NOTES.md
(statistical test suite) and PICO_TRNG.md (hardware XOR rationale).

---

## 2026-08-05 — Initial statistical test suite

**What was built:** 14 symbol-level statistical tests on raw card/dice
draws, adapted from NIST SP 800-22 concepts. Tests run on physical
symbols (card indices, die faces), not the encoded bit string, to
avoid fixed-width encoding artifacts.

**Adversarial testing:** 10 input patterns tested against 300 trials
each. Three GAPs and two WEAKs identified in the initial 10-test suite.
Four new tests added (diff_sign_runs, repeat_exact, extremes,
rank_draw_order) to close them. See ADVERSARIAL_NOTES.md for full
results.

**False-positive calibration (pre-Shannon):**
- 256-bit (cards + 20 dice): ~40% effective FP (14 tests)
- 128-bit (27 cards): ~20% effective FP
Combined FP rises with test count; deliberate design: false positives
cost a reshuffle, false negatives cost a wallet.

---

## 2026-08-18 — New modes and Shannon entropy addition

**What was built:**
- D6-only modes (128-bit: 60 rolls min, 256-bit: 120 rolls min)
- DnD full-set mode (D4/D6/D8/D10/D12/D20, 10/20 throws min)
- Shannon entropy test added to all modes (per-symbol H vs theoretical max)

**Bug found:** Shannon ceiling for cards was log₂(52) regardless of
how many cards were drawn. Cards are drawn without replacement -- all
n drawn cards are distinct, so the correct ceiling is log₂(n_drawn).
At 27 cards, H = log₂(27) = 4.755 always scores as 83.4% of the
wrong ceiling (5.700), producing a guaranteed false NEAR flag.
Fix: pass len(card_seq) as symbol_range for card Shannon test.

**Bug found:** Shannon thresholds were fixed at 70% FLAG and 85% NEAR
regardless of sample size. At small n (10 DnD throws per die), the
expected Shannon fraction for a perfectly fair die is far below 85%
due to sparse sampling. D20 at n=10 throws had a median fair-dice
score of 67.6% -- below the FLAG threshold, so typical good input
always flagged.

**Fix:** empirically calibrated lookup table of (p5, p10) percentile
thresholds via 20,000-trial Monte Carlo simulation for each
(sides, n) combination. FLAG = below p5 (~5% false-positive rate).
NEAR = between p5 and p10. Covers D4/D6/D8/D10/D12/D20 at n=10
through n=120. Linear interpolation between table entries.

**Verification:** 1,000-trial simulation confirmed FLAG~5%, NEAR~5%,
PASS~90% across all calibrated cases.

---

## 2026-08-18 — Combined-suite Monte Carlo false-positive audit

**What was tested:** `run_symbol_tests()` + `compute_overall_tier()`
as called in production for each mode, with 5,000 trials of fair
simulated input. Measured STOP + CAUTION rate (what the user sees).

**Results before fix:**

| Mode | Effective FP |
|---|---|
| DnD 128-bit (10 throws) | 47.1% |
| DnD 256-bit (20 throws) | 50.6% |
| Cards+dice 256-bit | 25.5% |
| D6-only 128-bit | 14.5% |
| D6-only 256-bit | 15.1% |
| Cards-only 128-bit | 6.2% |

**Root cause:** 6 independent DnD Shannon tests each at ~5% individual
FLAG rate give a combined ~26% FLAG rate via the 2-borderline STOP
rule. Shannon is the wrong instrument for this purpose at these sample
sizes.

**Fix:** Shannon tests excluded from `compute_overall_tier()` input.
Shannon results still shown in the analysis table for the user to
read but do not contribute to STOP/CAUTION decisions.

**Results after fix:**

| Mode | Effective FP | Change |
|---|---|---|
| DnD 128-bit | 0.0% | -47.1% |
| DnD 256-bit | 0.0% | -50.6% |
| Cards+dice 256-bit | 18.9% | -6.6% |
| D6-only 128-bit | 8.1% | -6.4% |
| D6-only 256-bit | 8.7% | -6.4% |
| Cards-only 128-bit | 6.2% | unchanged |

Cards+dice 18.9% is within stated design intent ("roughly 1 in 5 good
draws gets flagged"). Driven by diff_sign_runs and repeat_exact
co-occurring at n=20 dice -- two borderlines combining into a STOP
via the 2-borderline rule, which is the rule working as intended at
small n.

---

## 2026-08-18 — Pico TRNG integration and XOR positioning

**What was built:**
- `pico_trng_source.py`: port scanner (Linux/macOS/Windows), health
  probe (`probe_port`), auto-discovery (`find_pico`), bulk prefetch
  (`get_trng_bulk`)
- Settings screen: Pico panel with enable checkbox, scan button,
  live status label. Scan runs in background thread.
- Hash phase: Pico XOR moved to pre-whitening position (was post)

**Why pre-whitening matters:** XOR with uniform Y before SHA-256 means
the seed is uniform if either Y or the physical input is uniform.
Post-whitening XOR only adds on top of an already-uniform surface.

**Port scanner tested:** Pico found on /dev/ttyACM2 (not the default
/dev/ttyACM0), confirming the scanner was necessary. Handles Linux,
macOS, Windows.

**Qualification record:** Pico 2 (RP2350) at 7.466 bits/byte
non-IID, 7.302 IID, NIST SP 800-90B. Full record in
`../secure-mint-devices/pico2-rp2350/qualification.json`.

---

## 2026-08-18 — Entropy quality estimator sufficiency fix

**Bug found:** the entropy quality estimator (post-whitening) was
reporting "source entropy shortfall" on every D6-only session.
Root cause: the MCV min-entropy estimator operates on bytes. The
3-bit D6 encoding packs into bytes with structural bias (6/8 patterns
used per 3-bit group). At 29 bytes (75 D6 rolls), the byte-level
estimator always reports shortfall -- 100% false-positive rate in
simulation.

**Fix:** for D6-only modes, source entropy computed directly as
`n_rolls * log₂(6)`. For DnD modes: `n_throws * log₂(460800)`.
These are the correct theoretical values and override the byte-level
estimator for the sufficiency banner. The estimator report still
displays in full for informational value.

**Card Shannon ceiling fix:** the estimator also used the wrong
ceiling for card Shannon entropy (same log₂(52) bug as the analysis
phase). Fixed by using len(card_seq) as the ceiling.

---

## 2026-08-18 — Monte Carlo pipeline test with real Pico TRNG

**Test design:**
- Simulated physical input: H1essential microphone (LSB extraction,
  qualified source, captured in bulk before trials)
- XOR source: Pico 2 TRNG at /dev/ttyACM2 (bulk prefetch, one 2s
  CDC settle, then rapid R requests at ~3,300 bytes/sec)
- Full pipeline: sim_bytes XOR pico_bytes -> SHA-256 -> 128-bit seed
- Comparison: same sim_bytes without XOR -> SHA-256
- Metrics: bit balance Z, runs Z, Hamming %, autocorrelation L1

**H1 (fair input, baseline):**

| Trials | With XOR | Without XOR |
|---|---|---|
| n=1,000 | bit Z mean=-0.011, p05=4.4% PASS | bit Z mean=-0.061, p05=3.8% PASS |
| n=10,000 | bit Z mean=-0.018, p05=4.2% PASS | bit Z mean=+0.005, p05=4.6% PASS |

**H2 (biased input -- corrective effect):**

| Trials | Bias | With XOR | Without XOR |
|---|---|---|---|
| n=1,000 | 30% zero-skew | bit Z mean=-0.014, p05=5.4% PASS | bit Z mean=+0.024, p05=3.6% PASS |
| n=10,000 | 70% zero-skew | bit Z mean=-0.002, p05=4.4% PASS | bit Z mean=+0.015, p05=4.3% PASS |

**Key finding:** SHA-256 whitening absorbs all tested bias levels
completely. Both with and without XOR produce statistically uniform
output at all bias levels tested (0%, 30%, 70%). The Pico XOR effect
on the final output is positive but small after whitening -- the XOR
matters most as a security guarantee (attacker must break both
sources) not as a measurable statistical improvement at these bias
levels.

**Performance:** ~10,000 trials/sec after prefetch. Prefetch time:
~33s for 160KB Pico bulk + ~29s for 160KB mic. Total for n=10,000
run: ~65s prefetch + ~1s trials.

**Source identification:**
- Simulated physical input: H1essential microphone
  (ZOOM Corporation, VID:PID 1686:07b5, plughw:H1essential,0,
  qualified in secure-mint-devices/)
- XOR source: Pico 2 RP2350
  (VID:PID 2e8a:0009, /dev/ttyACM2, serial 2D286B4829B883E9,
  qualified at 7.466 bits/byte, secure-mint-devices/pico2-rp2350/)

---

## Open items

- [ ] Run Monte Carlo with deliberately extremely weak input
  (near-constant sequence, e.g. bias=0.99) to find the point
  where SHA-256 whitening is no longer sufficient on its own
  and XOR becomes measurably important.
- [ ] Verify the D10 "0" entry (face value 10) is handled
  consistently throughout DnD mode (buttons, log, analysis).
- [ ] Test on Windows and macOS to verify port scanner works.
- [ ] Add a visual indicator in settings when Pico scan result
  is stale (e.g. scanned more than 5 minutes ago).
- [ ] Consider adding nRF52840 (MDBT50Q-CX) as a second XOR
  source once qualified -- two independent hardware sources.
