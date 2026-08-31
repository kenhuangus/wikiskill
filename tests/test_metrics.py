from wikiskill.metrics import accuracy, paired_bootstrap


def test_accuracy():
    assert accuracy([True, False, True, True]) == 0.75
    assert accuracy([]) == 0.0


def test_paired_bootstrap_significant_and_not():
    a = [True] * 10 + [False] * 0
    b = [True] * 5 + [False] * 5
    assert paired_bootstrap(a, b, n=500, seed=1) < 0.05
    assert paired_bootstrap(a, a, n=200, seed=1) == 1.0
