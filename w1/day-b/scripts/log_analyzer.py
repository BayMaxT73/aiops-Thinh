#!/usr/bin/env python3
"""Parse logs with Drain3 and report recent spikes and new templates."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

import pandas as pd

try:
    from drain3.drain import Drain
except ImportError:
    print("Error: drain3 not installed. Install with: pip install drain3", file=sys.stderr)
    raise SystemExit(1)


def normalize_result(result):
    if isinstance(result, tuple):
        cluster, change_type = result
        return cluster.cluster_id, cluster.get_template(), change_type
    return result.cluster_id, result.get_template(), None


class LogAnalyzer:
    def __init__(self, sim_th: float = 0.5) -> None:
        self.sim_th = sim_th
        self.drain = Drain(sim_th=sim_th, max_children=100, max_clusters=None)
        self.logs: list[str] = []
        self.df = pd.DataFrame()
        self.template_map: dict[int, str] = {}

    def load_logs(self, filepath: str) -> int:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
            self.logs = [line.strip() for line in handle if line.strip()]
        return len(self.logs)

    def parse_logs(self) -> pd.DataFrame:
        parsed = []
        for idx, log in enumerate(self.logs):
            cluster_id, template, change_type = normalize_result(self.drain.add_log_message(log))
            parsed.append(
                {
                    "log_id": idx,
                    "original_log": log,
                    "template_id": int(cluster_id),
                    "template": template,
                    "change_type": change_type,
                    "timestamp": self.extract_timestamp(log),
                }
            )

        self.df = pd.DataFrame(parsed)
        self.template_map = {int(cluster.cluster_id): cluster.get_template() for cluster in self.drain.clusters}
        return self.df

    @staticmethod
    def extract_timestamp(log_line: str):
        parts = log_line.split()
        if len(parts) >= 5:
            bgl_ts = parts[4]
            try:
                return pd.to_datetime(bgl_ts, format="%Y-%m-%d-%H.%M.%S.%f", errors="raise")
            except (ValueError, TypeError):
                pass

        if len(parts) >= 2:
            try:
                return pd.to_datetime(f"{parts[0]} {parts[1]}", format="%y%m%d %H%M%S", errors="raise")
            except (ValueError, TypeError):
                pass
            try:
                return pd.to_datetime(f"{parts[0]} {parts[1]}", format="%Y-%m-%d %H:%M:%S", errors="raise")
            except (ValueError, TypeError):
                pass

        return pd.NaT

    def template_counts(self) -> pd.DataFrame:
        if self.df.empty:
            return pd.DataFrame(columns=["template_id", "template", "count", "percentage"])

        counts = self.df.groupby(["template_id"], as_index=False).size().rename(columns={"size": "count"})
        counts["template"] = counts["template_id"].map(self.template_map)
        counts = counts.sort_values(["count", "template_id"], ascending=[False, True])
        counts["percentage"] = counts["count"] / len(self.df) * 100
        return counts[["template_id", "template", "count", "percentage"]]

    def recent_window_report(self) -> tuple[pd.Timestamp | None, pd.DataFrame, pd.DataFrame]:
        valid = self.df.dropna(subset=["timestamp"]).copy()
        if valid.empty:
            return None, pd.DataFrame(), pd.DataFrame()

        last_ts = valid["timestamp"].max()
        last_hour_start = last_ts - timedelta(hours=1)
        recent = valid[valid["timestamp"] > last_hour_start].copy()
        history = valid[valid["timestamp"] <= last_hour_start].copy()

        recent_counts = recent.groupby(["template_id"], as_index=False).size().rename(columns={"size": "recent_count"})
        recent_counts["template"] = recent_counts["template_id"].map(self.template_map)

        if history.empty:
            spikes = recent_counts.copy()
            spikes["baseline_mean"] = 0.0
            spikes["baseline_std"] = 0.0
            spikes["ratio_vs_mean"] = float("inf")
            return last_hour_start, spikes.sort_values("recent_count", ascending=False), recent_counts

        history["hour_bucket"] = history["timestamp"].dt.floor("1h")
        hourly = (
            history.groupby(["hour_bucket", "template_id"], as_index=False)
            .size()
            .rename(columns={"size": "hourly_count"})
        )
        baseline = (
            hourly.groupby(["template_id"], as_index=False)["hourly_count"]
            .agg(["mean", "std"])
            .reset_index()
            .rename(columns={"mean": "baseline_mean", "std": "baseline_std"})
        )
        baseline["template"] = baseline["template_id"].map(self.template_map)
        baseline["baseline_std"] = baseline["baseline_std"].fillna(0.0)

        merged = recent_counts.merge(baseline, on=["template_id", "template"], how="left").fillna(
            {"baseline_mean": 0.0, "baseline_std": 0.0}
        )
        merged["ratio_vs_mean"] = merged.apply(
            lambda row: (row["recent_count"] / row["baseline_mean"]) if row["baseline_mean"] > 0 else float("inf"),
            axis=1,
        )

        spikes = merged[
            (merged["recent_count"] > merged["baseline_mean"] + 2 * merged["baseline_std"])
            | ((merged["baseline_std"] == 0) & (merged["baseline_mean"] > 0) & (merged["recent_count"] >= 2 * merged["baseline_mean"]))
            | ((merged["baseline_mean"] == 0) & (merged["recent_count"] > 0))
        ].copy()
        spikes = spikes.sort_values(["recent_count", "ratio_vs_mean"], ascending=[False, False])
        return last_hour_start, spikes, recent_counts

    def new_templates_last_hour(self) -> tuple[pd.Timestamp | None, pd.DataFrame]:
        valid = self.df.dropna(subset=["timestamp"]).copy()
        if valid.empty:
            return None, pd.DataFrame()

        last_ts = valid["timestamp"].max()
        last_hour_start = last_ts - timedelta(hours=1)
        recent = valid[valid["timestamp"] > last_hour_start]
        history = valid[valid["timestamp"] <= last_hour_start]

        history_ids = set(history["template_id"].unique())
        new_rows = recent.loc[~recent["template_id"].isin(history_ids), ["template_id"]].drop_duplicates().sort_values("template_id")
        new_rows["template"] = new_rows["template_id"].map(self.template_map)
        return last_hour_start, new_rows

    def print_report(self, filepath: str) -> None:
        self.load_logs(filepath)
        self.parse_logs()
        counts = self.template_counts()

        print("\n" + "=" * 70)
        print("LOG ANALYSIS REPORT")
        print("=" * 70)
        print(f"\nFile: {filepath}")
        print(f"Total lines: {len(self.logs):,}")
        print(f"Unique templates: {len(counts)}")
        if len(counts) > 0:
            print(f"Avg cluster size: {len(self.logs) / len(counts):.2f}")

        print("\nTOP 5 TEMPLATES")
        print("-" * 70)
        for rank, row in enumerate(counts.head(5).itertuples(index=False), 1):
            print(f"\n{rank}. Template {row.template_id}")
            print(f"   Count: {row.count:,} ({row.percentage:.2f}%)")
            print(f"   Pattern: {row.template[:100]}")

        last_hour_start, spikes, _ = self.recent_window_report()
        print("\nSPIKES IN THE LAST HOUR")
        print("-" * 70)
        if last_hour_start is None:
            print("No parseable timestamps found.")
        elif spikes.empty:
            print(f"No spike templates detected after {last_hour_start}.")
        else:
            print(f"Window start: {last_hour_start}")
            for row in spikes.head(10).itertuples(index=False):
                baseline = f"{row.baseline_mean:.2f}"
                ratio = "inf" if row.ratio_vs_mean == float("inf") else f"{row.ratio_vs_mean:.2f}x"
                print(
                    f"Template {row.template_id}: recent={row.recent_count}, baseline_mean={baseline}, "
                    f"baseline_std={row.baseline_std:.2f}, ratio={ratio}"
                )
                print(f"   {row.template[:100]}")

        new_start, new_templates = self.new_templates_last_hour()
        print("\nNEW TEMPLATES IN THE LAST HOUR")
        print("-" * 70)
        if new_start is None:
            print("No parseable timestamps found.")
        elif new_templates.empty:
            print(f"No new templates appeared after {new_start}.")
        else:
            print(f"Window start: {new_start}")
            for row in new_templates.itertuples(index=False):
                print(f"Template {row.template_id}: {row.template[:100]}")

        print("\n" + "=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze log files with Drain3 template extraction")
    parser.add_argument("logfile", help="Path to log file")
    parser.add_argument("--sim-th", type=float, default=0.5, help="Drain3 similarity threshold (default: 0.5)")
    args = parser.parse_args()

    if not os.path.exists(args.logfile):
        print(f"Error: Log file not found: {args.logfile}", file=sys.stderr)
        return 1

    analyzer = LogAnalyzer(sim_th=args.sim_th)
    analyzer.print_report(args.logfile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
