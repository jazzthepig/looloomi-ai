def test_a():
    pass
TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
def test_b_never_runs():
    pass
