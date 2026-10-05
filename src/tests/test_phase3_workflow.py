import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository
from src.modules.incident_management.workflow import OperatorWorkflow, ReviewQueue, PermissionDenied, VersionConflict, WorkflowError

ROOT=Path(__file__).resolve().parents[2]

def setup(tmp_path,severity="HIGH",is_demo=0):
    repo=IncidentRepository(tmp_path/"phase3.db",GovernanceConfig()); incident,_=repo.create_incident("collision","ZONE_B_INTERSECTION"); repo.writer.drain()
    repo.writer.submit_wait(lambda db: db.execute("UPDATE incidents SET severity=?,is_demo=? WHERE incident_id=?",(severity,is_demo,incident)))
    return repo,incident,OperatorWorkflow(repo,tmp_path/"dispatch.jsonl")

def test_legal_workflow_audit_and_times(tmp_path):
    repo,incident,flow=setup(tmp_path)
    try:
        row=flow.get_incident(incident); row=flow.act(incident,"acknowledge","op","OPERATOR",row["version"])
        row=flow.act(incident,"confirm","op","OPERATOR",row["version"],"visually confirmed")
        row=flow.act(incident,"note","op","OPERATOR",row["version"],"lane blocked")
        row=flow.act(incident,"resolve","cmd","COMMANDER",row["version"],"scene cleared")
        assert row["status"]=="CLOSED" and row["acknowledged_seconds"] is not None and row["resolution_seconds"] is not None
        assert [x["action"] for x in row["operator_actions"]]==["acknowledge","confirm","resolve"]
        assert len(row["incident_notes"])==3
    finally: repo.close()

def test_illegal_roles_false_alarm_and_conflict(tmp_path):
    repo,incident,flow=setup(tmp_path)
    try:
        with pytest.raises(PermissionDenied): flow.act(incident,"acknowledge","viewer","VIEWER",1)
        with pytest.raises(WorkflowError): flow.act(incident,"confirm","op","OPERATOR",1)
        with pytest.raises(WorkflowError): flow.act(incident,"false_alarm","op","OPERATOR",1)
        row=flow.act(incident,"acknowledge","op","OPERATOR",1)
        with pytest.raises(VersionConflict): flow.act(incident,"confirm","op","OPERATOR",1)
        assert flow.act(incident,"false_alarm","op","OPERATOR",row["version"],"shadow trigger")["status"]=="FALSE_ALARM"
    finally: repo.close()

def test_closed_immutable_except_notes_and_escalate_simulated(tmp_path):
    repo,incident,flow=setup(tmp_path)
    try:
        row=flow.act(incident,"acknowledge","cmd","COMMANDER",1)
        row=flow.act(incident,"escalate","cmd","COMMANDER",row["version"],"operator approved")
        assert "simulation" in (tmp_path/"dispatch.jsonl").read_text()
        row=flow.act(incident,"resolve","cmd","COMMANDER",row["version"],"resolved")
        with pytest.raises(WorkflowError): flow.act(incident,"acknowledge","cmd","COMMANDER",row["version"])
        assert flow.act(incident,"note","cmd","COMMANDER",row["version"],"post-close note")["incident_notes"][-1]["note"]=="post-close note"
    finally: repo.close()

def test_feedback_history_queue_priority_and_manifest(tmp_path):
    repo,incident,_=setup(tmp_path)
    try:
        model=tmp_path/"model.bin"; model.write_bytes(b"m")
        repo.writer.submit_wait(lambda db: db.execute("INSERT INTO models VALUES(?,?,?,?,?,?,?,?,?)",("m1","model","1",None,"UNVERIFIED","UNVERIFIED","RESEARCH_ONLY","READY","2026-01-01")))
        repo.add_prediction(incident,"UNKNOWN",.3,"m1",{"reason_codes":["LOW_TOP2_MARGIN"]}); repo.writer.drain()
        pid=repo._read("SELECT id FROM predictions")[0]["id"]
        evidence=tmp_path/"clip.wav"; evidence.write_bytes(b"audio"); repo.attach_evidence(incident,"audio",evidence); repo.writer.drain()
        queue=ReviewQueue(repo); assert queue.claim(pid,"eng","ENGINEER"); assert not queue.claim(pid,"other","ENGINEER")
        queue.feedback(pid,"INCORRECT","eng","ENGINEER","crash","wrong class"); queue.feedback(pid,"UNSURE","eng","ENGINEER",comment="second review"); repo.writer.drain()
        assert queue.list()[0]["priority"]>0 and queue.list()[0]["status"]=="reviewed"
        exported=json.loads(queue.export()); assert len(exported)==2 and exported[0]["research_only"] is True and exported[0]["sha256"]
    finally: repo.close()

def test_demo_excluded_and_dashboard_routes_present(tmp_path):
    repo,incident,_=setup(tmp_path,is_demo=1)
    try:
        repo.add_prediction(incident,"UNKNOWN",.2,None,{}); repo.writer.drain(); pid=repo._read("SELECT id FROM predictions")[0]["id"]
        ReviewQueue(repo).feedback(pid,"UNSURE","eng","ENGINEER"); repo.writer.drain(); assert json.loads(ReviewQueue(repo).export())==[]
        html=(ROOT/"src/modules/dashboard/web/index.html").read_text(encoding="utf-8"); js=(ROOT/"src/modules/dashboard/web/app.js").read_text(encoding="utf-8")
        assert "view-emergency-plan" in html and "View full plan" in html and '"emergency-plan"' in js and "view-review" in html
    finally: repo.close()


def test_incident_api_happy_path_and_errors(tmp_path, monkeypatch):
    from http.server import HTTPServer
    from src.modules.dashboard import app as dashboard_app

    repo,incident,flow=setup(tmp_path)
    server=None
    try:
        monkeypatch.setattr(dashboard_app,"OPERATOR_WORKFLOW",flow)
        monkeypatch.setattr(dashboard_app,"AUTH_SESSIONS",{
            "operator-token":{"operator_id":"op","role":"OPERATOR"},
            "viewer-token":{"operator_id":"viewer","role":"VIEWER"},
        })
        server=HTTPServer(("127.0.0.1",0),dashboard_app.DashboardHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base=f"http://127.0.0.1:{server.server_port}"

        with urlopen(f"{base}/api/incidents") as response:
            assert response.status==200 and json.loads(response.read())[0]["incident_id"]==incident

        def post(token,version):
            request=Request(f"{base}/api/incidents/{incident}/acknowledge",data=json.dumps({"version":version}).encode(),method="POST",headers={"Content-Type":"application/json",**({"Authorization":f"Bearer {token}"} if token else {})})
            try:
                with urlopen(request) as response: return response.status,json.loads(response.read())
            except HTTPError as exc: return exc.code,json.loads(exc.read())

        assert post("",1)[0]==401
        assert post("viewer-token",1)[0]==403
        status,body=post("operator-token",1); assert status==200 and body["status"]=="ACKNOWLEDGED"
        assert post("operator-token",1)[0]==409
    finally:
        if server: server.shutdown(); server.server_close()
        repo.close()
