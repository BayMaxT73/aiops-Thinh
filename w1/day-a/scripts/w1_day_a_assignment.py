from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde, skew
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score

matplotlib.use("Agg")

DATASET_KEY = "realKnownCause/machine_temperature_system_failure.csv"
DATASET_PATH = Path("data") / DATASET_KEY
LABELS_PATH = Path("labels/combined_windows.json")
DEFAULT_OUTPUT_DIR = Path("deliverables/w1_day_a")


def load_dataset(path: Path = DATASET_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_ground_truth_windows(labels_path: Path = LABELS_PATH) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    labels = json.loads(labels_path.read_text())
    windows = []
    for start, end in labels[DATASET_KEY]:
        windows.append((pd.Timestamp(start), pd.Timestamp(end)))
    return windows


def build_ground_truth_mask(
    timestamps: pd.Series, windows: list[tuple[pd.Timestamp, pd.Timestamp]]
) -> np.ndarray:
    mask = np.zeros(len(timestamps), dtype=bool)
    for start, end in windows:
        mask |= ((timestamps >= start) & (timestamps <= end)).to_numpy()
    return mask


def autocorrelation(series: pd.Series, max_lag: int) -> np.ndarray:
    values = series.to_numpy(dtype=float)
    centered = values - values.mean()
    denominator = np.dot(centered, centered)
    acf_values = np.empty(max_lag + 1, dtype=float)
    acf_values[0] = 1.0
    for lag in range(1, max_lag + 1):
        acf_values[lag] = np.dot(centered[:-lag], centered[lag:]) / denominator
    return acf_values


def compute_eda(df: pd.DataFrame) -> dict[str, object]:
    series = df["value"]
    acf_lags = 576
    acf_values = autocorrelation(series, max_lag=acf_lags)
    top_acf_lags = sorted(
        ((lag, float(acf_values[lag])) for lag in range(1, len(acf_values))),
        key=lambda item: item[1],
        reverse=True,
    )[:8]
    granularity_minutes = float(
        (df["timestamp"].iloc[1] - df["timestamp"].iloc[0]).total_seconds() / 60.0
    )
    return {
        "rows": int(len(df)),
        "start": str(df["timestamp"].iloc[0]),
        "end": str(df["timestamp"].iloc[-1]),
        "granularity_minutes": granularity_minutes,
        "mean": float(series.mean()),
        "std": float(series.std()),
        "skewness": float(skew(series)),
        "min": float(series.min()),
        "max": float(series.max()),
        "daily_lag_points": int((24 * 60) / granularity_minutes),
        "top_acf_lags": top_acf_lags,
    }


def plot_eda(
    df: pd.DataFrame,
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    output_path: Path,
    max_acf_lag: int = 576,
) -> None:
    series = df["value"]
    timestamps = df["timestamp"]
    acf_values = autocorrelation(series, max_lag=max_acf_lag)
    density_x = np.linspace(series.min(), series.max(), 400)
    density = gaussian_kde(series)(density_x)

    fig, axes = plt.subplots(3, 1, figsize=(15, 14))

    axes[0].plot(timestamps, series, color="#1f77b4", linewidth=0.8)
    for idx, (start, end) in enumerate(windows):
        label = "Ground truth window" if idx == 0 else None
        axes[0].axvspan(start, end, color="#ff7f0e", alpha=0.2, label=label)
    axes[0].set_title("Raw Time Series With Ground Truth Windows")
    axes[0].set_ylabel("Temperature")
    axes[0].legend(loc="upper right")

    axes[1].hist(series, bins=60, density=True, alpha=0.7, color="#4c78a8", label="Histogram")
    axes[1].plot(density_x, density, color="#e45756", linewidth=2, label="Density")
    axes[1].set_title("Distribution of Metric Values")
    axes[1].set_xlabel("Value")
    axes[1].set_ylabel("Density")
    axes[1].legend(loc="upper left")

    axes[2].stem(
        range(max_acf_lag + 1),
        acf_values,
        linefmt="#54a24b",
        markerfmt=" ",
        basefmt=" ",
    )
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_title("Autocorrelation Function (Manual ACF)")
    axes[2].set_xlabel("Lag (5-minute steps)")
    axes[2].set_ylabel("Autocorrelation")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def rolling_iqr_detector(series: pd.Series, window: int, multiplier: float) -> np.ndarray:
    rolling = series.rolling(window=window, min_periods=max(24, window // 2))
    q1 = rolling.quantile(0.25).shift(1)
    q3 = rolling.quantile(0.75).shift(1)
    iqr = (q3 - q1).replace(0, 1e-10)
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    predictions = ((series < lower) | (series > upper)).fillna(False)
    return predictions.to_numpy(dtype=bool)


def apply_cooldown(predictions: np.ndarray, cooldown: int) -> np.ndarray:
    if cooldown <= 0:
        return predictions.copy()
    expanded = predictions.copy()
    anomaly_indices = np.flatnonzero(predictions)
    for index in anomaly_indices:
        expanded[index : min(len(expanded), index + cooldown + 1)] = True
    return expanded


def build_if_features(df: pd.DataFrame) -> pd.DataFrame:
    series = df["value"]
    timestamps = df["timestamp"]
    features = pd.DataFrame(index=df.index)
    features["value"] = series
    features["rolling_mean_1h"] = series.rolling(12).mean()
    features["rolling_std_1h"] = series.rolling(12).std()
    features["rolling_mean_6h"] = series.rolling(72).mean()
    features["rolling_std_6h"] = series.rolling(72).std()
    features["rate_of_change_1"] = series.diff()
    features["rate_of_change_12"] = series.diff(12)
    features["lag_1"] = series.shift(1)
    features["lag_12"] = series.shift(12)
    features["hour"] = timestamps.dt.hour
    features["day_of_week"] = timestamps.dt.dayofweek
    features["ema_ratio_1h"] = series / series.ewm(span=12, adjust=False).mean()
    return features.replace([np.inf, -np.inf], np.nan)


def isolation_forest_detector(
    df: pd.DataFrame,
    contamination: float,
    n_estimators: int = 200,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray, IsolationForest, list[str]]:
    features = build_if_features(df)
    clean_features = features.dropna()
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
    )
    model.fit(clean_features)
    labels = model.predict(clean_features) == -1
    raw_scores = -model.decision_function(clean_features)

    full_predictions = np.zeros(len(df), dtype=bool)
    full_scores = np.full(len(df), np.nan)
    full_predictions[clean_features.index] = labels
    full_scores[clean_features.index] = raw_scores
    return full_predictions, full_scores, model, list(clean_features.columns)


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | int]:
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    false_alarms = int(np.sum((~y_true) & y_pred))
    true_positives = int(np.sum(y_true & y_pred))
    false_negatives = int(np.sum(y_true & (~y_pred)))
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_alarms": false_alarms,
        "true_positives": true_positives,
        "false_negatives": false_negatives,
        "predicted_anomalies": int(np.sum(y_pred)),
    }


