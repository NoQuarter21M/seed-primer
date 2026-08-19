#!/usr/bin/env python3
"""
monte_carlo_pico.py

Monte Carlo test of the entropy mixer pipeline with real Pico TRNG XOR.

Tests two distinct hypotheses:
  H1 (Baseline): For fair simulated physical input, the full pipeline
     (physical_bytes XOR pico_bytes -> SHA-256) produces output that
     is statistically indistinguishable from uniform.
  H2 (Corrective): For deliberately biased physical input, the Pico
     XOR pulls the pipeline output toward uniformity, reducing or
     eliminating measurable bias before SHA-256 whitening.

Simulated physical input:
  The "physical draw" (cards/dice) is simulated using a qualified
  hardware entropy source -- either the H1essential microphone or
  the second Pico/Tiny TRNG -- so the simulation uses real physical
  randomness rather than a CSPRNG. This avoids begging the question.

  For H2 (biased input), the qualified-source bytes are deliberately
  skewed by zeroing a fraction of bits before XOR, simulating a
  physical draw with known bias.

Pico XOR source:
  The Pico TRNG identified in settings (default: first responsive
  ttyACM port). If two Picos are present, the simulation source and
  the XOR source use different devices.

Usage:
  python3 monte_carlo_pico.py [--trials 1000] [--bias 0.0] [--source mic|pico]
                              [--pico-port /dev/ttyACMx] [--sim-port /dev/ttyACMy]
                              [--seed-bytes 16] [--csv output.csv]

Author: NoQuarter21M + Claude (Anthropic)
Date:   2026-08-18
"""

import sys, os, math, time, argparse, csv, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pico_trng_source as pico_mod
import entropy_mix_core as core

# ---------------------------------------------------------------------------
# Entropy source: H1essential microphone
# ---------------------------------------------------------------------------

