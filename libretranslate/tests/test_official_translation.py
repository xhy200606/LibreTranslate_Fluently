"""Offline contract tests for official FluentRead-style translation APIs.

No real external request is sent; all credentials are dummy values.
"""
import copy
import hashlib
import hmac
import json
import re

import pytest
from flask import Flask

from libretranslate import official_translation as official
from libretranslate.fluently import fluently, normalize_responses_url
from libretranslate.default_values import _default_options_objects
from libretranslate.gui_settings import (
    validate_cloud, read_settings, save_settings, public_settings, admin_settings,
)


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("LT_SETTINGS_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH", str(tmp_path / "settings.json"))


def test_nine_official_protocols_and_signatures():
    assert len(official.SERVICE_PRESETS) == 9
    form = official.baidu_form("Hello", "en", "zh", "app", "secret", "123")
    assert form["sign"] == hashlib.md5(b"appHello123secret").hexdigest()
    signed = official.youdao_form("Hello", "en", "zh-CHS", "app", "secret", "salt", "1234")
    assert signed["sign"] == hashlib.sha256(b"appHellosalt1234secret").hexdigest()
    auth = official.tc3_authorization('{"SourceText":"Hi"}', "my-secret-id",
                                       "dummy-secret", 1700000000)
    assert auth.startswith("TC3-HMAC-SHA256 Credential=my-secret-id/")
    assert re.search(r"Signature=[0-9a-f]{64}$", auth)
    aliyun = official.aliyun_form(
        "Hello", "en", "zh", "my-id", "secret", "cn-hangzhou",
        nonce="nonce", now=official.dt.datetime(2024,1,1,tzinfo=official.dt.timezone.utc),
    )
    assert aliyun["Signature"] and aliyun["SignatureNonce"] == "nonce"
    assert aliyun["Timestamp"] == "2024-01-01T00:00:00Z"


def test_official_cloud_provider_secrets_masked_preserved_and_cleared():
    item = {"id":"mt_test", "service":"baidu", "name":"百度翻译",
            "enabled":True, "region":"", "endpoint":"",
            "key_id":"APP-ID", "secret":"sensitive"}
    save_settings({"cloud":{"providers":[item]}}, _default_options_objects)
    raw = read_settings()["cloud"]["providers"][0]
    assert raw["key_id"] == "APP-ID" and raw["secret"] == "sensitive"
    for output in (public_settings(), admin_settings(_default_options_objects)):
        assert "APP-ID" not in json.dumps(output)
        assert "sensitive" not in json.dumps(output)
    public = public_settings()["cloud"]["providers"][0]
    assert public["configured"] is True
    masked = admin_settings(_default_options_objects)["cloud"]["providers"][0]
    assert masked["has_key_id"] is True and masked["has_secret"] is True
    save_settings({"cloud":{"providers":[
        {"id":"mt_test","service":"baidu","name":"百度翻译",
         "region":"","endpoint":"","enabled":True}
    ]}}, _default_options_objects)
    assert read_settings()["cloud"]["providers"][0]["secret"] == "sensitive"
    save_settings({"cloud":{"providers":[{
        "id":"mt_test","service":"baidu","name":"百度翻译",
        "region":"","endpoint":"","enabled":True,"clear_secret":True,
    }]}}, _default_options_objects)
    assert read_settings()["cloud"]["providers"][0]["secret"] == ""
    assert public_settings()["cloud"]["providers"][0]["configured"] is False


@pytest.mark.parametrize("bad",[
    {"id":"invalid provider","service":"baidu","name":"Baidu"},
    {"id":"mt_test","service":"unknown","name":"Unknown"},
    {"id":"mt_test","service":"deepl","name":"DeepL","region":"mars"},
    {"id":"mt_test","service":"aliyun","name":"Aliyun","region":"evil.example.com"},
    {"id":"mt_test","service":"baidu","name":"Baidu","endpoint":"http://192.168.1.1"},
])
def test_configuration_rejects_unknown_or_unsafe_service(bad):
    with pytest.raises(ValueError):
        validate_cloud({"providers":[bad]})


