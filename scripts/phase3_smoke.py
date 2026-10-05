"""Exercise the governed operator workflow and feedback queue."""
from pathlib import Path
import json, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository
from src.modules.incident_management.workflow import OperatorWorkflow, ReviewQueue

def main():
    repo=IncidentRepository(ROOT/"data"/"phase3_smoke.db",GovernanceConfig())
    try:
        incident,_=repo.create_incident("collision","ZONE_B_INTERSECTION"); repo.writer.drain()
        repo.writer.submit_wait(lambda db: db.execute("UPDATE incidents SET severity='HIGH' WHERE incident_id=?",(incident,)))
        repo.add_prediction(incident,"UNKNOWN",.42,None,{"reason_codes":["LOW_TOP2_MARGIN"]}); repo.writer.drain()
        flow=OperatorWorkflow(repo,ROOT/"logs"/"simulated_dispatch.jsonl"); row=flow.get_incident(incident)
        for action,actor,role,note in [("acknowledge","operator","OPERATOR",""),("confirm","operator","OPERATOR","visual confirmation"),("note","operator","OPERATOR","north lane blocked"),("resolve","commander","COMMANDER","scene cleared")]:
            row=flow.act(incident,action,actor,role,row["version"],note)
        prediction=repo._read("SELECT id FROM predictions WHERE incident_id=?",(incident,))[0]["id"]
        queue=ReviewQueue(repo); queue.feedback(prediction,"UNSURE","engineer","ENGINEER",comment="needs real-world replay"); repo.writer.drain()
        row=flow.get_incident(incident)
        print(json.dumps({"incident_id":incident,"status":row["status"],"acknowledgement_seconds":row["acknowledged_seconds"],"resolution_seconds":row["resolution_seconds"],"audit_trail":row["operator_actions"],"notes":row["incident_notes"],"feedback":dict(repo._read("SELECT * FROM prediction_feedback WHERE prediction_id=?",(prediction,))[0]),"review_queue":queue.list()},indent=2,default=str))
    finally: repo.close()
if __name__=="__main__": main()
