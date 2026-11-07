"""Offline tests: never send text to external translation providers."""
import pytest

from libretranslate.alignment import align, sentences, validate_ai_groups
from libretranslate.free_providers import (
    CATALOG, CATALOG_IDS, FREE_DEFAULTS, FreeProtocolError, _line_chunks,
    translate, translate_with_fallback,
)
from libretranslate.gui_settings import validate_free


def test_all_sixteen_protocols_registered():
    assert len(CATALOG) == 16
    assert len(CATALOG_IDS) == 16
    assert {"bilibiliFree", "microsoft", "myMemory", "doubaoWeb"}.issubset(CATALOG_IDS)


def test_alignment_supports_split_and_offsets():
    result = align("Hello world.", "你好。 世界。")
    assert len(result["source"]) == 1
    assert len(result["target"]) == 2
    assert result["groups"][0]["source_ids"] == [0]
    assert result["groups"][0]["target_ids"] == [0, 1]
    assert result["source"][0]["start"] == 0
    assert result["source"][0]["end"] == 12


def test_alignment_handles_merge_and_empty():
    assert align("", "译文")["groups"] == []
    result = align("Hello. World.", "你好世界。")
    assert result["groups"] and sum(
        len(g["source_ids"]) for g in result["groups"]
    ) == len(result["source"])


def test_alignment_ignores_decimal_periods():
    actual = sentences("It costs 3.14 dollars. Keep reading.")
    assert len(actual) == 2


def test_ai_alignment_refuses_hallucinated_indexes():
    assert len(validate_ai_groups([{"source_ids": [0, 1], "target_ids": [0]}], 2, 1)) == 1
    with pytest.raises(ValueError):
        validate_ai_groups([{"source_ids": [0, 0], "target_ids": [0]}], 2, 1)
    with pytest.raises(ValueError):
        validate_ai_groups([{"source_ids": [1], "target_ids": [0]}], 2, 1)


def test_free_configuration_validation():
    result = validate_free({"mode": "balanced", "my_memory_email": "tester@example.org"})
    assert result["my_memory_email"] == "tester@example.org"
    with pytest.raises(ValueError):
        validate_free({"enabled": []})
    with pytest.raises(ValueError):
        validate_free({"order": ["unknown"]})
    with pytest.raises(ValueError):
        validate_free({"my_memory_email": "bad address"})


def test_chunking_preserves_unicode_and_whitespace():
    source = " 你好 " * 190 + "\n" + " Hello. " * 220
    chunks = list(_line_chunks(source, 500, True))
    assert "".join(p + t + s for p, t, s in chunks) == source
    assert all(len(t.encode("utf-8")) <= 500 for _, t, _ in chunks)


def test_mymemory_mocked_protocol(monkeypatch):
    calls = []

    def fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return {"responseStatus": 200, "responseData": {"translatedText": "你好"}}

    monkeypatch.setattr("libretranslate.free_providers._request", fake_request)
    value = translate("myMemory", "Hello world", "en", "zh", FREE_DEFAULTS)
    assert value == "你好"
    assert calls[0][0] == "GET"
    assert calls[0][2]["params"]["langpair"] == "en|zh-CN"


def test_bilibili_mocked_protocol(monkeypatch):
    def fake_request(method, endpoint, **kwargs):
        assert method == "POST"
        assert "index-translate.bilibili.com" in endpoint
        assert kwargs["json_body"]["model"] == "Index-Translate-35B-A3B"
        return {"choices": [{"finish_reason": "stop",
                             "message": {"content": "<think>reasoning</think>你好！"}}]}

    monkeypatch.setattr("libretranslate.free_providers._request", fake_request)
    assert translate("bilibiliFree", "Hello", "en", "zh", FREE_DEFAULTS) == "你好！"


def test_free_fallback_without_network(monkeypatch):
    calls = []

    def fake_translate(provider_id, text, source, target, settings, **kwargs):
        calls.append(provider_id)
        if provider_id == "google":
            raise FreeProtocolError("limited", 429, "rate-limit")
        return "translated"

    monkeypatch.setattr("libretranslate.free_providers.translate", fake_translate)
    settings = dict(FREE_DEFAULTS, order=["google", "microsoft"], enabled=["google", "microsoft"],
                    mode="sequential", total_timeout=20)
    result = translate_with_fallback("Hello", "en", "zh", settings)
    assert result["provider_id"] == "microsoft"
    assert result["text"] == "translated"
    assert calls == ["google", "microsoft"]
