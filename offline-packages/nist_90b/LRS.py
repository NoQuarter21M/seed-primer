"""
LRS.py — NIST SP 800-90B §6.3.7 Length of Longest Repeated Substring.

Reconstructed from the SP 800-90B specification (January 2016 draft) to
replace the missing GitHub stub. Public domain (NIST-derived work).
"""

import math

def lenLRS(dataset, verbose=False):
    """Longest Repeated Substring (LRS) test.
    Returns True (pass) if the dataset does not have suspiciously long
    repeated substrings. Used as an IID pre-check in iid_main.py.
    Also exports LRS_estimate for min-entropy estimation.
    """
    n = len(dataset)
    if n < 2:
        return True
    v = _find_lrs(dataset)
    if verbose:
        print(f"  LRS length: {v}")
    # If LRS length is >= log2(n)+1, the data may not be IID
    threshold = math.log2(n) + 1 if n > 1 else 2
    return v < threshold


def LRS_estimate(dataset, verbose=False):
    """SP 800-90B §6.3.7 LRS min-entropy estimate."""
    n = len(dataset)
    if n < 2:
        return 1.0
    v = _find_lrs(dataset)
    if v == 0:
        return math.log2(len(set(dataset))) if dataset else 1.0
    # p = 2^(v+1) / (n*(n-1)); min_h = -log2(p_max upper bound)
    p = min(1.0, (2 ** (v + 1)) / (n * (n - 1)))
    return -math.log2(p)


def _find_lrs(dataset):
    """Find length of longest repeated non-overlapping substring."""
    n = len(dataset)
    best = 0
    for length in range(1, n // 2 + 1):
        seen = set()
        found = False
        for i in range(n - length + 1):
            t = tuple(dataset[i:i+length])
            if t in seen:
                found = True
                best = length
                break
            seen.add(t)
        if not found:
            break
    return best
