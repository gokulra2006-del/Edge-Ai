"""Sentinel-AI Reproducible Evaluation Framework (Phase 6A).

Modules:
- scenarios: versioned scenario format, generator, loader, and deterministic fault injectors.
- systems: common evaluation interface and 5 system implementations (audio-only, vision-only,
  sensor-only, static-fusion, temporal-ood-fusion).
- metrics: classification, latency, edge resource accounting, bootstrap confidence intervals.
- runner: evaluation harness with config hash, reproducibility lock, and results export.
"""
from __future__ import annotations

__version__ = "1.0.0"
