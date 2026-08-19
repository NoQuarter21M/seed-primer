#!/usr/bin/env python3
"""
dev_test_harness.py -- DEVELOPMENT ONLY, not part of the production app.

Two modes:

  1. INTERACTIVE: generates a single random card draw + dice sequence
     and prints it in a format you can manually enter into the GUI for
     UX testing, without needing a physical deck each time.

  2. BATCH: runs N trials of random draws through the full statistical
     test suite, reports tier distribution and which tests trigger most
     often -- mass adversarial stress testing of the analysis pipeline.
     Supports all six production modes: 128, 256, d6_128, d6_256,
     dnd_128, dnd_256.

Uses secrets.SystemRandom() (OS CSPRNG) for the shuffle, which is
appropriate here because this is a TEST TOOL measuring how the
statistical tests behave on known-good random input, not a seed
generation tool. The production app deliberately avoids software RNG
for seed generation; this tool exists precisely to verify that the
production tests don't over- or under-flag on genuinely random draws.

USAGE:
  python3 dev_test_harness.py                         # interactive, 256-bit
  python3 dev_test_harness.py --mode 128              # interactive, 128-bit
  python3 dev_test_harness.py --batch 1000            # cards+dice 256-bit
  python3 dev_test_harness.py --batch 1000 --mode 128 # cards-only 128-bit
  python3 dev_test_harness.py --batch 1000 --mode d6_128
  python3 dev_test_harness.py --batch 1000 --mode d6_256
  python3 dev_test_harness.py --batch 1000 --mode dnd_128
  python3 dev_test_harness.py --batch 1000 --mode dnd_256
  python3 dev_test_harness.py --adversarial 500       # crafted bad input
  python3 dev_test_harness.py --all-modes 1000        # all 6 modes, N trials each
"""

import argparse
import secrets
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seed_primer_core as core

