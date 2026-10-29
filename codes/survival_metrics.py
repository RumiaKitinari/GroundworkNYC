"""Interval-aware diagnostics; unresolved horizon outcomes never become labels."""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from temporal_cohort import three_year_outcome


def interval_nll(median, lower, upper, scale=1.0):
    median, lower, upper = np.broadcast_arrays(np.asarray(median, float), np.asarray(lower, float), np.asarray(upper, float))
    if (not np.isfinite(median).all() or (median <= 0).any() or not np.isfinite(lower).all()
            or (lower <= 0).any() or np.isnan(upper).any() or (upper < lower).any()
            or not np.isfinite(scale) or scale <= 0):
        raise ValueError("Ordered positive interval bounds and median times are required")
    lo, hi = (np.log(lower) - np.log(median)) / scale, (np.log(upper) - np.log(median)) / scale
    exact, censored = lower == upper, np.isposinf(upper)
    log_likelihood = np.empty(median.shape)
    log_likelihood[exact] = norm.logpdf(lo[exact]) - np.log(lower[exact] * scale)
    log_likelihood[censored] = norm.logsf(lo[censored])
    interval = ~exact & ~censored
    a = np.where(lo[interval] > 0, norm.logsf(lo[interval]), norm.logcdf(hi[interval]))
    b = np.where(lo[interval] > 0, norm.logsf(hi[interval]), norm.logcdf(lo[interval]))
    with np.errstate(divide="ignore", invalid="ignore"):
        log_likelihood[interval] = a + np.log(-np.expm1(b - a))
    return -log_likelihood


def fit_constant_aft(lower, upper, scale=1.0):
    """Intercept-only comparator fitted exclusively to the training fold."""
    if not np.isfinite(np.asarray(upper, float)).any():
        raise ValueError("All-censored rows cannot identify the baseline")
    result = minimize_scalar(lambda log_median: interval_nll(np.exp(log_median), lower, upper, scale).mean(),
                             bounds=(-10, 10), method="bounded", options={"xatol": 1e-9})
    if not result.success or not np.isfinite(result.fun) or abs(result.x) > 9.99:
        raise ValueError("Constant AFT baseline is not stably identified")
    return float(np.exp(result.x))


def comparable_concordance(median, lower, upper, groups=None, bootstrap=200, seed=440):
    median, lower, upper = map(lambda a: np.asarray(a, float), (median, lower, upper))
    n = len(median)
    rng = np.random.default_rng(seed)
    if n <= 800:
        i, j = np.indices((n, n)).reshape(2, -1)
        mode = "all_ordered_pairs"
    else:
        i, j = rng.integers(0, n, (2, 300000))
        mode = "sampled_300000_ordered_pairs"
    usable = (i != j) & np.isfinite(upper[i]) & (upper[i] < lower[j]) & np.isfinite(median[i]) & np.isfinite(median[j])
    i, j = i[usable], j[usable]
    credit = (median[i] < median[j]).astype(float) + .5 * (median[i] == median[j])
    estimate = float(credit.mean()) if len(credit) else None
    result = {"estimate": estimate, "comparable_pairs": len(credit), "pair_method": mode,
              "nta_cluster_bootstrap_95_ci": None, "bootstrap_replicates_used": 0}
    if groups is None or estimate is None:
        return result
    labels, codes = np.unique(np.asarray(groups, str), return_inverse=True)
    if len(labels) < 2:
        return result
    estimates = []
    for _ in range(bootstrap):
        counts = np.bincount(rng.integers(0, len(labels), len(labels)), minlength=len(labels))
        weights = counts[codes[i]] * counts[codes[j]]
        if weights.sum():
            estimates.append(float(np.average(credit, weights=weights)))
    result["bootstrap_replicates_used"] = len(estimates)
    if len(estimates) >= 20:
        result["nta_cluster_bootstrap_95_ci"] = np.quantile(estimates, [.025, .975]).tolist()
    return result


def evaluate_predictions(median, lower, upper, groups=None, scale=1.0):
    median, lower, upper = map(lambda a: np.asarray(a, float), (median, lower, upper))
    known = three_year_outcome(lower, upper)
    resolved = np.isfinite(known)
    survival = norm.sf((np.log(3) - np.log(median)) / scale)
    result = {"rows": len(median), "finite_event_intervals": int(np.isfinite(upper).sum()),
        "right_censored_rows": int(np.isposinf(upper).sum()),
        "interval_negative_log_likelihood": float(interval_nll(median, lower, upper, scale).mean()),
        "concordance": comparable_concordance(median, lower, upper, groups),
        "resolved_3yr_rows": int(resolved.sum()), "unresolved_3yr_rows": int((~resolved).sum()),
        "known_3yr_closures": int((known == 0).sum()), "known_3yr_survivors": int((known == 1).sum()),
        "resolved_subset_brier_3yr": float(np.mean((survival[resolved] - known[resolved]) ** 2)) if resolved.any() else None,
        "calibration_scope": "Resolved subset only; not IPCW or population calibration. Interval-censored and unresolved outcomes require further methodology.",
        "calibration_bins": []}
    bins = np.minimum((survival * 5).astype(int), 4)
    for index in range(5):
        mask = resolved & (bins == index)
        if mask.any():
            result["calibration_bins"].append({"bin": index, "rows": int(mask.sum()),
                "mean_prediction": float(survival[mask].mean()), "observed_survival": float(known[mask].mean())})
    return result


def paired_concordance_delta(reference, candidate, lower, upper, groups, bootstrap=200, seed=440):
    """Matched-model difference using identical pairs and NTA resamples."""
    reference, candidate, lower, upper = map(lambda a: np.asarray(a, float), (reference, candidate, lower, upper))
    if not (reference.shape == candidate.shape == lower.shape == upper.shape) or reference.ndim != 1:
        raise ValueError("Align prediction and outcome rows before paired comparison")
    if len(groups) != len(reference) or not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        raise ValueError("Finite aligned model predictions and groups required")
    rng = np.random.default_rng(seed)
    if len(reference) <= 800:
        i, j = np.indices((len(reference), len(reference))).reshape(2, -1)
    else:
        i, j = rng.integers(0, len(reference), (2, 300000))
    valid = (i != j) & np.isfinite(upper[i]) & (upper[i] < lower[j])
    i, j = i[valid], j[valid]
    def credit(values):
        return (values[i] < values[j]).astype(float) + .5 * (values[i] == values[j])
    difference = credit(candidate) - credit(reference)
    result = {"candidate_minus_reference": float(difference.mean()) if len(difference) else None,
        "comparable_pairs": len(difference), "paired_nta_bootstrap_95_ci": None,
        "scope": "Conditional on fitted models and proxy labels; not training uncertainty or verified survival improvement"}
    labels, codes = np.unique(np.asarray(groups, str), return_inverse=True)
    if not len(difference) or len(labels) < 2:
        return result
    estimates = []
    for _ in range(bootstrap):
        counts = np.bincount(rng.integers(0, len(labels), len(labels)), minlength=len(labels))
        weight = counts[codes[i]] * counts[codes[j]]
        if weight.sum():
            estimates.append(float(np.average(difference, weights=weight)))
    if len(estimates) >= 20:
        result["paired_nta_bootstrap_95_ci"] = np.quantile(estimates, [.025, .975]).tolist()
    return result
