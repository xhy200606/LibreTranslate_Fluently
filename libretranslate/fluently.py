"""Fluently settings and OpenAI-compatible translation endpoints."""
import hmac
import time
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit

import requests
import json
import re
from flask import Blueprint, abort, jsonify, render_template, request

from .alignment import align, sentences, validate_ai_groups
from .free_providers import CATALOG_PUBLIC, CATALOG_IDS, FreeProtocolError, public_health, translate as translate_free, translate_with_fallback, bilibili_chat

from .fluently_probe import probe_all
from .default_values import _default_options_objects
from .gui_settings import (
    admin_settings, normalize_chat_url, public_settings,
    read_settings, save_settings,
)

fluently = Blueprint("fluently", __name__)


def _admin_required():
    """LAN-first setup: no secret required when env token is absent.

    Optional LT_SETTINGS_ADMIN_TOKEN is preserved for administrators who
    explicitly opt in. Write operations remain same-origin.
    """
    if request.method != "GET":
        origin = request.headers.get("Origin")
        if origin:
            current = urlsplit(request.host_url)
            supplied_origin = urlsplit(origin)
            if (current.scheme, current.netloc) != (
                    supplied_origin.scheme, supplied_origin.netloc):
                abort(403, description="Cross-origin changes are not allowed.")
        if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            abort(403, description="Only same-origin requests are allowed.")
        if not request.is_json:
            abort(415, description="JSON requests only.")
    required = os.environ.get("LT_SETTINGS_ADMIN_TOKEN", "")
    if required:
        supplied = request.headers.get("Authorization", "")
        if not supplied.startswith("Bearer ") or not hmac.compare_digest(
                supplied[7:], required):
            abort(401, description="The optional administrator token is required.")


def _json_object():
    obj = request.get_json(silent=True)
    if not isinstance(obj, dict):
        abort(400, description="Expected a JSON object.")
    return obj


@fluently.get("/fluently")
def workspace():
    return render_template("fluently.html")


@fluently.get("/fluently/settings")
def settings_page():
    return render_template("fluently_settings.html")


@fluently.get("/fluently/api/public")
def public_api():
    return jsonify(public_settings())


@fluently.route("/fluently/api/settings", methods=["GET", "PUT"])
def settings_api():
    _admin_required()
    if request.method == "GET":
        return jsonify(admin_settings(_default_options_objects))
    try:
        save_settings(_json_object(), _default_options_objects)
        return jsonify({
            "success": True, "settings": admin_settings(_default_options_objects),
            "server_restart_required": "server" in (request.get_json(silent=True) or {}),
        })
    except (ValueError, TypeError) as error:
        return jsonify({"error": str(error)}), 400


