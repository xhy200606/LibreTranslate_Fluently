"""Offline tests for weighted routing, AI reading cards, and FluentRead dictionaries."""
import copy
import os

import pytest
from flask import Flask

from libretranslate import free_providers
from libretranslate.gui_settings import DEFAULT_AI, DEFAULT_UI, validate_ai
from libretranslate.free_providers import FREE_DEFAULTS, routing_snapshot
from libretranslate.reading_presets import AI_PRESETS, READING_DEFAULTS
from libretranslate.word_dictionary import SOURCES, _local, lookup_word
from libretranslate.fluently import fluently


@pytest.fixture(autouse=True)
def reset_free_health():
    with free_providers._LOCK:
        for item in free_providers._HEALTH.values():
            item.last_ms = 0
            item.cooldown_until = 0.0
            item.success_count = 0
            item.failure_count = 0
            item.selections = 0
    yield


def test_balanced_mode_and_default_pool():
    assert FREE_DEFAULTS["mode"] == "balanced"
    assert DEFAULT_UI["default_engine"] == "freeAuto"
    settings = dict(FREE_DEFAULTS, enabled=["bilibiliFree", "microsoft", "myMemory"])
    snapshot = routing_snapshot(settings, "en", "zh")
    assert snapshot["mode"] == "balanced"
    assert snapshot["weight_total"] == 100
    assert round(sum(snapshot["weights"].values()), 1) == 100.0
    assert snapshot["weights"]["microsoft"] > snapshot["weights"]["myMemory"]


def test_language_incompatible_source_does_not_receive_traffic():
    settings = dict(FREE_DEFAULTS, enabled=["bilibiliFree", "apertiumFree"])
    snapshot = routing_snapshot(settings, "en", "zh")
    assert snapshot["weights"]["apertiumFree"] == 0
    assert snapshot["weights"]["bilibiliFree"] == 100


def test_cooldown_drops_share_and_weight_renormalizes():
    settings = dict(FREE_DEFAULTS, enabled=["microsoft", "bilibiliFree", "myMemory"])
    with free_providers._LOCK:
        free_providers._HEALTH["microsoft"].cooldown_until = free_providers.time.monotonic() + 500
    snapshot = routing_snapshot(settings, "en", "zh")
    assert snapshot["weights"]["microsoft"] == 0
    assert sum(snapshot["weights"].values()) == 100.0


def test_sampled_balanced_fallback(monkeypatch):
    settings = dict(FREE_DEFAULTS, enabled=["bilibiliFree", "microsoft"],
                    order=["bilibiliFree", "microsoft"], mode="balanced")
    chosen = []
    def translate(provider, text, source, target, config, deadline=None):
        chosen.append(provider)
        return "译文"
    monkeypatch.setattr(free_providers, "translate", translate)
    monkeypatch.setattr(free_providers.random, "choices",
                        lambda items, weights, k: ["bilibiliFree"])
    result = free_providers.translate_with_fallback("Hello", "en", "zh", settings)
    assert result["provider_id"] == "bilibiliFree"
    assert free_providers._HEALTH["bilibiliFree"].selections == 1
    assert chosen == ["bilibiliFree"]


def test_dictionary_sources_match_reference():
    assert {s["id"] for s in SOURCES} == {
        "auto", "ecdict-local", "youdao-web", "free-dictionary",
        "wiktionary-rest", "wiktapi", "datamuse",
    }


def test_local_ecdict_includes_common_word():
    card = lookup_word("curious", "ecdict-local")
    assert card is not None
    assert card["word"] == "curious"
    assert card["meanings"]
    assert "ecdict-local" in card["sources"]


def test_dictionary_prevents_arbitrary_destination():
    with pytest.raises(ValueError):
        lookup_word("https://localhost/secret", "auto")
    with pytest.raises(ValueError):
        lookup_word("curious", "random-provider")


def test_ai_catalog_has_supported_families_and_bilibili():
    assert len(AI_PRESETS) >= 22
    by_id = {p["id"]: p for p in AI_PRESETS}
    assert by_id["bilibiliFree"]["protocol"] == "bilibili"
    assert by_id["claude"]["protocol"] == "anthropic"
    assert by_id["gemini"]["protocol"] == "gemini"
    assert by_id["openai"]["protocol"] == "openai"


