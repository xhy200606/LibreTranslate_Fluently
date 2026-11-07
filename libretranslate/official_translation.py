"""Official machine-translation adapters corresponding to FluentRead's native APIs.

Unlike keyless web providers these require the operator's own credentials.
All official endpoints are fixed; only self-hosted DeepLX can use a custom URL.
No credentials are returned by GUI read APIs or copied to the browser.
"""
import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

import requests

SERVICE_PRESETS = [
    {"id": "deepl", "name": "DeepL API", "key_label": "DeepL Auth Key",
     "secret_label": "", "region_label": "套餐（free / pro）", "default_region": "free",
     "description": "官方文本翻译 v2；使用 DeepL Free 或 Pro 套餐"},
    {"id": "deeplx", "name": "DeepLX 自建代理", "key_label": "可选 Bearer Token",
     "secret_label": "", "region_label": "", "default_region": "",
     "custom_endpoint": True, "description": "需提供可信的自建 DeepLX /translate URL"},
    {"id": "baidu", "name": "百度翻译开放平台", "key_label": "APP ID",
     "secret_label": "密钥", "region_label": "", "default_region": "",
     "description": "开放平台通用翻译；MD5 签名"},
    {"id": "youdao", "name": "有道智云", "key_label": "App Key",
     "secret_label": "App Secret", "region_label": "", "default_region": "",
     "description": "有道 v3 SHA-256 签名"},
    {"id": "tencent", "name": "腾讯云机器翻译", "key_label": "SecretId",
     "secret_label": "SecretKey", "region_label": "", "default_region": "",
     "description": "腾讯云 TMT，TC3-HMAC-SHA256 签名"},
    {"id": "google-cloud", "name": "Google Cloud Translation", "key_label": "API Key",
     "secret_label": "", "region_label": "", "default_region": "",
     "description": "Cloud Translation v2 官方 REST API"},
    {"id": "azure-translator", "name": "Azure AI Translator", "key_label": "Subscription Key",
     "secret_label": "", "region_label": "Region（global / eastus 等）",
     "default_region": "global", "description": "Translator Text v3 官方 REST API"},
    {"id": "aliyun", "name": "阿里云机器翻译", "key_label": "AccessKey ID",
     "secret_label": "AccessKey Secret", "region_label": "地域（cn-hangzhou 等）",
     "default_region": "cn-hangzhou", "description": "通用 TranslateGeneral，RPC HMAC-SHA1 签名"},
    {"id": "xiaoniu", "name": "小牛翻译", "key_label": "API Key",
     "secret_label": "", "region_label": "", "default_region": "",
     "description": "小牛翻译官方 REST API"},
]
SERVICE_MAP = {item["id"]: item for item in SERVICE_PRESETS}
ALLOWED_ALI_REGIONS = {"cn-hangzhou", "cn-shanghai", "cn-beijing", "cn-shenzhen",
                       "ap-southeast-1", "us-west-1"}
LANGUAGES = {
    "zh-hans": "zh", "zh-cn": "zh", "zh": "zh",
    "zh-tw": "zh-tw", "zh-hant": "zh-tw",
}
CLOUD_MAX_CHARS = 10000


def _lang(code, service, target=False):
    if not isinstance(code, str) or not code or len(code) > 30:
        raise ValueError("Invalid language")
    name = code.lower().replace("_", "-")
    import re
    if not re.fullmatch(r"[a-z]{2,4}(?:-[a-z0-9]{2,8})*|auto", name):
        raise ValueError("Invalid language")
    if target and name == "auto":
        raise ValueError("Target language cannot be auto")
    name = LANGUAGES.get(name, name)
    special = {
        "deepl": {"zh": "ZH", "zh-tw": "ZH-HANT", "fil": "TL"},
        "deeplx": {"zh": "ZH", "zh-tw": "ZH-HANT", "fil": "TL"},
        "baidu": {"zh-tw": "cht", "ja": "jp", "ko": "kor",
                  "fr": "fra", "es": "spa", "ar": "ara", "vi": "vie"},
        "youdao": {"zh": "zh-CHS", "zh-tw": "zh-CHT"},
        "tencent": {"zh-tw": "zh-TW"},
        "google-cloud": {"zh": "zh-CN", "zh-tw": "zh-TW"},
        "azure-translator": {"zh": "zh-Hans", "zh-tw": "zh-Hant"},
        "aliyun": {"zh-tw": "zh-tw"},
        "xiaoniu": {"zh-tw": "cht", "nb": "no"},
    }
    if service in ("deepl", "deeplx"):
        return special[service].get(name, name.upper())
    return special.get(service, {}).get(name, name)


