from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.config.governance_config import load_decision_config, GovernanceConfig
from src.modules.database.governed_store import IncidentRepository
from src.modules.sensor_fusion.decision_logic import FakeClock, TemporalStateMachine, ZoneAwareRiskEngine

def main():
    config=load_decision_config(ROOT/'src/config/advanced_platform.json')
    repo=IncidentRepository(ROOT/'data'/'phase2_smoke.db',GovernanceConfig())
    try:
        incident,_=repo.create_incident('smoke','SERVER_ROOM'); repo.writer.drain()
        clock=FakeClock(); machine=TemporalStateMachine(config['temporal_rules'],clock,repo,incident)
        states=[machine.ingest('smoke',.86)['state'] for _ in range(4)]
        risk=ZoneAwareRiskEngine(config,repo,incident).assess('smoke','SERVER_ROOM',.86,states[-1],{'gas':True,'temperature':True})
        repo.writer.drain()
        print(json.dumps({'incident_id':incident,'states':states,'timeline':repo.rows('incident_events',incident),'risk_breakdown':risk},indent=2,default=str))
    finally: repo.close()
if __name__=='__main__': main()
