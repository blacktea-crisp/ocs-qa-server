"""管理 API：鉴权、CRUD、dashboard、settings。"""
from __future__ import annotations


def test_admin_auth_required(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_token", "secret123", raising=False)
    r = client.get("/api/admin/dashboard")
    assert r.status_code == 401
    r2 = client.get("/api/admin/dashboard", headers={"X-Admin-Token": "secret123"})
    assert r2.status_code == 200


def test_dashboard(client, mock_llm):
    client.post("/search", json={"title": "dashboard题", "type": "single", "options": ["A", "B"]})
    r = client.get("/api/admin/dashboard")
    data = r.json()
    assert data["total_requests"] >= 1
    assert "hit_rate" in data
    assert "questions_total" in data


def test_questions_crud(client, mock_llm):
    client.post("/search", json={"title": "CRUD题", "type": "single", "options": ["A", "B"]})
    r = client.get("/api/admin/questions")
    items = r.json()["items"]
    assert len(items) >= 1
    qkey = items[0]["qkey"]
    # 删除
    d = client.delete(f"/api/admin/questions/{qkey}")
    assert d.json()["ok"] is True


def test_settings_roundtrip(client):
    r = client.put("/api/admin/settings", json={"default_answer_trust": "allow_candidate"})
    assert r.json()["ok"] is True
    g = client.get("/api/admin/settings").json()
    assert g["effective"]["default_answer_trust"] == "allow_candidate"
