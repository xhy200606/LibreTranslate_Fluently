"""Regression checks for FluentRead/Fluently dark and system theme rendering."""
import json
import re
from pathlib import Path

import pytest
from flask import Flask

from libretranslate.fluently import fluently


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static/css/fluently.css").read_text(encoding="utf-8")
HOME = (ROOT / "templates/fluently.html").read_text(encoding="utf-8")
SETTINGS = (ROOT / "templates/fluently_settings.html").read_text(encoding="utf-8")


def _contrast(a, b):
    def lum(value):
        channels = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        channels = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4
                    for x in channels]
        return sum(x*w for x,w in zip(channels, (.2126, .7152, .0722)))
    low, high = sorted((lum(a), lum(b)))
    return (high + .05) / (low + .05)


def test_dark_mode_contrast_is_readable():
    assert _contrast("#eef3ff", "#27344b") >= 7.0  # source textarea
    assert _contrast("#eef3ff", "#222e43") >= 7.0  # translated output
    assert _contrast("#b4c2d8", "#101522") >= 7.0  # secondary text
    assert _contrast("#abbad0", "#27344b") >= 4.5  # placeholders


def test_both_dark_paths_receive_same_control_tokens():
    for variable in ("--ui-control:#27344b", "--ui-output:#222e43",
                     "--ui-placeholder:#abbad0", "--ui-toast-bg:rgba(36,49,70,.98)"):
        assert CSS.count(variable) == 2, variable  # dark and system-dark only
    assert 'html[data-theme="dark"]' in CSS
    assert '@media (prefers-color-scheme:dark)' in CSS
    assert 'html[data-theme="system"]' in CSS
    assert 'html[data-theme] .compare-workspace .version-input' in CSS
    assert 'html[data-theme] .compare-workspace .version-output' in CSS
    assert 'html[data-theme] .compare-workspace .toolbar-field select' in CSS
    assert 'html[data-theme] :is(input:not([type="checkbox"]),select,textarea)' in CSS
    assert 'html[data-theme] select option' in CSS
    assert 'html[data-theme] button:not(.primary)' in CSS
    assert 'html[data-theme] .selection-popup' in CSS
    assert 'html[data-theme] .glass' in CSS


@pytest.mark.parametrize("page", ["/fluently", "/fluently/settings"])
@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_theme_is_rendered_before_async_js(monkeypatch, tmp_path, page, theme):
    path = tmp_path / "gui_settings.json"
    path.write_text(json.dumps({"ui": {"theme": theme}}), encoding="utf-8")
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH", str(path))
    app = Flask(__name__, template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"))
    app.register_blueprint(fluently)
    app.testing = True
    result = app.test_client().get(page)
    assert result.status_code == 200
    text = result.get_data(as_text=True)
    assert '<html lang="zh-CN" data-theme="' + theme + '">' in text
    assert "fluently.css?v=8" in text
    assert "fluently" in text


def test_light_dark_system_css_do_not_break_layout():
    assert "grid-template-areas:" in CSS
    assert '"source translation"' in CSS
    assert "@media(max-width:760px)" in CSS
    assert "syncVersionRowHeight" in (ROOT / "static/js/fluently.js").read_text(
        encoding="utf-8")
    for html in (HOME, SETTINGS):
        assert "data-theme=" in html
        assert "v='8'" in html
