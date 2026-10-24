import numpy as np
import pandas as pd
import pytest

@pytest.fixture
def sample_ohlcv():
    idx = pd.bdate_range("2022-01-03", periods=500)
    rng = np.random.default_rng(42)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(idx))))
    open_ = close * (1 + rng.normal(0, 0.002, len(idx)))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = rng.integers(1_000_000, 2_000_000, len(idx)).astype(float)
    return pd.DataFrame({"Open":open_,"High":high,"Low":low,"Close":close,"Volume":volume}, index=idx)
