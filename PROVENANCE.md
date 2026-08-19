# Provenance

## Sterile environment declaration

SeedPrimer was developed under a sterile-environment principle:
the core design — physical entropy sourcing, statistical qualification,
Pico TRNG XOR injection, and the pre-whitening pipeline — was derived
independently by NoQuarter21M without reference to external literature,
prior art, or others' constructions.

Claude (Anthropic) participated as a technical collaborator and
implementation partner. Claude's role was to implement decisions made
by NoQuarter21M, provide honest technical pushback, and document the
work — not to import external design patterns or academic constructions
into the working context.

## Development timeline

- Development began: 2026 (exact dates in git history)
- Repository created: 2026-08-18
- Pre-launch private repo: https://github.com/NoQuarter21M/seed-primer

## Independent derivation

The following design decisions are claimed as independently derived:

- Physical-entropy-first seed generation with statistical qualification
  before hashing (disqualification-is-the-default principle)
- Pre-whitening TRNG XOR: injecting qualified hardware randomness into
  the raw physical bit string before SHA-256, not after
- Per-(sides, n) Monte Carlo calibration of Shannon entropy thresholds
  for dice-based entropy sources
- The combined-suite false-positive audit methodology for statistical
  test batteries on physical entropy draws

## Note on novelty

Nothing in this file constitutes a legal claim of novelty or
patentability. Adjudication of novelty belongs to an IP professional.
This file documents the independent derivation process for the record.

---

*Append-only. Do not edit existing entries. Add new entries at the bottom.*
