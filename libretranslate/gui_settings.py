"""Persistent, validated settings for LibreTranslate Fluently.

An administrator bootstrap token is supplied through LT_SETTINGS_ADMIN_TOKEN.
Credentials are write-only in API responses and saved with owner-only file mode.
"""
import copy
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

_LOCK = threading.RLock()
SECRET_OPTIONS = {
    "API_KEYS_REMOTE", "REQ_LIMIT_STORAGE", "SHARED_STORAGE",
    "TRANSLATION_CACHE", "METRICS_AUTH_TOKEN",
}
GROUPS = {
    "network": ("HOST", "PORT", "SSL", "URL_PREFIX", "TRUST_FORWARDED_FOR"),
    "security": ("API_KEYS", "API_KEYS_DB_PATH", "API_KEYS_REMOTE", "GET_API_KEY_LINK",
                 "REQUIRE_API_KEY_ORIGIN", "REQUIRE_API_KEY_SECRET",
                 "REQUIRE_API_KEY_FINGERPRINT", "UNDER_ATTACK", "HIDE_API"),
    "limits": ("CHAR_LIMIT", "REQ_LIMIT", "REQ_LIMIT_STORAGE", "HOURLY_REQ_LIMIT",
               "HOURLY_REQ_LIMIT_DECAY", "DAILY_REQ_LIMIT",
               "REQ_FLOOD_THRESHOLD", "REQ_TIME_COST", "BATCH_LIMIT",
               "ALTERNATIVES_LIMIT"),
    "frontend": ("FRONTEND_LANGUAGE_SOURCE", "FRONTEND_LANGUAGE_TARGET",
                 "FRONTEND_LANGUAGE", "FRONTEND_TIMEOUT", "FRONTEND_TITLE",
                 "SUGGESTIONS", "DISABLE_FILES_TRANSLATION", "DISABLE_WEB_UI"),
    "models": ("LOAD_ONLY", "UPDATE_MODELS", "FORCE_UPDATE_MODELS"),
    "operations": ("DEBUG", "SHARED_STORAGE", "SECONDARY", "THREADS",
                   "METRICS", "METRICS_AUTH_TOKEN", "TRANSLATION_CACHE"),
}
DEFAULT_UI = {
    "theme": "system", "glass": True, "font_size": 16,
    "compare_count": 3, "highlight": True, "deep_explain": True,
    "auto_translate": False, "source_language": "auto",
    "target_language": "en", "debounce_ms": 650,
}
DEFAULT_AI = {
    "providers": [],
    "translation_prompt": (
        "You are a professional translator. Translate from {source} to {target}, "
        "preserving meaning, context, formatting, terminology, and tone. "
        "Return only the translation."
    ),
    "explanation_prompt": (
        "Explain the selected expression in Simplified Chinese, including its "
        "contextual meaning, grammar, nuances, alternative translations and examples."
    ),
    "temperature": 0.2, "timeout": 60, "max_tokens": 2048,
}
PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
LANGUAGE_CODE = re.compile(r"^(auto|[a-zA-Z]{2,4}(-[a-zA-Z]{2,4})?)$")
_URL_SCHEMES = {"http", "https"}


def settings_path():
    return Path(os.environ.get("LT_GUI_SETTINGS_PATH", "db/gui_settings.json"))


def _read_unlocked():
    saved = {}
    path = settings_path()
    if path.is_file():
        with path.open("r", encoding="utf-8") as stream:
            saved = json.load(stream)
        if not isinstance(saved, dict):
            raise ValueError("Invalid GUI settings file")
    value = {
        "server": {},
        "ui": copy.deepcopy(DEFAULT_UI),
        "ai": copy.deepcopy(DEFAULT_AI),
    }
    for group in value:
        incoming = saved.get(group, {})
        if not isinstance(incoming, dict):
            raise ValueError("Invalid settings group: " + group)
        value[group].update(incoming)
    return value


def read_settings():
    with _LOCK:
        return _read_unlocked()


@contextmanager
def _file_lock():
    """Cross-worker lock for multi-process Gunicorn settings writes."""
    import fcntl
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a+b") as lock:
        os.chmod(str(path) + ".lock", 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_unlocked(value):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(path.parent),
            prefix=".fluently-", delete=False
        ) as output:
            temporary = output.name
            os.chmod(temporary, 0o600)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _server_value(name, value, kind):
    if value is None:
        return None
    if kind == "bool":
        if type(value) is not bool:
            raise ValueError(name + " must be a boolean")
    elif kind == "int":
        if type(value) is not int or not -100000000 <= value <= 100000000:
            raise ValueError(name + " must be an integer")
        if name == "PORT" and not 1 <= value <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        if name == "THREADS" and not 1 <= value <= 64:
            raise ValueError("THREADS must be 1 to 64")
    elif not isinstance(value, str) or len(value) > 2000:
        raise ValueError(name + " must be a string (maximum 2000 characters)")
    return value


def load_server_overrides(option_definitions):
    saved = read_settings()["server"]
    schema = {entry["name"]: entry for entry in option_definitions}
    result = {}
    for name, value in saved.items():
        if name in schema and value is not None:
            result[name] = _server_value(name, value, schema[name]["value_type"])
    return result


def server_schema(option_definitions, current_arguments=None):
    value = read_settings()["server"]
    result = []
    for entry in option_definitions:
        name = entry["name"]
        group = next((key for key, names in GROUPS.items() if name in names), "operations")
        secret = name in SECRET_OPTIONS
        saved = value.get(name)
        result.append({
            "name": name, "group": group, "type": entry["value_type"],
            "default": None if secret else entry["default_value"],
            "value": None if secret else saved,
            "configured": saved is not None,
            "restart_required": True,
            "secret": secret,
        })
    return result


