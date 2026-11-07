"""FluentRead-compatible English word lookup with fixed trusted dictionary sources.

Sources follow FluentRead's six-source taxonomy. 3000 licensed ECDICT
entries are bundled; other dictionaries are independent public HTTP queries.
No arbitrary URL is accepted, and external content is rendered as text only.
"""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import requests

SOURCES = (
    {"id": "auto", "name": "自动 · 本地优先"},
    {"id": "ecdict-local", "name": "ECDICT 本地词典"},
    {"id": "youdao-web", "name": "有道词典"},
    {"id": "free-dictionary", "name": "Free Dictionary API"},
    {"id": "wiktionary-rest", "name": "Wiktionary"},
    {"id": "wiktapi", "name": "WiktApi"},
    {"id": "datamuse", "name": "Datamuse"},
)
SOURCE_IDS = {source["id"] for source in SOURCES}
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]{0,59}$")
TAG_RE = re.compile(r"<[^>]+>")
POS_LABELS = {
    "n": "名词", "v": "动词", "adj": "形容词",
    "adv": "副词", "prep": "介词", "conj": "连词",
    "pron": "代词", "art": "冠词", "interj": "感叹词",
}


def _clean(value, limit=400):
    if not isinstance(value, str):
        return ""
    return html.unescape(TAG_RE.sub(" ", value)).replace("\x00", "").strip()[:limit]


def _new(word, source):
    return {"word": word, "phonetic": "", "pronunciations": [],
            "meanings": [], "sources": [source], "origin": ""}


def _meaning(card, pos, definition, translation="", example=""):
    if len(card["meanings"]) >= 12:
        return
    definition = _clean(definition)
    translation = _clean(translation)
    if not definition and not translation:
        return
    card["meanings"].append({
        "pos": POS_LABELS.get(str(pos).lower(), _clean(pos, 50)) or "其他",
        "definition": definition,
        "translation": translation,
        "example": _clean(example, 200),
    })


@lru_cache(maxsize=1)
def _ecdict():
    path = Path(__file__).parent / "static" / "data" / "ecdict-core.json"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf8") as f:
        data = json.load(f)
    return {row[0].lower(): row for row in data if isinstance(row, list) and len(row) >= 4}


def _local(word):
    row = _ecdict().get(word)
    if not row:
        return None
    card = _new(word, "ecdict-local")
    card["phonetic"] = _clean(row[1], 100)
    # Raw ECDICT source uses backslash-n for multi-line definitions.
    raw_translation = _clean(row[3], 700).replace("\\n", "\n")
    raw_definition = _clean(row[2], 700).replace("\\n", "\n")
    translations = [x.strip() for x in raw_translation.splitlines() if x.strip()]
    definitions = [x.strip() for x in raw_definition.splitlines() if x.strip()]
    for index in range(min(max(len(translations), len(definitions)), 5)):
        item = translations[index] if index < len(translations) else ""
        match = re.match(r"^(n|v|adj|adv|prep|conj|pron|art)\.\s*", item, re.I)
        _meaning(card, match.group(1).lower() if match else "",
                 definitions[index] if index < len(definitions) else "",
                 item[match.end():] if match else item)
    return card


