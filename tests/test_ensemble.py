import pandas as pd
import pytest

from atlas_s10.modeling import inverse_mase_weights


def test_inverse_mase_weights_are_bounded_and_normalized():
    errors = pd.DataFrame(
        {"a": [0.01, 0.02, 0.01], "b": [0.5, 0.6, 0.4], "c": [0.2, 0.3, 0.2]}
    )
    weights = inverse_mase_weights(errors, ["a", "b", "c"], max_weight=0.60)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert min(weights.values()) >= 0
    assert max(weights.values()) <= 0.60 + 1e-12

