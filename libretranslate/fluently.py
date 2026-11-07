"""Fluently settings and OpenAI-compatible translation endpoints."""
import hmac
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit

import requests
from flask import Blueprint, abort, jsonify, render_template, request

from .default_values import _default_options_objects
from .gui_settings import (
    admin_settings, normalize_chat_url, public_settings,
    read_settings, save_settings,
)

fluently = Blueprint("fluently", __name__)


def _admin_required():
    required = os.environ.get("LT_SETTINGS_ADMIN_TOKEN", "")
    if not required:
        abort(503, description="Set LT_SETTINGS_ADMIN_TOKEN to enable GUI administration.")
    supplied = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not supplied.startswith(prefix) or not hmac.compare_digest(supplied[len(prefix):], required):
        abort(401, description="Administrator token required.")
    if request.method != "GET":
        # Never accept cross-origin administrative writes; bearer tokens alone
        # authenticate but a hostile web page must not trigger them.
        origin = request.headers.get("Origin")
        if origin:
            current = urlsplit(request.host_url)
            supplied_origin = urlsplit(origin)
            if ((current.scheme, current.netloc) !=
                    (supplied_origin.scheme, supplied_origin.netloc)):
                abort(403, description="Cross-origin changes are not allowed.")


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
    provider_id = data.get("provider_id")
    settings = read_settings()["ai"]
    provider = next((p for p in settings["providers"]
                     if p["id"] == provider_id and p.get("enabled", True)), None)
    if not provider:
        return jsonify({"error": "Provider not configured or disabled."}), 404
    source = str(data.get("source", "auto"))[:40]
    target = str(data.get("target", "en"))[:40]
    if action == "explain":
        system = settings["explanation_prompt"]
        contextual = str(data.get("context", ""))[:5000]
        content = "Selected text:\n" + text + "\nContext:\n" + contextual
    elif action == "test":
        system = "Translate to English. Return only the translation."
        content = "你好"
    else:
        system = settings["translation_prompt"].replace(
            "{source}", source
        ).replace("{target}", target)
        content = text
    try:
        answer = _call_provider(
            provider, [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ], settings,
        )
        return jsonify({"text": answer, "provider_id": provider_id,
                        "model": provider["model"]})
    except ValueError as error:
        return jsonify({"error": str(error)}), 502
