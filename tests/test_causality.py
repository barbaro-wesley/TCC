import pandas as pd
import pytest

from atlas_s10.data import load_market_frame, normalized_observations, snapshot
from atlas_s10.features import assert_causal_training, build_features


def test_snapshot_excludes_future_publications():
    observations = normalized_observations(load_market_frame())
    cutoff = pd.Timestamp("2025-01-01T00:00:00Z")
    known = snapshot(observations, cutoff)
    assert not known.empty
    assert known["available_at"].le(cutoff).all()


def test_training_assertion_rejects_future_target():
    features = build_features(load_market_frame())
    origin = features.iloc[80]
    contaminated = features.iloc[:80].dropna(subset=["target_7"]).copy()
    contaminated.loc[contaminated.index[-1], "target_available_at_7"] = (
        pd.to_datetime(origin["available_at"], utc=True) + pd.Timedelta(days=1)
    )
    with pytest.raises(AssertionError, match="Future publication leakage"):
        assert_causal_training(contaminated, origin, 7)

