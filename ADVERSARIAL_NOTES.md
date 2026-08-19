# Adversarial Test Notes

Tracks known gaps, weaknesses, and detection rates in the statistical
test suite. Updated after each adversarial testing session.

## Test parameters

- **128-bit mode:** 27 cards, no dice
- **256-bit mode:** 52 cards, 20 dice rolls (minimum enforced)
- **Significance:** two-sided z-score bands: |z| > 2.576 = FLAG,
  |z| > 1.96 = BORDERLINE. Chi-square at α=0.01 and α=0.05.
  Exact binomial for repeat-exact test: P < 0.01 = FLAG, P < 0.05 =
  BORDERLINE.
- **Total tests:** 14 (6 card, 8 dice)

## Session: 2026-08-05 — initial adversarial run (10 tests)

Identified three GAPs and two WEAKs. See "Gap analysis" section below
for root causes that motivated the four new tests added afterward.

### Dice patterns (256-bit mode, 20 rolls, 10-test suite)

| Pattern | Caught | Rate | Status |
|---|---|---|---|
| Constant (all 3s) | 300/300 | 100% | OK |
| Cycling (1-6 repeat) | 300/300 | 100% | OK |
| Alternating (1,6,1,6) | 300/300 | 100% | OK |
| Sawtooth (1-6-1 wave) | 300/300 | 100% | OK |
| Chunked pairs (1,1,3,3...) | 300/300 | 100% | OK |
| Strict odd-even varying | 300/300 | 100% | OK |
| Nearly-sorted ascending | 300/300 | 100% | OK |
| Increment-by-1 mod 6 | 300/300 | 100% | OK |
| **Ascending wave** | 58/300 | **19.3%** | **GAP** |
| **Descending wave** | 60/300 | **20.0%** | **GAP** |
| **Avoid-repeat** | 79/300 | **26.3%** | **GAP** |
| **Center bias (favor 3,4)** | 206/300 | **68.7%** | **WEAK** |

### Card patterns (128-bit mode, 27 cards, 10-test suite)

| Pattern | Caught | Rate | Status |
|---|---|---|---|
| **All face cards first** | 255/300 | **85.0%** | **WEAK** |
| All other patterns | 300/300 | 100% | OK |

## Session: 2026-08-05 — after adding 4 new tests (14 total)

Four tests added to close the identified gaps:
- **test_dice_diff_sign_runs**: empirically-calibrated runs test on
  the sign of consecutive differences; catches wave patterns
- **test_dice_repeat_exact**: exact binomial probability for low
  repeat counts; catches avoid-repeat at n=20
- **test_dice_extremes**: count of 1s and 6s vs expected 1/3; catches
  center bias
- **test_card_rank_draw_order**: Spearman rank-position correlation;
  catches composition-ordering bias in partial draws

### Dice patterns (256-bit mode, 20 rolls, 14-test suite)

| Pattern | Before | After | Status |
|---|---|---|---|
| Ascending wave | 19.3% | **100%** | **FIXED** |
| Descending wave | 20.0% | **100%** | **FIXED** |
| Avoid-repeat | 26.3% | **100%** | **FIXED** |
| Center bias | 68.7% | **79.7%** | **IMPROVED (still WEAK)** |
| Gentle wave (2,3,2,3,4,...) | (not tested) | **100%** | OK |
| Random-looking wave (3,5,2,4,...) | (not tested) | **100%** | OK |
| All other patterns | 100% | 100% | OK |

### Card patterns (128-bit mode, 27 cards, 14-test suite)

| Pattern | Before | After | Status |
|---|---|---|---|
| All face cards first | 85.0% | **100%** | **FIXED** |
| All other patterns | 100% | 100% | OK |

### False positive rate (14-test suite, 2000 trials)

| Mode | STOP | CAUTION | Combined FP |
|---|---|---|---|
| 256-bit (random cards + dice) | ~13% | ~26% | **~40%** |
| 128-bit (random cards only) | ~5% | ~15% | **~20%** |

The FP increase from ~25% (10 tests) to ~40% (14 tests) is a direct
consequence of more tests at unchanged per-test significance levels.
Per-test FP rates are 3-7% each (well-calibrated individually); the
combined rate rises because P(at least 1 borderline among 14 tests)
grows with the test count. Bonferroni correction is deliberately NOT
applied per the existing design philosophy: false positives cost a
reshuffle; false negatives cost a wallet.

### Remaining weakness

**Center bias (3,4 heavily favored):** 79.7% detection. The chi-square
test is underpowered at n=20 for moderate distributional bias (expected
cell count ~3.3), and the extremes test catches it when 1s/6s are
sufficiently absent but not when the bias is mild. Accepted as a
residual weakness: moderate center bias on 20 rolls produces less
entropy loss than severe bias and is partially mitigated by the card
entropy dominating the pool.

## Gap analysis (pre-fix)

### GAP: Ascending/descending wave

**Root cause:** near-uniform face frequency and enough variation to
dodge periodicity. Transition-direction test sees balanced up/down
counts (wave backtracks enough to equalize). No test measured
sequential sign structure of consecutive differences.

**Fix:** test_dice_diff_sign_runs — empirically calibrated for n=20
D6 rolls (theoretical Wald-Wolfowitz is biased for bounded-range
diffs). Ascending wave: 16 sign-change runs vs empirical mean 11.89,
z=2.14 (BORDERLINE). Descending wave: 17 runs, z=2.66 (FLAG).

### GAP: Avoid-repeat

**Root cause:** 0 repeats in 19 transitions gives z=-1.95 in the
existing z-score repeat-rate test — 0.01 below the BORDERLINE
threshold of 1.96. The z-score approximation is not sharp enough at
n=20 for this specific boundary case.

**Fix:** test_dice_repeat_exact — exact binomial probability.
P(0 repeats | n=19, p=1/6) = (5/6)^19 = 0.031, clearly below the
0.05 BORDERLINE threshold.

### WEAK: Face cards first (128-bit)

**Root cause:** rank-clustering test uses a binary middle/edge split
that detects composition bias but not position-ordering bias.

**Fix:** test_card_rank_draw_order — Spearman rank-position
correlation. Face-cards-first gives rho=-0.59, z=-3.0 (FLAG).
