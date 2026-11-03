"""识图：含图触发、无图不触发、失败降级。"""
from __future__ import annotations


def test_vision_triggered_when_image(client, mock_llm, mock_vision):
    title = "请看图片作答 http://example.com/question.png"
    r = client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"]})
    assert r.json()["code"] == 1
    assert len(mock_vision) == 1  # 识图被调用


def test_vision_not_triggered_without_image(client, mock_llm, mock_vision):
    r = client.post("/search", json={"title": "纯文字题目", "type": "single", "options": ["A", "B"]})
    assert r.json()["code"] == 1
    assert len(mock_vision) == 0  # 无图不调用


def test_vision_failure_degrades(client, mock_llm, monkeypatch):
    from app.llm import vision as vmod

    def boom(title, options):
        raise RuntimeError("识图服务不可用")

    monkeypatch.setattr(vmod, "recognize", boom)
    title = "图片题 http://example.com/x.jpg"
    r = client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"]})
    # 识图失败仍应降级为文本答题成功
    assert r.json()["code"] == 1
