import pytest

from libretranslate.gui_settings import (
    normalize_chat_url, validate_ai, validate_ui, validate_base_url,
    save_settings, read_settings,
)
from libretranslate.default_values import _default_options_objects


def test_openai_url_normalization():
    assert normalize_chat_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
    assert normalize_chat_url("https://example.com") == "https://example.com/v1/chat/completions"
    assert normalize_chat_url("http://localhost:11434/v1") == "http://localhost:11434/v1/chat/completions"


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://192.168.0.1/v1", "https://user:pass@example.com",
    "https://example.com/#fragment", "not-a-url",
])
def test_provider_url_rejected(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_ui_ranges():
    with pytest.raises(ValueError):
        validate_ui({"compare_count": 99})
    with pytest.raises(ValueError):
        validate_ui({"unknown": True})
    assert validate_ui({"theme": "dark"})["theme"] == "dark"


def test_provider_key_masking_and_preservation(tmp_path, monkeypatch):
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    provider = {
        "id": "first", "name": "Local AI", "model": "sample",
        "base_url": "http://localhost:11434/v1", "enabled": True, "api_key": "secret",
    }
    save_settings({"ai": {"providers": [provider]}}, _default_options_objects)
    saved = read_settings()
    assert saved["ai"]["providers"][0]["api_key"] == "secret"
    updated = dict(provider)
    updated.pop("api_key")
    save_settings({"ai": {"providers": [updated]}}, _default_options_objects)
    assert read_settings()["ai"]["providers"][0]["api_key"] == "secret"
    assert validate_ai({"providers": [updated]}, read_settings()["ai"])["providers"][0]["api_key"] == "secret"


def test_server_options_reject_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    with pytest.raises(ValueError):
        save_settings({"server": {"UNEXPECTED": "oops"}}, _default_options_objects)
