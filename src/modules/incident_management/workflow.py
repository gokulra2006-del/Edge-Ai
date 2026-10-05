"""Audited operator workflow and review queue built on the Phase 1 repository."""
from __future__ import annotations

import csv
from datetime import datetime
from hashlib import sha256
import io
import json
from pathlib import Path
from typing import Any

from src.modules.database.governed_store import IncidentRepository, IncidentStatus, utc_now


class WorkflowError(ValueError): pass
class PermissionDenied(WorkflowError): pass
class VersionConflict(WorkflowError): pass


ROLE_ACTIONS = {
    "VIEWER": set(), "ENGINEER": set(),
    "OPERATOR": {"acknowledge", "confirm", "false_alarm", "note"},
    "COMMANDER": {"acknowledge", "confirm", "false_alarm", "note", "escalate", "resolve"},
}

TRANSITIONS = {
    "acknowledge": ({IncidentStatus.OPEN, IncidentStatus.ESCALATED, IncidentStatus.REVIEW_REQUIRED}, IncidentStatus.ACKNOWLEDGED),
    "confirm": ({IncidentStatus.ACKNOWLEDGED}, IncidentStatus.CONFIRMED),
    "false_alarm": ({IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.REVIEW_REQUIRED}, IncidentStatus.FALSE_ALARM),
    "escalate": ({IncidentStatus.ACKNOWLEDGED, IncidentStatus.CONFIRMED}, IncidentStatus.ESCALATED),
    "resolve": ({IncidentStatus.ACKNOWLEDGED, IncidentStatus.CONFIRMED, IncidentStatus.ESCALATED, IncidentStatus.FALSE_ALARM}, IncidentStatus.CLOSED),
}


class OperatorWorkflow:
    def __init__(self, repository: IncidentRepository, dispatch_log: Path | None = None):
        self.repository = repository; self.dispatch_log = dispatch_log

    def act(self, incident_id: str, action: str, operator_id: str, role: str, version: int,
            note: str = "") -> dict[str, Any]:
        role, action, note = role.upper(), action.lower(), note.strip()
        if action not in ROLE_ACTIONS.get(role, set()):
            self._audit_denied(incident_id, action, operator_id, role)
            raise PermissionDenied(f"{role} is not allowed to {action}")
        if action == "note":
            if not note: raise WorkflowError("A note is required")
            self.repository.writer.submit_wait(lambda db: db.execute("INSERT INTO incident_notes(incident_id,timestamp,operator_id,operator_role,note) VALUES(?,?,?,?,?)", (incident_id,utc_now(),operator_id,role,note)))
            return self.get_incident(incident_id)
        if action not in TRANSITIONS: raise WorkflowError("Unknown incident action")
        allowed, destination = TRANSITIONS[action]
        def transaction(db):
            row = db.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
            if not row: raise WorkflowError("Incident not found")
            current = IncidentStatus(row["status"])
            if current == IncidentStatus.CLOSED: raise WorkflowError("Closed incidents are immutable except for notes")
            if int(row["version"]) != int(version): raise VersionConflict("Incident changed; reload before retrying")
            if current not in allowed: raise WorkflowError(f"{action} is not allowed from {current.value}")
            if action == "false_alarm" and not note: raise WorkflowError("False-alarm reason is required")
            if action == "resolve" and not note: raise WorkflowError("Resolution summary is required")
            if action == "resolve" and row["severity"] == "CRITICAL" and row["acknowledged_seconds"] is None and not note:
                raise WorkflowError("A note is required to close an unacknowledged CRITICAL incident")
            now = utc_now(); created = datetime.fromisoformat(row["created_at"]); elapsed = max(0.0, (datetime.fromisoformat(now)-created).total_seconds())
            ack = elapsed if action == "acknowledge" and row["acknowledged_seconds"] is None else row["acknowledged_seconds"]
            resolution = elapsed if action == "resolve" else row["resolution_seconds"]
            changed = db.execute("UPDATE incidents SET status=?, version=version+1, updated_at=?, acknowledged_seconds=?, resolution_seconds=? WHERE incident_id=? AND version=?", (destination.value,now,ack,resolution,incident_id,version)).rowcount
            if changed != 1: raise VersionConflict("Incident changed; reload before retrying")
            payload={"operator_role":role,"previous_status":current.value,"new_status":destination.value,"note":note,"operator_confirmation_required":True}
            if action == "escalate": payload["dispatch"]="escalated to the authority, operator-approved (simulation only)"
            db.execute("INSERT INTO operator_actions(incident_id,timestamp,operator_id,action,approved,payload_json) VALUES(?,?,?,?,?,?)", (incident_id,now,operator_id,action,1,json.dumps(payload,sort_keys=True)))
            if note: db.execute("INSERT INTO incident_notes(incident_id,timestamp,operator_id,operator_role,note) VALUES(?,?,?,?,?)", (incident_id,now,operator_id,role,note))
            return destination.value
        self.repository.writer.submit_wait(transaction)
        if action == "escalate" and self.dispatch_log:
            self.dispatch_log.parent.mkdir(parents=True,exist_ok=True)
            with self.dispatch_log.open("a",encoding="utf-8") as stream: stream.write(json.dumps({"incident_id":incident_id,"timestamp":utc_now(),"message":"escalated to the authority, operator-approved","simulation":True})+"\n")
        return self.get_incident(incident_id)

    def _audit_denied(self, incident_id: str, action: str, operator_id: str, role: str) -> None:
        self.repository.add_operator_action(incident_id,operator_id,f"DENIED:{action}",False,{"operator_role":role,"reason":"forbidden"})

    def list_incidents(self, filters: dict[str,str]|None=None) -> list[dict[str,Any]]:
        filters=filters or {}; clauses=[]; args=[]
        for key in ("status","severity","zone_id"):
            if filters.get(key): clauses.append(f"{key}=?"); args.append(filters[key])
        sql="SELECT * FROM incidents"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY created_at DESC"
        return [dict(x) for x in self.repository._read(sql,tuple(args))]

    def get_incident(self, incident_id: str) -> dict[str,Any]:
        rows=self.repository._read("SELECT * FROM incidents WHERE incident_id=?",(incident_id,))
        if not rows: raise WorkflowError("Incident not found")
        result=dict(rows[0])
        for table in ("incident_events","predictions","operator_actions","incident_notes","evidence","assurance_states"):
            result[table]=[dict(x) for x in self.repository._read(f"SELECT * FROM {table} WHERE incident_id=? ORDER BY id",(incident_id,))]
        models={row["model_id"]:dict(row) for row in self.repository._read("SELECT * FROM models")}
        for prediction in result["predictions"]:
            model=models.get(prediction.get("model_id"),{})
            prediction["model_version"]=model.get("version")
            prediction["usage_restriction"]=model.get("usage_restriction","UNVERIFIED")
        for evidence in result["evidence"]:
            path=Path(evidence.get("source_path") or "")
            evidence["hash_verified"]=bool(path.is_file() and sha256(path.read_bytes()).hexdigest()==evidence.get("sha256"))
        return result