def _require(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(where + " returned empty translation")
    return value


def _request(url, *, headers=None, body=None, form=None, timeout=15, destination_guard=None):
    if destination_guard:
        destination_guard(url)
    try:
        response = requests.post(
            url, json=body, data=form, headers=headers,
            timeout=min(30, max(1, timeout)), allow_redirects=False,
        )
    except requests.RequestException as error:
        raise ValueError("Translation provider network request failed") from error
    if response.status_code != 200:
        # Avoid echoing full upstream responses: they may contain sensitive text.
        raise ValueError("Translation provider returned HTTP " + str(response.status_code))
    if len(response.content) > 2_000_000:
        raise ValueError("Translation response exceeded size limit")
    try:
        return response.json()
    except ValueError as error:
        raise ValueError("Translation provider returned non-JSON response") from error


def baidu_form(text, source, target, app_id, secret, salt):
    return {
        "q": text, "from": source, "to": target, "appid": app_id,
        "salt": salt,
        "sign": hashlib.md5((app_id + text + salt + secret).encode("utf-8")).hexdigest(),
    }


def youdao_form(text, source, target, app_key, secret, salt, current_time):
    # Length is UTF-16 code units in JavaScript. Use that for parity with
    # the FluentRead truncate() implementation and the official signed input.
    units = text.encode("utf-16-le")
    length = len(units) // 2
    if length > 20:
        first = units[:20].decode("utf-16-le", "surrogatepass")
        last = units[-20:].decode("utf-16-le", "surrogatepass")
        input_text = first + str(length) + last
    else:
        input_text = text
    signature = hashlib.sha256(
        (app_key + input_text + salt + current_time + secret).encode("utf-8")
    ).hexdigest()
    return {
        "q": text, "from": source, "to": target, "appKey": app_key,
        "salt": salt, "sign": signature, "signType": "v3", "curtime": current_time,
    }


def tc3_authorization(payload, secret_id, secret_key, timestamp):
    date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m-%d")
    hashed = hashlib.sha256(payload.encode("utf8")).hexdigest()
    canonical = ("POST\n/\n\ncontent-type:application/json; charset=utf-8\n"
                 "host:tmt.tencentcloudapi.com\n\ncontent-type;host\n" + hashed)
    scope = date + "/tmt/tc3_request"
    string_to_sign = ("TC3-HMAC-SHA256\n" + str(timestamp) + "\n" +
                      scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest())
    def digest(key, message):
        return hmac.new(key, message.encode(), hashlib.sha256).digest()
    key_date = digest(("TC3" + secret_key).encode(), date)
    key_service = digest(key_date, "tmt")
    signing_key = digest(key_service, "tc3_request")
    signature = digest(signing_key, string_to_sign).hex()
    return ("TC3-HMAC-SHA256 Credential=" + secret_id + "/" + scope +
            ", SignedHeaders=content-type;host, Signature=" + signature)


def aliyun_form(text, source, target, key_id, secret, region, now=None, nonce=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    params = {
        "Action": "TranslateGeneral", "FormatType": "text", "Scene": "general",
        "SourceLanguage": source, "TargetLanguage": target, "SourceText": text,
        "Format": "JSON", "Version": "2018-10-12",
        "AccessKeyId": key_id, "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0", "SignatureNonce": nonce or str(uuid.uuid4()),
        "Timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # RFC 3986 canonical query sorted by key.
    query = urlencode(sorted(params.items()), quote_via=quote, safe="~")
    canonical = "POST&%2F&" + quote(query, safe="~")
    signature = hmac.new((secret + "&").encode(), canonical.encode(), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(signature).decode()
    return params


def translate(provider, text, source, target, timeout=15, destination_guard=None):
    service = provider.get("service")
    if service not in SERVICE_MAP:
        raise ValueError("Unknown official translator")
    if not isinstance(text, str) or not text.strip() or len(text) > CLOUD_MAX_CHARS:
        raise ValueError("Translation text must be between 1 and 10000 characters")
    src = _lang(source, service)
    dst = _lang(target, service, target=True)
    key = provider.get("key_id", "")
    secret = provider.get("secret", "")
    region = provider.get("region", SERVICE_MAP[service]["default_region"])
    headers = {"Content-Type": "application/json; charset=utf-8",
               "Accept": "application/json"}
    if service == "deepl":
        if not key:
            raise ValueError("DeepL API key not configured")
        url = ("https://api.deepl.com/v2/translate" if region == "pro"
               else "https://api-free.deepl.com/v2/translate")
        payload = {"text": [text], "target_lang": dst, "preserve_formatting": True}
        if src != "AUTO":
            payload["source_lang"] = "ZH" if src == "ZH-HANT" else src
        headers["Authorization"] = "DeepL-Auth-Key " + key
        data = _request(url, headers=headers, body=payload, timeout=timeout,
                        destination_guard=destination_guard)
        items = data.get("translations") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != 1:
            raise ValueError("DeepL response slot count mismatch")
        return _require(items[0].get("text"), "DeepL")
    if service == "deeplx":
        url = provider.get("endpoint", "")
        if not url:
            raise ValueError("Set your trusted DeepLX server URL in GUI")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        data = _request(url, headers=headers, body={
            "text": text, "source_lang": src, "target_lang": dst,
        }, timeout=timeout, destination_guard=destination_guard)
        if not isinstance(data, dict) or data.get("code", 200) != 200:
            raise ValueError("DeepLX service reported an error")
        return _require(data.get("data"), "DeepLX")
    if service == "baidu":
        if not key or not secret:
            raise ValueError("Baidu App ID and secret required")
        form = baidu_form(text, src, dst, key, secret, str(int(time.time()*1000)))
        data = _request("https://fanyi-api.baidu.com/api/trans/vip/translate",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        form=form, timeout=timeout, destination_guard=destination_guard)
        if not isinstance(data, dict) or str(data.get("error_code", "52000")) != "52000":
            raise ValueError("Baidu returned an error code")
        parts = data.get("trans_result")
        if not isinstance(parts, list) or not parts or not all(
            isinstance(x, dict) and isinstance(x.get("dst"), str) for x in parts
        ):
            raise ValueError("Baidu response format invalid")
        return _require("\n".join(x["dst"] for x in parts), "Baidu")
    if service == "youdao":
        if not key or not secret:
            raise ValueError("Youdao App Key and Secret required")
        nonce = str(int(time.time()*1000))
        form = youdao_form(text, src, dst, key, secret, nonce, str(int(time.time())))
        data = _request("https://openapi.youdao.com/api",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        form=form, timeout=timeout, destination_guard=destination_guard)
        if not isinstance(data, dict) or str(data.get("errorCode")) != "0":
            raise ValueError("Youdao returned an error code")
        result = data.get("translation")
        if not isinstance(result, list) or not result or not all(
            isinstance(x, str) for x in result
        ):
            raise ValueError("Youdao response format invalid")
        return _require(" ".join(result), "Youdao")
    if service == "tencent":
        if not key or not secret:
            raise ValueError("Tencent SecretId and SecretKey required")
        payload = {"SourceText": text, "Source": src, "Target": dst, "ProjectId": 0}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        timestamp = int(time.time())
        headers.update({
            "Authorization": tc3_authorization(body, key, secret, timestamp),
            "X-TC-Action": "TextTranslate", "X-TC-Version": "2018-03-21",
            "X-TC-Region": "ap-beijing", "X-TC-Timestamp": str(timestamp),
        })
        # Sign the exact UTF-8 JSON bytes sent on the wire.
        data = _request("https://tmt.tencentcloudapi.com/",
                        headers=headers, form=body.encode("utf-8"), timeout=timeout,
                        destination_guard=destination_guard)
        body_data = data.get("Response", {}) if isinstance(data, dict) else {}
        if body_data.get("Error"):
            raise ValueError("Tencent TMT returned an error")
        return _require(body_data.get("TargetText"), "Tencent TMT")
    if service == "google-cloud":
        if not key:
            raise ValueError("Google Cloud API key required")
        headers["x-goog-api-key"] = key
        body = {"q": [text], "target": dst, "format": "text"}
        if src != "auto":
            body["source"] = src
        data = _request("https://translation.googleapis.com/language/translate/v2",
                        headers=headers, body=body, timeout=timeout,
                        destination_guard=destination_guard)
        if not isinstance(data, dict) or data.get("error"):
            raise ValueError("Google Cloud Translation returned an error")
        parts = (data.get("data") or {}).get("translations")
        if not isinstance(parts, list) or len(parts) != 1:
            raise ValueError("Google Cloud response count invalid")
        translated = parts[0].get("translatedText") if isinstance(parts[0], dict) else None
        return _require(html.unescape(translated) if isinstance(translated, str) else translated,
                        "Google Cloud")
    if service == "azure-translator":
        if not key:
            raise ValueError("Azure subscription key required")
        headers["Ocp-Apim-Subscription-Key"] = key
        if region != "global":
            headers["Ocp-Apim-Subscription-Region"] = region
        query = {"api-version": "3.0", "to": dst, "textType": "plain"}
        if src != "auto":
            query["from"] = src
        url = "https://api.cognitive.microsofttranslator.com/translate?" + urlencode(query)
        data = _request(url, headers=headers, body=[{"Text": text}], timeout=timeout,
                        destination_guard=destination_guard)
        if not isinstance(data, list) or len(data) != 1:
            raise ValueError("Azure response count invalid")
        translations = data[0].get("translations") if isinstance(data[0], dict) else None
        if not isinstance(translations, list) or len(translations) != 1:
            raise ValueError("Azure response format invalid")
        return _require(translations[0].get("text"), "Azure")
    if service == "aliyun":
        if not key or not secret or region not in ALLOWED_ALI_REGIONS:
            raise ValueError("Aliyun credentials or region invalid")
        form = aliyun_form(text, src, dst, key, secret, region)
        data = _request("https://mt." + region + ".aliyuncs.com/",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        form=form, timeout=timeout, destination_guard=destination_guard)
        if not isinstance(data, dict) or str(data.get("Code")) != "200":
            raise ValueError("Aliyun machine translation returned an error")
        return _require((data.get("Data") or {}).get("Translated"), "Aliyun")
    if service == "xiaoniu":
        if not key:
            raise ValueError("Niutrans API key required")
        form = {"from": src, "to": dst, "apikey": key, "src_text": text}
        data = _request("https://api.niutrans.com/NiuTransServer/translationXML",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        form=form, timeout=timeout, destination_guard=destination_guard)
        if not isinstance(data, dict):
            raise ValueError("Niutrans response invalid")
        return _require(data.get("tgt_text"), "Niutrans")
    raise ValueError("Unsupported translator")
