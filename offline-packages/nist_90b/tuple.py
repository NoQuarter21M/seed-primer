"""
tuple.py — NIST SP 800-90B tuple-based min-entropy estimators.

Reconstructed from the SP 800-90B specification (January 2016 draft).
Public domain (NIST-derived work).
"""

import math
from collections import Counter

def find_tuples(dataset, t_len):
    """Count occurrences of each t-length tuple in the dataset."""
    tuples = [tuple(dataset[i:i+t_len]) for i in range(len(dataset) - t_len + 1)]
    return Counter(tuples)

def t_tuple(dataset, verbose=False):
    """SP 800-90B §6.3.6 t-Tuple Estimate.
    Returns min-entropy estimate in bits/symbol.
    """
    n = len(dataset)
    if n < 4:
        return 0.0
    # Try tuple lengths 1 through log2(n)/2
    max_t = max(1, int(math.log2(n) / 2))
    best_h = float('inf')
    for t in range(1, max_t + 1):
        counts = find_tuples(dataset, t)
        if not counts:
            continue
        q = max(counts.values()) / (n - t + 1)
        # Upper 99% confidence bound
        q_bar = min(1.0, q + 2.576 * math.sqrt(q * (1 - q) / (n - t + 1)))
        h = -math.log2(q_bar) / t
        best_h = min(best_h, h)
        if verbose:
            print(f"  t={t}: q={round(q,6)}, H={round(h,4)}")
    return best_h if best_h != float('inf') else 0.0
