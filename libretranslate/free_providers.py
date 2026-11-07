"""Keyless translation adapters inspired by documented FluentRead protocols.

Each adapter calls only a fixed, supplier-operated endpoint. These are public
web protocols, NOT guaranteed/contracted APIs. No user cookies or API keys are
forwarded. Failure is surfaced to the caller; never present a failed response
as a successful translation.
"""
import base64
import hashlib
import html
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

CATALOG = (
    ("microsoft", "微软 Edge", "Edge 网页内部接口"),
    ("bilibiliFree", "B站 Index-Translate", "匿名文本模型"),
    ("transmart", "腾讯交互翻译", "匿名网页接口"),
    ("volcengineFree", "火山翻译", "匿名网页接口"),
    ("doubaoWeb", "豆包网页翻译", "实验性访客/SSE 协议"),
    ("google", "Google 翻译", "网页翻译协议"),
    ("youdaoFree", "有道网页翻译", "中英方向；网页签名"),
    ("icibaFree", "金山词霸", "中英方向；AES 响应"),
    ("yandexFree", "Yandex", "匿名网页协议"),
    ("myMemory", "MyMemory", "官方匿名查询；有限额"),
    ("reversoFree", "Reverso", "实验性网页接口"),
    ("apertiumFree", "Apertium", "公开语言对；不支持中日韩"),
    ("alibabaFree", "阿里网页翻译", "动态 CSRF"),
    ("modernMtFree", "ModernMT", "网页匿名接口；可能停用"),
    ("laraFree", "Lara Translate", "网页匿名接口"),
    ("lingvanexFree", "Lingvanex", "官网临时 Token"),
)
CATALOG_IDS = {item[0] for item in CATALOG}
CATALOG_PUBLIC = [
    {"id": ident, "name": name, "description": description}
    for ident, name, description in CATALOG
]
FREE_DEFAULTS = {
    "enabled": ["bilibiliFree", "microsoft", "google", "transmart",
                "volcengineFree", "myMemory", "apertiumFree"],
    "order": ["bilibiliFree"] + [item[0] for item in CATALOG if item[0] != "bilibiliFree"],
    "mode": "sequential",
    "timeout": 5,
    "total_timeout": 20,
    "my_memory_email": "",
    "cooldown_seconds": 120,
    "max_characters": 8000,
}


class FreeProtocolError(Exception):
    def __init__(self, message, status=502, category="unavailable"):
        super().__init__(message)
        self.status = status
        self.category = category


def normalize_lang(value, target=False):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z]{2,4}(?:[-_][a-zA-Z0-9]{2,8})*|auto", value):
        raise FreeProtocolError("语言代码无效", 400, "request")
    code = value.lower().replace("_", "-")
    if target and code == "auto":
        raise FreeProtocolError("目标语言不能自动检测", 400, "request")
    if code in {"zh-hans", "zh-cn", "zh-chs"}:
        return "zh"
    if code in {"zh-hant", "zh-tw", "zh-cht", "zh-hk"}:
        return "zh-tw"
    return code


def provider_language(provider, value, target=False):
    code = normalize_lang(value, target)
    if provider in {"youdaoFree", "icibaFree"}:
        if code not in {"auto", "en", "zh"}:
            raise FreeProtocolError("该服务只支持中英互译", 400, "request")
        return "zh-CHS" if code == "zh" else code
    if provider == "yandexFree" and target and code == "zh-tw":
        raise FreeProtocolError("Yandex 不支持繁体目标", 400, "request")
    if provider == "transmart" and code == "zh":
        return "zh"
    if provider == "volcengineFree" and code == "zh-tw":
        return "zh-Hant"
    if provider in {"microsoft", "bilibiliFree"}:
        return {"zh": "zh-Hans", "zh-tw": "zh-Hant"}.get(code, code)
    if provider in {"alibabaFree", "reversoFree", "modernMtFree", "laraFree", "lingvanexFree"}:
        return {"zh": "zh-cn", "zh-tw": "zh-tw"}.get(code, code)
    if provider in {"myMemory", "google"}:
        return {"zh": "zh-CN", "zh-tw": "zh-TW"}.get(code, code)
    return code


def guess_source(text):
    if re.search(r"[\u4e00-\u9fff]", text) and not re.search(r"[a-zA-Z]{3,}", text):
        return "zh"
    if re.search(r"[a-zA-Z]{5,}", text) and not re.search(r"[\u4e00-\u9fff]", text):
        return "en"
    raise FreeProtocolError("该节点无法可靠识别源语言，请手动选择", 400, "request")


