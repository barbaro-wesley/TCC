"""Forecast, probability and interval metrics with explicit edge cases."""

from __future__ import annotations

import numpy as np

EPSILON = 1e-12


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(predicted))))


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(np.asarray(actual) - np.asarray(predicted)))))


def smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    denominator = np.abs(actual) + np.abs(predicted)
    return float(np.mean(200 * np.abs(predicted - actual) / np.maximum(denominator, EPSILON)))


def mase(actual: np.ndarray, predicted: np.ndarray, scale: float) -> float:
    if scale <= EPSILON:
        return float("nan")
    return mae(actual, predicted) / float(scale)


def directional_accuracy(actual: np.ndarray, predicted: np.ndarray, current: np.ndarray) -> float:
    actual_direction = np.sign(np.asarray(actual) - np.asarray(current))
    predicted_direction = np.sign(np.asarray(predicted) - np.asarray(current))
    return float(np.mean(actual_direction == predicted_direction))


def brier_score(actual_event: np.ndarray, probability: np.ndarray) -> float:
    return float(np.mean(np.square(np.asarray(probability) - np.asarray(actual_event))))


def log_loss(actual_event: np.ndarray, probability: np.ndarray) -> float:
    probability = np.clip(np.asarray(probability, dtype=float), 1e-6, 1 - 1e-6)
    actual_event = np.asarray(actual_event, dtype=float)
    return float(-np.mean(actual_event * np.log(probability) + (1 - actual_event) * np.log(1 - probability)))


def picp(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    actual = np.asarray(actual)
    return float(np.mean((actual >= np.asarray(lower)) & (actual <= np.asarray(upper))))


def pinball_loss(actual: np.ndarray, predicted_quantile: np.ndarray, quantile: float) -> float:
    error = np.asarray(actual) - np.asarray(predicted_quantile)
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


def classification_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=bool)
    predicted = np.asarray(predicted, dtype=bool)
    tp = int(np.sum(actual & predicted))
    fp = int(np.sum(~actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision_up": precision, "recall_up": recall, "f1_up": f1}

