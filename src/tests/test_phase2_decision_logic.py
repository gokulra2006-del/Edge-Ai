from pathlib import Path
from src.config.governance_config import load_decision_config, GovernanceConfig
from src.modules.database.governed_store import IncidentRepository
from src.modules.sensor_fusion.decision_logic import FakeClock, TemporalStateMachine, OODDecision, ZoneAwareRiskEngine

ROOT=Path(__file__).resolve().parents[2]
CONFIG=load_decision_config(ROOT/'src/config/advanced_platform.json')

def test_temporal_transitions_timeout_and_persistence(tmp_path):
    clock=FakeClock(); machine=TemporalStateMachine(CONFIG['temporal_rules'],clock)
    assert machine.ingest('smoke',.8)['state']=='OBSERVING'
    assert machine.ingest('smoke',.8)['state']=='OBSERVING'
    assert machine.ingest('smoke',.8)['state']=='CONFIRMED'
    assert machine.ingest('smoke',.8)['state']=='ESCALATED'
    clock.advance(16); assert machine.tick('smoke')['state']=='CLEARED'

def test_crash_and_audio_class_rules():
    clock=FakeClock(); m=TemporalStateMachine(CONFIG['temporal_rules'],clock)
    assert m.ingest('crash',.9,{'vehicle_stationary':False})['state']=='OBSERVING'
    assert m.ingest('crash',.9,{'vehicle_stationary':True,'stationary_after_seconds':4})['state']=='CONFIRMED'
    s=TemporalStateMachine(CONFIG['temporal_rules'],clock)
    assert [s.ingest('siren',.8)['state'] for _ in range(3)][-1]=='CONFIRMED'

def test_temporal_events_are_persisted(tmp_path):
    repo=IncidentRepository(tmp_path/'db.sqlite',GovernanceConfig())
    try:
        incident,_=repo.create_incident('smoke','ZONE_B_INTERSECTION'); repo.writer.drain()
        m=TemporalStateMachine(CONFIG['temporal_rules'],FakeClock(),repo,incident)
        for _ in range(3): m.ingest('smoke',.8)
        repo.writer.drain(); assert repo.rows('incident_events',incident)[0]['event_type']=='temporal_transition'
    finally: repo.close()

def test_ood_each_trigger_and_unknown():
    d=OODDecision(CONFIG['ood'])
    assert d.assess([.4,.3])['status']=='UNKNOWN'
    assert 'LOW_TOP2_MARGIN' in d.assess([.7,.65])['reason_codes']
    assert 'MODALITY_CONFLICT' in d.assess([.9,.05],'crash','fire')['reason_codes']
    assert 'INPUT_QUALITY_FAILURE' in d.assess([.9,.05],quality={'darkness':.9})['reason_codes']
    result=d.assess([.4,.3]); assert result['calibrated_confidence']['calibrated'] is False and result['usage_restriction']=='RESEARCH_ONLY'

def test_zone_matrix_breakdown_fallback_and_event(tmp_path):
    repo=IncidentRepository(tmp_path/'db.sqlite',GovernanceConfig())
    try:
        incident,_=repo.create_incident('smoke','SERVER_ROOM'); repo.writer.drain(); risk=ZoneAwareRiskEngine(CONFIG,repo,incident)
        server=risk.assess('smoke','SERVER_ROOM',.9,'ESCALATED',{'gas':1,'temperature':1,'imu':0})
        assert server['baseline_severity']=='CRITICAL' and abs(sum(server['contributions'].values())-server['score'])<1e-5
        assert risk.assess('vehicle','RESTRICTED_AREA',.7,'CONFIRMED',{})['baseline_severity']=='HIGH'
        assert risk.assess('smoke','MISSING',.7,'CONFIRMED',{})['warning']=='UNKNOWN_ZONE_FALLBACK'
        repo.writer.drain(); assert any(x['event_type']=='risk_change' for x in repo.rows('incident_events',incident))
    finally: repo.close()
