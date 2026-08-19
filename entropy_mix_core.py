"""
entropy_mix_core.py

Core, testable functions for the Card + Dice Entropy Generator.

PIPELINE (matches the agreed spec):
  1. Pre-flight settings: seed length (128/256 bit), shuffle count,
     dice quality. Produces a fixed upfront bit-penalty.
  2. Card draws (23 for 128-bit, 52 for 256-bit) + D6 dice top-up.
     A single live discounted-bit counter tracks progress against
     the target, gated red/orange/green.
  3. Raw physical draws are tested with SYMBOL-LEVEL statistical
     checks (card suit runs, card rank sequences, dice uniformity
     chi-square, dice repeat rate) adapted from NIST SP 800-22
     concepts. Advisory only -- not a compliance claim. See the test
     section below for why symbol-level (not bit-level) is correct
     for this encoding.
  4. SHA-256(raw entropy bytes) -> whitened entropy.
     SHA-256(whitened entropy) -> SEPARATE call, first N bits used
     as the BIP-39 checksum. These are two distinct hash operations.
  5. Standard BIP-39 entropy-to-mnemonic mapping (12 or 24 words).

This tool makes NO NIST compliance claims. Statistical tests are
symbol-level checks adapted from NIST SP 800-22 concepts for short
physical-draw inputs, and are indicative only -- not certifying.

No network code. No disk writes of entropy/mnemonic. No clipboard use.
Data exists only in process memory while running; Python cannot
guarantee secure memory scrubbing, and this tool does not claim it.
"""

import hashlib
import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CARDS_FOR_128 = 27    # cards-only 128-bit: 27 cards clears 128 discounted bits without dice
CARDS_FOR_256 = 52    # mixed 256-bit: full deck + 20 dice rolls
DICE_SIDES = 6
DICE_BITS = math.log2(DICE_SIDES)
DICE_MIN_ROLLS = 20   # minimum rolls enforced in 256-bit mixed mode for meaningful statistical testing

# ---------------------------------------------------------------------------
# D6-only mode constants
# ---------------------------------------------------------------------------
# Consumer-grade D6: 5% bias discount per roll -> 2.222 discounted bits/roll
# Rolls needed (group of 5): ceil(target / (5 * discounted_bits_per_roll))
# 128-bit: ceil(128 / (5 * 2.222)) = ceil(11.52) = 12 groups = 60 rolls min
# 256-bit: ceil(256 / (5 * 2.222)) = ceil(23.04) = 24 groups = 120 rolls min
D6_MIN_GROUPS_128 = 12   # groups of 5 rolls for 128-bit D6-only
D6_MIN_GROUPS_256 = 24   # groups of 5 rolls for 256-bit D6-only

# ---------------------------------------------------------------------------
# DnD set constants (D4/D6/D8/D10/D12/D20, fixed order)
# ---------------------------------------------------------------------------
DND_DICE = [
    ("D4",  4),
    ("D6",  6),
    ("D8",  8),
    ("D10", 10),
    ("D12", 12),
    ("D20", 20),
]
# Raw bits per full DnD throw: log2(4*6*8*10*12*20) = log2(460800) = 18.807
DND_RAW_BITS_PER_THROW = math.log2(4 * 6 * 8 * 10 * 12 * 20)  # 18.807
# Consumer 5% discount applied per-die across 6 dice: 0.95^6 factor on raw bits
DND_CONSUMER_FACTOR = 0.95 ** 6   # ~0.7351
DND_PRECISION_FACTOR = 0.98 ** 6  # ~0.8858
# Discounted bits per throw:
#   consumer:  18.807 * 0.7351 = 13.827
#   precision: 18.807 * 0.8858 = 16.658
# Throws needed (consumer):
#   128-bit: ceil(128 / 13.827) = 10
#   256-bit: ceil(256 / 13.827) = 19  (use 20 for statistical test power)
DND_MIN_THROWS_128 = 10
DND_MIN_THROWS_256 = 20

# Total variation distance of a riffle-shuffled 52-card deck from uniform,
# after k shuffles. Bayer & Diaconis, "Trailing the Dovetail Shuffle to its
# Lair" (1992) -- the standard reference result for riffle-shuffle mixing.
# For k > 12, TV distance is extrapolated as roughly halving per additional
# shuffle, consistent with the cutoff phenomenon documented in that paper.
_BAYER_DIACONIS_TV = {
    1: 1.0000, 2: 1.0000, 3: 1.0000, 4: 1.0000,
    5: 0.9237, 6: 0.6135, 7: 0.3352, 8: 0.1671,
    9: 0.0854, 10: 0.0429, 11: 0.0215, 12: 0.0108,
}

_CARD_PERMUTATION_BITS = math.log2(math.factorial(52) - 1)


def _tv_distance(k: int) -> float:
    if k in _BAYER_DIACONIS_TV:
        return _BAYER_DIACONIS_TV[k]
    if k > 12:
        return _BAYER_DIACONIS_TV[12] * 0.5 ** (k - 12)
    return 1.0


def _binary_entropy(d: float) -> float:
    if d <= 0.0 or d >= 1.0:
        return 0.0
    return -d * math.log2(d) - (1 - d) * math.log2(1 - d)


def shuffle_entropy_loss_bits(shuffle_count: int) -> float:
    """
    Bits of card-permutation entropy lost to imperfect mixing, via the
    Fannes-Audenaert inequality: for a distribution within total variation
    distance d of uniform over N outcomes,
        |H - log2(N)| <= d * log2(N-1) + h2(d)
    This bounds how far the *actual* shuffle entropy can fall short of the
    log2(52!) ceiling, using the real Bayer-Diaconis mixing distance rather
    than an arbitrary percentage. Capped at the full permutation ceiling.
    """
    d = _tv_distance(shuffle_count)
    loss = d * _CARD_PERMUTATION_BITS + _binary_entropy(d)
    return min(loss, _CARD_PERMUTATION_BITS)


# Small fixed per-roll discount for consumer-grade dice vs precision.
DICE_QUALITY_DISCOUNT = {
    "consumer": 0.05,    # 5% of each roll's bit value docked
    "precision": 0.0,
}

ZONE_THRESHOLDS = {
    "weak_max": 0.50,      # 0-50% of target = red
    "marginal_max": 0.85,  # 50-85% = orange
    # 85-100% = yellow-green, 100%+ = green
}

# ---------------------------------------------------------------------------
# Pre-flight: shuffle / dice-quality penalty
# ---------------------------------------------------------------------------

def shuffle_status(shuffle_count: int):
    """
    Returns (blocked: bool, loss_bits: float, message: str)
    blocked=True means the caller must refuse to proceed (re-shuffle
    required) rather than merely warn.

    Below 7 shuffles is blocked outright: at 5-6 shuffles the Bayer-Diaconis
    bound shows 139-209 bits of the ~225.6-bit card permutation ceiling are
    lost to imperfect mixing -- far more than a "penalty", closer to total
    loss. 7 shuffles is the well-documented point (Bayer-Diaconis) where a
    riffle-shuffled deck becomes reasonably close to uniform.
    """
    if shuffle_count < 7:
        theoretical_loss = shuffle_entropy_loss_bits(max(shuffle_count, 1))
        return True, theoretical_loss, (
            f"{shuffle_count} shuffle(s) is too few -- at this count, "
            f"Bayer-Diaconis mixing theory indicates roughly "
            f"{theoretical_loss:.0f} of the deck's ~226-bit permutation "
            f"entropy is lost to imperfect mixing. Re-shuffle at least 7 "
            f"times (10+ recommended) before drawing cards."
        )
    loss_bits = shuffle_entropy_loss_bits(shuffle_count)
    return False, loss_bits, (
        f"{shuffle_count} shuffles: an estimated {loss_bits:.1f} bits of "
        f"card-permutation entropy are lost to imperfect mixing "
        f"(Bayer-Diaconis bound)."
    )


def target_bits_for_mode(mode: str) -> int:
    """128 or 256 bits depending on mode string."""
    return 256 if mode in ("256", "d6_256", "dnd_256") else 128


def cards_needed_for_mode(mode: str) -> int:
    """0 for dice-only modes; card count for card-based modes."""
    if mode in ("d6_128", "d6_256", "dnd_128", "dnd_256"):
        return 0
    return CARDS_FOR_256 if mode == "256" else CARDS_FOR_128


def is_cards_only_mode(mode: str) -> bool:
    return mode == "128"


def is_dice_only_mode(mode: str) -> bool:
    return mode in ("d6_128", "d6_256", "dnd_128", "dnd_256")


def is_d6_mode(mode: str) -> bool:
    return mode in ("d6_128", "d6_256")


def is_dnd_mode(mode: str) -> bool:
    return mode in ("dnd_128", "dnd_256")


def is_two_deck_mode(mode: str) -> bool:
    return False  # two-deck mode removed; retained for future use


def d6_min_groups(mode: str) -> int:
    """Minimum number of 5-roll groups for a D6-only mode."""
    return D6_MIN_GROUPS_256 if mode == "d6_256" else D6_MIN_GROUPS_128