def tune_statistical_detector(df: pd.DataFrame, y_true: np.ndarray) -> pd.DataFrame:
    configs = [
        {"window": 144, "multiplier": 1.5},
        {"window": 288, "multiplier": 1.5},
        {"window": 288, "multiplier": 2.0},
        {"window": 576, "multiplier": 1.5},
    ]
    cooldowns = [0, 12, 24, 48, 96]
    rows = []
    for config in configs:
        base_predictions = rolling_iqr_detector(df["value"], **config)
        for cooldown in cooldowns:
            y_pred = apply_cooldown(base_predictions, cooldown)
            metrics = classification_metrics(y_true, y_pred)
            rows.append({"detector": "rolling_iqr", **config, "cooldown": cooldown, **metrics})
    return pd.DataFrame(rows).sort_values(["f1", "recall", "precision"], ascending=False)


def tune_isolation_forest(df: pd.DataFrame, y_true: np.ndarray) -> pd.DataFrame:
    contamination_values = [0.01, 0.02, 0.05]
    cooldowns = [0, 12, 24, 48, 96]
    rows = []
    for contamination in contamination_values:
        base_predictions, _, _, _ = isolation_forest_detector(df, contamination=contamination)
        for cooldown in cooldowns:
            y_pred = apply_cooldown(base_predictions, cooldown)
            metrics = classification_metrics(y_true, y_pred)
            rows.append(
                {
                    "detector": "isolation_forest",
                    "contamination": contamination,
                    "cooldown": cooldown,
                    **metrics,
                }
            )
    return pd.DataFrame(rows).sort_values(["f1", "recall", "precision"], ascending=False)


def plot_detector_comparison(
    df: pd.DataFrame,
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    detector_outputs: list[dict[str, object]],
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(len(detector_outputs), 1, figsize=(15, 10), sharex=True)
    if len(detector_outputs) == 1:
        axes = [axes]

    timestamps = df["timestamp"]
    values = df["value"]

    for axis, detector_output in zip(axes, detector_outputs):
        predictions = detector_output["predictions"]
        metrics = detector_output["metrics"]
        axis.plot(timestamps, values, color="#4c78a8", linewidth=0.8)
        for idx, (start, end) in enumerate(windows):
            label = "Ground truth window" if idx == 0 else None
            axis.axvspan(start, end, color="#ff7f0e", alpha=0.15, label=label)
        anomaly_idx = np.flatnonzero(predictions)
        axis.scatter(
            timestamps.iloc[anomaly_idx],
            values.iloc[anomaly_idx],
            color="#d62728",
            s=14,
            label="Predicted anomaly",
            zorder=5,
        )
        axis.set_title(
            f"{detector_output['name']} | "
            f"P={metrics['precision']:.3f}, R={metrics['recall']:.3f}, "
            f"F1={metrics['f1']:.3f}, FP={metrics['false_alarms']}"
        )
        axis.set_ylabel("Value")
        axis.legend(loc="upper right")

    axes[-1].set_xlabel("Timestamp")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_predictions(
    df: pd.DataFrame,
    y_true: np.ndarray,
    detector_name: str,
    predictions: np.ndarray,
    scores: np.ndarray | None,
    output_dir: Path,
) -> Path:
    result = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "value": df["value"],
            "ground_truth": y_true.astype(int),
            "prediction": predictions.astype(int),
        }
    )
    if scores is not None:
        result["score"] = scores
    path = output_dir / f"{detector_name}_predictions.csv"
    result.to_csv(path, index=False)
    return path