def _request(method, url, *, deadline=None, timeout=5, json_body=None, data=None,
             params=None, headers=None, text=False):
    remain = (deadline - time.monotonic()) if deadline is not None else timeout
    if remain <= 0:
        raise FreeProtocolError("免费翻译总等待预算耗尽", 504, "timeout")
    try:
        response = requests.request(
            method, url, timeout=max(0.1, min(timeout, remain)),
            allow_redirects=False, headers=headers or {},
            params=params, data=data, json=json_body,
        )
    except requests.Timeout as error:
        raise FreeProtocolError("请求超时", 504, "timeout") from error
    except requests.RequestException as error:
        raise FreeProtocolError("服务网络连接失败", 502, "network") from error
    if response.status_code != 200:
        status = response.status_code
        category = ("rate-limit" if status == 429
                    else "blocked" if status in (401, 403, 404, 410)
                    else "quota" if status in (402, 456) else "unavailable")
        raise FreeProtocolError("外部服务返回 HTTP " + str(status), status, category)
    if len(response.content) > 2_000_000:
        raise FreeProtocolError("外部响应超过安全长度")
    if text:
        return response.text, response
    try:
        return response.json()
    except ValueError as error:
        raise FreeProtocolError("外部服务没有返回有效 JSON") from error


def _require(value, message="外部服务未返回有效译文"):
    if not isinstance(value, str) or not value.strip():
        raise FreeProtocolError(message)
    return value.strip()


def _as_list(value):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) for x in value):
        raise FreeProtocolError("译文数组损坏")
    return _require("".join(value))


def _split_by_size(text, max_chars, by_bytes=False):
    """Prefer punctuation/space boundaries, with no dropped Unicode codepoints."""
    result = []
    remaining = text
    while remaining:
        length = 0
        boundary = 0
        pos = 0
        for char in remaining:
            cost = len(char.encode("utf-8")) if by_bytes else 1
            if length + cost > max_chars:
                break
            length += cost
            pos += len(char)
            if char.isspace() or char in "。！？.!?；;,，":
                boundary = pos
        if not pos:
            raise FreeProtocolError("无法拆分超长字符", 400, "request")
        split = boundary if pos < len(remaining) and boundary else pos
        result.append(remaining[:split])
        remaining = remaining[split:]
    return result


def _line_chunks(text, limit, by_bytes=False):
    for line in re.split(r"(\r\n|\n|\r)", text):
        if not line.strip():
            yield ("", line, "")
            continue
        for chunk in _split_by_size(line, limit, by_bytes):
            content = chunk.strip()
            left = len(chunk) - len(chunk.lstrip())
            right = len(chunk.rstrip())
            yield chunk[:left], content, chunk[right:]


BILIBILI_API_URL = "https://index-translate.bilibili.com/v1/chat/completions"
BILIBILI_MODEL = "Index-Translate-35B-A3B"


def language_name(code, allow_auto=False):
    """Bilibili's official public endpoint accepts a text translation instruction."""
    names = {
        "auto": "", "zh": "简体中文", "zh-cn": "简体中文",
        "zh-Hans": "简体中文", "zh-tw": "繁体中文",
        "zh-Hant": "繁体中文", "en": "英语",
        "ja": "日语", "ko": "韩语", "fr": "法语",
        "de": "德语", "es": "西班牙语", "ru": "俄语",
        "it": "意大利语", "pt": "葡萄牙语", "ar": "阿拉伯语",
        "hi": "印地语", "vi": "越南语", "th": "泰语",
    }
    if code == "auto" and allow_auto:
        return ""
    if code not in names:
        # Index Translate's official model supports many more languages, so
        # let documented ISO codes through in place of an incomplete allowlist.
        if not re.fullmatch(r"[A-Za-z]{2,4}(?:-[A-Za-z0-9]{2,8})*", code):
            raise FreeProtocolError("B站不支持此语言代码", 400, "request")
        return code
    return names[code]


