"""Pure temporal, uncertainty and zone-risk decisions for the fusion adapter."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
from time import monotonic
from typing import Any, Protocol

class Clock(Protocol):
    def now(self) -> float: ...
class RealClock:
    def now(self) -> float: return monotonic()
class FakeClock:
    def __init__(self, value: float=0): self.value=value
    def now(self) -> float: return self.value
    def advance(self, seconds: float) -> None: self.value += seconds

class TemporalState(str, Enum):
    CANDIDATE='CANDIDATE'; OBSERVING='OBSERVING'; CONFIRMED='CONFIRMED'; ESCALATED='ESCALATED'; CLEARED='CLEARED'

@dataclass
class Transition:
    previous: TemporalState; current: TemporalState; reason_code: str; reason: str; evidence: dict[str, Any]

class TemporalStateMachine:
    """Bounded per-class validation with injectable time and optional async persistence."""
    def __init__(self, rules: dict[str, Any], clock: Clock|None=None, repository: Any=None, incident_id: str|None=None):
        self.rules=rules; self.clock=clock or RealClock(); self.repository=repository; self.incident_id=incident_id
        self.state: dict[str, TemporalState]={}; self.history: dict[str, deque[tuple[float,float,dict[str,Any]]]]={}; self.last_seen: dict[str,float]={}
    def _rule(self, event: str) -> dict[str, Any]: return self.rules.get(event, self.rules['default'])
    def ingest(self, event: str, confidence: float, evidence: dict[str,Any]|None=None) -> dict[str, Any]:
        now=self.clock.now(); rule=self._rule(event); old=self.state.get(event, TemporalState.CANDIDATE)
        q=self.history.setdefault(event, deque(maxlen=int(rule.get('window', rule.get('consecutive_windows', 5)))))
        data=evidence or {}; q.append((now, confidence, data)); self.last_seen[event]=now
        values=[v for _,v,_ in q]; threshold=float(rule['threshold']); good=[v for v in values if v>=threshold]
        passed=False; reason='insufficient persistence'; code='PERSISTENCE_PENDING'
        if event in ('siren','horn'):
            k=int(rule['consecutive_windows']); passed=len(values)>=k and all(v>=threshold for v in values[-k:]); code='CONSECUTIVE_AUDIO' if passed else code; reason='consecutive audio windows' if passed else reason
        elif event=='crash':
            stationary=bool(data.get('vehicle_stationary')) and float(data.get('stationary_after_seconds', 1e9))<=float(rule['stationary_within_seconds'])
            passed=confidence>=threshold and stationary; code='IMPACT_STATIONARY' if passed else 'CRASH_NEEDS_STATIONARY'; reason='impact corroborated by stationary vehicle' if passed else 'crash needs stationary vehicle corroboration'
        else:
            passed=len(good)>=int(rule['positive_frames']); code='FRAME_PERSISTENCE' if passed else code; reason='enough positive frames' if passed else reason
        new = TemporalState.ESCALATED if old==TemporalState.CONFIRMED and passed else TemporalState.CONFIRMED if passed else TemporalState.OBSERVING
        transition=self._transition(event, old, new, code, reason, {'samples':len(values),'positive':len(good),'threshold':threshold, **data})
        return {'state':self.state[event].value,'transition':transition,'persistence_ratio':len(good)/len(values),'evidence':transition.evidence}
    def tick(self, event: str) -> dict[str, Any]:
        old=self.state.get(event, TemporalState.CANDIDATE); rule=self._rule(event); elapsed=self.clock.now()-self.last_seen.get(event, self.clock.now())
        if old in (TemporalState.CANDIDATE,TemporalState.OBSERVING) and elapsed>=float(rule['observe_timeout_seconds']): new,code,reason=TemporalState.CLEARED,'OBSERVE_TIMEOUT','observation expired without confirmation'
        elif old in (TemporalState.CONFIRMED,TemporalState.ESCALATED) and elapsed>=float(rule['clear_timeout_seconds']): new,code,reason=TemporalState.CLEARED,'EVIDENCE_DECAY','evidence decayed after clear timeout'
        else: return {'state':old.value,'transition':None}
        t=self._transition(event,old,new,code,reason,{'elapsed_seconds':elapsed}); return {'state':new.value,'transition':t}
    def _transition(self,event:str,old:TemporalState,new:TemporalState,code:str,reason:str,evidence:dict[str,Any])->Transition:
        # Regression from ESCALATED requires timeout, preventing one-frame flapping.
        if old==TemporalState.ESCALATED and new in (TemporalState.OBSERVING,TemporalState.CONFIRMED): new=old
        self.state[event]=new; t=Transition(old,new,code,reason,evidence)
        if old!=new and self.repository and self.incident_id:
            self.repository.add_event(self.incident_id,'temporal_transition',{'event_type':event,'from_state':old.value,'to_state':new.value,'reason_code':code,'reason':reason,'supporting_evidence':evidence},dedupe_key=f'transition:{event}:{old.value}:{new.value}:{int(self.clock.now())}')
        return t

class OODDecision:
    def __init__(self, config:dict[str,Any], synthetic:bool=True): self.config=config; self.synthetic=synthetic
    def assess(self, probabilities:list[float], audio_label:str|None=None, vision_label:str|None=None, quality:dict[str,float]|None=None, energy:float|None=None)->dict[str,Any]:
        quality=quality or {}; p=sorted((max(0,float(x)) for x in probabilities), reverse=True); maxp=p[0] if p else 0; margin=maxp-(p[1] if len(p)>1 else 0); entropy=-sum(x*math.log(max(x,1e-12)) for x in p)
        c=self.config; reasons=[]
        if maxp<c['minimum_max_softmax'] or entropy>c['maximum_entropy']: reasons.append('LOW_CONFIDENCE_OR_HIGH_ENTROPY')
        if margin<c['minimum_margin']: reasons.append('LOW_TOP2_MARGIN')
        if audio_label and vision_label and audio_label!=vision_label: reasons.append('MODALITY_CONFLICT')
        if quality.get('darkness',0)>c['maximum_darkness'] or quality.get('blur',0)>c['maximum_blur'] or quality.get('audio_rms',1)<c['minimum_audio_rms'] or quality.get('clipping',0)>c['maximum_clipping']: reasons.append('INPUT_QUALITY_FAILURE')
        if energy is not None and energy<0: reasons.append('ENERGY_OOD')
        status='UNKNOWN' if reasons else 'KNOWN'; status='REVIEW_REQUIRED' if reasons and audio_label==vision_label and maxp>=c['minimum_max_softmax'] else status
        return {'status':status,'reason_codes':reasons,'human_explanation':'Model output needs operator review.' if reasons else 'Known class supported by configured checks.','scores':{'max_softmax':maxp,'top2_margin':margin,'entropy':entropy,'energy':energy},'thresholds_used':dict(c),'calibrated_confidence':{'raw_score':maxp,'calibrated_score':maxp,'calibration_method':'UNCALIBRATED','calibrated':False},'usage_restriction':'RESEARCH_ONLY' if self.synthetic else None}

class ZoneAwareRiskEngine:
    LEVEL={'LOW':.25,'MEDIUM':.5,'HIGH':.75,'CRITICAL':1.0}
    def __init__(self, config:dict[str,Any], repository:Any=None, incident_id:str|None=None): self.c=config['zone_risk']; self.repository=repository; self.incident_id=incident_id; self.last={}
    def assess(self,event_type:str,zone_id:str,fused:float,temporal_state:str,sensors:dict[str,Any])->dict[str,Any]:
        zone_type=self.c['zone_types'].get(zone_id,self.c['default_zone_type']); warning=None
        if zone_id not in self.c['zone_types']: warning='UNKNOWN_ZONE_FALLBACK'
        matrix=self.c['severity_matrix']; event=event_type if event_type in matrix else 'vehicle'; baseline=matrix[event][zone_type]
        corroboration=min(1,(int(bool(sensors.get('gas')))+int(bool(sensors.get('temperature')))+int(bool(sensors.get('imu'))))/3)
        temporal={'CANDIDATE':.2,'OBSERVING':.4,'CONFIRMED':.75,'ESCALATED':1,'CLEARED':0}.get(temporal_state,.2); weights=self.c['weights']
        # Feature 9: Graceful degradation adapter - reduce fused confidence coverage if degraded
        coverage_factor = {'FULL': 1.0, 'VISION_ONLY': 0.75, 'AUDIO_ONLY': 0.75, 'SENSORS_ONLY': 0.65, 'DEGRADED': 0.8}.get(str(sensors.get('assurance_level', 'FULL')), 1.0)
        adapted_fused = round(fused * coverage_factor, 4)
        factors={'fused_confidence':adapted_fused,'zone_severity':self.LEVEL[baseline],'temporal_state':temporal,'corroboration':corroboration}
        contributions={k:round(weights[k]*factors[k],6) for k in weights}; score=sum(contributions.values()); level=next((x for x,v in self.LEVEL.items() if score<=v),'CRITICAL')
        breakdown={'zone_type':zone_type,'baseline_severity':baseline,'factors':factors,'weights':weights,'contributions':contributions,'score':score,'final_level':level,'warning':warning,'assurance_level':sensors.get('assurance_level','FULL')}
        if self.repository and self.incident_id:
            self.repository.update_incident_risk(self.incident_id, level, breakdown)
        if self.repository and self.incident_id and self.last.get(self.incident_id)!=level:
            self.repository.add_event(self.incident_id,'risk_change',{'from_level':self.last.get(self.incident_id),'to_level':level,'risk_breakdown':breakdown},dedupe_key=f'risk:{level}')
        if self.incident_id: self.last[self.incident_id]=level
        return breakdown