def choose_best_row(frame: pd.DataFrame) -> pd.Series:
    return frame.sort_values(["f1", "recall", "precision"], ascending=False).iloc[0]


def analyze_dataset(output_dir: Path = DEFAULT_OUTPUT_DIR, write_outputs: bool = True) -> dict[str, object]:
    output_dir = Path(output_dir)
    plots_dir = output_dir / "plots"
    metrics_dir = output_dir / "metrics"
    models_dir = output_dir / "models"

    if write_outputs:
        plots_dir.mkdir(parents=True, exist_ok=True)
        metrics_dir.mkdir(parents=True, exist_ok=True)
        models_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataset()
    windows = load_ground_truth_windows()
    y_true = build_ground_truth_mask(df["timestamp"], windows)

    eda = compute_eda(df)
    statistical_tuning = tune_statistical_detector(df, y_true)
    if_tuning = tune_isolation_forest(df, y_true)

    best_stat = choose_best_row(statistical_tuning)
    stat_predictions = rolling_iqr_detector(
        df["value"],
        window=int(best_stat["window"]),
        multiplier=float(best_stat["multiplier"]),
    )
    stat_predictions = apply_cooldown(stat_predictions, cooldown=int(best_stat["cooldown"]))
    stat_metrics = classification_metrics(y_true, stat_predictions)

    best_if = choose_best_row(if_tuning)
    if_predictions, if_scores, if_model, if_features = isolation_forest_detector(
        df, contamination=float(best_if["contamination"])
    )
    if_predictions = apply_cooldown(if_predictions, cooldown=int(best_if["cooldown"]))
    if_metrics = classification_metrics(y_true, if_predictions)

    results = {
        "dataset_key": DATASET_KEY,
        "eda": eda,
        "ground_truth_windows": [(str(start), str(end)) for start, end in windows],
        "best_statistical": {
            "name": "Rolling IQR",
            "params": {
                "window": int(best_stat["window"]),
                "multiplier": float(best_stat["multiplier"]),
                "cooldown": int(best_stat["cooldown"]),
            },
            "metrics": stat_metrics,
        },
        "best_isolation_forest": {
            "name": "Isolation Forest",
            "params": {
                "contamination": float(best_if["contamination"]),
                "cooldown": int(best_if["cooldown"]),
            },
            "metrics": if_metrics,
            "features": if_features,
        },
        "tuning": {
            "rolling_iqr": statistical_tuning.to_dict(orient="records"),
            "isolation_forest": if_tuning.to_dict(orient="records"),
        },
    }

    if write_outputs:
        plot_eda(df, windows, plots_dir / "eda_overview.png")
        plot_detector_comparison(
            df,
            windows,
            [
                {"name": "Rolling IQR", "predictions": stat_predictions, "metrics": stat_metrics},
                {
                    "name": "Isolation Forest",
                    "predictions": if_predictions,
                    "metrics": if_metrics,
                },
            ],
            plots_dir / "detector_comparison.png",
        )

        statistical_tuning.to_csv(metrics_dir / "rolling_iqr_tuning.csv", index=False)
        if_tuning.to_csv(metrics_dir / "isolation_forest_tuning.csv", index=False)
        comparison = pd.DataFrame(
            [
                {"detector": "Rolling IQR", **stat_metrics},
                {"detector": "Isolation Forest", **if_metrics},
            ]
        )
        comparison.to_csv(metrics_dir / "comparison_summary.csv", index=False)

        save_predictions(
            df,
            y_true,
            "rolling_iqr",
            stat_predictions,
            scores=None,
            output_dir=metrics_dir,
        )
        save_predictions(
            df,
            y_true,
            "isolation_forest",
            if_predictions,
            scores=if_scores,
            output_dir=metrics_dir,
        )

        joblib.dump(if_model, models_dir / "isolation_forest.joblib", compress=3)
        (output_dir / "analysis_summary.json").write_text(json.dumps(results, indent=2))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run W1-D1 metric anomaly detection assignment pipeline.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where plots, metrics, and model artifacts will be written.",
    )
    args = parser.parse_args()
    results = analyze_dataset(output_dir=args.output_dir, write_outputs=True)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