def dnd_min_throws(mode: str) -> int:
    """Minimum number of full DnD throws for a DnD mode."""
    return DND_MIN_THROWS_256 if mode == "dnd_256" else DND_MIN_THROWS_128


def dnd_throw_bits(dice_quality: str) -> float:
    """Discounted bits per complete DnD throw (all 6 dice)."""
    factor = DND_CONSUMER_FACTOR if dice_quality == "consumer" else DND_PRECISION_FACTOR
    return DND_RAW_BITS_PER_THROW * factor


def dnd_throws_to_raw_bits(throws: list) -> str:
    """
    Encode a list of DnD throws as a fixed-width binary string for hashing.
    Each throw is a tuple (d4, d6, d8, d10, d12, d20), 1-indexed face values.
    Encoding: mixed-radix integer N = ((((d4-1)*6 + d6-1)*8 + d8-1)*10 + d10-1)*12 + d12-1)*20 + d20-1
    Range: 0 .. 460799 -> 19 bits each throw (2^19=524288 > 460800, no bias issue
    at encoding; the physical uniformity is what matters, tested separately).
    """
    bits = []
    for throw in throws:
        d4, d6, d8, d10, d12, d20 = throw
        n = ((((((d4 - 1) * 6 + (d6 - 1)) * 8 + (d8 - 1)) * 10 + (d10 - 1)) * 12 + (d12 - 1)) * 20 + (d20 - 1))
        bits.append(format(n, "019b"))
    return "".join(bits)


def compute_upfront_discount_bits(mode: str, shuffle_count: int) -> float:
    """Bits deducted upfront, from the Bayer-Diaconis mixing bound. This is
    an absolute bit quantity tied to the deck's permutation entropy, not a
    percentage of the seed-length target -- a 5-shuffle deck loses the same
    number of bits whether you're making a 12-word or 24-word seed."""
    blocked, loss_bits, _msg = shuffle_status(shuffle_count)
    if blocked:
        return _CARD_PERMUTATION_BITS  # effectively unreachable; caller blocks progression
    return loss_bits


# ---------------------------------------------------------------------------
# Progressive (discounted) bit counter
# ---------------------------------------------------------------------------

def card_draw_bits(draw_index: int) -> float:
    """Ceiling bits contributed by the draw_index-th card (0-based),
    drawn without replacement from a 52-card deck."""
    remaining = 52 - draw_index
    if remaining <= 0:
        raise ValueError("no cards remain to draw")
    return math.log2(remaining)


def dice_roll_bits(dice_quality: str) -> float:
    discount = DICE_QUALITY_DISCOUNT.get(dice_quality, 0.05)
    return DICE_BITS * (1.0 - discount)


def zone_for_fraction(fraction: float) -> str:
    """fraction = discounted_bits_so_far / target_bits"""
    if fraction < ZONE_THRESHOLDS["weak_max"]:
        return "red"
    if fraction < ZONE_THRESHOLDS["marginal_max"]:
        return "orange"
    if fraction < 1.0:
        return "yellow-green"
    return "green"


# ---------------------------------------------------------------------------
# Raw binary construction (this is what the NIST subset must run on --
# NEVER run these tests on the SHA-256 output, which always looks random
# regardless of input quality)
#
# IMPORTANT: cards/dice are encoded as fixed-width raw binary directly --
# NOT as an ASCII/text string. A text encoding (e.g. "AS-10H-KD|3261")
# bakes in separator characters and repeated letter patterns that are
# themselves structured, which would fail the NIST subset regardless of
# how good the underlying physical entropy actually is. Fixed-width binary
# per symbol avoids that artifact entirely.
# ---------------------------------------------------------------------------

