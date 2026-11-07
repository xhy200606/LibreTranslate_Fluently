"""Regression checks for the dark settings sidebar menu overlap."""
from pathlib import Path
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/"templates/fluently_settings.html").read_text(encoding="utf-8")
CSS=(ROOT/"static/css/fluently.css").read_text(encoding="utf-8")


class SidebarInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nav_depth=0
        self.group_count=0
        self.nav_items=0
        self.labels=0

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        classes=set(attrs.get("class","").split())
        if tag=="nav" and "sidebar-navigation" in classes:
            self.nav_depth=1
        elif self.nav_depth:
            if "sidebar-group" in classes:
                self.group_count+=1
            if "nav-item" in classes:
                self.nav_items+=1
            if "aside-label" in classes:
                self.labels+=1


def test_sidebar_navigation_is_grouped():
    doc=SidebarInspector()
    doc.feed(HTML)
    assert doc.group_count==2
    assert doc.labels==2
    assert doc.nav_items==8
    assert 'aria-label="设置导航"' in HTML


def test_inactive_dark_buttons_are_transparent_and_separated():
    # Generic dark button fill is defined earlier; nav-specific overrides
    # must come after it, with greater specificity.
    marker="/* v9 — Keep settings sidebar buttons separated"
    assert marker in CSS
    patch=CSS[CSS.rfind(marker):]
    assert ".sidebar-group{" in patch
    assert "gap:7px;" in patch
    assert "background:transparent;" in patch
    assert ".sidebar button.nav-item:not(.primary)" in patch
    assert ".sidebar .nav-item.active" in patch
    assert "background:var(--ui-badge-bg);" in patch
    assert "min-height:45px;" in patch
    assert "transform:none;" in patch
    assert patch.count("html[data-theme]")>=6


def test_small_screen_menu_is_grid_and_keeps_spacing():
    patch=CSS[CSS.rfind("/* v9 — Keep settings sidebar buttons separated"):]
    assert "@media(max-width:650px)" in patch
    assert "grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));" in patch
    assert "gap:8px;" in patch


def test_stylesheet_cache_updated_for_both_pages():
    home=(ROOT/"templates/fluently.html").read_text(encoding="utf-8")
    assert "filename='css/fluently.css', v='9'" in HTML
    assert "filename='css/fluently.css',v='9'" in home
