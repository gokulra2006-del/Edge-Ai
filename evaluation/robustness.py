"""Environmental robustness and subgroup fairness evaluation framework (Phase 6H).

Evaluates system performance across 8 operational condition axes:
1. Time of Day (day / night)
2. Weather (clear / rain / fog)
3. Camera Angle (overhead / street_level / oblique)
4. Traffic Density (low / medium / high)
5. Microphone Placement (pole_mounted / curbside / enclosed)
6. Road Surface (asphalt / wet_concrete / gravel)
7. Acoustic Zone (quiet_suburb / noisy_intersection / commercial)
8. Hardware Node (rpi4_node1 / jetson_node2 / edge_server)

Features:
- Sample adequacy gate: flags N < min_samples as INSUFFICIENT_DATA.
- Non-parametric bootstrap confidence intervals (95% CI) for Macro-F1, FAR, and Miss Rate.
- Expected Calibration Error (ECE) and Brier Score accounting.
- Honest data labeling (SYNTHETIC, REPLAYED_REAL, REAL_HARDWARE) and real-data disclosure.
- Subgroup disparity / fairness gap analysis (best vs worst).
- Publication-quality JSON, CSV, and HTML reporting.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from evaluation.metrics import (
    ClassificationMetrics,
    compute_bootstrap_far_ci,
    compute_bootstrap_macro_f1_ci,
    compute_bootstrap_miss_ci,
    compute_classification_metrics,
)
from evaluation.scenarios import (
    DataTag,
    EnvironmentalConditions,
    EventClass,
    Scenario,
    ScenarioGenerator,
)
from evaluation.systems import (
    ALL_SYSTEMS,
    BaseSystemUnderTest,
    TemporalOodFusionSystem,
)
from src.modules.calibration.calibration_engine import compute_calibration_metrics


DIMENSIONS = [
    "time_of_day",
    "weather",
    "camera_angle",
    "traffic_density",
    "microphone_placement",
    "road_surface",
    "acoustic_zone",
    "hardware_node",
]

# Real hardware data / replayed real benchmark conditions currently deployed
REAL_DATA_CONDITIONS: Dict[str, Set[str]] = {
    "time_of_day": {"day"},
    "weather": {"clear"},
    "camera_angle": {"overhead"},
    "traffic_density": {"medium"},
    "microphone_placement": {"pole_mounted"},
    "road_surface": {"asphalt"},
    "acoustic_zone": {"quiet_suburb", "commercial"},
    "hardware_node": {"rpi4_node1"},
}


def get_git_hash() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN_GIT_HASH"


def compute_config_hash(config_dict: Dict[str, Any]) -> str:
    serialized = json.dumps(config_dict, sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()[:16]


@dataclass
class ConditionEvaluationResult:
    dimension: str
    condition_value: str
    sample_count: int
    status: Literal["VALID", "INSUFFICIENT_DATA"]
    data_tag: DataTag
    has_real_data: bool
    macro_f1: Optional[float] = None
    ci_macro_f1: Optional[Tuple[float, float]] = None
    false_alarm_rate_pct: Optional[float] = None
    ci_far: Optional[Tuple[float, float]] = None
    miss_rate_pct: Optional[float] = None
    ci_miss: Optional[Tuple[float, float]] = None
    ece: Optional[float] = None
    brier_score: Optional[float] = None
    accuracy_pct: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DimensionDisparitySummary:
    dimension: str
    best_condition: Optional[str]
    worst_condition: Optional[str]
    best_macro_f1: Optional[float]
    worst_macro_f1: Optional[float]
    disparity_gap_f1: Optional[float]
    disparity_gap_far: Optional[float]
    disparity_gap_miss: Optional[float]
    insufficient_data_subgroups: List[str] = field(default_factory=list)
    vulnerability_finding: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RobustnessSuiteResult:
    eval_id: str
    timestamp: str
    git_hash: str
    seed: int
    config_hash: str
    min_samples_threshold: int
    system_name: str
    total_evaluated_scenarios: int
    total_evaluated_steps: int
    condition_results: List[ConditionEvaluationResult]
    dimension_disparities: Dict[str, DimensionDisparitySummary]
    real_data_disclosure: Dict[str, Any]
    nominal_baseline_metrics: Dict[str, Any]
    hypothesis_confirmed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RobustnessEvaluator:
    """
    Evaluates environmental robustness and subgroup performance fairness across 8 axes.
    """

    def __init__(
        self,
        min_samples: int = 10,
        bootstrap_rounds: int = 500,
        seed: int = 42,
    ):
        self.min_samples = min_samples
        self.bootstrap_rounds = bootstrap_rounds
        self.seed = seed

    def evaluate(
        self,
        system: BaseSystemUnderTest,
        scenarios: List[Scenario],
        eval_id: str = "robustness_eval",
    ) -> RobustnessSuiteResult:
        step_records: List[Dict[str, Any]] = []

        # 1. Execute system across all scenarios step-by-step
        for sc in scenarios:
            system.reset()
            cond_dict = sc.conditions.to_dict()

            for step in sc.steps:
                inf = system.process_step(step)
                # Compute accuracy indicator (1 if correct class, 0 otherwise)
                is_correct = 1 if inf.predicted_class == step.ground_truth else 0

                step_records.append({
                    "scenario_id": sc.scenario_id,
                    "ground_truth": step.ground_truth,
                    "predicted_class": inf.predicted_class,
                    "confidence": float(inf.confidence),
                    "is_correct": is_correct,
                    "data_tag": sc.data_tag,
                    "conditions": cond_dict,
                })

        # 2. Compute nominal baseline (all scenarios combined as unstratified baseline)
        all_true = [r["ground_truth"] for r in step_records]
        all_pred = [r["predicted_class"] for r in step_records]
        all_confs = [r["confidence"] for r in step_records]
        all_accs = [r["is_correct"] for r in step_records]

        nominal_cls = compute_classification_metrics(all_true, all_pred, bootstrap_rounds=self.bootstrap_rounds, seed=self.seed)
        nominal_cal = compute_calibration_metrics(all_confs, all_accs)
        nominal_baseline = {
            "macro_f1": nominal_cls.macro_f1,
            "false_alarm_rate_pct": nominal_cls.false_alarm_rate_pct,
            "miss_rate_pct": nominal_cls.miss_rate_pct,
            "ece": nominal_cal.ece,
            "brier_score": nominal_cal.brier_score,
            "total_samples": len(step_records),
        }

        # 3. Evaluate each dimension and condition value
        condition_results: List[ConditionEvaluationResult] = []

        for dim in DIMENSIONS:
            # Collect unique condition values present in suite
            unique_vals = sorted({r["conditions"].get(dim, "default") for r in step_records})

            for val in unique_vals:
                subset = [r for r in step_records if r["conditions"].get(dim) == val]
                n = len(subset)

                # Determine data tags present in this subgroup
                tags = {r["data_tag"] for r in subset}
                if "REAL_HARDWARE" in tags:
                    primary_tag: DataTag = "REAL_HARDWARE"
                elif "REPLAYED_REAL" in tags:
                    primary_tag = "REPLAYED_REAL"
                else:
                    primary_tag = "SYNTHETIC"

                has_real = val in REAL_DATA_CONDITIONS.get(dim, set()) or any(t != "SYNTHETIC" for t in tags)

                if n < self.min_samples:
                    condition_results.append(
                        ConditionEvaluationResult(
                            dimension=dim,
                            condition_value=val,
                            sample_count=n,
                            status="INSUFFICIENT_DATA",
                            data_tag=primary_tag,
                            has_real_data=has_real,
                            notes=f"INSUFFICIENT_DATA: Sample count N={n} < threshold {self.min_samples}; metrics omitted to prevent unrepresentative estimates.",
                        )
                    )
                else:
                    sub_true = [r["ground_truth"] for r in subset]
                    sub_pred = [r["predicted_class"] for r in subset]
                    sub_confs = [r["confidence"] for r in subset]
                    sub_accs = [r["is_correct"] for r in subset]

                    cls_metrics = compute_classification_metrics(
                        sub_true, sub_pred, bootstrap_rounds=self.bootstrap_rounds, seed=self.seed
                    )
                    far_ci = compute_bootstrap_far_ci(
                        sub_true, sub_pred, rounds=self.bootstrap_rounds, seed=self.seed
                    )
                    miss_ci = compute_bootstrap_miss_ci(
                        sub_true, sub_pred, rounds=self.bootstrap_rounds, seed=self.seed
                    )
                    cal_metrics = compute_calibration_metrics(sub_confs, sub_accs)

                    condition_results.append(
                        ConditionEvaluationResult(
                            dimension=dim,
                            condition_value=val,
                            sample_count=n,
                            status="VALID",
                            data_tag=primary_tag,
                            has_real_data=has_real,
                            macro_f1=cls_metrics.macro_f1,
                            ci_macro_f1=cls_metrics.bootstrap_ci_macro_f1,
                            false_alarm_rate_pct=cls_metrics.false_alarm_rate_pct,
                            ci_far=far_ci,
                            miss_rate_pct=cls_metrics.miss_rate_pct,
                            ci_miss=miss_ci,
                            ece=round(cal_metrics.ece, 4),
                            brier_score=round(cal_metrics.brier_score, 4),
                            accuracy_pct=cls_metrics.accuracy_pct,
                        )
                    )

        # 4. Disparity & Fairness Gap Analysis per Dimension
        dimension_disparities: Dict[str, DimensionDisparitySummary] = {}
        divergence_detected = False

        for dim in DIMENSIONS:
            dim_results = [r for r in condition_results if r.dimension == dim]
            valid_results = [r for r in dim_results if r.status == "VALID" and r.macro_f1 is not None]
            insufficient = [r.condition_value for r in dim_results if r.status == "INSUFFICIENT_DATA"]

            if not valid_results:
                dimension_disparities[dim] = DimensionDisparitySummary(
                    dimension=dim,
                    best_condition=None,
                    worst_condition=None,
                    best_macro_f1=None,
                    worst_macro_f1=None,
                    disparity_gap_f1=None,
                    disparity_gap_far=None,
                    disparity_gap_miss=None,
                    insufficient_data_subgroups=insufficient,
                    vulnerability_finding="All subgroups under this dimension have insufficient sample data.",
                )
                continue

            best_r = max(valid_results, key=lambda r: r.macro_f1 or 0.0)
            worst_r = min(valid_results, key=lambda r: r.macro_f1 or 0.0)

            f1_gap = round((best_r.macro_f1 or 0.0) - (worst_r.macro_f1 or 0.0), 4)
            far_vals = [r.false_alarm_rate_pct for r in valid_results if r.false_alarm_rate_pct is not None]
            miss_vals = [r.miss_rate_pct for r in valid_results if r.miss_rate_pct is not None]

            far_gap = round(max(far_vals) - min(far_vals), 2) if far_vals else 0.0
            miss_gap = round(max(miss_vals) - min(miss_vals), 2) if miss_vals else 0.0

            if f1_gap >= 0.05:
                divergence_detected = True

            vulnerability = (
                f"Performance disparity of {f1_gap * 100.0:.1f}% Macro-F1 detected: "
                f"best '{best_r.condition_value}' ({best_r.macro_f1:.3f}) vs "
                f"worst '{worst_r.condition_value}' ({worst_r.macro_f1:.3f}). "
                f"Miss rate gap: {miss_gap:.1f}%."
            )

            dimension_disparities[dim] = DimensionDisparitySummary(
                dimension=dim,
                best_condition=best_r.condition_value,
                worst_condition=worst_r.condition_value,
                best_macro_f1=best_r.macro_f1,
                worst_macro_f1=worst_r.macro_f1,
                disparity_gap_f1=f1_gap,
                disparity_gap_far=far_gap,
                disparity_gap_miss=miss_gap,
                insufficient_data_subgroups=insufficient,
                vulnerability_finding=vulnerability,
            )

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        git_hash = get_git_hash()
        cfg_hash = compute_config_hash({
            "min_samples": self.min_samples,
            "seed": self.seed,
            "system": system.name,
            "total_scenarios": len(scenarios),
        })

        real_data_disclosure = {
            "real_hardware_deployed_conditions": {k: list(v) for k, v in REAL_DATA_CONDITIONS.items()},
            "disclosure_text": (
                "Real hardware edge data is currently verified on Raspberry Pi 4 (rpi4_node1) "
                "under day, clear, overhead camera, asphalt road surface, and quiet/commercial zones. "
                "Adverse and rare conditions (such as heavy fog, night precipitation, and gravel surfaces) "
                "are synthetically perturbed to quantify resilience bounds."
            ),
        }

        return RobustnessSuiteResult(
            eval_id=eval_id,
            timestamp=now,
            git_hash=git_hash,
            seed=self.seed,
            config_hash=cfg_hash,
            min_samples_threshold=self.min_samples,
            system_name=system.name,
            total_evaluated_scenarios=len(scenarios),
            total_evaluated_steps=len(step_records),
            condition_results=condition_results,
            dimension_disparities=dimension_disparities,
            real_data_disclosure=real_data_disclosure,
            nominal_baseline_metrics=nominal_baseline,
            hypothesis_confirmed=divergence_detected,
        )

    def export_json(self, result: RobustnessSuiteResult, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, sort_keys=True)
        return output_path

    def export_csv(self, result: RobustnessSuiteResult, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "dimension",
            "condition_value",
            "status",
            "data_tag",
            "has_real_data",
            "sample_count",
            "macro_f1",
            "ci_f1_low",
            "ci_f1_high",
            "far_pct",
            "ci_far_low",
            "ci_far_high",
            "miss_rate_pct",
            "ci_miss_low",
            "ci_miss_high",
            "ece",
            "brier_score",
            "notes",
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in result.condition_results:
                f1_ci = r.ci_macro_f1 or (None, None)
                far_ci = r.ci_far or (None, None)
                miss_ci = r.ci_miss or (None, None)

                writer.writerow({
                    "dimension": r.dimension,
                    "condition_value": r.condition_value,
                    "status": r.status,
                    "data_tag": r.data_tag,
                    "has_real_data": r.has_real_data,
                    "sample_count": r.sample_count,
                    "macro_f1": f"{r.macro_f1:.4f}" if r.macro_f1 is not None else "INSUFFICIENT_DATA",
                    "ci_f1_low": f"{f1_ci[0]:.4f}" if f1_ci[0] is not None else "",
                    "ci_f1_high": f"{f1_ci[1]:.4f}" if f1_ci[1] is not None else "",
                    "far_pct": f"{r.false_alarm_rate_pct:.2f}" if r.false_alarm_rate_pct is not None else "INSUFFICIENT_DATA",
                    "ci_far_low": f"{far_ci[0]:.2f}" if far_ci[0] is not None else "",
                    "ci_far_high": f"{far_ci[1]:.2f}" if far_ci[1] is not None else "",
                    "miss_rate_pct": f"{r.miss_rate_pct:.2f}" if r.miss_rate_pct is not None else "INSUFFICIENT_DATA",
                    "ci_miss_low": f"{miss_ci[0]:.2f}" if miss_ci[0] is not None else "",
                    "ci_miss_high": f"{miss_ci[1]:.2f}" if miss_ci[1] is not None else "",
                    "ece": f"{r.ece:.4f}" if r.ece is not None else "",
                    "brier_score": f"{r.brier_score:.4f}" if r.brier_score is not None else "",
                    "notes": r.notes,
                })
        return output_path

    def export_html(self, result: RobustnessSuiteResult, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        rows_html = []
        for r in result.condition_results:
            is_valid = r.status == "VALID"
            badge_class = "badge-valid" if is_valid else "badge-insufficient"
            tag_class = "tag-real" if r.data_tag == "REAL_HARDWARE" else ("tag-replayed" if r.data_tag == "REPLAYED_REAL" else "tag-synth")

            f1_str = f"<b>{r.macro_f1:.3f}</b>" if r.macro_f1 is not None else "<span class='text-muted'>INSUFFICIENT_DATA</span>"
            ci_f1_str = f"[{r.ci_macro_f1[0]:.3f}, {r.ci_macro_f1[1]:.3f}]" if r.ci_macro_f1 else "—"
            far_str = f"{r.false_alarm_rate_pct:.1f}%" if r.false_alarm_rate_pct is not None else "—"
            miss_str = f"{r.miss_rate_pct:.1f}%" if r.miss_rate_pct is not None else "—"
            ece_str = f"{r.ece:.3f}" if r.ece is not None else "—"
            brier_str = f"{r.brier_score:.3f}" if r.brier_score is not None else "—"

            row = f"""
            <tr>
              <td><code>{r.dimension}</code></td>
              <td><strong>{r.condition_value}</strong></td>
              <td><span class="badge {badge_class}">{r.status}</span></td>
              <td><span class="tag {tag_class}">{r.data_tag}</span></td>
              <td class="text-center">{r.sample_count}</td>
              <td class="text-right">{f1_str}</td>
              <td class="text-center text-small">{ci_f1_str}</td>
              <td class="text-right">{far_str}</td>
              <td class="text-right">{miss_str}</td>
              <td class="text-right">{ece_str}</td>
              <td class="text-right">{brier_str}</td>
            </tr>
            """
            rows_html.append(row)

        disparity_cards = []
        for dim, disp in result.dimension_disparities.items():
            gap_str = f"{disp.disparity_gap_f1 * 100:.1f}%" if disp.disparity_gap_f1 is not None else "N/A"
            card = f"""
            <div class="card">
              <div class="card-header">
                <h3>{dim.replace('_', ' ').title()}</h3>
                <span class="gap-pill">F1 Gap: {gap_str}</span>
              </div>
              <div class="card-body">
                <p><strong>Best:</strong> {disp.best_condition or 'None'} ({disp.best_macro_f1 if disp.best_macro_f1 is not None else '—'})</p>
                <p><strong>Worst:</strong> {disp.worst_condition or 'None'} ({disp.worst_macro_f1 if disp.worst_macro_f1 is not None else '—'})</p>
                <p class="text-muted text-small">{disp.vulnerability_finding}</p>
                {f'<p class="text-warning text-small">Low-sample subgroups: {", ".join(disp.insufficient_data_subgroups)}</p>' if disp.insufficient_data_subgroups else ''}
              </div>
            </div>
            """
            disparity_cards.append(card)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sentinel-AI Environmental Robustness & Subgroup Fairness Report</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.5;
      color: #1a202c;
      background: #f7fafc;
      margin: 0;
      padding: 24px;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
      background: #ffffff;
      padding: 32px;
      border-radius: 8px;
      box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }}
    header {{
      border-bottom: 2px solid #edf2f7;
      padding-bottom: 20px;
      margin-bottom: 24px;
    }}
    h1 {{ margin: 0 0 8px 0; color: #2d3748; font-size: 24px; }}
    .meta-bar {{ color: #718096; font-size: 13px; display: flex; gap: 20px; flex-wrap: wrap; }}
    .disclosure-box {{
      background: #ebf8ff;
      border-left: 4px solid #3182ce;
      padding: 12px 16px;
      margin: 20px 0;
      font-size: 14px;
      color: #2b6cb0;
      border-radius: 4px;
    }}
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .card {{
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #ffffff;
      overflow: hidden;
    }}
    .card-header {{
      background: #f8fafc;
      padding: 10px 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid #e2e8f0;
    }}
    .card-header h3 {{ margin: 0; font-size: 14px; color: #4a5568; }}
    .gap-pill {{
      background: #fed7d7;
      color: #9b2c2c;
      font-size: 11px;
      font-weight: bold;
      padding: 2px 8px;
      border-radius: 12px;
    }}
    .card-body {{ padding: 12px 14px; font-size: 13px; }}
    .card-body p {{ margin: 4px 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 16px;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid #e2e8f0;
      text-align: left;
    }}
    th {{
      background: #f7fafc;
      color: #4a5568;
      font-weight: 600;
    }}
    .text-center {{ text-align: center; }}
    .text-right {{ text-align: right; }}
    .text-small {{ font-size: 11px; }}
    .text-muted {{ color: #a0aec0; }}
    .text-warning {{ color: #dd6b20; }}
    .badge {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
    }}
    .badge-valid {{ background: #c6f6d5; color: #22543d; }}
    .badge-insufficient {{ background: #feebc8; color: #7b341e; }}
    .tag {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .tag-real {{ background: #bee3f8; color: #2a4365; }}
    .tag-replayed {{ background: #e9d8fd; color: #44337a; }}
    .tag-synth {{ background: #edf2f7; color: #4a5568; }}
    footer {{
      margin-top: 40px;
      padding-top: 16px;
      border-top: 1px solid #edf2f7;
      color: #a0aec0;
      font-size: 12px;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Environmental Robustness & Subgroup Fairness Evaluation</h1>
      <div class="meta-bar">
        <span><strong>System:</strong> {result.system_name}</span>
        <span><strong>Git:</strong> {result.git_hash[:8]}</span>
        <span><strong>Config Hash:</strong> {result.config_hash}</span>
        <span><strong>Total Scenarios:</strong> {result.total_evaluated_scenarios}</span>
        <span><strong>Total Steps:</strong> {result.total_evaluated_steps}</span>
        <span><strong>Seed:</strong> {result.seed}</span>
        <span><strong>Sample Gate:</strong> N &ge; {result.min_samples_threshold}</span>
      </div>
    </header>

    <div class="disclosure-box">
      <strong>Data Origin & Provenance Disclosure:</strong>
      <p style="margin: 4px 0 0 0;">{result.real_data_disclosure["disclosure_text"]}</p>
    </div>

    <h2>Subgroup Disparities & Fairness Gaps</h2>
    <div class="cards-grid">
      {''.join(disparity_cards)}
    </div>

    <h2>Detailed Per-Condition Performance Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Dimension</th>
          <th>Condition</th>
          <th>Status</th>
          <th>Data Origin</th>
          <th class="text-center">N</th>
          <th class="text-right">Macro-F1</th>
          <th class="text-center">95% Bootstrap CI</th>
          <th class="text-right">FAR (%)</th>
          <th class="text-right">Miss (%)</th>
          <th class="text-right">ECE</th>
          <th class="text-right">Brier</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>

    <footer>
      Sentinel-AI Offline Urban Emergency Detection Platform &bull; Phase 6H Robustness Benchmark
    </footer>
  </div>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return output_path


def run_robustness_cli(args: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sentinel-AI Environmental Robustness Evaluation (Phase 6H)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--count", type=int, default=4, help="Scenarios per condition setting")
    parser.add_argument("--duration", type=float, default=6.0, help="Duration in seconds per scenario")
    parser.add_argument("--min-samples", type=int, default=10, help="Minimum sample threshold for VALID status")
    parser.add_argument("--output", type=str, default="results/robustness_evaluation.json", help="Path to JSON output")
    parser.add_argument("--csv", type=str, default="results/robustness_evaluation.csv", help="Path to CSV output")
    parser.add_argument("--html", type=str, default="reports/robustness_report.html", help="Path to HTML report")
    parsed = parser.parse_args(args)

    print(f"Generating robustness evaluation suite (seed={parsed.seed}, count={parsed.count})...")
    gen = ScenarioGenerator(seed=parsed.seed)
    suite = gen.generate_robustness_suite(count_per_condition=parsed.count, duration_seconds=parsed.duration)

    print(f"Generated {len(suite)} scenarios spanning all 8 condition dimensions.")
    system = TemporalOodFusionSystem()
    evaluator = RobustnessEvaluator(min_samples=parsed.min_samples, seed=parsed.seed)

    print("Running evaluation across all condition subgroups...")
    result = evaluator.evaluate(system, suite)

    json_path = evaluator.export_json(result, Path(parsed.output))
    csv_path = evaluator.export_csv(result, Path(parsed.csv))
    html_path = evaluator.export_html(result, Path(parsed.html))

    print(f"\n--- Robustness Evaluation Summary ---")
    print(f"Evaluated Steps: {result.total_evaluated_steps} across {result.total_evaluated_scenarios} scenarios")
    print(f"Nominal Macro-F1: {result.nominal_baseline_metrics['macro_f1']:.4f}")
    for dim, disp in result.dimension_disparities.items():
        gap = f"{disp.disparity_gap_f1 * 100:.1f}%" if disp.disparity_gap_f1 is not None else "N/A"
        print(f" - {dim:22s} | Gap: {gap:6s} | Best: {disp.best_condition} | Worst: {disp.worst_condition}")
    print(f"\nSaved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")
    print(f"Saved HTML: {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(run_robustness_cli())
