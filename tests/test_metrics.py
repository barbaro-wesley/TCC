import numpy as np
import pytest

from atlas_s10.metrics import brier_score, directional_accuracy, mae, mase, picp, rmse


def test_regression_metrics_known_values():
    actual = np.array([1.0, 2.0, 3.0])
    predicted = np.array([1.0, 2.5, 2.5])
    assert mae(actual, predicted) == pytest.approx(1 / 3)
    assert rmse(actual, predicted) == pytest.approx(np.sqrt(0.5 / 3))
    assert mase(actual, predicted, 0.5) == pytest.approx(2 / 3)


def test_probability_interval_and_direction_metrics():
    assert brier_score(np.array([0, 1]), np.array([0.25, 0.75])) == pytest.approx(0.0625)
    assert picp(np.array([1, 3]), np.array([0, 2]), np.array([2, 2.9])) == 0.5
    assert directional_accuracy(
        np.array([2.0, 1.0]), np.array([1.8, 1.2]), np.array([1.0, 2.0])
    ) == 1.0

