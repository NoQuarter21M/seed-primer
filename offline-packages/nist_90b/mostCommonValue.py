"""
mostCommonValue.py — NIST SP 800-90B §6.3.1 Most Common Value Estimate.

Reconstructed from the SP 800-90B specification (January 2016 draft) to
replace the missing GitHub stub. Public domain (NIST-derived work).
"""

import math

def most_common(dataset):
    """Most Common Value min-entropy estimate (SP 800-90B §6.3.1).
    Returns (p_max, min_entropy) where:
      p_max       = (count of most common value + 2.576*sqrt(n*p*(1-p))) / n
                    (upper bound with 99% confidence)
      min_entropy = -log2(min(p_max, 1.0))
    """
    n = len(dataset)
    if n == 0:
        return (1.0, 0.0)
    counts = {}
    for s in dataset:
        counts[s] = counts.get(s, 0) + 1
    max_count = max(counts.values())
    p_hat = max_count / n
    # Upper 99% confidence bound (z=2.576)
    p_max = min(1.0, p_hat + 2.576 * math.sqrt(p_hat * (1 - p_hat) / n))
    min_h = -math.log2(p_max)
    return (p_max, min_h)
