"""Metrics (paper Appendix C): accuracy + paired bootstrap significance testing."""
from __future__ import annotations

import random
from typing import Sequence


def accuracy(correct_flags: Sequence[bool]) -> float:
    return sum(bool(c) for c in correct_flags) / len(correct_flags) if correct_flags else 0.0


def paired_bootstrap(a: Sequence[bool], b: Sequence[bool], n: int = 1000,
                     seed: int = 0) -> float:
    """Paired bootstrap (paper App. C): resample test tasks with replacement; return
    the p-value that method `a` does not outperform `b` (one-sided)."""
    assert len(a) == len(b)
    rng = random.Random(seed)
    N = len(a)
    if N == 0:
        return 1.0
    margins = [1.0 if x and not y else (-1.0 if y and not x else 0.0)
               for x, y in zip(a, b)]
    worse_or_equal = 0
    for _ in range(n):
        sample = [margins[rng.randrange(N)] for _ in range(N)]
        if sum(sample) / N <= 0:
            worse_or_equal += 1
    return worse_or_equal / n
