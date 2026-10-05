"""Compatibility facade for the Phase 2 temporal state machine."""
from __future__ import annotations
from typing import Any, Dict
from src.modules.sensor_fusion.decision_logic import TemporalStateMachine

class EventValidator:
    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        base=config.get('temporal',{})
        rules=config.get('temporal_rules') or {'default': {'threshold':base.get('minimum_average_confidence',.6),'window':base.get('window_size',6),'positive_frames':base.get('positive_frames',3),'observe_timeout_seconds':base.get('decay_seconds',15),'clear_timeout_seconds':base.get('decay_seconds',15)}}
        self.machine=TemporalStateMachine(rules, **kwargs)
    def ingest(self,event:str,confidence:float,evidence:Dict[str,Any]|None=None)->Dict[str,Any]:
        result=self.machine.ingest(event,confidence,evidence)
        return {'state':result['state'],'confirmed':result['state'] in {'CONFIRMED','ESCALATED'},'positive_frames':result['evidence'].get('positive',0),'window_size':result['evidence'].get('samples',0),'persistence_ratio':round(result['persistence_ratio'],3),'average_confidence':confidence,'transition':result['transition']}
    def tick(self,event:str)->Dict[str,Any]: return self.machine.tick(event)
