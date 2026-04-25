# demo_detectors.py
import numpy as np
from statistics import mean
from enum import Enum

class BaselineChoice(Enum):
    MEAN = "mean"
    PREV = "prev"
    
class DirectionChoice(Enum):
    BOTH = "both"
    ONLY_UP = "only_up"
    ONLY_DOWN = "only_down"

def detect_zscore(
    prices: list[float],
    current_price: float,
    threshold: float = 3.0,
    min_std: float = 1e-3,
    min_samples: int = 3,
    direction: DirectionChoice = DirectionChoice.BOTH,
) -> tuple[bool, dict]:
    """
    Z-score detector. Returns (triggered, info).
    direction: DirectionChoice.BOTH | ONLY_UP | ONLY_DOWN
    """
    if len(prices) < min_samples:
        return False, {"reason": "not_enough_samples", "samples": len(prices)}

    current_price = float(current_price)
    prices = [float(p) for p in prices]

    mu = float(np.mean(prices))
    raw_sigma = float(np.std(prices, ddof=1))
    sigma_floor = float(min_std)
    sigma = max(raw_sigma, sigma_floor)
    std_floor_applied = raw_sigma < sigma_floor

    z = (current_price - mu) / sigma

    # handle direction (accept both DirectionChoice and strings)
    if isinstance(direction, DirectionChoice):
        dir_enum = direction
    else:
        try:
            dir_enum = DirectionChoice(direction)
        except Exception:
            return False, {"reason": "unknown_direction", "direction": str(direction)}

    if dir_enum == DirectionChoice.BOTH:
        triggered = abs(z) > threshold
    elif dir_enum == DirectionChoice.ONLY_UP:
        triggered = z > threshold
    elif dir_enum == DirectionChoice.ONLY_DOWN:
        triggered = z < -threshold
    else:
        return False, {"reason": "unknown_direction", "direction": str(direction)}

    info = {
        "method": "zscore",
        "z": float(z),
        "mean": mu,
        "std": sigma,
        "raw_std": raw_sigma,
        "std_floor_applied": std_floor_applied,
        "threshold": float(threshold),
        "direction": dir_enum.value,
        "samples": len(prices),
        "triggered": bool(triggered),
    }

    return bool(triggered), info


def detect_pct_change(
    past_prices: list[float],
    current_price: float,
    threshold_pct: float = 10.0,
    baseline: BaselineChoice = BaselineChoice.MEAN,  # BaselineChoice or string
    min_samples: int = 1,
    min_baseline: float = 1e-6,
    direction: DirectionChoice = DirectionChoice.BOTH,  # DirectionChoice or string
) -> tuple[bool, dict]:
    """Percent-change detector. Always returns (triggered, info). Accepts enums or their string values."""
    if len(past_prices) < min_samples:
        return False, {"reason": "not_enough_samples", "samples": len(past_prices)}

    # normalize baseline (accept enum or string)
    if isinstance(baseline, BaselineChoice):
        base_choice = baseline
    else:
        try:
            base_choice = BaselineChoice(baseline)
        except Exception:
            return False, {"reason": "unknown_baseline", "baseline_choice": str(baseline)}

    if base_choice == BaselineChoice.MEAN:
        base = float(mean(past_prices))
        base_type = "mean"
    else:  # PREV
        base = float(past_prices[-1])
        base_type = "prev"

    if abs(base) < min_baseline:
        return False, {"reason": "baseline_too_small", "baseline": base, "min_baseline": min_baseline}

    base = float(base)
    current_price = float(current_price)

    pct = float((current_price - base) / base * 100.0)

    # normalize direction (accept enum or string)
    if isinstance(direction, DirectionChoice):
        dir_enum = direction
    else:
        try:
            dir_enum = DirectionChoice(direction)
        except Exception:
            return False, {"reason": "unknown_direction", "direction": str(direction)}

    if dir_enum == DirectionChoice.BOTH:
        triggered = abs(pct) >= abs(threshold_pct)
    elif dir_enum == DirectionChoice.ONLY_UP:
        triggered = pct >= threshold_pct
    elif dir_enum == DirectionChoice.ONLY_DOWN:
        triggered = pct <= -abs(threshold_pct)
    else:
        return False, {"reason": "unknown_direction", "direction": dir_enum.value}

    info = {
        "method": "pct_change",
        "baseline": base,
        "baseline_type": base_type,
        "pct_change": pct,
        "threshold_pct": float(threshold_pct),
        "direction": dir_enum.value,
        "samples": len(past_prices),
        "triggered": bool(triggered),
    }
    return bool(triggered), info


def detect_below_threshold(
    past_prices: list[float] | None,
    current_price: float,
    threshold_value: float | None = None,
    threshold_pct: float | None = None,
    pct_baseline: BaselineChoice = BaselineChoice.MEAN,  # BaselineChoice or string
    min_samples: int = 1,
    min_baseline: float = 1e-6,
) -> tuple[bool, dict]:
    """Below-threshold detector. Always returns (triggered, info). Accepts enums or strings."""
    if threshold_value is None and threshold_pct is None:
        return False, {"reason": "no_threshold_provided"}

    # Absolute threshold has priority
    if threshold_value is not None:
        triggered = float(current_price) < float(threshold_value)
        info = {
            "method": "below_threshold",
            "mode": "absolute",
            "threshold_value": float(threshold_value),
            "current_price": float(current_price),
            "triggered": bool(triggered),
        }
        return bool(triggered), info

    # Relative percent threshold
    if past_prices is None or len(past_prices) < min_samples:
        return False, {"reason": "not_enough_samples_for_pct", "samples": 0 if past_prices is None else len(past_prices)}

    # normalize pct_baseline
    if isinstance(pct_baseline, BaselineChoice):
        pct_base_choice = pct_baseline
    else:
        try:
            pct_base_choice = BaselineChoice(pct_baseline)
        except Exception:
            return False, {"reason": "unknown_pct_baseline", "pct_baseline": str(pct_baseline)}

    if pct_base_choice == BaselineChoice.MEAN:
        base = float(mean(past_prices))
        pct_baseline_str = "mean"
    else:
        base = float(past_prices[-1])
        pct_baseline_str = "prev"

    if abs(base) < min_baseline:
        return False, {"reason": "baseline_too_small", "baseline": base, "min_baseline": min_baseline}

    base = float(base)
    current_price = float(current_price)

    threshold_abs = base * (1.0 - float(threshold_pct) / 100.0)
    triggered = current_price < threshold_abs
    info = {
        "method": "below_threshold",
        "mode": "relative_pct",
        "baseline": base,
        "pct_baseline": pct_baseline_str,
        "threshold_pct": float(threshold_pct),
        "threshold_abs": float(threshold_abs),
        "current_price": float(current_price),
        "samples": len(past_prices),
        "triggered": bool(triggered),
    }
    return bool(triggered), info