def _get_json(url, *, params=None, timeout=2.8):
    try:
        response = requests.get(url, params=params, timeout=timeout,
                                allow_redirects=False,
                                headers={"User-Agent": "LibreTranslate-Fluently/1.0",
                                         "Accept": "application/json"})
        if response.status_code != 200 or len(response.content) > 250000:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def _lookup(word, source):
    if source == "ecdict-local":
        return _local(word)
    if source == "free-dictionary":
        data = _get_json("https://api.dictionaryapi.dev/api/v2/entries/en/" + word)
        if not isinstance(data, list) or not data:
            return None
        card = _new(word, source)
        for entry in data[:3]:
            if not isinstance(entry, dict):
                continue
            card["phonetic"] = card["phonetic"] or _clean(entry.get("phonetic"), 100)
            for item in entry.get("phonetics", [])[:6]:
                if isinstance(item, dict) and item.get("text"):
                    card["pronunciations"].append({"text": _clean(item["text"], 100)})
            for meaning in entry.get("meanings", [])[:5]:
                if not isinstance(meaning, dict):
                    continue
                for defin in meaning.get("definitions", [])[:3]:
                    if isinstance(defin, dict):
                        _meaning(card, meaning.get("partOfSpeech"), defin.get("definition"),
                                 example=defin.get("example"))
        return card if card["meanings"] else None
    if source == "youdao-web":
        data = _get_json("https://dict.youdao.com/jsonapi_s",
                         params={"doctype": "json", "jsonversion": "4",
                                 "q": word, "le": "eng"}, timeout=2)
        if not isinstance(data, dict):
            return None
        ec = data.get("ec") or {}
        record = ec.get("word") or {}
        if not isinstance(record, dict):
            return None
        card = _new(word, source)
        card["phonetic"] = _clean(record.get("usphone") or record.get("ukphone"), 100)
        for item in record.get("trs", [])[:10]:
            if isinstance(item, dict):
                _meaning(card, item.get("pos"), "", _clean(item.get("tran")))
        return card if card["meanings"] else None
    if source == "wiktionary-rest":
        data = _get_json("https://en.wiktionary.org/api/rest_v1/page/definition/" + word)
        if not isinstance(data, dict):
            return None
        card = _new(word, source)
        for entry in data.get("en", [])[:5]:
            if not isinstance(entry, dict):
                continue
            for definition in entry.get("definitions", [])[:4]:
                if isinstance(definition, dict):
                    examples = definition.get("examples") or []
                    example = examples[0].get("example") if examples and isinstance(examples[0], dict) else ""
                    _meaning(card, entry.get("partOfSpeech"), definition.get("definition"), example=example)
        return card if card["meanings"] else None
    if source == "wiktapi":
        data = _get_json("https://api.wiktapi.dev/v1/en/word/" + word)
        if not isinstance(data, dict):
            return None
        card = _new(word, source)
        for entry in data.get("entries", [])[:8]:
            if not isinstance(entry, dict) or entry.get("lang_code", "en") != "en":
                continue
            pos = entry.get("pos") or entry.get("partOfSpeech")
            for sense in entry.get("senses", [])[:4]:
                if isinstance(sense, dict):
                    glosses = sense.get("glosses") or []
                    if glosses:
                        _meaning(card, pos, glosses[0])
        return card if card["meanings"] else None
    if source == "datamuse":
        data = _get_json("https://api.datamuse.com/words",
                         params={"sp": word, "md": "dpr", "ipa": 1, "max": 8})
        if not isinstance(data, list):
            return None
        card = _new(word, source)
        for item in data:
            if not isinstance(item, dict) or item.get("word", "").lower() != word:
                continue
            for tag in item.get("tags", []):
                if isinstance(tag, str) and tag.startswith("pron:"):
                    card["phonetic"] = tag[5:][:100]
                    break
            for definition in item.get("defs", [])[:8]:
                if isinstance(definition, str):
                    pos, _, detail = definition.partition("\t")
                    _meaning(card, pos, detail or pos)
        return card if card["meanings"] else None
    return None


def lookup_word(value, source="auto"):
    """Return a common schema or None. In auto mode local result is immediate."""
    if not isinstance(value, str) or not WORD_RE.fullmatch(value.strip()):
        raise ValueError("Dictionary lookup requires a single English word (max 60 chars)")
    if source not in SOURCE_IDS:
        raise ValueError("Unknown dictionary source")
    word = value.strip().lower()
    if source != "auto":
        return _lookup(word, source)
    local = _local(word)
    if local and local["meanings"]:
        return local
    # Bounded concurrent external fallbacks: first useful result, cancel others.
    candidates = ("youdao-web", "free-dictionary", "wiktapi",
                  "wiktionary-rest", "datamuse")
    executor = ThreadPoolExecutor(max_workers=5)
    futures = [executor.submit(_lookup, word, entry) for entry in candidates]
    try:
        for future in as_completed(futures, timeout=3.5):
            try:
                card = future.result()
                if card and card.get("meanings"):
                    return card
            except (ValueError, TypeError, KeyError):
                continue
    except TimeoutError:
        pass
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    return None
