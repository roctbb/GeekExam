"""Optional fractional score steps; existing questions retain integer rounding."""
import math


def score_step(config):
    value = (config or {}).get('score_step', 1)
    if type(value) not in (int, float) or value not in (0.5, 1):
        raise ValueError('score_step должен быть равен 0.5 или 1')
    return value


def round_points(value, config=None):
    step = score_step(config)
    points = round(value / step) * step
    return int(points) if points == int(points) else points


def valid_points(value, maximum, config=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        return False
    return 0 <= value <= maximum and math.isclose(
        value / score_step(config), round(value / score_step(config)), abs_tol=1e-9,
    )
