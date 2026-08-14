import numpy as np
import pytest

from atlas_s10.reporting import diebold_mariano


def test_diebold_mariano_sign_and_bounds():
    actual = np.arange(12, dtype=float)
    candidate = actual + 0.1
    baseline = actual + np.array([1.0, 1.1] * 6)
    result = diebold_mariano(actual, candidate, baseline, horizon_steps=2)
    assert result["statistic"] < 0
    assert 0 <= result["p_value"] <= 1
    assert result["observations"] == 12


def test_diebold_mariano_short_panel_is_explicit():
    result = diebold_mariano([1, 2], [1, 2], [2, 3])
    assert result == {"statistic": None, "p_value": None, "observations": 2, "lag": 0}


def test_serialized_lightgbm_artifacts_exist_and_load():
    lightgbm = pytest.importorskip("lightgbm")
    from atlas_s10.config import MODELS_DIR

    for horizon in (7, 14, 30):
        path = MODELS_DIR / f"lightgbm_h{horizon}.txt"
        assert path.exists()
        booster = lightgbm.Booster(model_file=str(path))
        assert booster.num_trees() > 0
