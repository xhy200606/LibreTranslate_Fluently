"""Bounded one-click diagnostics of all documented keyless providers."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic

from .free_providers import (
    CATALOG, FreeProtocolError, translate, _report,
)


def probe_all(settings, *, translate_fn=None):
    """Probe every known supplier, including disabled ones, using public sample text.

    The test translates only a fixed, non-personal short sentence. Each supplier
    gets a bounded timeout. The result is a snapshot, not a guarantee of uptime.
    """
    translate_fn = translate_fn or translate
    test_settings = dict(settings, timeout=min(4, settings["timeout"]),
                         total_timeout=min(5, settings["total_timeout"]))
    descriptions = {id_: name for id_, name, _ in CATALOG}

    def check(ident):
        source_text = "Hello world."
        target = "es" if ident == "apertiumFree" else "zh"
        started = monotonic()
        try:
            result = translate_fn(ident, source_text, "en", target, test_settings)
            if not isinstance(result, str) or not result.strip() or result.strip() == source_text:
                raise FreeProtocolError("供应商没有返回有效的目标语言译文", 502, "unavailable")
            elapsed = monotonic() - started
            _report(ident, duration=elapsed)
            return {"id": ident, "name": descriptions[ident], "available": True,
                    "latency_ms": round(elapsed * 1000), "preview": result[:100],
                    "tested_direction": "en→" + target}
        except Exception as error:
            elapsed = monotonic() - started
            if not isinstance(error, FreeProtocolError):
                error = FreeProtocolError("供应商返回错误或无法识别的响应")
            _report(ident, duration=elapsed, error=error,
                    wait=settings["cooldown_seconds"])
            return {"id": ident, "name": descriptions[ident], "available": False,
                    "latency_ms": round(elapsed * 1000),
                    "error": str(error)[:240], "category": error.category,
                    "tested_direction": "en→" + target}

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(check, ident): ident for ident, _, _ in CATALOG}
        for future in as_completed(futures):
            results.append(future.result())
    rank = {ident: i for i, (ident, _, _) in enumerate(CATALOG)}
    results.sort(key=lambda item: rank[item["id"]])
    return results
