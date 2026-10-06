"""
Module: Zone-Aware Risk Scoring.
================================
Dynamically calculates spatial risk multipliers based on environmental zone profiles
(e.g., school crossing, transit hub, hospital perimeter vs open industrial yard)
and real-time pedestrian/vehicle density.

Research Hypothesis:
Incorporating dynamic zone criticality profiles and crowding density multipliers
into the raw event confidence equation produces a calibrated risk score that reduces
false alert fatigue in low-consequence zones by >35% while increasing true hazard
sensitivity in vulnerable public corridors.

Primary Metrics:
1. Risk Calibration / Brier Separation: Calibrated risk scores reliably separate
   high-hazard situations in sensitive zones from identical raw detections in empty yards.
2. Sensitivity Amplification: High-density school zone events scale upwards by up to
   1.5x (bounded <= 1.0) compared to open-storage baseline zones.
3. Monotonic Density Scaling: Risk monotonically increases as local pedestrian count
   or vehicle traffic exceeds safe density thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ZoneProfile:
    zone_id: str
    name: str
    vulnerability_tier: str  # CRITICAL, HIGH, MEDIUM, LOW
    base_multiplier: float
    crowd_density_factor: float
    max_risk_cap: float = 1.0


@dataclass
class ZoneRiskAssessment:
    zone_id: str
    raw_confidence: float
    base_risk: float
    calibrated_risk: float
    vulnerability_tier: str
    crowd_density: int
    applied_multiplier: float
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "raw_confidence": round(self.raw_confidence, 4),
            "base_risk": round(self.base_risk, 4),
            "calibrated_risk": round(self.calibrated_risk, 4),
            "vulnerability_tier": self.vulnerability_tier,
            "crowd_density": self.crowd_density,
            "applied_multiplier": round(self.applied_multiplier, 4),
            "reasons": self.reasons,
        }


class ZoneAwareRiskEngine:
    """
    Computes zone-aware risk scores adjusted for spatial context and crowd density.
    """

    DEFAULT_PROFILES = {
        "ZONE_SCHOOL": ZoneProfile("ZONE_SCHOOL", "School Crossing", "CRITICAL", 1.40, 0.05, 1.0),
        "ZONE_HOSPITAL": ZoneProfile("ZONE_HOSPITAL", "Hospital Emergency Perimeter", "HIGH", 1.25, 0.03, 1.0),
        "ZONE_COMMERCIAL": ZoneProfile("ZONE_COMMERCIAL", "Shopping Plaza / Market", "MEDIUM", 1.05, 0.02, 1.0),
        "ZONE_INDUSTRIAL": ZoneProfile("ZONE_INDUSTRIAL", "Industrial Yard / Storage", "LOW", 0.75, 0.01, 1.0),
    }

    def __init__(self, profiles: Optional[Dict[str, ZoneProfile]] = None):
        self.profiles = profiles or dict(self.DEFAULT_PROFILES)

    def assess_risk(
        self,
        zone_id: str,
        raw_confidence: float,
        event_severity: str = "MEDIUM",
        crowd_density: int = 0,
    ) -> ZoneRiskAssessment:
        reasons: List[str] = []
        conf = max(0.0, min(1.0, float(raw_confidence)))

        severity_weight = {
            "CRITICAL": 1.0,
            "HIGH": 0.85,
            "MEDIUM": 0.65,
            "LOW": 0.40,
        }.get(event_severity.upper(), 0.65)

        base_risk = conf * severity_weight

        profile = self.profiles.get(
            zone_id,
            ZoneProfile(zone_id, "Standard Zone", "MEDIUM", 1.0, 0.02, 1.0)
        )

        # Compute dynamic multiplier
        crowd_boost = min(0.30, max(0, crowd_density) * profile.crowd_density_factor)
        multiplier = profile.base_multiplier + crowd_boost
        if crowd_density > 0:
            reasons.append(f"CROWD_DENSITY_BOOST (+{crowd_boost:.2f} for {crowd_density} people)")

        reasons.append(f"ZONE_TIER_{profile.vulnerability_tier} (base={profile.base_multiplier:.2f})")

        calibrated_risk = min(profile.max_risk_cap, base_risk * multiplier)

        return ZoneRiskAssessment(
            zone_id=zone_id,
            raw_confidence=conf,
            base_risk=base_risk,
            calibrated_risk=calibrated_risk,
            vulnerability_tier=profile.vulnerability_tier,
            crowd_density=crowd_density,
            applied_multiplier=multiplier,
            reasons=reasons,
        )
