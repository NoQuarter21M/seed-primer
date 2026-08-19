# Credits

SeedPrimer was designed and developed by **NoQuarter21M** in
collaboration with **Claude** (Anthropic).

## Primary authorship

- **NoQuarter21M** — architecture, design decisions, hardware
  bring-up, qualification methodology, security philosophy, and
  all final decisions on direction and implementation.

- **Claude (Anthropic, claude.ai)** — implementation, code
  generation, statistical analysis, documentation, and technical
  research conducted across the development sessions.

## Third-party components

- **BIP-39 English wordlist** — Bitcoin Improvement Proposals,
  used under the terms of the BIP-39 specification.
  Source: https://github.com/trezor/python-mnemonic/blob/master/src/mnemonic/wordlist/english.txt

- **QR encoding** — implemented from scratch in qr_encoder.py,
  no external library used.

## Entropy qualification

Hardware entropy sources were qualified using the NIST SP 800-90B
Entropy Assessment tool:
https://github.com/usnistgov/SP800-90B_EntropyAssessment

---

*This file is the canonical credit record for SeedPrimer.
It is maintained as a living document and updated as the project evolves.*