def get_mic_block(n_bytes: int, device: str = "plughw:H1essential,0",
                  rate: int = 44100, warmup_samples: int = 8192) -> bytes:
    """
    Capture a large block of mic entropy in one arecord call.
    Used to pre-fill a buffer; sliced per trial in main().
    Discards warmup_samples at the start.
    """
    import subprocess, struct
    n_samples = n_bytes * 8
    total_samples = warmup_samples + n_samples
    cmd = [
        "arecord", "-D", device,
        "-f", "S16_LE", "-r", str(rate), "-c", "1",
        "-t", "raw", "-q",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        total_bytes_needed = total_samples * 2
        raw = b""
        while len(raw) < total_bytes_needed:
            chunk = proc.stdout.read(total_bytes_needed - len(raw))
            if not chunk:
                break
            raw += chunk
    finally:
        proc.terminate()
        proc.wait()
    raw = raw[warmup_samples*2:]
    samples = struct.unpack_from(f"<{n_samples}h", raw[:n_samples*2])
    out = bytearray()
    for i in range(0, len(samples), 8):
        byte = 0
        for j, s in enumerate(samples[i:i+8]):
            byte |= (s & 1) << j
        out.append(byte)
    return bytes(out[:n_bytes])


# ---------------------------------------------------------------------------
# Bias injection
# ---------------------------------------------------------------------------

def apply_bias(data: bytes, zero_fraction: float) -> bytes:
    """
    Artificially bias data toward zeros by zeroing a fraction of bits.
    zero_fraction=0.0 -> no change (fair).
    zero_fraction=0.3 -> ~30% of 1-bits are flipped to 0 (skewed toward zeros).
    This simulates a physically biased draw.
    """
    if zero_fraction <= 0.0:
        return data
    import random
    bits = list(''.join(bin(b)[2:].zfill(8) for b in data))
    one_indices = [i for i, b in enumerate(bits) if b == '1']
    n_flip = int(len(one_indices) * zero_fraction)
    to_flip = random.sample(one_indices, min(n_flip, len(one_indices)))
    for i in to_flip:
        bits[i] = '0'
    bit_str = ''.join(bits)
    return int(bit_str, 2).to_bytes(len(data), 'big')


# ---------------------------------------------------------------------------
# Pipeline: simulated physical -> XOR pico -> SHA-256
# ---------------------------------------------------------------------------

def pipeline(sim_bytes: bytes, pico_bytes: bytes, target_bits: int = 128) -> bytes:
    """
    Reproduce the entropy mixer pre-whitening XOR pipeline exactly:
      sim_bytes XOR pico_bytes -> raw bit string -> SHA-256 -> entropy_bytes
    """
    # XOR
    combined = core.xor_mix_external_source(sim_bytes, pico_bytes)
    # Convert to bit string (same encoding as raw_entropy_bits for card/dice)
    bit_str = bin(int.from_bytes(combined, 'big'))[2:].zfill(len(combined)*8)
    # Whiten
    return core.whiten_entropy(bit_str, target_bits)


def pipeline_no_pico(sim_bytes: bytes, target_bits: int = 128) -> bytes:
    """Same pipeline without Pico XOR -- baseline comparison."""
    bit_str = bin(int.from_bytes(sim_bytes, 'big'))[2:].zfill(len(sim_bytes)*8)
    return core.whiten_entropy(bit_str, target_bits)


# ---------------------------------------------------------------------------
# Per-trial statistics
# ---------------------------------------------------------------------------

def measure(entropy_bytes: bytes) -> dict:
    bits = ''.join(bin(b)[2:].zfill(8) for b in entropy_bytes)
    n_bits = len(bits)
    ones = bits.count('1')
    zeros = n_bits - ones

    # Bit balance Z
    z_bits = (ones - n_bits/2) / math.sqrt(n_bits/4)

    # Runs
    runs = sum(1 for i in range(1, n_bits) if bits[i] != bits[i-1]) + 1
    er = (2*ones*zeros)/n_bits + 1
    denom_sq = (2*ones*zeros*(2*ones*zeros - n_bits)) / (n_bits**2 * (n_bits-1))
    z_runs = (runs - er) / math.sqrt(denom_sq) if denom_sq > 0 else 0.0

    # Hamming
    hw_pct = ones / n_bits * 100

    # Bit autocorrelation lag-1
    bit_list = [int(b) for b in bits]
    mb = ones / n_bits
    vb = mb * (1 - mb)
    if vb > 0 and n_bits > 1:
        ac1 = sum((bit_list[i]-mb)*(bit_list[i+1]-mb)
                  for i in range(n_bits-1)) / ((n_bits-1)*vb)
    else:
        ac1 = 0.0

    return {
        "ones": ones, "zeros": zeros, "z_bits": z_bits,
        "runs": runs, "er": er, "z_runs": z_runs,
        "hw_pct": hw_pct, "ac1": ac1,
    }


def summarise(stats: list, label: str) -> dict:
    """Compute mean, std, and tail rates for a list of trial stat dicts."""
    n = len(stats)
    def mean(key):  return sum(s[key] for s in stats) / n
    def std(key):
        m = mean(key)
        return math.sqrt(sum((s[key]-m)**2 for s in stats) / n)

    z_bits  = [s["z_bits"] for s in stats]
    z_runs  = [s["z_runs"] for s in stats]
    ac1s    = [s["ac1"]    for s in stats]
    hws     = [s["hw_pct"] for s in stats]

    # Fraction of trials with |Z| > 1.96 (p<0.05) and |Z| > 2.576 (p<0.01)
    def tail(vals, thresh): return sum(1 for v in vals if abs(v) > thresh) / n

    return {
        "label":       label,
        "n":           n,
        "z_bits_mean": mean("z_bits"),
        "z_bits_std":  std("z_bits"),
        "z_bits_p05":  tail(z_bits, 1.96),
        "z_bits_p01":  tail(z_bits, 2.576),
        "z_runs_mean": mean("z_runs"),
        "z_runs_std":  std("z_runs"),
        "z_runs_p05":  tail(z_runs, 1.96),
        "hw_mean":     mean("hw_pct"),
        "hw_std":      std("hw_pct"),
        "ac1_mean":    mean("ac1"),
        "ac1_std":     std("ac1"),
        "ac1_p05":     sum(1 for v in ac1s if abs(v) > 0.05) / n,
    }


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def print_summary(s: dict, expected_z_p05: float = 0.05):
    label = s["label"]
    print(f"\n{'='*70}")
    print(f"  {label}  (n={s['n']})")
    print(f"{'='*70}")
    flag = lambda actual, thresh, name: (
        f"  *** {name}: {actual*100:.1f}% > {thresh*100:.0f}% expected"
        if actual > thresh * 1.5 else "")

    print(f"  Bit balance Z:  mean={s['z_bits_mean']:+.4f}  std={s['z_bits_std']:.4f}"
          f"  |Z|>1.96: {s['z_bits_p05']*100:.1f}%  |Z|>2.576: {s['z_bits_p01']*100:.1f}%"
          + flag(s['z_bits_p05'], expected_z_p05, 'BIT-BIAS'))
    print(f"  Runs Z:         mean={s['z_runs_mean']:+.4f}  std={s['z_runs_std']:.4f}"
          f"  |Z|>1.96: {s['z_runs_p05']*100:.1f}%")
    print(f"  Hamming %:      mean={s['hw_mean']:.2f}%  std={s['hw_std']:.2f}%"
          f"  (ideal 50.0%)")
    print(f"  Autocorr L1:    mean={s['ac1_mean']:+.5f}  std={s['ac1_std']:.5f}"
          f"  |ac|>0.05: {s['ac1_p05']*100:.1f}%")

    # Verdict
    ok = (abs(s['z_bits_mean']) < 0.1 and
          s['z_bits_p05'] < 0.10 and
          s['z_bits_p01'] < 0.02 and
          abs(s['ac1_mean']) < 0.02)
    print(f"\n  Verdict: {'PASS -- output distribution consistent with uniform' if ok else 'REVIEW -- see flagged metrics above'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Monte Carlo Pico TRNG pipeline test")
    ap.add_argument("--trials",    type=int,   default=1000,
                    help="Number of trials per condition (default 1000; use 10000 for full run)")
    ap.add_argument("--bias",      type=float, default=0.0,
                    help="Zero-bias fraction for H2 test 0.0-1.0 (default 0.0 = fair)")
    ap.add_argument("--source",    choices=["mic","pico"], default="mic",
                    help="Simulated physical entropy source (default: mic)")
    ap.add_argument("--pico-port", default=None,
                    help="Pico TRNG port for XOR (default: auto-scan)")
    ap.add_argument("--sim-port",  default=None,
                    help="Second Pico port for simulated input (--source pico only)")
    ap.add_argument("--seed-bytes",type=int,   default=16,
                    help="Seed byte length: 16=128-bit, 32=256-bit (default 16)")
    ap.add_argument("--csv",       default=None,
                    help="Write per-trial stats to CSV file")
    ap.add_argument("--no-xor",    action="store_true",
                    help="Also run trials WITHOUT Pico XOR for comparison")
    args = ap.parse_args()

    target_bits = args.seed_bytes * 8
    print(f"\nEntropy Mixer Monte Carlo Test")
    print(f"  Date:         {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Trials:       {args.trials}")
    print(f"  Seed size:    {args.seed_bytes} bytes ({target_bits} bits)")
    print(f"  Bias:         {args.bias:.0%} zero-skew {'(fair input)' if args.bias==0 else '(biased input -- H2 test)'}")
    print(f"  Sim source:   {args.source}")

    # --- Locate Pico XOR port ---
    if args.pico_port:
        pico_port = args.pico_port
        ok, msg, _ = pico_mod.probe_port(pico_port)
        if not ok:
            print(f"ERROR: Pico XOR port {pico_port}: {msg}", file=sys.stderr)
            sys.exit(1)
    else:
        pico_port, msg, _ = pico_mod.find_pico()
        if not pico_port:
            print(f"ERROR: No Pico found for XOR: {msg}", file=sys.stderr)
            sys.exit(1)
    print(f"  Pico XOR:     {pico_port}")

    CHUNK = args.seed_bytes

    # --- Locate sim source ---
    if args.source == "pico":
        sim_port = args.sim_port
        if not sim_port:
            # Find a second Pico different from XOR port
            for port in pico_mod.scan_ports():
                if port == pico_port:
                    continue
                ok, msg, _ = pico_mod.probe_port(port)
                if ok:
                    sim_port = port
                    break
        if not sim_port:
            print("ERROR: --source pico requires a second Pico for simulation.",
                  file=sys.stderr)
            sys.exit(1)
        print(f"  Sim source:   Pico TRNG at {sim_port}")
    else:
        print(f"  Sim source:   H1essential microphone (plughw:H1essential,0)")

    print(f"\nPre-fetching entropy from all sources (one bulk read each)...")

    # Pico XOR bytes -- bulk prefetch in one serial session
    PICO_NEEDED = args.trials * CHUNK + 64
    print(f"  Pico TRNG ({pico_port}): fetching {PICO_NEEDED} bytes...")
    t_pico = time.time()
    pico_buf = bytearray(pico_mod.get_trng_bulk(PICO_NEEDED, port=pico_port))
    print(f"  Pico: {len(pico_buf)} bytes in {time.time()-t_pico:.1f}s, "
          f"distinct={len(set(pico_buf))}/256")

    # Sim source prefetch
    SIM_NEEDED = args.trials * CHUNK + 64
    if args.source == "mic":
        print(f"  H1essential mic: fetching {SIM_NEEDED} bytes...")
        t_mic = time.time()
        sim_buf = bytearray(get_mic_block(SIM_NEEDED))
        print(f"  Mic: {len(sim_buf)} bytes in {time.time()-t_mic:.1f}s, "
              f"distinct={len(set(sim_buf))}/256")
    else:
        # Already have sim_port from source setup above
        print(f"  Pico sim ({sim_port}): fetching {SIM_NEEDED} bytes...")
        t_sim = time.time()
        sim_buf = bytearray(pico_mod.get_trng_bulk(SIM_NEEDED, port=sim_port))
        print(f"  Sim Pico: {len(sim_buf)} bytes in {time.time()-t_sim:.1f}s, "
              f"distinct={len(set(sim_buf))}/256")

    print(f"  All sources ready.\n")

    # --- Run trials ---
    stats_with_xor    = []
    stats_without_xor = [] if args.no_xor else None
    csv_rows          = []
    t0 = time.time()

    pico_pos = 0
    sim_pos  = 0

    def next_pico():
        nonlocal pico_pos
        chunk = bytes(pico_buf[pico_pos:pico_pos+CHUNK])
        pico_pos += CHUNK
        return chunk

    def next_sim():
        nonlocal sim_pos
        chunk = bytes(sim_buf[sim_pos:sim_pos+CHUNK])
        sim_pos += CHUNK
        return chunk

    print(f"Running {args.trials} trials...")

    for trial in range(args.trials):
        pico_bytes = next_pico()
        sim_bytes  = next_sim()

        # Apply bias if requested
        if args.bias > 0:
            sim_bytes = apply_bias(sim_bytes, args.bias)

        # With XOR
        out_with = pipeline(sim_bytes, pico_bytes, target_bits)
        m_with   = measure(out_with)
        stats_with_xor.append(m_with)

        # Without XOR (comparison)
        if args.no_xor:
            out_without = pipeline_no_pico(sim_bytes, target_bits)
            m_without   = measure(out_without)
            stats_without_xor.append(m_without)

        if args.csv:
            row = {"trial": trial, "bias": args.bias}
            for k, v in m_with.items():
                row[f"xor_{k}"] = v
            if args.no_xor:
                for k, v in m_without.items():
                    row[f"noxor_{k}"] = v
            csv_rows.append(row)

        if (trial+1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (trial+1) / elapsed
            print(f"  {trial+1}/{args.trials}  ({rate:.0f} trials/sec)")

    elapsed = time.time() - t0
    print(f"\nCompleted {args.trials} trials in {elapsed:.1f}s "
          f"({args.trials/elapsed:.0f} trials/sec)")

    # --- Summaries ---
    bias_label = f"bias={args.bias:.0%}" if args.bias > 0 else "fair input"
    s_with = summarise(stats_with_xor,
                       f"WITH Pico XOR  [{bias_label}, {args.source}, n={args.trials}]")
    print_summary(s_with)

    if args.no_xor and stats_without_xor:
        s_without = summarise(stats_without_xor,
                              f"WITHOUT Pico XOR [{bias_label}, {args.source}, n={args.trials}]")
        print_summary(s_without)

        # Delta analysis
        print(f"\n{'='*70}")
        print("  Pico XOR effect (with - without):")
        print(f"  Bit balance Z mean:  "
              f"{s_with['z_bits_mean']:+.4f} vs {s_without['z_bits_mean']:+.4f}  "
              f"delta={s_with['z_bits_mean']-s_without['z_bits_mean']:+.4f}")
        print(f"  Bit balance p05:     "
              f"{s_with['z_bits_p05']*100:.1f}% vs {s_without['z_bits_p05']*100:.1f}%")
        print(f"  Hamming mean:        "
              f"{s_with['hw_mean']:.2f}% vs {s_without['hw_mean']:.2f}%")
        print(f"  Autocorr L1 mean:    "
              f"{s_with['ac1_mean']:+.5f} vs {s_without['ac1_mean']:+.5f}")
        print(f"{'='*70}")

    # --- CSV output ---
    if args.csv and csv_rows:
        fieldnames = list(csv_rows[0].keys())
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(csv_rows)
        print(f"\nPer-trial data written to: {args.csv}")

    print()


if __name__ == "__main__":
    main()