SUITS = ["S", "H", "D", "C"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
FULL_DECK = [f"{r}{s}" for s in SUITS for r in RANKS]

rng = secrets.SystemRandom()


def random_draw(n_cards, n_dice):
    deck = FULL_DECK[:]
    rng.shuffle(deck)
    cards = deck[:n_cards]
    dice = [rng.randint(1, 6) for _ in range(n_dice)]
    return cards, dice


def estimate_dice_needed(mode, shuffle_count, dice_quality):
    """Approximate how many dice rolls the GUI would require to fill
    the entropy gauge AND meet the minimum roll count, matching the
    production app's combined gate logic."""
    target = core.target_bits_for_mode(mode)
    n_cards = core.cards_needed_for_mode(mode)
    loss = core.shuffle_entropy_loss_bits(shuffle_count)
    card_bits = sum(core.card_draw_bits(i) for i in range(n_cards))
    remaining = target - max(0.0, card_bits - loss)
    if remaining <= 0:
        gauge_rolls = 0
    else:
        per_roll = core.dice_roll_bits(dice_quality)
        gauge_rolls = max(1, int(remaining / per_roll) + 2)
    # Enforce the same minimum the GUI enforces
    return max(gauge_rolls, core.DICE_MIN_ROLLS)


def interactive(mode, shuffle_count=10, dice_quality="consumer"):
    n_cards = core.cards_needed_for_mode(mode)
    n_dice = estimate_dice_needed(mode, shuffle_count, dice_quality)
    cards, dice = random_draw(n_cards, n_dice)

    print(f"=== Random draw for {mode}-bit mode ===")
    print(f"Settings: {shuffle_count} shuffles, {dice_quality} dice")
    print()
    print(f"Cards ({n_cards}):")
    # Print in rows of 13 for easy visual scanning
    for i in range(0, len(cards), 13):
        print("  " + "  ".join(f"{c:>3}" for c in cards[i:i+13]))
    print()
    print(f"Dice ({n_dice}): {' '.join(str(d) for d in dice)}")
    print()

    results = core.run_symbol_tests(cards, dice)
    tier = core.compute_overall_tier(results)
    print(f"Analysis tier: {tier['label']}")
    print(f"  {tier['reason']}")
    for r in results:
        marker = {"pass": "  ", "borderline": "~ ", "flag": "! ", "skipped": "- "}
        print(f"  {marker[r['level']]}{r['name']:30s} {r['level']:10s} stat={r['statistic']}")


def batch(n_trials, mode, shuffle_count=10, dice_quality="consumer"):
    n_cards = core.cards_needed_for_mode(mode)
    n_dice = estimate_dice_needed(mode, shuffle_count, dice_quality)

    tiers = {"stop": 0, "caution": 0, "limited": 0, "full": 0}
    test_flags = {}
    test_borderlines = {}

    for trial in range(n_trials):
        cards, dice = random_draw(n_cards, n_dice)
        results = core.run_symbol_tests(cards, dice)
        tier = core.compute_overall_tier(results)
        tiers[tier["tier"]] += 1
        for r in results:
            name = r["name"]
            if r["level"] == "flag":
                test_flags[name] = test_flags.get(name, 0) + 1
            elif r["level"] == "borderline":
                test_borderlines[name] = test_borderlines.get(name, 0) + 1

    print(f"=== Batch: {n_trials} random trials, {mode}-bit mode ===")
    print(f"Settings: {shuffle_count} shuffles, {dice_quality} dice, {n_dice} rolls/trial")
    print()
    print("Tier distribution:")
    for t in ("stop", "caution", "limited", "full"):
        pct = 100 * tiers[t] / n_trials
        bar = "#" * int(pct / 2)
        print(f"  {t:12s} {tiers[t]:5d} ({pct:5.1f}%)  {bar}")
    print()
    fp_rate = 100 * (tiers["stop"] + tiers["caution"]) / n_trials
    print(f"Combined false-positive rate (STOP + CAUTION on fair input): {fp_rate:.1f}%")
    print()

    if test_flags:
        print("Tests that triggered FLAG (should be rare on fair input):")
        for name, count in sorted(test_flags.items(), key=lambda x: -x[1]):
            print(f"  {name:35s} {count:5d} ({100*count/n_trials:.1f}%)")
        print()
    if test_borderlines:
        print("Tests that triggered BORDERLINE:")
        for name, count in sorted(test_borderlines.items(), key=lambda x: -x[1]):
            print(f"  {name:35s} {count:5d} ({100*count/n_trials:.1f}%)")


def batch_d6(n_trials, mode, dice_quality="consumer"):
    """Batch test for D6-only modes (d6_128 or d6_256)."""
    min_groups = core.d6_min_groups(mode)
    n_rolls = min_groups * 5  # default group size 5

    tiers = {"stop": 0, "caution": 0, "limited": 0, "full": 0}
    test_flags = {}
    test_borderlines = {}
    rng = secrets.SystemRandom()

    for _ in range(n_trials):
        dice = [rng.randint(1, 6) for _ in range(n_rolls)]
        results = core.run_symbol_tests([], dice, None)
        tier = core.compute_overall_tier(results)
        tiers[tier["tier"]] += 1
        for r in results:
            if r["level"] == "flag":
                test_flags[r["name"]] = test_flags.get(r["name"], 0) + 1
            elif r["level"] == "borderline":
                test_borderlines[r["name"]] = test_borderlines.get(r["name"], 0) + 1

    _print_batch_results(n_trials, mode, tiers, test_flags, test_borderlines,
                         extra=f"{n_rolls} rolls/trial (groups of 5), {dice_quality} dice")


def batch_dnd(n_trials, mode, dice_quality="consumer"):
    """Batch test for DnD modes (dnd_128 or dnd_256)."""
    min_throws = core.dnd_min_throws(mode)
    rng = secrets.SystemRandom()

    tiers = {"stop": 0, "caution": 0, "limited": 0, "full": 0}
    test_flags = {}
    test_borderlines = {}

    for _ in range(n_trials):
        throws = [
            (rng.randint(1,4), rng.randint(1,6), rng.randint(1,8),
             rng.randint(1,10), rng.randint(1,12), rng.randint(1,20))
            for _ in range(min_throws)
        ]
        results = core.run_symbol_tests([], [], throws)
        tier = core.compute_overall_tier(results)
        tiers[tier["tier"]] += 1
        for r in results:
            if r["level"] == "flag":
                test_flags[r["name"]] = test_flags.get(r["name"], 0) + 1
            elif r["level"] == "borderline":
                test_borderlines[r["name"]] = test_borderlines.get(r["name"], 0) + 1

    _print_batch_results(n_trials, mode, tiers, test_flags, test_borderlines,
                         extra=f"{min_throws} throws/trial (D4/D6/D8/D10/D12/D20), {dice_quality} dice")


def batch_d8d16(n_trials, mode):
    """Batch test for D8+D16×2 modes (d8d16_128 or d8d16_256).
    D8+D16×2 maps directly to word indices -- no symbol-level tests
    apply (the statistical tests are designed for repeated die faces,
    not one-throw-per-word). We verify BIP-39 checksum validity instead."""
    n_throws = core.d8d16_throws_needed(mode)

    import os, sys
    wl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wordlist_english.txt")
    with open(wl_path) as f:
        wordlist = [l.strip() for l in f if l.strip()]

    import hashlib
    failures = 0
    for _ in range(n_trials):
        throws = [
            (rng.randint(1,8), rng.randint(1,16), rng.randint(1,16))
            for _ in range(n_throws)
        ]
        words = core.d8d16_throws_to_mnemonic(throws, wordlist)
        # Verify checksum
        bits = "".join(bin(wordlist.index(w))[2:].zfill(11) for w in words)
        ent_bits = 128 if n_throws == 12 else 256
        cs_bits = ent_bits // 32
        ent_bytes = int(bits[:ent_bits], 2).to_bytes(ent_bits // 8, "big")
        expected_cs = bin(hashlib.sha256(ent_bytes).digest()[0])[2:].zfill(8)[:cs_bits]
        if bits[ent_bits:] != expected_cs:
            failures += 1

    print(f"\n=== D8+D16×2 checksum test: {n_trials} trials, mode={mode} ===")
    print(f"Settings: {n_throws} throws/trial (1 throw = 1 word, 8×16×16=2048 exact)")
    if failures == 0:
        print(f"  All {n_trials} trials produced valid BIP-39 checksums. PASS")
    else:
        print(f"  FAIL: {failures}/{n_trials} invalid checksums")


def _print_batch_results(n_trials, mode, tiers, test_flags, test_borderlines, extra=""):
    print(f"\n=== Batch: {n_trials} trials, mode={mode} ===")
    if extra:
        print(f"Settings: {extra}")
    print()
    print("Tier distribution:")
    for t in ("stop", "caution", "limited", "full"):
        pct = 100 * tiers[t] / n_trials
        bar = "#" * int(pct / 2)
        print(f"  {t:12s} {tiers[t]:5d} ({pct:5.1f}%)  {bar}")
    print()
    fp_rate = 100 * (tiers["stop"] + tiers["caution"]) / n_trials
    print(f"Effective false-positive rate (STOP + CAUTION): {fp_rate:.1f}%")
    print()
    if test_flags:
        print("Tests that triggered FLAG:")
        for name, count in sorted(test_flags.items(), key=lambda x: -x[1]):
            print(f"  {name:40s} {count:5d} ({100*count/n_trials:.1f}%)")
        print()
    if test_borderlines:
        print("Tests that triggered BORDERLINE:")
        for name, count in sorted(test_borderlines.items(), key=lambda x: -x[1]):
            print(f"  {name:40s} {count:5d} ({100*count/n_trials:.1f}%)")


def adversarial(n_trials, mode, shuffle_count=10, dice_quality="consumer"):
    """Run crafted bad-input patterns through the test suite to confirm
    they're caught. Reports how many of each pattern type are detected
    vs missed."""
    n_cards = core.cards_needed_for_mode(mode)
    n_dice = estimate_dice_needed(mode, shuffle_count, dice_quality)

    def _rand_cards():
        d = FULL_DECK[:]
        rng.shuffle(d)
        return d[:n_cards]

    def _rand_dice():
        return [rng.randint(1, 6) for _ in range(n_dice)]

    def _middle_rank_cards():
        middle = [f"{r}{s}" for s in SUITS for r in ["5", "6", "7", "8", "9"]]
        rng.shuffle(middle)
        if n_cards > len(middle):
            edge = [c for c in FULL_DECK if c not in middle]
            rng.shuffle(edge)
            middle.extend(edge)
        return middle[:n_cards]

    def gen_factory():
        return FULL_DECK[:n_cards], _rand_dice()

    def gen_reversed():
        return FULL_DECK[:n_cards][::-1], _rand_dice()

    def gen_suit_blocked():
        blocked = (
            [f"{r}S" for r in RANKS] + [f"{r}H" for r in RANKS] +
            [f"{r}D" for r in RANKS] + [f"{r}C" for r in RANKS]
        )[:n_cards]
        return blocked, _rand_dice()

    def gen_cycling_dice():
        return _rand_cards(), [((i % 6) + 1) for i in range(n_dice)]

    def gen_constant_dice():
        return _rand_cards(), [3] * n_dice

    def gen_alternating_dice():
        return _rand_cards(), [(1 if i % 2 == 0 else 6) for i in range(n_dice)]

    def gen_oddeven_dice():
        return _rand_cards(), [
            rng.choice([1, 3, 5]) if i % 2 == 0 else rng.choice([2, 4, 6])
            for i in range(n_dice)
        ]

    def gen_middle_rank():
        return _middle_rank_cards(), _rand_dice()

    patterns = [
        ("Factory-order deck", gen_factory),
        ("Reversed deck", gen_reversed),
        ("Suit-blocked deck", gen_suit_blocked),
        ("Cycling dice (1-6 repeat)", gen_cycling_dice),
        ("Constant dice (all 3s)", gen_constant_dice),
        ("Alternating dice (1,6,1,6...)", gen_alternating_dice),
        ("Odd/even alternation (varying)", gen_oddeven_dice),
        ("Middle-rank-only draw", gen_middle_rank),
    ]

    print(f"=== Adversarial: {n_trials} trials each, {mode}-bit mode ===")
    print(f"Settings: {shuffle_count} shuffles, {dice_quality} dice, {n_dice} rolls/trial")
    print()

    for name, gen in patterns:
        caught = 0
        for _ in range(n_trials):
            cards, dice = gen()
            results = core.run_symbol_tests(cards, dice)
            tier = core.compute_overall_tier(results)
            if tier["tier"] in ("stop", "caution"):
                caught += 1
        pct = 100 * caught / n_trials
        status = "OK" if pct > 80 else ("WEAK" if pct > 50 else "GAP")
        print(f"  {status:4s} {name:40s} caught {caught}/{n_trials} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description="Dev-only test harness for SeedPrimer statistical tests")
    parser.add_argument("--mode",
                        choices=["128", "256", "d6_128", "d6_256", "dnd_128", "dnd_256",
                                 "d8d16_128", "d8d16_256"],
                        default="256",
                        help="Seed mode (default: 256)")
    parser.add_argument("--all-modes", type=int, metavar="N",
                        help="Run batch test on ALL eight modes with N trials each")
    parser.add_argument("--batch", type=int, metavar="N",
                        help="Run N random trials and report tier distribution")
    parser.add_argument("--adversarial", type=int, metavar="N",
                        help="Run N trials of each crafted bad-input pattern")
    parser.add_argument("--shuffles", type=int, default=10,
                        help="Simulated shuffle count (default: 10)")
    parser.add_argument("--dice-quality", choices=["consumer", "precision"],
                        default="consumer", help="Dice quality setting (default: consumer)")
    args = parser.parse_args()

    if args.all_modes:
        n = args.all_modes
        for m in ["128", "256", "d6_128", "d6_256", "dnd_128", "dnd_256",
                  "d8d16_128", "d8d16_256"]:
            if core.is_d6_mode(m):
                batch_d6(n, m, args.dice_quality)
            elif core.is_dnd_mode(m):
                batch_dnd(n, m, args.dice_quality)
            elif core.is_d8d16_mode(m):
                batch_d8d16(n, m)
            else:
                batch(n, m, args.shuffles, args.dice_quality)
    elif args.batch:
        if core.is_d6_mode(args.mode):
            batch_d6(args.batch, args.mode, args.dice_quality)
        elif core.is_dnd_mode(args.mode):
            batch_dnd(args.batch, args.mode, args.dice_quality)
        elif core.is_d8d16_mode(args.mode):
            batch_d8d16(args.batch, args.mode)
        else:
            batch(args.batch, args.mode, args.shuffles, args.dice_quality)
    elif args.adversarial:
        adversarial(args.adversarial, args.mode, args.shuffles, args.dice_quality)
    else:
        if core.is_dice_only_mode(args.mode):
            print(f"Interactive mode not yet supported for {args.mode} -- use --batch")
            sys.exit(1)
        interactive(args.mode, args.shuffles, args.dice_quality)


if __name__ == "__main__":
    main()