def _bounded(value, name, low, high, integer=True):
    if type(value) not in ((int,) if integer else (int, float)):
        raise ValueError(name + " must be a number")
    if not low <= value <= high:
        raise ValueError(name + " out of range")
    return value


def validate_ui(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_UI):
        raise ValueError("Unknown UI settings")
    result = copy.deepcopy(DEFAULT_UI)
    result.update(value)
    if result["theme"] not in ("light", "dark", "system"):
        raise ValueError("Invalid theme")
    for name in ("glass", "highlight", "deep_explain", "auto_translate"):
        if type(result[name]) is not bool:
            raise ValueError(name + " must be a boolean")
    for name, a, b in (("font_size", 12, 24), ("compare_count", 1, 6),
                       ("debounce_ms", 150, 3000)):
        _bounded(result[name], name, a, b)
    for name in ("source_language", "target_language"):
        if (not isinstance(result[name], str)
                or not LANGUAGE_CODE.fullmatch(result[name])):
            raise ValueError("Invalid " + name)
    return result


def validate_base_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Invalid provider URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid provider URL") from error
    if (parsed.scheme not in _URL_SCHEMES or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment
            or port == 0):
        raise ValueError("Use an http(s) API URL without credentials or a fragment")
    if parsed.scheme == "http" and parsed.hostname not in (
            "localhost", "127.0.0.1", "::1", "host.docker.internal"):
        raise ValueError("Use HTTPS for remote providers (HTTP is limited to local services)")
    return url.rstrip("/")


def normalize_chat_url(url):
    """Follow FluentRead's OpenAI-compatible URL convention."""
    value = validate_base_url(url)
    path = urlsplit(value).path
    if path in ("", "/"):
        return value + "/v1/chat/completions"
    if path in ("/v1", "/openai/v1"):
        return value + "/chat/completions"
    return value


def _provider(value, prior=None):
    if not isinstance(value, dict):
        raise ValueError("Invalid provider")
    allowed = {"id", "name", "base_url", "model", "enabled", "api_key",
               "clear_api_key"}
    if set(value) - allowed:
        raise ValueError("Unknown provider fields")
    ident = value.get("id")
    if not isinstance(ident, str) or not PROVIDER_ID.fullmatch(ident):
        raise ValueError("Provider ID must use letters, digits, hyphen or underscore")
    name = value.get("name", "")
    model = value.get("model", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Provider name must be 1–80 characters")
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 256:
        raise ValueError("Model ID must be 1–256 characters")
    enabled = value.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    result = {
        "id": ident, "name": name.strip(), "model": model.strip(),
        "base_url": validate_base_url(value.get("base_url")),
        "enabled": enabled,
    }
    if value.get("clear_api_key") is True:
        result["api_key"] = ""
    elif "api_key" in value and value["api_key"]:
        key = value["api_key"]
        if not isinstance(key, str) or len(key) > 4096:
            raise ValueError("Invalid API key")
        result["api_key"] = key
    else:
        result["api_key"] = (prior or {}).get("api_key", "")
    return result


def validate_ai(value, previous=None):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_AI):
        raise ValueError("Unknown AI settings")
    previous = previous or DEFAULT_AI
    result = copy.deepcopy(DEFAULT_AI)
    result.update({k: v for k, v in value.items() if k != "providers"})
    for key in ("translation_prompt", "explanation_prompt"):
        if not isinstance(result[key], str) or not 1 <= len(result[key]) <= 8000:
            raise ValueError("Invalid " + key)
    _bounded(result["temperature"], "temperature", 0, 2, integer=False)
    _bounded(result["timeout"], "timeout", 5, 180)
    _bounded(result["max_tokens"], "max_tokens", 64, 8192)
    entries = value.get("providers", previous.get("providers", []))
    if not isinstance(entries, list) or len(entries) > 12:
        raise ValueError("Provide no more than 12 AI providers")
    old = {p["id"]: p for p in previous.get("providers", [])}
    providers = [_provider(p, old.get(p.get("id"))) for p in entries]
    if len({p["id"] for p in providers}) != len(providers):
        raise ValueError("Provider IDs must be unique")
    result["providers"] = providers
    return result


def public_settings():
    data = read_settings()
    return {
        "ui": data["ui"],
        "ai": {
            "providers": [
                {"id": p["id"], "name": p["name"], "model": p["model"],
                 "enabled": p.get("enabled", True)}
                for p in data["ai"]["providers"]
            ],
        },
        "admin_enabled": bool(os.environ.get("LT_SETTINGS_ADMIN_TOKEN")),
    }


def admin_settings(option_definitions):
    data = read_settings()
    for p in data["ai"]["providers"]:
        p["has_api_key"] = bool(p.pop("api_key", ""))
    return {
        "ui": data["ui"], "ai": data["ai"],
        "server": server_schema(option_definitions),
    }


def save_settings(data, option_definitions):
    if not isinstance(data, dict) or set(data) - {"ui", "ai", "server"}:
        raise ValueError("Unknown settings sections")
    definitions = {item["name"]: item for item in option_definitions}
    with _LOCK, _file_lock():
        current = _read_unlocked()
        if "ui" in data:
            current["ui"] = validate_ui(data["ui"])
        if "ai" in data:
            current["ai"] = validate_ai(data["ai"], current["ai"])
        if "server" in data:
            overrides = data["server"]
            if not isinstance(overrides, dict):
                raise ValueError("Invalid server settings")
            for name, value in overrides.items():
                if name not in definitions:
                    raise ValueError("Unknown server option: " + name)
                cleaned = _server_value(name, value, definitions[name]["value_type"])
                if cleaned is None:
                    current["server"].pop(name, None)
                else:
                    current["server"][name] = cleaned
        _write_unlocked(current)
    return current