def bilibili_chat(messages, *, deadline=None, timeout=5, max_tokens=4096):
    """Official Bilibili Index-Translate Free Public OpenAI-compatible API.

    Reference: github.com/bilibili/Index-Translate/inference/llm/call_api.py
    No API key, browser Cookie, or invented redirect is used.
    """
    data = _request(
        "POST", BILIBILI_API_URL, deadline=deadline, timeout=timeout,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": "LibreTranslate-Fluently/1.0"},
        json_body={
            "model": BILIBILI_MODEL,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    try:
        choice = data["choices"][0]
        if choice.get("finish_reason") in ("length", "content_filter"):
            raise FreeProtocolError("B站返回截断或受限的内容")
        content = choice["message"]["content"]
    except (IndexError, KeyError, TypeError) as error:
        raise FreeProtocolError("B站官方免费 API 响应结构无效") from error
    content = re.sub(r"<think>[\s\S]*?</think>", "", _require(content)).strip()
    if not content or "<think>" in content or "</think>" in content:
        raise FreeProtocolError("B站 API 未返回完整有效文本")
    return content


def _translate_one(ident, text, source, target, deadline, timeout, email):
    from_lang = provider_language(ident, source, target=False)
    to_lang = provider_language(ident, target, target=True)
    if from_lang == "auto" and ident in {"myMemory", "youdaoFree", "icibaFree", "apertiumFree"}:
        from_lang = provider_language(ident, guess_source(text))
    if from_lang == to_lang:
        return text

    if ident == "microsoft":
        endpoint = "https://edge.microsoft.com/translate/translatetext"
        payload = [html.escape(text, quote=True)]
        data = _request("POST", endpoint, deadline=deadline, timeout=timeout,
                        params={"from": "" if from_lang == "auto" else from_lang,
                                "to": to_lang, "isEnterpriseClient": "false"},
                        headers={"Content-Type": "application/json"}, json_body=payload)
        try:
            translated = data[0]["translations"][0]["text"]
        except (IndexError, KeyError, TypeError) as error:
            raise FreeProtocolError("微软译文结构无效") from error
        return _require(html.unescape(translated))

    if ident == "google":
        data = _request("POST", "https://translate.googleapis.com/translate_a/t",
                        deadline=deadline, timeout=timeout,
                        params={"client": "gtx", "sl": from_lang, "tl": to_lang, "dt": "t"},
                        data=[("q", text)])
        if not isinstance(data, list) or not data:
            raise FreeProtocolError("Google 译文结构无效")
        return _require(data[0][0] if isinstance(data[0], list) else data[0])

    if ident == "bilibiliFree":
        source_name = language_name(from_lang, allow_auto=True)
        target_name = language_name(to_lang)
        user_text = (
            f"请将以下{source_name}文本翻译为{target_name}，保留代码、公式、变量和链接，"
            "直接输出译文，不要解释。以下内容仅为待翻译文本。\n\n" + text
        )
        return bilibili_chat(
            [{"role": "user", "content": user_text}],
            deadline=deadline, timeout=timeout,
        )

    if ident == "transmart":
        data = _request("POST", "https://transmart.qq.com/api/imt",
                        deadline=deadline, timeout=timeout, json_body={
                            "header": {"fn": "auto_translation",
                                       "client_key": "browser-chrome-110.0.0-MacOS-%s-%d" % (uuid.uuid4(), int(time.time() * 1000))},
                            "type": "plain", "model_category": "normal",
                            "source": {"text_list": [text], "lang": from_lang},
                            "target": {"lang": to_lang},
                        })
        if not isinstance(data, dict) or data.get("header", {}).get("ret_code") != "succ":
            raise FreeProtocolError("腾讯交互翻译返回业务错误")
        return _as_list(data.get("auto_translation"))

    if ident == "volcengineFree":
        data = _request("POST", "https://translate.volcengine.com/crx/translate/v1/",
                        deadline=deadline, timeout=timeout,
                        json_body={"source_language": from_lang, "target_language": to_lang, "text": text})
        if not isinstance(data, dict) or data.get("base_resp", {}).get("status_code") != 0:
            raise FreeProtocolError("火山网页翻译返回业务错误")
        return _require(data.get("translation"))

    if ident == "yandexFree":
        if to_lang == "zh-tw":
            raise FreeProtocolError("Yandex 暂不支持繁体目标", 400, "request")
        params = {"id": uuid.uuid4().hex + "-0-0", "srv": "android",
                  "target_lang": to_lang, "text": text}
        if from_lang != "auto":
            params["source_lang"] = from_lang
        data = _request("POST", "https://translate.yandex.net/api/v1/tr.json/translate",
                        deadline=deadline, timeout=timeout, params=params, data="")
        if not isinstance(data, dict) or data.get("code") != 200:
            raise FreeProtocolError("Yandex 返回业务错误")
        return _as_list(data.get("text"))

    if ident == "myMemory":
        if from_lang == "auto":
            from_lang = provider_language(ident, guess_source(text))
        params = {"q": text, "langpair": from_lang + "|" + to_lang}
        if email:
            params["de"] = email
        data = _request("GET", "https://api.mymemory.translated.net/get",
                        deadline=deadline, timeout=timeout, params=params)
        if not isinstance(data, dict) or data.get("quotaFinished") is True:
            raise FreeProtocolError("MyMemory 每日免费额度耗尽", 429, "quota")
        if str(data.get("responseStatus")) != "200":
            raise FreeProtocolError("MyMemory 查询失败")
        return _require((data.get("responseData") or {}).get("translatedText"))

    if ident == "reversoFree":
        codes = {"en": "eng", "zh-cn": "chi", "fr": "fra", "de": "deu",
                 "es": "spa", "it": "ita", "pt": "por", "ja": "jpn",
                 "ko": "kor", "ru": "rus", "ar": "ara", "nl": "nld",
                 "pl": "pol", "tr": "tur"}
        src = codes.get(from_lang, from_lang)
        dst = codes.get(to_lang, to_lang)
        data = _request("POST", "https://api.reverso.net/translate/v1/translation",
                        deadline=deadline, timeout=timeout,
                        headers={"x-reverso-origin": "translation.web"},
                        json_body={"format": "text", "from": src, "to": dst, "input": text,
                                   "options": {"languageDetection": True, "contextResults": True,
                                               "origin": "translation.web"}})
        return _as_list(data.get("translation") if isinstance(data, dict) else None)

    if ident == "apertiumFree":
        codes = {"en": "eng", "es": "spa", "fr": "fra", "de": "deu",
                 "it": "ita", "pt": "por", "ca": "cat", "gl": "glg",
                 "ro": "ron", "eo": "epo", "oc": "oci", "cy": "cym",
                 "sv": "swe", "da": "dan", "ru": "rus", "pl": "pol",
                 "cs": "ces", "uk": "ukr"}
        if from_lang in {"auto", "zh", "zh-tw", "ja", "ko"} or to_lang in {"zh", "zh-tw", "ja", "ko"}:
            raise FreeProtocolError("Apertium 不支持当前语言方向", 400, "request")
        pair = codes.get(from_lang, from_lang) + "|" + codes.get(to_lang, to_lang)
        pairs = _request("GET", "https://apertium.org/apy/listPairs", deadline=deadline, timeout=timeout)
        listed = pairs.get("responseData", pairs) if isinstance(pairs, dict) else pairs
        if not isinstance(listed, (list, dict)):
            raise FreeProtocolError("Apertium 语言列表损坏")
        def matches(item):
            if isinstance(item, str):
                return item.replace("-", "|") == pair
            return isinstance(item, dict) and (
                item.get("langpair", "").replace("-", "|") == pair or
                item.get("sourceLanguage", "") + "|" + item.get("targetLanguage", "") == pair
            )
        if not (any(matches(p) for p in listed) if isinstance(listed, list)
                else any(matches(p) for p in listed)):
            raise FreeProtocolError("Apertium 不支持此语言方向", 400, "request")
        data = _request("GET", "https://apertium.org/apy/translate", deadline=deadline, timeout=timeout,
                        params={"q": text, "langpair": pair, "format": "txt"})
        if not isinstance(data, dict) or data.get("responseStatus") != 200:
            raise FreeProtocolError("Apertium 翻译失败")
        return _require((data.get("responseData") or {}).get("translatedText"))

    if ident == "alibabaFree":
        csrf = _request("GET", "https://translate.alibaba.com/api/translate/csrftoken",
                        deadline=deadline, timeout=timeout)
        if (not isinstance(csrf, dict) or csrf.get("headerName") != "X-XSRF-TOKEN_PROPERTY_ITEM" or
                not isinstance(csrf.get("token"), str) or
                not re.fullmatch(r"[A-Za-z0-9-]{1,128}", csrf["token"])):
            raise FreeProtocolError("阿里网页 CSRF 初始化失败")
        data = _request("POST", "https://translate.alibaba.com/api/translate/text",
                        deadline=deadline, timeout=timeout,
                        data={"query": text, "srcLang": from_lang, "tgtLang": to_lang,
                              "domain": "general", "_csrf": csrf["token"]},
                        headers={"X-XSRF-TOKEN_PROPERTY_ITEM": csrf["token"]})
        if not isinstance(data, dict) or data.get("success") is not True:
            raise FreeProtocolError("阿里网页翻译失败")
        return _require((data.get("data") or {}).get("translateText"))

    if ident == "modernMtFree":
        timestamp = str(int(time.time() * 1000))
        signature = hashlib.md5(("webkey_E3sTuMjpP8Jez49GcYpDVH7r#" + timestamp + "#" + text).encode()).hexdigest()
        data = _request("POST", "https://webapi.modernmt.com/translate",
                        deadline=deadline, timeout=timeout,
                        headers={"X-HTTP-Method-Override": "GET"},
                        json_body={"q": text, "source": from_lang, "target": to_lang,
                                   "ts": int(timestamp), "verify": signature,
                                   "hints": "", "multiline": "true"})
        if not isinstance(data, dict) or data.get("status") != 200:
            raise FreeProtocolError("ModernMT 免费网页接口失败")
        return _require((data.get("data") or {}).get("translation"))

    if ident == "laraFree":
        data = _request("POST", "https://webapi.laratranslate.com/translate/segmented",
                        deadline=deadline, timeout=timeout,
                        headers={"X-Lara-Client": "Webapp"},
                        json_body={"q": text, "source": from_lang, "target": to_lang,
                                   "source_hint": "", "style": "faithful",
                                   "content_type": "text/plain", "adapt_to": [],
                                   "glossaries": [], "instructions": []})
        if not isinstance(data, dict) or data.get("status") != 200:
            raise FreeProtocolError("Lara 免费网页接口失败")
        items = (data.get("content") or {}).get("translations")
        if not isinstance(items, list) or not items:
            raise FreeProtocolError("Lara 返回译文结构无效")
        return _as_list([item.get("translation") if isinstance(item, dict) else None for item in items])

    if ident == "lingvanexFree":
        mapping = {
            "en": "en_GB", "zh-cn": "zh-Hans_CN", "zh-tw": "zh-Hant_TW",
            "ja": "ja_JP", "ko": "ko_KR", "de": "de_DE", "fr": "fr_FR",
            "es": "es_ES", "ru": "ru_RU", "pt": "pt_PT", "it": "it_IT",
            "ar": "ar_SA", "hi": "hi_IN", "tr": "tr_TR", "uk": "uk_UA",
            "vi": "vi_VN", "nl": "nl_NL",
        }
        if to_lang not in mapping or (from_lang != "auto" and from_lang not in mapping):
            raise FreeProtocolError("Lingvanex 不支持此语言方向", 400, "request")
        homepage, _ = _request("GET", "https://lingvanex.com/en/translate/",
                               deadline=deadline, timeout=timeout, text=True)
        match = re.search(r'const\s+API_BEARER_TOKEN\s*=\s*"(Bearer [A-Za-z0-9_-]{1,256})"', homepage)
        if not match:
            raise FreeProtocolError("无法从 Lingvanex 官网获取临时令牌")
        data = _request("POST", "https://api-b2b.backenster.com/b1/api/v3/translate",
                        deadline=deadline, timeout=timeout,
                        headers={"Authorization": match.group(1)},
                        json_body={"from": mapping.get(from_lang, ""),
                                   "to": mapping[to_lang], "text": text, "platform": "dp"})
        if not isinstance(data, dict) or data.get("err"):
            raise FreeProtocolError("Lingvanex 翻译失败")
        return _require(data.get("result"))

    if ident == "youdaoFree":
        stamp = str(int(time.time() * 1000) + (len(text + "webfanyi.webmain") % 10))
        digest = hashlib.md5((text + "webfanyi.webmain").encode()).hexdigest()
        sign = hashlib.md5(("webmain" + text + stamp + "t2he2k4m2g6QKRigK0KAmSpXKgAezyWg" + digest).encode()).hexdigest()
        data = _request("GET", "https://dict.youdao.com/jsonapi_s", deadline=deadline,
                        timeout=timeout,
                        params={"doctype": "json", "jsonversion": "4", "q": text,
                                "from": from_lang, "to": to_lang, "t": stamp,
                                "client": "webmain", "sign": sign,
                                "keyfrom": "webfanyi.webmain"})
        translation = data.get("fanyi", {}) if isinstance(data, dict) else {}
        actual = translation.get("type", "").lower()
        if actual in {"en2zh-chs", "zh-chs2en"} and actual != (from_lang + "2" + to_lang).lower():
            raise FreeProtocolError("有道返回了反向译文", 400, "request")
        return _require(translation.get("tran"))

    if ident == "icibaFree":
        # The website's anonymous response uses AES-ECB. This is a fixed website
        # protocol, not end-to-end encryption or any account authentication.
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad, unpad
        digest = hashlib.md5(("6key_web_new_fanyi6dVjYLFyzfkFkk" + text).encode()).hexdigest()[:16]
        cipher = AES.new(b"L4fBtD5fLC9FQw22", AES.MODE_ECB)
        sign = base64.b64encode(cipher.encrypt(pad(digest.encode(), 16))).decode()
        data = _request("POST", "https://ifanyi.iciba.com/index.php",
                        deadline=deadline, timeout=timeout,
                        params={"c": "trans", "m": "fyV2"},
                        data={"from": "zh" if from_lang == "zh-CHS" else from_lang,
                              "to": "zh" if to_lang == "zh-CHS" else to_lang,
                              "q": text, "client": "6", "auth_user": "key_web_new_fanyi",
                              "sign": sign})
        envelope = data.get("content") if isinstance(data, dict) else None
        if not isinstance(envelope, str):
            raise FreeProtocolError("词霸返回错误格式")
        try:
            raw = AES.new(b"aahc3TfyfCEmER33", AES.MODE_ECB).decrypt(base64.b64decode(envelope))
            decoded = json.loads(unpad(raw, 16).decode())
        except (ValueError, TypeError, UnicodeError) as error:
            raise FreeProtocolError("词霸响应解密失败") from error
        if decoded.get("err_no") != 0:
            raise FreeProtocolError("词霸服务返回业务错误")
        return _require(decoded.get("out"))

    if ident == "doubaoWeb":
        if to_lang == "zh-tw":
            raise FreeProtocolError("豆包网页翻译不支持繁体中文目标", 400, "request")
        landing, response = _request("GET", "https://www.doubao.com/",
                                     deadline=deadline, timeout=timeout, text=True)
        cookie = re.search(r"(?:^|[,;]\s*)ttwid=([^;,\s]+)", response.headers.get("Set-Cookie", ""))
        visitor = cookie.group(1) if cookie else None
        if not visitor:
            m = re.search(r"""["']ttwid["']\s*:\s*["']([^"'\\]+)""", landing)
            visitor = m.group(1) if m else None
        m = re.search(r"""["']web_id["']\s*:\s*["']([1-9]\d{18})""", landing)
        web_id = m.group(1) if m else None
        if (not visitor or not web_id or not re.fullmatch(r"[A-Za-z0-9._%-]{1,512}", visitor)):
            raise FreeProtocolError("豆包匿名访客初始化失败")
        qs = {
            "aid": "586864", "device_platform": "web", "tea_uuid": str(uuid.uuid4()),
            "version": "1.38.0", "use-olympus-account": "1", "language": "zh",
            "browser_language": "zh-CN", "real_aid": "586864",
            "pkg_type": "release_version", "device_id": web_id, "web_id": web_id,
            "is_new_user": "0", "region": "CN", "sys_region": "CN",
            "samantha_web": "1", "version_code": "20800", "pc_version": "1.38.0",
            "web_tab_id": str(uuid.uuid4()),
        }
        stream, _ = _request("POST", "https://www.doubao.com/samantha/plugin/stream_article_translate",
                             deadline=deadline, timeout=timeout, text=True,
                             params=qs, headers={"Cookie": "ttwid=" + visitor,
                                                 "Accept": "text/event-stream",
                                                 "Agw-Js-Conv": "str"},
                             json_body={"raw_text": [text], "target_lang": to_lang,
                                        "translate_service": "1", "frontend_source": 1, "scene": 2})
        latest, done = None, False
        for block in re.split(r"\r?\n\r?\n", stream):
            event = re.search(r"^event:\s*(.+)$", block, re.M)
            data_lines = re.findall(r"^data:\s*(.*)$", block, re.M)
            if event and event.group(1) == "done":
                done = True
                break
            if not event or event.group(1) != "json" or not data_lines:
                continue
            try:
                packet = json.loads("\n".join(data_lines))
                if packet.get("code") != 0:
                    raise FreeProtocolError("豆包访客协议拒绝请求")
                items = packet["data"]["items"]
                if len(items) != 1 or items[0]["index"] != 0:
                    raise FreeProtocolError("豆包响应槽位不完整")
                latest = _require(items[0]["res"])
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise FreeProtocolError("豆包 SSE 响应无效") from error
        if not done:
            raise FreeProtocolError("豆包 SSE 译文未正常结束")
        return _require(latest)

    raise FreeProtocolError("未知免费翻译节点", 400, "request")


def translate(ident, text, source, target, settings, *, deadline=None):
    if ident not in CATALOG_IDS:
        raise FreeProtocolError("未知免费翻译节点", 400, "request")
    if not isinstance(text, str) or not text.strip() or len(text) > settings["max_characters"]:
        raise FreeProtocolError("原文为空或超过免费服务字符上限", 400, "request")
    if ident == "myMemory" and source == "auto":
        source = guess_source(text)
    chunk_limit = 500 if ident == "youdaoFree" else 2000 if ident in {"bilibiliFree", "doubaoWeb"} else 1000
    by_bytes = ident == "myMemory"
    if by_bytes:
        chunk_limit = 500
    ending = deadline if deadline is not None else time.monotonic() + settings["total_timeout"]
    parts = []
    for prefix, content, suffix in _line_chunks(text, chunk_limit, by_bytes):
        if not content:
            parts.append(prefix + suffix)
            continue
        translated = _translate_one(ident, content, source, target, ending,
                                    settings["timeout"], settings.get("my_memory_email", ""))
        if content != translated and not translated:
            raise FreeProtocolError("服务返回空译文")
        parts.append(prefix + translated + suffix)
    return "".join(parts)


@dataclass
class Health:
    last_error: str = ""
    cooldown_until: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    last_ms: int = 0


_LOCK = threading.RLock()
_HEALTH = {ident: Health() for ident in CATALOG_IDS}


def public_health():
    now = time.monotonic()
    with _LOCK:
        return {
            ident: {
                "cooldown": max(0, round(value.cooldown_until - now)),
                "success_count": value.success_count,
                "failure_count": value.failure_count,
                "last_ms": value.last_ms,
                "last_error": value.last_error[:200],
            } for ident, value in _HEALTH.items()
        }


def _report(ident, *, duration=0, error=None, wait=120):
    with _LOCK:
        record = _HEALTH[ident]
        record.last_ms = round(duration * 1000)
        if error is None:
            record.success_count += 1
            record.last_error = ""
            record.cooldown_until = 0
        else:
            record.failure_count += 1
            record.last_error = str(error)[:200]
            if error.category != "request":
                record.cooldown_until = time.monotonic() + (min(86400, max(wait, 300)) if error.category in ("blocked", "quota") else wait)


def translate_with_fallback(text, source, target, settings):
    enabled = [ident for ident in settings["order"] if ident in settings["enabled"]]
    if not enabled:
        raise FreeProtocolError("没有启用任何免费服务", 400, "request")
    if settings["mode"] == "balanced":
        with _LOCK:
            enabled.sort(key=lambda key: (
                _HEALTH[key].cooldown_until > time.monotonic(),
                (_HEALTH[key].last_ms or 1000) * (1 + _HEALTH[key].failure_count) /
                (1 + _HEALTH[key].success_count),
            ))
    deadline = time.monotonic() + settings["total_timeout"]
    errors = []
    for ident in enabled:
        if time.monotonic() >= deadline:
            break
        with _LOCK:
            if _HEALTH[ident].cooldown_until > time.monotonic():
                errors.append({"id": ident, "error": "冷却中"})
                continue
        started = time.monotonic()
        try:
            result = translate(ident, text, source, target, settings, deadline=deadline)
            _report(ident, duration=time.monotonic() - started)
            return {"provider_id": ident, "text": result, "attempts": errors}
        except FreeProtocolError as error:
            _report(ident, duration=time.monotonic() - started, error=error,
                    wait=settings["cooldown_seconds"])
            errors.append({"id": ident, "error": str(error), "category": error.category})
    return {"provider_id": None, "text": "", "attempts": errors}