def test_reading_prompts_and_provider_schema():
    assert set(READING_DEFAULTS["prompts"]) == {
        "system", "meaning", "grammar", "usage", "practice",
    }
    value = validate_ai({"reading":{"dictionary_source":"datamuse",
                                    "analysis_provider_id":"bilibiliFree",
                                    "prompts":{"grammar":"Check the syntactic backbone."}}})
    assert value["reading"]["prompts"]["grammar"] == "Check the syntactic backbone."
    assert value["reading"]["prompts"]["meaning"]
    with pytest.raises(ValueError):
        validate_ai({"reading":{"dictionary_source":"untrusted"}})


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.delenv("LT_SETTINGS_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    app = Flask(__name__)
    app.register_blueprint(fluently)
    app.testing = True
    return app.test_client()


def test_reading_api_accepts_word_and_context(app_client, monkeypatch):
    inputs = {}
    def mocked_chat(messages, **kwargs):
        inputs["messages"] = messages
        return "### 主干\nEvery language offers.\n\n| Text | POS | Role | Meaning |\n|---|---|---|---|\n| Every language | noun phrase | 主语 | 每一种语言 |"
    monkeypatch.setattr("libretranslate.fluently.bilibili_chat", mocked_chat)
    result = app_client.post("/fluently/api/reading", json={
        "action":"grammar", "text":"Every language offers.",
        "context":"Every language offers a new way to see the world.",
        "target":"zh",
    })
    assert result.status_code == 200
    assert "Every language" in result.get_json()["text"]
    assert "paragraph_context_untrusted" in inputs["messages"][1]["content"]


def test_dictionary_route_is_write_authenticated_when_configured(app_client, monkeypatch):
    monkeypatch.setenv("LT_SETTINGS_ADMIN_TOKEN", "admin-secret")
    response = app_client.post("/fluently/api/dictionary", json={"word":"curious"})
    assert response.status_code == 401
    response2 = app_client.post("/fluently/api/dictionary",
                                headers={"Authorization":"Bearer admin-secret"},
                                json={"word":"curious"})
    assert response2.status_code == 200


def test_routing_endpoint_exposes_weights_no_keys(app_client):
    response = app_client.get("/fluently/api/free/routing?source=en&target=zh")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] == "balanced"
    assert "weights" in payload and payload["weight_total"] == 100.0


def test_fluently_native_anthropic_adapter(monkeypatch):
    from libretranslate.fluently import _call_provider
    from types import SimpleNamespace
    captured = {}
    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return SimpleNamespace(
            status_code=200, content=b'{"content":[]}',
            json=lambda:{"stop_reason":"end_turn","content":[{"type":"text","text":"你好"}]},
        )
    monkeypatch.setattr("libretranslate.fluently._destination_safe", lambda url: None)
    monkeypatch.setattr("libretranslate.fluently.requests.post", fake_post)
    provider = {"protocol":"anthropic", "base_url":"https://api.anthropic.com/v1/messages",
                "api_key":"private-token","model":"claude"}
    reply = _call_provider(provider,[{"role":"system","content":"Translate"},
                                    {"role":"user","content":"Hello"}],
                           {"temperature":0.2,"max_tokens":128,"timeout":8})
    assert reply == "你好"
    assert captured["headers"]["x-api-key"] == "private-token"
    assert captured["json"]["system"] == "Translate"
    assert "Authorization" not in captured["headers"]


def test_fluently_native_gemini_adapter(monkeypatch):
    from libretranslate.fluently import _call_provider
    from types import SimpleNamespace
    captured={}
    def fake_post(url, **kwargs):
        captured["url"]=url
        captured.update(kwargs)
        return SimpleNamespace(status_code=200, content=b'{"candidates":[]}',
                               json=lambda:{"candidates":[{"finishReason":"STOP",
                                  "content":{"parts":[{"text":"译文"},{"text":"hidden","thought":True}]}}]})
    monkeypatch.setattr("libretranslate.fluently._destination_safe", lambda url: None)
    monkeypatch.setattr("libretranslate.fluently.requests.post", fake_post)
    provider={"protocol":"gemini",
              "base_url":"https://generativelanguage.googleapis.com/v1beta/models",
              "api_key":"test-only","model":"gemini-test"}
    reply=_call_provider(provider,[{"role":"system","content":"Translate"},
                                  {"role":"user","content":"Hello"}],
                         {"temperature":0.1,"max_tokens":128,"timeout":8})
    assert reply == "译文"
    assert captured["url"].endswith("/gemini-test:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "test-only"


def test_homepage_compact_and_toasts():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "templates" / "fluently.html").read_text(encoding="utf-8")
    settings = (root / "templates" / "fluently_settings.html").read_text(encoding="utf-8")
    assert "英文版本对照</h1>" not in html
    assert 'class="fluently-toast' in html
    assert 'class="fluently-toast' in settings
    assert "fluently-logo.svg" in html and "fluently-logo.svg" in settings
    assert 'id="analysis-structure"' in html
    assert 'id="dictionary-details"' in html
    assert 'id="free-weight-total"' in settings
    assert 'data-reading-prompt="grammar"' in settings


def test_version_layout_stacks_cards_and_keeps_original_translation_horizontal():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    styles = (root / "static" / "css" / "fluently.css").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "fluently.js").read_text(encoding="utf-8")
    html = (root / "templates" / "fluently.html").read_text(encoding="utf-8")

    assert ".compare-workspace .versions-grid{" in styles
    assert "grid-template-columns:minmax(0,1fr);" in styles
    assert '"source translation"' in styles
    assert '"head head"' in styles and '"footer footer"' in styles
    assert '@media(max-width:760px)' in styles
    assert '"source"' in styles and '"translation"' in styles
    assert "resize:none;" in styles
    assert "function syncVersionRowHeight(versionId)" in script
    assert "input.scrollHeight" in script and "output.scrollHeight" in script
    assert "Math.max(sourceHeight, targetHeight)" in script
    assert "syncVersionRowHeight(version.id)" in script
    assert "window.addEventListener('resize'" in script
    assert 'id="versions"' in html
    assert "v='5'" in html