def test_official_adapters_against_synthetic_responses(monkeypatch):
    replies = {
        "deepl": {"translations":[{"text":"译文"}]},
        "deeplx": {"code":200,"data":"译文"},
        "baidu": {"error_code":52000,"trans_result":[{"dst":"译文"}]},
        "youdao": {"errorCode":"0","translation":["译文"]},
        "tencent": {"Response":{"TargetText":"译文"}},
        "google-cloud": {"data":{"translations":[{"translatedText":"译文"}]}},
        "azure-translator": [{"translations":[{"text":"译文"}]}],
        "aliyun": {"Code":"200","Data":{"Translated":"译文"}},
        "xiaoniu": {"tgt_text":"译文"},
    }
    for service, reply in replies.items():
        observed=[]
        def mocked_request(url, **kwargs):
            observed.append((url,kwargs))
            assert kwargs.get("destination_guard") is not None
            return reply
        monkeypatch.setattr(official, "_request", mocked_request)
        item={"service":service,"key_id":"fake-key","secret":"fake-secret",
              "region":"free" if service=="deepl" else "cn-hangzhou" if service=="aliyun"
              else "global" if service=="azure-translator" else "",
              "endpoint":"https://trusted.example/translate" if service=="deeplx" else ""}
        actual=official.translate(item,"Hello world.","en","zh",destination_guard=lambda u:None)
        assert actual == "译文"
        assert len(observed)==1
        assert observed[0][0].startswith("https://")


def test_official_translation_rejects_invalid_language_and_missing_key():
    with pytest.raises(ValueError):
        official.translate({"service":"deepl", "key_id":""},"Hello","en","auto")
    with pytest.raises(ValueError):
        official.translate({"service":"baidu", "key_id":"", "secret":""},"Hello","en","zh")
    with pytest.raises(ValueError):
        official.translate({"service":"deeplx", "endpoint":""},"Hello","en","zh")


def test_cloud_endpoint_disabled_fails_without_network(monkeypatch):
    app=Flask(__name__)
    app.register_blueprint(fluently)
    app.testing=True
    client=app.test_client()
    response=client.post("/fluently/api/cloud/translate",
                         json={"provider_id":"does-not-exist","text":"Hello","source":"en","target":"zh"})
    assert response.status_code == 404
    save_settings({"cloud":{"providers":[
        {"id":"mt_demo","name":"My DeepL","service":"deepl","enabled":True,
         "key_id":"private-key","region":"free","endpoint":""}
    ]}}, _default_options_objects)
    called=[]
    def fake_translate(provider, text, source, target, **kwargs):
        called.append(provider["key_id"])
        return "你好"
    monkeypatch.setattr("libretranslate.fluently.translate_official",fake_translate)
    okay=client.post("/fluently/api/cloud/translate",
                     json={"provider_id":"mt_demo","text":"Hello","source":"en","target":"zh"})
    assert okay.status_code==200
    assert okay.get_json()["text"]=="你好"
    assert called==["private-key"]
    assert "private-key" not in json.dumps(okay.get_json())


def test_responses_api_path_normalization_and_output(monkeypatch):
    assert normalize_responses_url("https://api.openai.com/v1") == "https://api.openai.com/v1/responses"
    assert normalize_responses_url("https://api.openai.com/v1/chat/completions") == "https://api.openai.com/v1/responses"
    assert normalize_responses_url("https://example.com/v1/responses") == "https://example.com/v1/responses"
    assert normalize_responses_url("https://example.com/v1?foo=bar").endswith("/v1/responses?foo=bar")
    from libretranslate.fluently import _call_provider
    from types import SimpleNamespace
    received={}
    def fake_post(url, **kwargs):
        received["url"]=url
        received.update(kwargs)
        return SimpleNamespace(status_code=200, content=b'{"output":[]}',
                               json=lambda:{"status":"completed","output":[
                                   {"type":"message","content":[{"type":"output_text","text":"翻译"}]}]})
    monkeypatch.setattr("libretranslate.fluently._destination_safe", lambda u:None)
    monkeypatch.setattr("libretranslate.fluently.requests.post", fake_post)
    provider={"protocol":"responses","base_url":"https://api.openai.com/v1",
              "model":"gpt-4.1-mini","api_key":"dummy-key"}
    value=_call_provider(provider, [
        {"role":"system","content":"Translate to Chinese"},
        {"role":"user","content":"hello"},
    ],{"max_tokens":100,"timeout":10,"temperature":0.2})
    assert value=="翻译"
    assert received["json"]["instructions"]=="Translate to Chinese"
    assert received["json"]["input"]=="hello"
    assert received["url"]=="https://api.openai.com/v1/responses"
