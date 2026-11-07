"""Sentence segmentation and interpretable cross-language alignment.

A conservative monotonic dynamic-programming matcher handles 1:n and n:1
relationships. Its confidence describes structural evidence, NOT semantic
correctness. Semantic reordering requires a separate, opt-in AI pass.
"""
import math
import re
from collections import Counter

NUMBERS = re.compile(r"\b\d+(?:[.,]\d+)*\b")
NAMES = re.compile(r"\b[A-Z][A-Za-z0-9_-]{2,}\b")
CJK = re.compile(r"[\u3400-\u9fff]")
LATIN = re.compile(r"[A-Za-z]+")
BOUNDARY = set("。！？!?")
MAX_SENTENCES = 100


def sentences(text):
    if not isinstance(text, str):
        raise ValueError("Expected text")
    if len(text) > 30000:
        raise ValueError("Text exceeds alignment limit")
    chunks = []
    begin = 0

    def push(end):
        nonlocal begin
        fragment = text[begin:end]
        content = fragment.strip()
        if content:
            left = begin + len(fragment) - len(fragment.lstrip())
            chunks.append({"id": len(chunks), "start": left,
                           "end": left + len(content), "text": content})
        begin = end

    for idx, char in enumerate(text):
        if char in "\r\n":
            push(idx)
            begin = idx + 1
        elif char in BOUNDARY:
            next_char = text[idx + 1] if idx + 1 < len(text) else ""
            if not next_char or next_char in ' "”’）)\r\n' or CJK.match(next_char):
                push(idx + 1)
        elif char == ".":
            prev = text[idx - 1] if idx else ""
            after = text[idx + 1] if idx + 1 < len(text) else ""
            if prev.isdigit() and after.isdigit():
                continue
            if not after or after.isspace() or after in "”’)]}":
                push(idx + 1)
    push(len(text))
    if len(chunks) > MAX_SENTENCES:
        raise ValueError("Too many sentences for alignment")
    return chunks


def weighted_length(text):
    chinese = len(CJK.findall(text))
    latin_words = LATIN.findall(text)
    # A rough semantic-size proxy: 1 CJK glyph ~ 1.1, 1 Latin word ~ 1.75.
    return max(1.0, chinese * 1.2 + len(latin_words) * 1.8 +
               sum(char.isdigit() for char in text) * 0.5)


def _anchors(text):
    return Counter(NUMBERS.findall(text.lower()) +
                   [name.lower() for name in NAMES.findall(text) if len(name) >= 4])


def _match_cost(source, target, count_from, count_to):
    source_text = " ".join(part["text"] for part in source)
    target_text = " ".join(part["text"] for part in target)
    length_ratio = abs(math.log((weighted_length(source_text) + 1) /
                                (weighted_length(target_text) + 1)))
    anchors_a, anchors_b = _anchors(source_text), _anchors(target_text)
    shared = sum((anchors_a & anchors_b).values())
    total = sum((anchors_a | anchors_b).values())
    penalty = (total - shared) / total * 0.85 if total else 0
    # prefer 1:1 unless evidence favors merge/split
    return min(2.2, length_ratio * 0.85) + penalty + (count_from + count_to - 2) * 0.22


def align(source_text, target_text):
    source, target = sentences(source_text), sentences(target_text)
    n, m = len(source), len(target)
    if not n or not m:
        return {"source": source, "target": target, "groups": [],
                "method": "heuristic", "confidence": "low"}
    inf = float("inf")
    costs = [[inf] * (m + 1) for _ in range(n + 1)]
    moves = [[None] * (m + 1) for _ in range(n + 1)]
    costs[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            if costs[i][j] == inf:
                continue
            for a, b in ((1, 1), (1, 2), (2, 1), (2, 2), (1, 3), (3, 1),
                         (1, 0), (0, 1)):
                if i + a > n or j + b > m:
                    continue
                if a == 0 or b == 0:
                    score = 2.35
                else:
                    score = _match_cost(source[i:i + a], target[j:j + b], a, b)
                if costs[i][j] + score < costs[i + a][j + b]:
                    costs[i + a][j + b] = costs[i][j] + score
                    moves[i + a][j + b] = (i, j, a, b, score)
    i, j = n, m
    groups = []
    while i or j:
        move = moves[i][j]
        if move is None:
            raise ValueError("Failed to build alignment")
        start_i, start_j, a, b, score = move
        groups.append({
            "source_ids": list(range(start_i, i)),
            "target_ids": list(range(start_j, j)),
            "confidence": round(max(0, 1 - score / 2.5), 2),
        })
        i, j = start_i, start_j
    groups.reverse()
    mean = sum(item["confidence"] for item in groups) / len(groups)
    return {"source": source, "target": target, "groups": groups,
            "method": "heuristic", "confidence": (
                "medium" if mean >= .62 else "low")}


def validate_ai_groups(groups, n, m):
    """Reject model hallucinations, duplicates, and out-of-range indices."""
    if not isinstance(groups, list) or len(groups) > n + m or not groups:
        raise ValueError("Invalid alignment groups")
    used_source, used_target = set(), set()
    output = []
    for item in groups:
        if not isinstance(item, dict):
            raise ValueError("Invalid alignment group")
        src, tgt = item.get("source_ids"), item.get("target_ids")
        if not isinstance(src, list) or not isinstance(tgt, list) or not (src or tgt):
            raise ValueError("Invalid alignment ids")
        if not all(type(x) is int and 0 <= x < n and x not in used_source for x in src):
            raise ValueError("Repeated or invalid source index")
        if not all(type(x) is int and 0 <= x < m and x not in used_target for x in tgt):
            raise ValueError("Repeated or invalid target index")
        used_source.update(src)
        used_target.update(tgt)
        output.append({
            "source_ids": src, "target_ids": tgt,
            "confidence": 0.85 if src and tgt else 0.1,
        })
    if used_source != set(range(n)) or used_target != set(range(m)):
        raise ValueError("AI alignment skipped sentences")
    return output
