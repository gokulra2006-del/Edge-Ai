from src.modules.autonomous_response.alert_manager import AlertDispatchManager

def test_accident_plan_requires_operator_and_names_response_services():
    plan = AlertDispatchManager().response_plan("ACCIDENT", "CRITICAL", "ROAD", "INC-1")
    assert plan["operator_confirmation_required"] is True
    assert set(plan["contacts_to_notify"]) == {"AMBULANCE", "POLICE"}
    assert plan["mode"] == "SIMULATED_DECISION_SUPPORT"
