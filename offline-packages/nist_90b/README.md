# NIST SP 800-90B Entropy Assessment — Python Implementation

Source: https://github.com/usnistgov/SP800-90B_EntropyAssessment (draft2 branch)
License: Public domain (NIST employee work, 15 U.S.C. §105)

## Files

Fetched directly from NIST GitHub (draft2 branch):
- iid_main.py
- chi_square_tests.py
- permutation_tests.py
- util90b.py

Reconstructed faithfully from SP 800-90B spec (missing GitHub stubs):
- mostCommonValue.py  — §6.3.1 Most Common Value estimate
- LRS.py             — §6.3.7 Longest Repeated Substring estimate
- tuple.py           — §6.3.6 t-Tuple estimate

## Usage (command line)

    cd offline-packages/nist_90b
    python3 iid_main.py /path/to/capture.bin 8

Where the .bin file contains raw byte samples (e.g. LSB bytes from filtered PCM).
bits_per_symbol=8 for byte-level analysis; use 1 for raw bit analysis.

## Usage (from audio_health_tests.py)

Imported automatically via test_min_entropy_estimate() if this directory exists.
mostCommonValue.most_common(dataset) returns (p_max, min_entropy_bits_per_sample).

## Notes

- The draft2 Python version works with Python 3, no compiled dependencies.
- permutation_tests.py optionally uses numpy for speed but falls back to stdlib.
- Recommended minimum input: 1000+ samples for meaningful estimates.
- SP 800-90B recommends 1,000,000+ samples for formal validation.