def canonical_card_index(card_id: str) -> int:
    """Fixed global index 0-51 for a card id like 'AS', '10H', 'KD'."""
    suit = card_id[-1]
    rank = card_id[:-1]
    suit_order = {"S": 0, "H": 1, "D": 2, "C": 3}
    rank_order = {r: i for i, r in enumerate(
        ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"])}
    return suit_order[suit] * 13 + rank_order[rank]


def build_raw_string(card_seq: list, dice_seq: list) -> str:
    """Human-readable audit string only -- NOT used for hashing or NIST
    testing. Kept for on-screen display / manual record-keeping."""
    card_part = "-".join(card_seq)
    dice_part = "".join(str(d) for d in dice_seq)
    return card_part + "|" + dice_part


def raw_entropy_bits(card_seq: list, dice_seq: list,
                     dnd_throws: list = None) -> str:
    """
    Fixed-width binary encoding used for NIST testing and hashing:
      - each card:     6 bits (global canonical index 0-51)
      - each D6 roll:  3 bits (value-1, i.e. 0-5)
      - each DnD throw: 19 bits (mixed-radix encoding, see dnd_throws_to_raw_bits)
    """
    bits = []
    for card_id in card_seq:
        idx = canonical_card_index(card_id)
        bits.append(format(idx, "06b"))
    for roll in dice_seq:
        bits.append(format(roll - 1, "03b"))
    if dnd_throws:
        bits.append(dnd_throws_to_raw_bits(dnd_throws))
    return "".join(bits)


# ---------------------------------------------------------------------------
# Statistical tests -- SYMBOL-LEVEL, advisory only, not certifying.
#
# WHY SYMBOL-LEVEL: the fixed-width binary encoding (6 bits/card for
# values 0-51, 3 bits/die for values 0-5) does not use the full range
# of each bit group, so even perfectly fair physical entropy produces
# systematically biased BITS (card MSB is '1' only 20/52 of the time;
# die MSB only 2/6). Bit-level NIST tests would therefore drift toward
# false FLAGs on genuinely good input. Testing the SYMBOLS themselves
# (card indices, die faces) tests what we actually care about -- are
# the physical draws uniform? -- without the encoding artifact.
# The bit string remains correct as HASH input; it is only wrong as
# TEST input.
#
# Methodology adapted from NIST SP 800-22 concepts (frequency, runs)
# applied at the symbol level. Each test returns:
#   {name, statistic, pass, note}
# ---------------------------------------------------------------------------

def _erfc(x):
    # Complementary error function via math.erf (stdlib, no scipy needed)
    return 1.0 - math.erf(x)


# Chi-square critical values at 0.01 significance, by degrees of freedom.
_CHI2_CRIT_001 = {1: 6.635, 3: 11.345, 5: 15.086, 12: 26.217, 51: 77.386}


_CHI2_CRIT_005 = {1: 3.841, 3: 7.815, 5: 11.070, 12: 21.026, 51: 68.669}

# α=0.02 critical values -- used for chi-square-based borderline
# after adversarial tuning showed α=0.05 produced too many FPs at n=20.
_CHI2_CRIT_002 = {1: 5.412, 2: 7.824, 3: 9.837, 5: 13.388, 12: 23.337, 51: 72.616}


def _chi2_crit(df: int, alpha: str = "01") -> float:
    """Critical value at the given significance ("01", "02", or "05").
    Wilson-Hilferty approximation for degrees of freedom not in the
    lookup tables."""
    if alpha == "01":
        table, z = _CHI2_CRIT_001, 2.326
    elif alpha == "02":
        table, z = _CHI2_CRIT_002, 2.054
    else:
        table, z = _CHI2_CRIT_005, 1.645
    if df in table:
        return table[df]
    return df * (1 - 2 / (9 * df) + z * math.sqrt(2 / (9 * df))) ** 3


# Two-tier z-score bands: |z| > 2.576 is a hard FLAG (α ≈ 0.01
# two-sided), |z| > 2.33 but <= 2.576 is BORDERLINE (α ≈ 0.02
# two-sided). Thresholds were tuned via adversarial testing to keep the
# combined false-positive rate (STOP + CAUTION) under 24% across 13
# tests, while maintaining ≥ 95% detection on all identified attack
# patterns. See ADVERSARIAL_NOTES.md for the full calibration record.
_Z_FLAG = 2.576
_Z_BORDERLINE = 2.33


def _level_from_z(z: float) -> str:
    az = abs(z)
    if az > _Z_FLAG:
        return "flag"
    if az > _Z_BORDERLINE:
        return "borderline"
    return "pass"


def test_dice_uniformity(dice_seq: list) -> dict:
    """Chi-square on die-face frequencies (df=5).

    Under a fair die (the null hypothesis), the EXPECTED VALUE of the
    chi-square statistic itself is approximately the degrees of freedom
    (5) -- that's the standard reference point a reader needs to judge
    the observed number against, not just a pass/fail critical value
    with no context."""
    n = len(dice_seq)
    df = 5
    if n < 12:
        return {
            "name": "Dice uniformity (chi-square)",
            "statistic": None,
            "expected": df,
            "critical": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 12+ for a meaningful test.",
        }
    counts = [dice_seq.count(v) for v in range(1, 7)]
    expected_count = n / 6
    chi2 = sum((c - expected_count) ** 2 / expected_count for c in counts)
    crit01 = _chi2_crit(df, "01")
    crit02 = _chi2_crit(df, "02")
    level = "flag" if chi2 > crit01 else ("borderline" if chi2 > crit02 else "pass")
    return {
        "name": "Dice uniformity (chi-square)",
        "statistic": round(chi2, 3),
        "expected": df,
        "critical": round(crit01, 2),
        "level": level,
        "note": f"Face counts {counts} (expected {expected_count:.1f} each). "
                f"This sample size can only flag strong bias; subtle "
                f"unfairness wouldn't trigger a FLAG.",
    }


def test_dice_repeat_rate(dice_seq: list) -> dict:
    """Repeat-transition rate. A fair D6 repeats the previous face 1/6 of
    the time; large deviation either way is flagged."""
    n = len(dice_seq)
    if n < 12:
        return {
            "name": "Dice repeat rate",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 12+ for a meaningful test.",
        }
    repeats = sum(1 for i in range(1, n) if dice_seq[i] == dice_seq[i - 1])
    trials = n - 1
    p = 1 / 6
    mean = trials * p
    sd = math.sqrt(trials * p * (1 - p))
    z = (repeats - mean) / sd if sd else 0.0
    level = _level_from_z(z)
    note = f"{repeats} repeats in {trials} transitions (expected ~{mean:.1f})."
    if z < -_Z_BORDERLINE:
        note += " Too FEW repeats -- classic human 'avoid repeating' bias."
    elif z > _Z_BORDERLINE:
        note += " Too MANY repeats -- possible stuck die or misreads."
    return {
        "name": "Dice repeat rate",
        "statistic": round(z, 3),
        "level": level,
        "note": note,
    }


def test_dice_transition_direction(dice_seq: list) -> dict:
    """3-way chi-square on whether each roll goes UP, DOWN, or stays the
    SAME relative to the previous roll (df=2).

    Catches monotonic/cycling patterns (e.g. 1,2,3,4,5,6,1,2,3,...) that
    the uniformity test is structurally blind to, since a full cycle has
    a perfectly uniform face distribution despite being maximally
    non-random in sequence. For a fair, memoryless D6, P(same)=1/6 and
    P(up)=P(down)=5/12 each, by symmetry over the 36 equally likely
    (prev, next) pairs. Needs more data than the single-face tests
    (three categories, smallest expected cell is 1/6 of transitions) --
    noted in the result rather than silently under-running."""
    n = len(dice_seq)
    if n < 16:
        return {
            "name": "Dice transition direction",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 16+ for a meaningful test.",
        }
    up = down = same = 0
    for i in range(1, n):
        if dice_seq[i] > dice_seq[i - 1]:
            up += 1
        elif dice_seq[i] < dice_seq[i - 1]:
            down += 1
        else:
            same += 1
    trials = n - 1
    exp_same = trials / 6
    exp_up = exp_down = trials * 5 / 12
    chi2 = ((same - exp_same) ** 2 / exp_same
            + (up - exp_up) ** 2 / exp_up
            + (down - exp_down) ** 2 / exp_down)
    crit01 = _chi2_crit(2, "01")
    crit02 = _chi2_crit(2, "02")
    level = "flag" if chi2 > crit01 else ("borderline" if chi2 > crit02 else "pass")
    note = (f"up={up} down={down} same={same} of {trials} transitions "
            f"(expected up/down~{exp_up:.1f} each, same~{exp_same:.1f}). "
            f"Catches cycling patterns invisible to the face-frequency test"
            + (" -- reduced power under ~31 rolls." if n < 31 else "."))
    return {
        "name": "Dice transition direction",
        "statistic": round(chi2, 3),
        "expected": 2,
        "critical": round(crit01, 2),
        "level": level,
        "note": note,
    }


def test_dice_parity(dice_seq: list) -> dict:
    """Wald-Wolfowitz runs test on odd/even parity of consecutive rolls.

    Directly targets strict odd/even alternation with VARYING magnitudes
    (e.g. 1,4,3,6,5,2,3,2,1,6,...) -- a pattern that face-frequency
    chi-square doesn't see (parity is balanced either way), the
    transition-direction test doesn't reliably see (no consistent
    up/down bias), and the periodicity test doesn't see (no exact
    repeat if the specific values keep varying). Same two-sided
    runs-test logic as test_card_rank_clustering, applied to parity
    instead of rank distance-from-center."""
    n = len(dice_seq)
    if n < 12:
        return {
            "name": "Dice parity alternation",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 12+ for a meaningful test.",
        }
    is_odd = [v % 2 == 1 for v in dice_seq]
    n1 = sum(is_odd)
    n2 = n - n1
    if n1 == 0 or n2 == 0:
        return {
            "name": "Dice parity alternation",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: all-odd or all-even draw, runs test not meaningful.",
        }
    runs = 1
    for i in range(1, n):
        if is_odd[i] != is_odd[i - 1]:
            runs += 1
    mean = 1 + (2 * n1 * n2) / n
    var = (2 * n1 * n2 * (2 * n1 * n2 - n)) / (n ** 2 * (n - 1))
    z = (runs - mean) / math.sqrt(var) if var > 0 else 0.0
    level = _level_from_z(z)
    note = f"{runs} odd/even runs among {n} rolls (expected ~{mean:.1f})."
    if z < -_Z_BORDERLINE:
        note += " Too FEW runs -- odd/even rolls are clustering together."
    elif z > _Z_BORDERLINE:
        note += " Too MANY runs -- odd/even rolls alternate more than chance would (e.g. deliberate odd-even-odd-even pattern)."
    return {
        "name": "Dice parity alternation",
        "statistic": round(z, 3),
        "level": level,
        "note": note,
    }


def _find_exact_period(seq: list) -> int:
    """Returns the shortest period p (1 <= p <= len(seq)//2) for which
    seq repeats exactly every p symbols, or None if no such period
    exists. Deliberately exact-match only (no fuzzy tolerance) -- kept
    as a simple, auditable structural check rather than adding another
    statistical threshold to tune."""
    n = len(seq)
    for p in range(1, n // 2 + 1):
        if all(seq[i] == seq[i % p] for i in range(n)):
            return p
    return None


def test_periodicity(seq: list, label: str, min_len: int) -> dict:
    """Direct check: does this sequence repeat exactly at some short
    period? The literal fix for deliberately-constructed cycling
    patterns (e.g. a hand-entered A,2,3,4,5,6,7,8,9,10,J,Q,K,A,2,...
    pattern) that frequency-only tests can't see by design."""
    n = len(seq)
    if n < min_len:
        return {
            "name": f"{label} periodicity",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} symbols; needs {min_len}+ for a meaningful check.",
        }
    period = _find_exact_period(seq)
    if period is not None:
        return {
            "name": f"{label} periodicity",
            "statistic": period,
            "level": "flag",
            "note": f"Sequence repeats exactly every {period} symbols -- not a random draw.",
        }
    return {
        "name": f"{label} periodicity",
        "statistic": None,
        "level": "pass",
        "note": "No exact short-period repeat found.",
    }


def test_card_suit_runs(card_seq: list) -> dict:
    """Longest run of consecutive same-suit cards in draw order. Long
    suit runs suggest an under-shuffled (suit-blocked) deck. One-sided
    by design -- the complementary "too evenly spread" failure mode
    (e.g. strict suit alternation) is covered separately by
    test_card_suit_transitions, which is inherently two-sided."""
    if len(card_seq) < 10:
        return {
            "name": "Card suit runs",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: too few cards for a meaningful suit-run check.",
        }
    longest = 1
    current = 1
    for i in range(1, len(card_seq)):
        if card_seq[i][-1] == card_seq[i - 1][-1]:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    # For a well-shuffled deck, suit runs of 7+ are rare (roughly
    # p < 0.01 territory across a 52-card sequence); flag at 7, treat
    # 6 as borderline. Thresholds raised from 5/6 after adversarial
    # testing showed 5 triggers on ~6% of fair shuffles -- too high
    # for a per-test false positive budget of ~2%.
    level = "flag" if longest >= 7 else ("borderline" if longest == 6 else "pass")
    return {
        "name": "Card suit runs",
        "statistic": longest,
        "level": level,
        "note": f"Longest same-suit run: {longest}. Runs of 7+ suggest an under-shuffled deck.",
    }


def test_card_rank_sequences(card_seq: list) -> dict:
    """Longest strictly ascending or descending consecutive rank chain.
    Long chains suggest surviving factory or sorted order. One-sided,
    same reasoning as test_card_suit_runs above."""
    if len(card_seq) < 10:
        return {
            "name": "Card rank sequences",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: too few cards for a meaningful rank-sequence check.",
        }
    rank_order = {r: i for i, r in enumerate(
        ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"])}
    ranks = [rank_order[c[:-1]] for c in card_seq]
    longest = 1
    current = 1
    direction = 0
    for i in range(1, len(ranks)):
        step = ranks[i] - ranks[i - 1]
        if step in (1, -1) and (direction == 0 or step == direction):
            current += 1
            direction = step
            longest = max(longest, current)
        else:
            current = 1
            direction = 0
    level = "flag" if longest >= 6 else ("borderline" if longest == 5 else "pass")
    return {
        "name": "Card rank sequences",
        "statistic": longest,
        "level": level,
        "note": f"Longest consecutive rank chain: {longest}. Chains of 6+ suggest surviving sorted order.",
    }


def test_card_suit_transitions(card_seq: list) -> dict:
    """Two-sided test on how often consecutive cards change suit. For a
    well-shuffled deck, P(different suit) is close to 3/4 per draw. Too
    FEW changes signals a blocked/under-shuffled deck (same failure mode
    as suit runs, seen from a different angle); too MANY changes signals
    unnaturally strict alternation -- e.g. someone drawing red-black-
    red-black on purpose, which produces no long same-suit run at all
    and would otherwise sail past test_card_suit_runs undetected."""
    n = len(card_seq)
    if n < 10:
        return {
            "name": "Card suit transitions",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: too few cards for a meaningful transition check.",
        }
    changes = sum(1 for i in range(1, n) if card_seq[i][-1] != card_seq[i - 1][-1])
    trials = n - 1
    p = 3 / 4
    mean = trials * p
    sd = math.sqrt(trials * p * (1 - p))
    z = (changes - mean) / sd if sd else 0.0
    level = _level_from_z(z)
    note = f"{changes} suit changes in {trials} transitions (expected ~{mean:.1f})."
    if z < -_Z_BORDERLINE:
        note += " Too FEW changes -- suggests a blocked, under-shuffled deck."
    elif z > _Z_BORDERLINE:
        note += " Too MANY changes -- suggests artificial alternation (e.g. red-black-red-black)."
    return {
        "name": "Card suit transitions",
        "statistic": round(z, 3),
        "level": level,
        "note": note,
    }


def test_card_rank_clustering(card_seq: list) -> dict:
    """Wald-Wolfowitz runs test on whether near-center ranks (5 through
    9, i.e. the middle 5 of 13 ranks) cluster together in draw order.

    This targets a specific, documented human bias: people asked to
    "act random" tend to avoid extremes -- the same phenomenon the dice
    repeat-rate test exploits for repeats, applied to card rank instead.
    Unlike a fixed 3-way bin split (e.g. A-4 / 5-9 / 10-K), the runs
    test is inherently two-sided: it flags BOTH middle ranks clustering
    together (too few runs) AND middle/edge ranks alternating too
    strictly (too many runs), without needing to pick bin boundaries.

    Deliberately about ORDER, not composition -- in 256-bit mode all 52
    cards get drawn regardless of shuffle quality, so a composition-only
    check (e.g. variance of drawn ranks) would be structurally powerless
    there. This test stays meaningful in both seed-length modes."""
    n = len(card_seq)
    if n < 10:
        return {
            "name": "Card rank clustering",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: too few cards for a meaningful clustering check.",
        }
    rank_order = {r: i for i, r in enumerate(
        ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"])}
    is_middle = [rank_order[c[:-1]] in (4, 5, 6, 7, 8) for c in card_seq]  # ranks 5-9
    n1 = sum(is_middle)
    n2 = n - n1
    if n1 == 0 or n2 == 0:
        # All-middle or all-edge among the drawn cards. For a partial
        # draw (128-bit mode, 20 of 52 cards), an all-middle draw is
        # astronomically unlikely from a well-shuffled deck (20 middle-
        # rank cards exist but you'd have to draw exactly those 20 out
        # of 52) -- flag it outright rather than skipping silently.
        # For a full 52-card draw this can't happen (both groups are
        # always present), so the flag only fires on the partial case.
        if n < 52:
            return {
                "name": "Card rank clustering",
                "statistic": None,
                "level": "flag",
                "note": f"All {n} drawn cards are {'middle (5-9)' if n1 > 0 else 'edge (A-4, 10-K)'} ranks "
                        f"-- astronomically unlikely from a shuffled deck. Suggests a biased draw.",
            }
        return {
            "name": "Card rank clustering",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: all-middle or all-edge draw, runs test not meaningful.",
        }
    runs = 1
    for i in range(1, n):
        if is_middle[i] != is_middle[i - 1]:
            runs += 1
    mean = 1 + (2 * n1 * n2) / n
    var = (2 * n1 * n2 * (2 * n1 * n2 - n)) / (n ** 2 * (n - 1))
    z = (runs - mean) / math.sqrt(var) if var > 0 else 0.0
    level = _level_from_z(z)
    note = f"{runs} middle/edge runs among {n} cards (expected ~{mean:.1f})."
    if z < -_Z_BORDERLINE:
        note += " Too FEW runs -- middle ranks (5-9) are clustering together."
    elif z > _Z_BORDERLINE:
        note += " Too MANY runs -- middle/edge ranks alternate more than chance would."
    return {
        "name": "Card rank clustering",
        "statistic": round(z, 3),
        "level": level,
        "note": note,
    }


# --- Tests added after adversarial testing session 2026-08-05 ---
# See ADVERSARIAL_NOTES.md for the gaps that motivated each test.
# Each test is calibrated for the actual sample sizes this app uses
# (20 dice rolls, 27 or 52 cards) rather than generic textbook
# thresholds designed for larger samples.


def test_dice_diff_sign_runs(dice_seq: list) -> dict:
    """Runs test on the SIGN of consecutive differences (d_i = x_{i+1} - x_i).

    Wave patterns (e.g. 1,3,2,4,3,5,4,6,...) produce an excess of sign
    alternations -- too many short runs of same-sign diffs -- because
    each upward step is immediately followed by a downward step (or
    vice versa). This structure is invisible to the face-frequency test
    (the wave has near-uniform frequency), the transition-direction test
    (up and down counts are balanced), and the periodicity test (the
    wave doesn't repeat exactly). It is the specific gap identified
    in adversarial testing.

    Calibrated empirically for n=20 D6 rolls: the theoretical Wald-
    Wolfowitz formula is systematically biased for die-roll diffs
    because the bounded range (1-6) creates regression-to-mean effects
    that inflate run counts under fair conditions. Empirical mean and
    SD from 50,000 simulated fair sequences are used instead.

    Two-sided: too MANY runs = alternating wave pattern; too FEW runs =
    sticky drift (consecutive values trending in the same direction)."""
    n = len(dice_seq)
    if n < 16:
        return {
            "name": "Dice diff-sign runs",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 16+ for a meaningful test.",
        }
    diffs = [dice_seq[i + 1] - dice_seq[i] for i in range(n - 1)]
    signs = [1 if d > 0 else -1 for d in diffs if d != 0]
    n_signed = len(signs)
    if n_signed < 8:
        return {
            "name": "Dice diff-sign runs",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n_signed} non-zero diffs; needs 8+ for a meaningful test.",
        }
    runs = 1
    for i in range(1, n_signed):
        if signs[i] != signs[i - 1]:
            runs += 1
    # Empirical calibration for n=20 D6 rolls (50k simulation):
    # mean ≈ 11.89, sd ≈ 1.92. For other n, scale linearly as a
    # rough approximation -- the test is primarily designed for n=20
    # and the scaling is conservative rather than precise.
    #
    # Percentile-based thresholds (from the same 50k simulation):
    #   runs >= 17: 0.62% of fair sequences (FLAG-level)
    #   runs >= 16: 2.69% of fair sequences (BORDERLINE-level)
    #   runs <= 8:  2.73% of fair sequences (BORDERLINE-level, low tail)
    #   runs <= 7:  0.85% of fair sequences (FLAG-level, low tail)
    # These are used directly instead of z-scores because the z-score
    # from the empirical mean/sd gives 2.14 for the ascending wave
    # (16 runs) -- below the global _Z_BORDERLINE of 2.33, which would
    # cause a miss. The percentile thresholds are the ground truth;
    # the z-score is an approximation of them that isn't accurate
    # enough in the tail for this test's specific distribution.
    scale = (n - 1) / 19  # 19 diffs for 20 rolls (the calibration point)
    flag_hi = 17 * scale
    bl_hi = 16 * scale
    bl_lo = 8 * scale
    flag_lo = 7 * scale
    if runs >= flag_hi or runs <= flag_lo:
        level = "flag"
    elif runs >= bl_hi or runs <= bl_lo:
        level = "borderline"
    else:
        level = "pass"
    emp_mean = 11.89 * scale
    note = f"{runs} sign-change runs in {n_signed} non-zero diffs (expected ~{emp_mean:.1f})."
    if runs >= bl_hi:
        note += " Too MANY runs -- consecutive diffs alternate sign more than expected (wave pattern)."
    elif runs <= bl_lo:
        note += " Too FEW runs -- consecutive diffs trend in the same direction (sticky drift)."
    return {
        "name": "Dice diff-sign runs",
        "statistic": runs,
        "level": level,
        "note": note,
    }


def test_dice_repeat_exact(dice_seq: list) -> dict:
    """Exact binomial probability of observing this few (or fewer) repeats.

    Supplements the existing z-score repeat-rate test with an exact
    calculation that is more powerful at small sample sizes. At n=20
    rolls, 0 repeats gives z ≈ -1.95 (just below BORDERLINE) but has
    exact probability 3.1% (clearly below 5%). The z-score
    approximation is not sharp enough at n=20 to catch this; the exact
    test is.

    One-sided lower tail only: too FEW repeats is the human-bias signal
    (people avoid repeating). Too MANY repeats is already caught by the
    existing repeat-rate z-test and the uniformity chi-square."""
    n = len(dice_seq)
    if n < 12:
        return {
            "name": "Dice repeat exact",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 12+ for a meaningful test.",
        }
    transitions = n - 1
    repeats = sum(1 for i in range(1, n) if dice_seq[i] == dice_seq[i - 1])
    p = 1 / 6
    # P(X <= repeats) under Binomial(transitions, 1/6)
    prob = 0.0
    for k in range(repeats + 1):
        prob += math.comb(transitions, k) * p ** k * (1 - p) ** (transitions - k)
    level = "flag" if prob < 0.01 else ("borderline" if prob < 0.05 else "pass")
    note = (f"{repeats} repeats in {transitions} transitions "
            f"(exact P(\u2264{repeats}) = {prob:.4f} under a fair die).")
    if level != "pass":
        note += f" Fewer repeats than expected -- suggests deliberate avoidance."
    return {
        "name": "Dice repeat exact",
        "statistic": round(prob, 4),
        "level": level,
        "note": note,
    }


def test_dice_extremes(dice_seq: list) -> dict:
    """Two-sided test on the count of extreme values (1s and 6s).

    Under a fair D6, P(extreme) = 2/6 = 1/3, so the expected count in
    n rolls is n/3. Center-biased human entry (favoring 3,4) produces
    too FEW extremes; edge-biased entry produces too MANY. Calibrated
    for n=20 with the standard binomial z-score, which is adequate
    at this sample size (expected cell count ~6.7, well above the
    chi-square minimum of 5)."""
    n = len(dice_seq)
    if n < 12:
        return {
            "name": "Dice extremes (1s and 6s)",
            "statistic": None,
            "level": "skipped",
            "note": f"Skipped: only {n} rolls; needs 12+ for a meaningful test.",
        }
    extremes = sum(1 for x in dice_seq if x in (1, 6))
    p = 1 / 3
    expected = n * p
    sd = math.sqrt(n * p * (1 - p))
    z = (extremes - expected) / sd if sd > 0 else 0.0
    level = _level_from_z(z)
    note = f"{extremes} extreme values (1 or 6) in {n} rolls (expected ~{expected:.1f})."
    if z < -_Z_BORDERLINE:
        note += " Too FEW extremes -- suggests center bias (favoring middle values)."
    elif z > _Z_BORDERLINE:
        note += " Too MANY extremes -- suggests edge bias (favoring 1s and 6s)."
    return {
        "name": "Dice extremes (1s and 6s)",
        "statistic": round(z, 3),
        "level": level,
        "note": note,
    }


def test_card_rank_draw_order(card_seq: list) -> dict:
    """Spearman rank correlation between draw position and card rank value.

    Catches patterns where high-rank or low-rank cards are systematically
    drawn earlier or later in the sequence -- e.g. all face cards drawn
    first, or aces drawn last. Under a well-shuffled deck, draw position
    and rank value are independent, giving expected Spearman rho ≈ 0.

    Calibrated for both n=27 (128-bit mode) and n=52 (256-bit mode)
    using the standard approximation Var(rho) ≈ 1/(n-1), which is
    accurate for n >= 10."""
    n = len(card_seq)
    if n < 10:
        return {
            "name": "Card rank draw order",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: too few cards for a meaningful rank-order check.",
        }
    rank_order = {r: i for i, r in enumerate(
        ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"])}
    rank_values = [rank_order[c[:-1]] for c in card_seq]
    positions = list(range(n))
    # Spearman: rank both variables, then compute Pearson on ranks.
    # For positions, ranks are trivially 0..n-1.
    # For rank_values, compute fractional ranks to handle ties.
    sorted_vals = sorted(enumerate(rank_values), key=lambda x: (x[1], x[0]))
    ranks_rv = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and sorted_vals[j][1] == sorted_vals[i][1]:
            j += 1
        avg_rank = (i + j - 1) / 2.0
        for k in range(i, j):
            ranks_rv[sorted_vals[k][0]] = avg_rank
        i = j
    # Pearson on (positions, ranks_rv)
    mean_p = (n - 1) / 2.0
    mean_r = sum(ranks_rv) / n
    cov = sum((positions[i] - mean_p) * (ranks_rv[i] - mean_r) for i in range(n)) / n
    sd_p = math.sqrt(sum((p - mean_p) ** 2 for p in positions) / n)
    sd_r = math.sqrt(sum((r - mean_r) ** 2 for r in ranks_rv) / n)
    rho = cov / (sd_p * sd_r) if (sd_p > 0 and sd_r > 0) else 0.0
    # z-test: Var(rho) ≈ 1/(n-1) under null
    z = rho * math.sqrt(n - 1)
    level = _level_from_z(z)
    note = f"Spearman rho = {rho:.4f} (draw position vs rank value, n={n})."
    if z < -_Z_BORDERLINE:
        note += " High-rank cards drawn early (face cards first)."
    elif z > _Z_BORDERLINE:
        note += " Low-rank cards drawn early (aces/low cards first)."
    return {
        "name": "Card rank draw order",
        "statistic": round(z, 3),
        "level": level,
        "note": note,
    }


def test_shannon_entropy(seq: list, symbol_range: int, label: str) -> dict:
    """
    Shannon entropy H = -sum(p_i * log2(p_i)) over observed symbol frequencies.
    Maximum possible = log2(symbol_range). Reports bits/symbol and fraction of max.

    Thresholds are empirically calibrated per (symbol_range, n) via Monte Carlo
    simulation of a fair die/source at each sample size. FLAG = below the p5
    percentile of fair draws (5% false-positive rate). NEAR = below p10.
    Without calibration, Shannon consistently under-reports at small n because
    sparse sampling leaves many symbols unseen even from a perfectly fair source.
    Fixed thresholds (e.g. 70%/85%) are wrong for any n below ~100 samples.

    For cards (drawn without replacement, all symbols distinct), symbol_range
    should be len(card_seq) not 52 -- fraction is always 1.0, always PASS.
    """
    n = len(seq)
    if n < 5:
        return {
            "name": f"Shannon entropy ({label})",
            "statistic": None,
            "level": "skipped",
            "note": "Skipped: too few symbols.",
        }
    from collections import Counter
    counts = Counter(seq)
    h = 0.0
    for c in counts.values():
        p = c / n
        if p > 0:
            h -= p * math.log2(p)
    h_max = math.log2(symbol_range) if symbol_range > 1 else 1.0
    fraction = h / h_max if h_max > 0 else 0.0

    # Empirically calibrated thresholds: (flag_frac, near_frac) = p5, p10
    # percentiles of Shannon fraction for a fair source at (sides, n).
    # Generated via 20k-trial Monte Carlo simulation (2026-08-18).
    # Sides not in table: fall back to fixed conservative thresholds.
    _THRESHOLDS = {
        # (sides, n): (p5_flag, p10_near)
        (4,  10): (0.680, 0.743), (4,  15): (0.777, 0.836),
        (4,  20): (0.856, 0.883), (4,  30): (0.903, 0.923),
        (4,  40): (0.928, 0.943), (4,  50): (0.943, 0.955),
        (4,  60): (0.954, 0.963), (4,  90): (0.969, 0.975),
        (4, 120): (0.976, 0.981),
        (6,  10): (0.666, 0.714), (6,  15): (0.770, 0.809),
        (6,  20): (0.830, 0.853), (6,  30): (0.889, 0.909),
        (6,  40): (0.919, 0.933), (6,  50): (0.937, 0.947),
        (6,  60): (0.947, 0.956), (6,  90): (0.965, 0.971),
        (6, 120): (0.974, 0.978),
        (8,  10): (0.654, 0.707), (8,  15): (0.752, 0.789),
        (8,  20): (0.811, 0.835), (8,  30): (0.876, 0.893),
        (8,  40): (0.910, 0.923), (8,  50): (0.930, 0.940),
        (8,  60): (0.942, 0.951), (8,  90): (0.962, 0.968),
        (8, 120): (0.972, 0.976),
        (10, 10): (0.639, 0.654), (10, 15): (0.735, 0.767),
        (10, 20): (0.797, 0.820), (10, 30): (0.865, 0.881),
        (10, 40): (0.901, 0.913), (10, 50): (0.921, 0.932),
        (10, 60): (0.935, 0.944), (10, 90): (0.958, 0.964),
        (10,120): (0.969, 0.973),
        (12, 10): (0.606, 0.648), (12, 15): (0.727, 0.748),
        (12, 20): (0.783, 0.810), (12, 30): (0.854, 0.871),
        (12, 40): (0.892, 0.904), (12, 50): (0.915, 0.925),
        (12, 60): (0.930, 0.939), (12, 90): (0.954, 0.960),
        (12,120): (0.966, 0.970),
        (20, 10): (0.566, 0.612), (20, 15): (0.676, 0.696),
        (20, 20): (0.741, 0.760), (20, 30): (0.818, 0.832),
        (20, 40): (0.860, 0.873), (20, 50): (0.889, 0.899),
        (20, 60): (0.908, 0.916), (20, 90): (0.941, 0.947),
        (20,120): (0.956, 0.960),
    }

    def _lookup(sides, n_samples):
        """Interpolate threshold from nearest n in table for given sides."""
        ns = sorted(k[1] for k in _THRESHOLDS if k[0] == sides)
        if not ns:
            return 0.70, 0.85  # fallback for unknown sides
        # Clamp to table range
        if n_samples <= ns[0]:
            return _THRESHOLDS[(sides, ns[0])]
        if n_samples >= ns[-1]:
            return _THRESHOLDS[(sides, ns[-1])]
        # Linear interpolation between bracketing entries
        lo = max(x for x in ns if x <= n_samples)
        hi = min(x for x in ns if x >= n_samples)
        if lo == hi:
            return _THRESHOLDS[(sides, lo)]
        t = (n_samples - lo) / (hi - lo)
        f_lo, n_lo = _THRESHOLDS[(sides, lo)]
        f_hi, n_hi = _THRESHOLDS[(sides, hi)]
        return f_lo + t*(f_hi - f_lo), n_lo + t*(n_hi - n_lo)

    flag_thresh, near_thresh = _lookup(symbol_range, n)

    if fraction < flag_thresh:
        level = "flag"
        note = (f"H = {h:.3f} bits/symbol ({fraction*100:.1f}% of max {h_max:.3f}). "
                f"Below p5 floor for fair {symbol_range}-sided source at n={n} "
                f"(threshold {flag_thresh*100:.1f}%). Symbol distribution notably non-uniform.")
    elif fraction < near_thresh:
        level = "borderline"
        note = (f"H = {h:.3f} bits/symbol ({fraction*100:.1f}% of max {h_max:.3f}). "
                f"Between p5 and p10 for fair {symbol_range}-sided source at n={n} "
                f"(thresholds {flag_thresh*100:.1f}%/{near_thresh*100:.1f}%). Borderline.")
    else:
        level = "pass"
        note = (f"H = {h:.3f} bits/symbol ({fraction*100:.1f}% of max {h_max:.3f}). "
                f"Above p10 floor for fair {symbol_range}-sided source at n={n}.")
    return {
        "name": f"Shannon entropy ({label})",
        "statistic": round(h, 3),
        "level": level,
        "note": note,
    }


def run_symbol_tests(card_seq: list, dice_seq: list,
                     dnd_throws: list = None) -> list:
    """Runs the symbol-level test suite on RAW physical draw data.
    Never test the SHA-256 output -- a hash always looks statistically
    random regardless of input quality, which would defeat the purpose.
    Tests operate on symbols (cards, die faces), not the encoded bit
    string, to avoid the fixed-width encoding's structural bit bias.

    dnd_throws: list of (d4,d6,d8,d10,d12,d20) tuples for DnD mode.
    When provided, per-die face sequences are extracted and tested.

    LIMIT WORTH STATING PLAINLY: no finite battery of statistical tests
    can prove a sequence is random -- a deliberately constructed
    sequence can be engineered to pass every specific test run here.
    These tests catch realistic accidental failure modes (under-shuffling,
    fatigue, unconscious patterning), not a determined adversary."""
    results = []

    # Card tests (skipped in dice-only modes)
    if card_seq:
        results += [
            test_card_suit_runs(card_seq),
            test_card_rank_sequences(card_seq),
            test_card_suit_transitions(card_seq),
            test_card_rank_clustering(card_seq),
            test_card_rank_draw_order(card_seq),
            test_periodicity(card_seq, "Card", min_len=10),
            # Shannon ceiling for cards is log2(n_drawn), not log2(52).
            # Cards are drawn without replacement so all n drawn cards are
            # distinct -- the maximum achievable H is log2(n_drawn), not
            # log2(52). Comparing against 52 always produces a false "below
            # maximum" result when n_drawn < 52.
            test_shannon_entropy(
                [canonical_card_index(c) for c in card_seq],
                len(card_seq), "cards"),
        ]

    # D6 / mixed-mode dice tests
    if dice_seq:
        results += [
            test_dice_uniformity(dice_seq),
            test_dice_repeat_exact(dice_seq),
            test_dice_transition_direction(dice_seq),
            test_dice_parity(dice_seq),
            test_dice_diff_sign_runs(dice_seq),
            test_dice_extremes(dice_seq),
            test_periodicity(dice_seq, "Dice", min_len=12),
            test_shannon_entropy(dice_seq, 6, "D6 rolls"),
        ]

    # DnD per-die tests (one Shannon test per die type)
    if dnd_throws:
        for i, (die_name, die_sides) in enumerate(DND_DICE):
            faces = [t[i] for t in dnd_throws]
            results.append(
                test_shannon_entropy(faces, die_sides, die_name))
        # Also test the flat sequence of all face values for runs/uniformity
        all_faces = [v for t in dnd_throws for v in t]
        results.append(test_periodicity(all_faces, "DnD", min_len=10))

    return results


def compute_overall_tier(results: list) -> dict:
    """
    Combines individual test results into one of four tiers. The tier
    is driven by the SINGLE WORST result, never an average or combined
    score -- a bad result on one test should never be smoothed over by
    good results on others. Given that a false negative here can cost
    real funds while a false positive costs a few minutes of
    re-shuffling, this is deliberately biased toward restricting rather
    than reassuring:

      STOP -- RE-SHUFFLE:        any single FLAG, OR 2+ simultaneous
                                  BORDERLINE results (two independent
                                  tests drifting toward their threshold
                                  at once is treated as a combined
                                  signal even if neither alone crosses
                                  the FLAG line)
      CAUTION -- BORDERLINE:     exactly one BORDERLINE, no FLAGs
      NO ISSUES -- LIMITED DATA: no FLAGs or BORDERLINEs, but one or
                                  more tests were SKIPPED for lack of
                                  data (small sample sizes limit test
                                  power -- this is surfaced, not hidden)
      NO ISSUES -- FULL COVERAGE: no FLAGs, no BORDERLINEs, every test
                                  ran with adequate sample size

    Deliberately never says "safe" or "safest" -- only "no issues
    DETECTED", which is the true claim (see the Kolmogorov-complexity
    note on run_symbol_tests: no finite test battery can prove
    randomness, only fail to find evidence against it).
    """
    # Shannon entropy tests are informational only -- excluded from tier
    # computation. At the sample sizes used here (10-120 rolls/throws),
    # running multiple independent Shannon tests simultaneously produces
    # unacceptable combined false-positive rates even after per-(sides,n)
    # calibration: 6 DnD per-die Shannon tests at ~5% individual FLAG rate
    # give a ~26% combined FLAG rate from fair dice, making the tier
    # effectively useless. Shannon is shown in the results table for the
    # user to read but never gates the STOP/CAUTION decision.
    gated = [r for r in results if not r["name"].startswith("Shannon entropy")]

    n_flag       = sum(1 for r in gated if r["level"] == "flag")
    n_borderline = sum(1 for r in gated if r["level"] == "borderline")
    n_skipped    = sum(1 for r in results if r["level"] == "skipped")

    if n_flag > 0:
        return {
            "tier": "stop", "label": "STOP \u2014 RE-SHUFFLE",
            "reason": f"{n_flag} test(s) flagged a problem.",
            "n_flag": n_flag, "n_borderline": n_borderline, "n_skipped": n_skipped,
        }
    if n_borderline >= 2:
        return {
            "tier": "stop", "label": "STOP \u2014 RE-SHUFFLE",
            "reason": f"{n_borderline} tests were simultaneously borderline -- treated as a combined signal.",
            "n_flag": n_flag, "n_borderline": n_borderline, "n_skipped": n_skipped,
        }
    if n_borderline == 1:
        return {
            "tier": "caution", "label": "CAUTION \u2014 BORDERLINE",
            "reason": "One test result was borderline.",
            "n_flag": n_flag, "n_borderline": n_borderline, "n_skipped": n_skipped,
        }
    if n_skipped > 0:
        return {
            "tier": "limited", "label": "NO ISSUES DETECTED \u2014 LIMITED DATA",
            "reason": f"{n_skipped} test(s) had insufficient data to run meaningfully.",
            "n_flag": n_flag, "n_borderline": n_borderline, "n_skipped": n_skipped,
        }
    return {
        "tier": "full", "label": "NO ISSUES DETECTED \u2014 FULL COVERAGE",
        "reason": "All tests ran with adequate data and found nothing.",
        "n_flag": n_flag, "n_borderline": n_borderline, "n_skipped": n_skipped,
    }


# ---------------------------------------------------------------------------
# Hashing (two SEPARATE SHA-256 calls -- entropy whitening, then checksum)
# ---------------------------------------------------------------------------

def xor_mix_external_source(entropy_bytes: bytes, external_bytes: bytes) -> bytes:
    """
    XOR-combine already-whitened card/dice entropy with bytes from an
    independent hardware source (e.g. the RP2350 Pico TRNG). Standard
    property this relies on: XOR of independent sources is uniform as
    long as AT LEAST ONE input is uniform/independent of the other --
    so this can only help or be neutral, never make the result worse
    than the card/dice entropy alone, regardless of the external
    source's actual quality. external_bytes must be the same length
    as entropy_bytes.
    """
    if len(external_bytes) != len(entropy_bytes):
        raise ValueError(
            f"external_bytes length ({len(external_bytes)}) must match "
            f"entropy_bytes length ({len(entropy_bytes)})"
        )
    return bytes(a ^ b for a, b in zip(entropy_bytes, external_bytes))


def whiten_entropy(raw_bits: str, target_bits: int) -> bytes:
    """
    SHA-256 the raw input bytes to whiten it, then truncate/expand to the
    target byte length. For 128-bit mode: first 16 bytes of SHA-256.
    For 256-bit mode: full 32 bytes of SHA-256.
    """
    raw_bytes = int(raw_bits, 2).to_bytes((len(raw_bits) + 7) // 8, "big")
    digest = hashlib.sha256(raw_bytes).digest()
    n_bytes = target_bits // 8
    return digest[:n_bytes]


def bip39_checksum_bits(entropy_bytes: bytes) -> str:
    """
    SEPARATE SHA-256 call (not reusing the whitening hash) over the
    final entropy bytes, per the BIP-39 spec: checksum length = ENT/32 bits.
    """
    ent_bits = len(entropy_bytes) * 8
    checksum_len = ent_bits // 32
    digest = hashlib.sha256(entropy_bytes).digest()
    checksum_full_bits = "".join(format(b, "08b") for b in digest)
    return checksum_full_bits[:checksum_len]


def entropy_to_mnemonic(entropy_bytes: bytes, wordlist: list) -> list:
    ent_bits = len(entropy_bytes) * 8
    entropy_bin = "".join(format(b, "08b") for b in entropy_bytes)
    checksum_bin = bip39_checksum_bits(entropy_bytes)
    full_bits = entropy_bin + checksum_bin
    n_words = len(full_bits) // 11
    words = []
    for i in range(n_words):
        chunk = full_bits[i * 11:(i + 1) * 11]
        index = int(chunk, 2)
        words.append(wordlist[index])
    return words


def mnemonic_to_seed(mnemonic_words: list, passphrase: str = "") -> bytes:
    """
    Standard BIP-39 seed derivation: PBKDF2-HMAC-SHA512, 2048 rounds,
    password = mnemonic sentence (NFKD), salt = 'mnemonic' + passphrase
    (NFKD). Returns the 64-byte wallet seed. This is where the optional
    passphrase actually takes effect -- it never alters the words or
    checksum, only this derivation.
    """
    import unicodedata
    sentence = unicodedata.normalize("NFKD", " ".join(mnemonic_words))
    salt = unicodedata.normalize("NFKD", "mnemonic" + passphrase)
    return hashlib.pbkdf2_hmac("sha512", sentence.encode("utf-8"),
                                salt.encode("utf-8"), 2048)


# ---------------------------------------------------------------------------
# BIP-32 master fingerprint -- pure Python, stdlib only.
#
# Wallets (SeedSigner, Sparrow, etc.) display a "master fingerprint" that
# identifies a seed without exposing it, and it's required when building a
# multisig wallet descriptor. Computing it requires: (1) HMAC-SHA512 to
# derive the master private key from the 64-byte BIP-39 seed (stdlib), and
# (2) secp256k1 EC point multiplication to get the master public key,
# then (3) HASH160 = RIPEMD160(SHA256(pubkey)) of that public key.
#
# hashlib.new("ripemd160") is NOT reliably available -- OpenSSL 3.x
# dropped RIPEMD-160 from its default provider on many distros, so this
# tool implements RIPEMD-160 from the public specification rather than
# depend on an OpenSSL feature that may be missing on an unfamiliar or
# air-gapped machine.
# ---------------------------------------------------------------------------

# secp256k1 curve parameters. Gy is DERIVED from Gx via the curve equation
# (y^2 = x^3 + 7 mod p) rather than hand-typed, because a single wrong hex
# digit in a 64-digit constant is easy to introduce and hard to spot, and
# would silently put every EC operation off-curve. Deriving it removes
# that transcription risk; the derivation is verified against the
# official BIP-32 test vectors below.
_P = 2 ** 256 - 2 ** 32 - 977
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = pow((_GX ** 3 + 7) % _P, (_P + 1) // 4, _P)  # even root, per convention


def _ec_inv(a, p):
    return pow(a, p - 2, p)


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        m = (3 * x1 * x1) * _ec_inv(2 * y1, _P) % _P
    else:
        m = (y2 - y1) * _ec_inv((x2 - x1) % _P, _P) % _P
    x3 = (m * m - x1 - x2) % _P
    y3 = (m * (x1 - x3) - y1) % _P
    return (x3, y3)


def _ec_mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_add(addend, addend)
        k >>= 1
    return result


def privkey_to_compressed_pubkey(privkey_bytes: bytes) -> bytes:
    """secp256k1 point multiplication: privkey * G -> 33-byte compressed pubkey."""
    k = int.from_bytes(privkey_bytes, "big")
    if not (0 < k < _N):
        raise ValueError("private key out of valid secp256k1 range")
    x, y = _ec_mul(k, (_GX, _GY))
    prefix = b"\x02" if y % 2 == 0 else b"\x03"
    return prefix + x.to_bytes(32, "big")


# --- RIPEMD-160, implemented from the public specification (pure Python,
# no external dependency, no reliance on OpenSSL's optional provider) ---

_R_LEFT = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
    3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
    1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
    4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13,
]
_R_RIGHT = [
    5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
    6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
    15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
    8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
    12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11,
]
_S_LEFT = [
    11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
    7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
    11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
    11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
    9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6,
]
_S_RIGHT = [
    8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
    9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
    9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
    15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
    8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11,
]
_K_LEFT = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
_K_RIGHT = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]
_MASK32 = 0xFFFFFFFF


def _rol(x, n):
    return ((x << n) | (x >> (32 - n))) & _MASK32


def _f_left(j, x, y, z):
    if j < 16:
        return x ^ y ^ z
    if j < 32:
        return (x & y) | (~x & z)
    if j < 48:
        return (x | ~y) ^ z
    if j < 64:
        return (x & z) | (y & ~z)
    return x ^ (y | ~z)


def _f_right(j, x, y, z):
    if j < 16:
        return x ^ (y | ~z)
    if j < 32:
        return (x & z) | (y & ~z)
    if j < 48:
        return (x | ~y) ^ z
    if j < 64:
        return (x & y) | (~x & z)
    return x ^ y ^ z


def ripemd160(data: bytes) -> bytes:
    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0

    msg = bytearray(data)
    orig_len_bits = len(data) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += orig_len_bits.to_bytes(8, "little")

    for block_start in range(0, len(msg), 64):
        block = msg[block_start:block_start + 64]
        X = [int.from_bytes(block[i:i + 4], "little") for i in range(0, 64, 4)]

        A, B, C, D, E = h0, h1, h2, h3, h4
        A2, B2, C2, D2, E2 = h0, h1, h2, h3, h4

        for j in range(80):
            T = (A + _f_left(j, B, C, D) + X[_R_LEFT[j]] + _K_LEFT[j // 16]) & _MASK32
            T = (_rol(T, _S_LEFT[j]) + E) & _MASK32
            A, E, D, C, B = E, D, _rol(C, 10), B, T

            T2 = (A2 + _f_right(j, B2, C2, D2) + X[_R_RIGHT[j]] + _K_RIGHT[j // 16]) & _MASK32
            T2 = (_rol(T2, _S_RIGHT[j]) + E2) & _MASK32
            A2, E2, D2, C2, B2 = E2, D2, _rol(C2, 10), B2, T2

        T = (h1 + C + D2) & _MASK32
        h1 = (h2 + D + E2) & _MASK32
        h2 = (h3 + E + A2) & _MASK32
        h3 = (h4 + A + B2) & _MASK32
        h4 = (h0 + B + C2) & _MASK32
        h0 = T

    return b"".join(h.to_bytes(4, "little") for h in (h0, h1, h2, h3, h4))


def hash160(data: bytes) -> bytes:
    return ripemd160(hashlib.sha256(data).digest())


def bip32_master_fingerprint(seed_bytes: bytes) -> str:
    """
    BIP-32 master key derivation + master fingerprint:
      I = HMAC-SHA512(key="Bitcoin seed", data=seed)
      master_privkey = I[:32], master_chaincode = I[32:]
      master_pubkey = master_privkey * G  (secp256k1)
      fingerprint = HASH160(compressed master_pubkey)[:4]
    Returns the 4-byte fingerprint as an 8-char hex string, matching what
    wallet coordinators (Sparrow, Specter, SeedSigner) display for a
    seed's root (path "m").
    """
    import hmac
    I = hmac.new(b"Bitcoin seed", seed_bytes, hashlib.sha512).digest()
    master_privkey = I[:32]
    pubkey = privkey_to_compressed_pubkey(master_privkey)
    fp = hash160(pubkey)[:4]
    return fp.hex()


# ---------------------------------------------------------------------------
# Wordlist integrity
# ---------------------------------------------------------------------------

def wordlist_sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_wordlist(path: str) -> list:
    with open(path, "r") as f:
        words = [line.strip().split("\t")[-1] for line in f if line.strip()]
    if len(words) != 2048:
        raise ValueError(f"wordlist has {len(words)} entries, expected 2048")
    return words


# ---------------------------------------------------------------------------
# Base58Check -- pure Python, stdlib only.
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58check_encode(payload: bytes) -> str:
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    data = payload + checksum
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    n_leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zeros + out


def base58check_decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_ALPHABET.index(ch)
    n_leading = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    data = b"\x00" * n_leading + body
    payload, checksum = data[:-4], data[-4:]
    expect = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expect:
        raise ValueError("bad base58check checksum")
    return payload


# ---------------------------------------------------------------------------
# BIP-32 hardened child derivation + extended pubkey serialization
# (xpub/ypub/zpub/tpub/upub/vpub, mainnet + testnet, SLIP-132 version bytes)
# ---------------------------------------------------------------------------

def ckd_priv_hardened(parent_privkey: bytes, parent_chaincode: bytes, index: int):
    """Hardened child key derivation (index gets the 0x80000000 bit set).
    Only hardened derivation is needed for standard account-level paths
    like m/84'/0'/0'."""
    import hmac
    if index < 0 or index >= 0x80000000:
        raise ValueError("index must be 0..0x7FFFFFFF for hardened derivation")
    hardened_index = index | 0x80000000
    data = b"\x00" + parent_privkey + hardened_index.to_bytes(4, "big")
    I = hmac.new(parent_chaincode, data, hashlib.sha512).digest()
    IL, IR = I[:32], I[32:]
    il_int = int.from_bytes(IL, "big")
    parent_int = int.from_bytes(parent_privkey, "big")
    child_int = (il_int + parent_int) % _N
    if il_int >= _N or child_int == 0:
        raise ValueError("invalid child key (astronomically unlikely) -- pick a different index")
    child_privkey = child_int.to_bytes(32, "big")
    return child_privkey, IR


def derive_hardened_path(seed_bytes: bytes, path_indexes: list):
    """
    Walks a fully-hardened path (e.g. [84,0,0] for m/84'/0'/0') from the
    master seed. Returns (privkey, chaincode, parent_fingerprint, depth,
    child_number) for the FINAL key -- parent_fingerprint is the
    fingerprint of the key ONE LEVEL UP (needed for extended key
    serialization), not the master fingerprint.
    """
    import hmac
    I = hmac.new(b"Bitcoin seed", seed_bytes, hashlib.sha512).digest()
    privkey, chaincode = I[:32], I[32:]
    parent_fingerprint = b"\x00\x00\x00\x00"
    depth = 0
    child_number = 0
    for index in path_indexes:
        parent_pubkey = privkey_to_compressed_pubkey(privkey)
        parent_fingerprint = hash160(parent_pubkey)[:4]
        privkey, chaincode = ckd_priv_hardened(privkey, chaincode, index)
        depth += 1
        child_number = index | 0x80000000
    return privkey, chaincode, parent_fingerprint, depth, child_number


# SLIP-132 extended public key version bytes. Taproot (BIP-86) has NO
# distinct SLIP-132 prefix -- by convention it reuses the standard
# xpub/tpub version bytes; the descriptor prefix ("tr(...)") is what
# identifies Taproot, not the extended key itself. This matches what
# Sparrow and SeedSigner display for Taproot accounts.
_SLIP132_VERSIONS = {
    ("mainnet", 44): (0x0488B21E, "xpub"),
    ("mainnet", 49): (0x049D7CB2, "ypub"),
    ("mainnet", 84): (0x04B24746, "zpub"),
    ("mainnet", 86): (0x0488B21E, "xpub"),
    ("testnet", 44): (0x043587CF, "tpub"),
    ("testnet", 49): (0x044A5262, "upub"),
    ("testnet", 84): (0x045F1CF6, "vpub"),
    ("testnet", 86): (0x043587CF, "tpub"),
}


def serialize_extended_pubkey(version_bytes: int, depth: int, parent_fingerprint: bytes,
                               child_number: int, chaincode: bytes, compressed_pubkey: bytes) -> str:
    payload = (
        version_bytes.to_bytes(4, "big")
        + depth.to_bytes(1, "big")
        + parent_fingerprint
        + child_number.to_bytes(4, "big")
        + chaincode
        + compressed_pubkey
    )
    return base58check_encode(payload)


def account_xpub(seed_bytes: bytes, purpose: int, network: str, account: int = 0) -> dict:
    """
    Standard account-level extended public key for a given purpose (44,
    49, 84, or 86) and network ("mainnet"/"testnet"), per BIP-44/49/84/86.
    Matches what Sparrow's "Export Xpub" and SeedSigner's Xpub screens
    display: path, master fingerprint (returned separately -- same for
    every path from a given seed), and the xpub/ypub/zpub/.../vpub string.
    """
    coin_type = 0 if network == "mainnet" else 1
    path_indexes = [purpose, coin_type, account]
    privkey, chaincode, parent_fp, depth, child_number = derive_hardened_path(seed_bytes, path_indexes)
    pubkey = privkey_to_compressed_pubkey(privkey)
    version_bytes, label = _SLIP132_VERSIONS[(network, purpose)]
    xpub_str = serialize_extended_pubkey(version_bytes, depth, parent_fp, child_number, chaincode, pubkey)
    path_str = f"m/{purpose}'/{coin_type}'/{account}'"
    return {"path": path_str, "label": label, "xpub": xpub_str}


STANDARDS = [
    (44, "Legacy (BIP-44)"),
    (49, "Nested SegWit (BIP-49)"),
    (84, "Native SegWit (BIP-84)"),
    (86, "Taproot (BIP-86)"),
]


def all_account_xpubs(seed_bytes: bytes, network: str, account: int = 0) -> list:
    """Returns the 4 standard account xpubs (Legacy/Nested/Native/Taproot)
    for the given network, in the order wallets conventionally list them."""
    results = []
    for purpose, name in STANDARDS:
        info = account_xpub(seed_bytes, purpose, network, account)
        info["name"] = name
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# CompactSeedQR (SeedSigner format) -- encodes RAW ENTROPY directly, not
# the mnemonic words or the full entropy+checksum stream. The checksum
# word is trivially recomputed from the entropy on read, so it doesn't
# need to be stored. This is what makes it "compact": a 24-word seed's
# 256-bit entropy is just 32 raw bytes, versus ~96 numeric digits for
# the word-index-based "Standard SeedQR" format.
#
# Per the SeedSigner spec, native CompactSeedQR sizes are 21x21 (12-word/
# 128-bit) and 25x25 (24-word/256-bit). This tool additionally supports
# forcing EITHER seed length into a 25x25 or 29x29 QR (QR version 2 or 3)
# so both seed lengths can render at either of two chosen sizes -- both
# 16-byte and 32-byte entropy fit both sizes, the only variable is how
# much error-correction headroom is left over.
#
# QR encoding is implemented FROM SCRATCH in qr_encoder.py (GF(256)
# Reed-Solomon, module placement, masking) -- no external dependency.
# It was developed and verified against segno (a mature third-party QR
# library) as a validation oracle: GF(256) tables, Reed-Solomon output,
# and format-info bits all match exactly; the codeword construction
# matches a spec-corrected reference across 200 random trials spanning
# every configuration this tool uses. See qr_encoder.py's docstring
# and this project's README for the full verification writeup.
# ---------------------------------------------------------------------------

QR_SIZE_TO_VERSION = {25: 2, 29: 3}


def build_compact_seedqr_matrix(entropy_bytes: bytes, target_size: int):
    """
    Returns (matrix, error_correction_level) where matrix is a list of
    lists of bool (True = dark module), sized exactly target_size x
    target_size, and error_correction_level is the highest level ('h'
    down to 'l') that fits the data at that size. Raises ValueError if
    target_size isn't 25 or 29, or if the data genuinely doesn't fit
    (shouldn't happen for 16- or 32-byte entropy at either supported
    size).
    """
    import qr_encoder

    if target_size not in QR_SIZE_TO_VERSION:
        raise ValueError(f"target_size must be one of {sorted(QR_SIZE_TO_VERSION)}, got {target_size}")
    version = QR_SIZE_TO_VERSION[target_size]

    for level in ("h", "q", "m", "l"):
        try:
            matrix, _mask = qr_encoder.build_matrix(entropy_bytes, version, level)
        except ValueError:
            continue
        return matrix, level

    raise ValueError(
        f"{len(entropy_bytes)}-byte entropy does not fit a "
        f"{target_size}x{target_size} QR at any error-correction level"
    )
