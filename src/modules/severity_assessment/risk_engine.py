"""Configurable risk assessment with Phase 2 zone-aware evidence breakdowns."""
from __future__ import annotations
from typing import Any, Dict
from src.modules.sensor_fusion.decision_logic import ZoneAwareRiskEngine

class RiskEngine:
    def __init__(self, config: Dict[str, Any], repository: Any=None, incident_id: str|None=None):
        self.config=config; self.zone_engine=ZoneAwareRiskEngine(config,repository,incident_id) if 'zone_risk' in config else None
    def assess(self, fusion: Dict[str, Any], temporal: Dict[str, Any], zone: str='ZONE_B_INTERSECTION') -> Dict[str, Any]:
        if self.zone_engine:
            event=str(fusion.get('incident_type','vehicle')).replace('vehicle_accident','crash').replace('fire_hazard','fire').replace('emergency_vehicle','ambulance')
            breakdown=self.zone_engine.assess(event,zone,float(fusion.get('fusion_confidence',0)),str(temporal.get('state','CANDIDATE')),fusion.get('sensor_corroboration',{}))
            return {'risk_score':round(breakdown['score']*100,1),'severity':breakdown['final_level'],'factors':breakdown['factors'],'breakdown':breakdown,'explanation':f"{event} is {breakdown['final_level']} in {breakdown['zone_type']}",'escalation_reason':breakdown['baseline_severity']}
        c,w=self.config,self.config['risk']['weights']; multiplier=c['zones'].get(zone,c['zones']['ZONE_B_INTERSECTION'])['risk_multiplier']
        factors={'fusion':fusion['fusion_confidence'],'persistence':temporal['persistence_ratio'],'reliability':fusion['model_reliability'],'modalities':min(1,len(fusion['contributing_modalities'])/2),'zone':min(1,multiplier/1.35)}
        score=round(min(100,sum(w[k]*factors[k] for k in w)*100*multiplier),1); severity='NORMAL'
        for name,threshold in c['risk']['thresholds'].items():
            if score>=threshold: severity=name
        return {'risk_score':score,'severity':severity,'factors':factors,'explanation':'evidence-based risk','escalation_reason':'legacy assessment'}
