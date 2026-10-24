from src.strategies.drbl_matrix import choose_rotation


def test_choose_rotation_initial_asset():
    assert choose_rotation({"SPY": 0.1, "QQQ": 0.2}, None) == "QQQ"


def test_rotation_hysteresis_positive():
    assert choose_rotation({"SPY": 1.0, "QQQ": 1.08}, "SPY") == "SPY"
    assert choose_rotation({"SPY": 1.0, "QQQ": 1.081}, "SPY") == "QQQ"


def test_rotation_hysteresis_negative_is_deterministic():
    assert choose_rotation({"SPY": -1.0, "QQQ": -0.95}, "SPY") == "SPY"
    assert choose_rotation({"SPY": -1.0, "QQQ": -0.91}, "SPY") == "QQQ"


def test_no_scores():
    assert choose_rotation({}, None) is None