class ReviewQueue:
    def __init__(self, repository: IncidentRepository): self.repository=repository
    def feedback(self,prediction_id:int,label:str,operator_id:str,role:str,corrected_class:str|None=None,comment:str|None=None)->None:
        if role.upper() not in {"OPERATOR","COMMANDER","ENGINEER"}: raise PermissionDenied("Role cannot review predictions")
        if label not in {"CORRECT","INCORRECT","UNSURE"}: raise WorkflowError("Invalid feedback label")
        self.repository.add_feedback(prediction_id,label,corrected_class,operator_id,role.upper(),comment)
    def claim(self,prediction_id:int,operator_id:str,role:str)->bool:
        if role.upper() not in {"ENGINEER","COMMANDER","OPERATOR"}: raise PermissionDenied("Role cannot claim reviews")
        return bool(self.repository.writer.submit_wait(lambda db: db.execute("INSERT OR IGNORE INTO review_claims VALUES(?,?,?,?)",(prediction_id,operator_id,role.upper(),utc_now())).rowcount))
    def list(self, filters:dict[str,str]|None=None)->list[dict[str,Any]]:
        filters=filters or {}
        sql="""SELECT p.*,i.zone_id,i.is_demo,i.ood_status,i.ood_reasons_json,m.version AS model_version,m.usage_restriction,
        e.kind AS evidence_kind,e.source_path AS evidence_path,e.sha256 AS evidence_sha256,
        (SELECT label FROM prediction_feedback f WHERE f.prediction_id=p.id ORDER BY f.id DESC LIMIT 1) feedback_label,
        c.operator_id claimed_by FROM predictions p JOIN incidents i ON i.incident_id=p.incident_id
        LEFT JOIN models m ON m.model_id=p.model_id LEFT JOIN review_claims c ON c.prediction_id=p.id
        LEFT JOIN evidence e ON e.id=(SELECT id FROM evidence WHERE incident_id=i.incident_id ORDER BY id LIMIT 1)"""
        result=[]
        for row in self.repository._read(sql):
            item=dict(row); payload=json.loads(item.get("payload_json") or "{}"); reasons=payload.get("reason_codes") or json.loads(item.get("ood_reasons_json") or "[]")
            include=item.get("label") in {"UNKNOWN","REVIEW_REQUIRED"} or bool(reasons) or item.get("feedback_label")=="INCORRECT" or float(item.get("confidence",1))<.6
            if not include: continue
            item["reason_codes"]=reasons; item["status"]="reviewed" if item.get("feedback_label") else "pending"
            item["priority"]=round((1-float(item["confidence"]))*50+len(reasons)*15+(20 if item["label"]=="UNKNOWN" else 0),2)
            if filters.get("reason") and filters["reason"] not in reasons: continue
            if filters.get("zone") and item.get("zone_id")!=filters["zone"]: continue
            if filters.get("model") and item.get("model_id")!=filters["model"]: continue
            if filters.get("status") and item["status"]!=filters["status"]: continue
            result.append(item)
        return sorted(result,key=lambda x:x["priority"],reverse=True)
    def export(self,fmt:str="json",include_demo:bool=False)->str:
        rows=[dict(x) for x in self.repository._read("""SELECT f.*,p.incident_id,p.model_id,i.zone_id,i.is_demo,m.usage_restriction,e.source_path,e.sha256
        FROM prediction_feedback f JOIN predictions p ON p.id=f.prediction_id JOIN incidents i ON i.incident_id=p.incident_id
        LEFT JOIN models m ON m.model_id=p.model_id LEFT JOIN evidence e ON e.incident_id=i.incident_id ORDER BY f.id""") if include_demo or not x["is_demo"]]
        version=utc_now(); data=[{"manifest_version":version,**row,"research_only":str(row.get("usage_restriction") or "").startswith("RESEARCH_ONLY")} for row in rows]
        if fmt=="json": return json.dumps(data,indent=2,default=str)
        output=io.StringIO(); fields=list(data[0]) if data else ["manifest_version"]
        writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader(); writer.writerows(data); return output.getvalue()
