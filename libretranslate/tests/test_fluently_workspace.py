"""Regression coverage for the LAN comparison workspace and free-source probing.

All supplier calls are mocked. This file does not require external internet access.
"""
import pytest
from flask import Flask

from libretranslate.free_providers import (
    BILIBILI_API_URL, BILIBILI_MODEL, CATALOG, FREE_DEFAULTS,
    bilibili_chat,
)
from libretranslate.fluently import fluently
from libretranslate.fluently_probe import probe_all
from libretranslate.gui_settings import DEFAULT_UI, read_settings, validate_ui


def test_comparison_defaults_use_balanced_pool_and_english_to_chinese():
    assert DEFAULT_UI["compare_count"] == 2
    assert DEFAULT_UI["source_language"] == "en"
    assert DEFAULT_UI["target_language"] == "zh"
    assert DEFAULT_UI["default_engine"] == "freeAuto"
    assert FREE_DEFAULTS["order"][0] == "bilibiliFree"
    assert validate_ui({"compare_count": 24})["compare_count"] == 24
    with pytest.raises(ValueError):
        validate_ui({"compare_count": 25})


def test_bilibili_matches_official_public_endpoint(monkeypatch):
    assert BILIBILI_API_URL == "https://index-translate.bilibili.com/v1/chat/completions"
    assert BILIBILI_MODEL == "Index-Translate-35B-A3B"
    observed = {}

    def response(method, url, **kwargs):
        observed.update({"method": method, "url": url, "kwargs": kwargs})
        return {
            "choices": [{"finish_reason": "stop",
                         "message": {"content": "<think>hidden</think>你好，世界。"}}],
        }

    monkeypatch.setattr("libretranslate.free_providers._request", response)
    assert bilibili_chat([{"role": "user", "content": "Hello world."}]) == "你好，世界。"
    assert observed["url"] == BILIBILI_API_URL
    assert observed["method"] == "POST"
    assert observed["kwargs"]["json_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert "Authorization" not in observed["kwargs"]["headers"]


def test_one_click_probe_all_sixteen_and_no_network():
    def fake_translate(ident, text, source, target, settings):
        assert text == "Hello world."
        assert source == "en"
        assert target == ("es" if ident == "apertiumFree" else "zh")
        if ident in ("bilibiliFree", "myMemory"):
            return "你好"
        raise ValueError("offline")

    found = probe_all(FREE_DEFAULTS, translate_fn=fake_translate)
    assert len(found) == len(CATALOG) == 16
    assert {r["id"] for r in found if r["available"]} == {"bilibiliFree", "myMemory"}
    assert all("latency_ms" in r for r in found)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("LT_SETTINGS_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH", str(tmp_path / "gui_settings.json"))
    app = Flask(__name__)
    app.register_blueprint(fluently)
    app.testing = True
    return app.test_client()


def test_lan_settings_work_without_token(client):
    response = client.get("/fluently/api/settings")
    assert response.status_code == 200
    assert response.get_json()["ui"]["default_engine"] == "freeAuto"
    update = client.put("/fluently/api/settings", json={
        "ui":{"theme":"dark","compare_count":4},
    })
    assert update.status_code == 200
    assert read_settings()["ui"]["compare_count"] == 4


def test_cross_origin_configuration_change_rejected(client):
    response = client.put("/fluently/api/settings",
                          headers={"Origin":"https://another-site.example"},
                          json={"ui":{"compare_count":3}})
    assert response.status_code == 403


def test_one_click_probe_persists_only_available_sources(client, monkeypatch):
    def fake_probe(settings):
        return [{"id":"bilibiliFree","name":"B站","available":True,"latency_ms":18,
                 "tested_direction":"en→zh"},
                {"id":"google","name":"Google","available":False,"error":"blocked",
                 "latency_ms":200}]

    monkeypatch.setattr("libretranslate.fluently.probe_all", fake_probe)
    response = client.post("/fluently/api/free/probe",json={"apply_available":True})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["applied"] is True
    assert payload["enabled"] == ["bilibiliFree"]
    assert read_settings()["free"]["enabled"] == ["bilibiliFree"]


def test_bilibili_ai_translation_requires_no_token(client, monkeypatch):
    def fake_translate(ident, text, source, target, settings):
        assert ident == "bilibiliFree"
        assert target == "zh"
        return "中文译文"

    monkeypatch.setattr("libretranslate.fluently.translate_free", fake_translate)
    response = client.post("/fluently/api/ai", json={
        "action": "translate", "provider_id":"bilibiliFree",
        "text": "English", "source": "en", "target": "zh",
    })
    assert response.status_code == 200
    assert response.get_json()["text"] == "中文译文"


def test_empty_probe_does_not_disable_every_source(client, monkeypatch):
    original = read_settings()["free"]["enabled"][:]
    monkeypatch.setattr("libretranslate.fluently.probe_all", lambda _: [
        {"id": "bilibiliFree", "name": "B站", "available": False,
         "latency_ms": 200, "error": "timeout"}
    ])
    response = client.post("/fluently/api/free/probe", json={"apply_available": True})
    assert response.status_code == 200
    assert response.get_json()["applied"] is False
    assert read_settings()["free"]["enabled"] == original


def test_comparison_template_single_engine_and_shared_word_popup():
    from pathlib import Path
    folder = Path(__file__).resolve().parents[1]
    html = (folder / "templates" / "fluently.html").read_text(encoding="utf-8")
    js = (folder / "static" / "js" / "fluently.js").read_text(encoding="utf-8")
    assert html.count('id="engine"') == 1
    assert 'id="add-version"' in html
    assert 'id="versions"' in html
    assert 'id="selection-translation"' in html
    assert 'id="selection-ai-section"' in html
    assert 'id="selection-analysis"' in html
    assert "showSelectedText(version, 'source'" in js
    assert "showSelectedText(version, 'target'" in js
    assert "config.ui.deep_explain" in js
    assert "translateText(selected,source,target)" in js