def _destination_safe(base_url):
    """Reject loopback redirects to private services unless explicitly opted in."""
    parsed = urlsplit(base_url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid destination")
    # The admin knowingly configured a local service. Other internal endpoints
    # are blocked unless operator explicitly enables private network access.
    local = hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
    allow_private = os.environ.get("LT_AI_ALLOW_PRIVATE_NETWORK") == "true"
    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError("Unable to resolve provider hostname") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global and not (allow_private or (local and ip.is_loopback)):
            raise ValueError("Provider resolves to a disallowed private network address")


def _call_provider(provider, messages, settings):
    url = normalize_chat_url(provider["base_url"])
    _destination_safe(url)
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = "Bearer " + provider["api_key"]
    payload = {
        "model": provider["model"], "messages": messages,
        "temperature": settings["temperature"], "max_tokens": settings["max_tokens"],
        "stream": False,
    }
    try:
        response = requests.post(
            url, headers=headers, json=payload, timeout=settings["timeout"],
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise ValueError("Provider connection failed: " + str(error)) from error
    if response.status_code >= 300:
        raise ValueError("Provider returned HTTP " + str(response.status_code))
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Provider returned an empty translation")
        return content.strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Provider returned an unsupported completion format") from error


@fluently.post("/fluently/api/ai")
def ai_api():
    _admin_required()
    data = _json_object()
    text = data.get("text", "")
    if not isinstance(text, str) or not text.strip() or len(text) > 30000:
        return jsonify({"error": "Text must be 1–30000 characters."}), 400
    action = data.get("action", "translate")
    if action not in ("translate", "explain", "test"):
        return jsonify({"error": "Invalid action."}), 400
    provider_id = data.get("provider_id", "bilibiliFree")
    settings = read_settings()
    source = str(data.get("source", "auto"))[:40]
    target = str(data.get("target", "zh"))[:40]
    ai = settings["ai"]
    provider = next((p for p in ai["providers"]
                     if p["id"] == provider_id and p.get("enabled", True)), None)
    if provider_id != "bilibiliFree" and provider is None:
        return jsonify({"error": "Provider not configured or disabled."}), 404

    context = str(data.get("context", ""))[:5000]
    if action == "explain":
        system = ai["explanation_prompt"]
        content = "Selected text:\n" + text + "\nFull context:\n" + context
    elif action == "test":
        system = "Translate to Chinese. Return only the translation."
        content = "Hello world."
    else:
        system = ai["translation_prompt"].replace(
            "{source}", source
        ).replace("{target}", target)
        content = text
    try:
        if provider_id == "bilibiliFree":
            if action == "translate":
                answer = translate_free(
                    "bilibiliFree", text, source, target, settings["free"])
            elif action == "test":
                answer = translate_free(
                    "bilibiliFree", "Hello world.", "en", "zh", settings["free"])
            else:
                # The free Index-Translate model is translation-focused; a
                # separate general-purpose LLM may be better at explanation.
                answer = bilibili_chat([
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ], timeout=min(ai["timeout"], 30), max_tokens=ai["max_tokens"])
            model = "Index-Translate-35B-A3B"
        else:
            answer = _call_provider(
                provider, [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ], ai)
            model = provider["model"]
        return jsonify({"text": answer, "provider_id": provider_id,
                        "model": model})
    except (FreeProtocolError, ValueError) as error:
        return jsonify({"error": str(error)}), 502


@fluently.get("/fluently/api/free/providers")
def free_catalog():
    return jsonify({"providers": CATALOG_PUBLIC, "health": public_health()})


@fluently.post("/fluently/api/free/probe")
def free_probe_api():
    """Probe all 16 suppliers. Optionally persist only currently reachable ones."""
    _admin_required()
    payload = _json_object()
    apply_available = payload.get("apply_available", False)
    if type(apply_available) is not bool:
        return jsonify({"error": "apply_available must be boolean"}), 400
    settings = read_settings()["free"]
    results = probe_all(settings)
    available = {r["id"] for r in results if r["available"]}
    # Only auto-enable services actually tested against this workspace's
    # target language. Apertium's English-to-Spanish success does not make it
    # usable for English-to-Chinese translation.
    from .free_providers import normalize_lang
    target = normalize_lang(read_settings()["ui"]["target_language"], target=True)
    eligible = {r["id"] for r in results if r["available"] and
                r.get("tested_direction", "").split("→")[-1] == target}
    applied = False
    if apply_available and eligible:
        enabled = [ident for ident in settings["order"] if ident in eligible]
        save_settings({"free": dict(settings, enabled=enabled)}, _default_options_objects)
        applied = True
    return jsonify({
        "results": results, "available_count": len(available),
        "total_count": len(results), "eligible_count": len(eligible),
        "applied": applied,
        "enabled": read_settings()["free"]["enabled"],
    })


@fluently.post("/fluently/api/free/translate")
def free_translate_api():
    _admin_required()
    data = _json_object()
    ident = data.get("provider_id")
    text = data.get("text")
    source, target = data.get("source", "auto"), data.get("target", "en")
    settings = read_settings()["free"]
    if not isinstance(text, str) or not text.strip() or len(text) > settings["max_characters"]:
        return jsonify({"error": "Invalid translation length"}), 400
    if not isinstance(source, str) or not isinstance(target, str):
        return jsonify({"error": "Invalid translation language"}), 400
    if ident != "freeAuto" and (ident not in CATALOG_IDS or ident not in settings["enabled"]):
        return jsonify({"error": "Free provider is not enabled"}), 400
    try:
        if ident == "freeAuto":
            result = translate_with_fallback(text, source, target, settings)
            if not result["provider_id"]:
                return jsonify({"error": "All free translation providers failed",
                                "attempts": result["attempts"]}), 502
            return jsonify(result)
        return jsonify({"text": translate_free(ident, text, source, target, settings),
                        "provider_id": ident})
    except FreeProtocolError as error:
        return jsonify({"error": str(error), "category": error.category}), (
            400 if error.category == "request" else 502
        )


@fluently.post("/fluently/api/align")
def alignment_api():
    _admin_required()
    data = _json_object()
    source = data.get("source")
    target = data.get("target")
    if not isinstance(source, str) or not isinstance(target, str):
        return jsonify({"error": "Source and target must be strings"}), 400
    if len(source) > 30000 or len(target) > 30000:
        return jsonify({"error": "Alignment input exceeds limit"}), 400
    try:
        result = align(source, target)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    # Opt-in semantic alignment: validate IDs and ensure complete coverage.
    if data.get("mode") == "ai":
        ai = read_settings()["ai"]
        provider = next((p for p in ai["providers"] if p.get("enabled")), None)
        if provider and result["source"] and result["target"]:
            system = (
                "You are a bilingual sentence aligner. Match source and translated "
                "sentence indices by meaning, including reordered and merged sentences. "
                "Return JSON only: {\"groups\":[{\"source_ids\":[0],\"target_ids\":[0]}]}. "
                "Every sentence index must appear exactly once in the groups."
            )
            payload = json.dumps({
                "source": [s["text"] for s in result["source"]],
                "target": [s["text"] for s in result["target"]],
            }, ensure_ascii=False)
            try:
                content = _call_provider(provider, [
                    {"role": "system", "content": system},
                    {"role": "user", "content": payload},
                ], dict(ai, temperature=0, max_tokens=min(4096, ai["max_tokens"])))
                match = re.search(r"\{[\s\S]*\}", content)
                parsed = json.loads(match.group(0) if match else content)
                result["groups"] = validate_ai_groups(
                    parsed["groups"], len(result["source"]), len(result["target"])
                )
                result["method"] = "ai"
                result["confidence"] = "medium"
            except (ValueError, KeyError, TypeError):
                # Correctness is preferable to claiming AI validation.
                result["method"] = "heuristic-fallback"
    return jsonify(result)
