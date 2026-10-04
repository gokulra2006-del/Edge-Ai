def test_system_health_reports_real_local_checks(monkeypatch):
    monkeypatch.setenv("EDGE_AI_MODEL_PROFILE", "synthetic")
    from src.modules.assurance.system_health import system_health
    result = system_health()
    assert result["profile"] == "synthetic"
    assert result["research_only"] is True
    assert any(check["component"] == "local_database" for check in result["checks"])
    assert all(check["status"] in {"PASS", "WARNING", "FAIL"} for check in result["checks"])
