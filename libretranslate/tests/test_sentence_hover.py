"""Hover-alignment regression: no browser selection and no AI tokens."""
import pytest
from flask import Flask

from libretranslate.alignment import align, sentences
from libretranslate.fluently import fluently


def test_english_academic_abbreviations_remain_in_one_sentence():
    text="Dr. Smith used Fig. 8 and Eq. 3.14. The result improved."
    parts=sentences(text)
    assert [x["text"] for x in parts]==[
        "Dr. Smith used Fig. 8 and Eq. 3.14.", "The result improved.",
    ]
    assert [text[x["start"]:x["end"]] for x in parts]==[x["text"] for x in parts]


def test_quoted_sentence_boundaries_are_not_split_from_quote():
    for sample,expected in [
        ('"Hello!" Next sentence.', ['"Hello!"', 'Next sentence.']),
        ("He said 'yes.' Then left.", ["He said 'yes.'", "Then left."]),
    ]:
        assert [p["text"] for p in sentences(sample)]==expected


def test_unicode_sentence_offsets_match_original_python_codepoints():
    sample="😀 Intro. 再见。 下一句！"
    parts=sentences(sample)
    assert len(parts)==3
    for p in parts:
        assert sample[p["start"]:p["end"]]==p["text"]


def test_monotonic_many_to_one_sentence_alignment():
    output=align("Hello. How are you?", "你好，你怎么样？")
    assert len(output["source"])==2
    assert len(output["target"])==1
    assert any(g["source_ids"]==[0,1] and g["target_ids"]==[0]
               for g in output["groups"])


def test_monotonic_one_to_many_sentence_alignment():
    output=align("Hello, how are you?", "你好！你怎么样？")
    assert len(output["source"])==1
    assert len(output["target"])==2
    assert any(g["source_ids"]==[0] and g["target_ids"]==[0,1]
               for g in output["groups"])


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.delenv("LT_SETTINGS_ADMIN_TOKEN",raising=False)
    monkeypatch.setenv("LT_GUI_SETTINGS_PATH",str(tmp_path/"settings.json"))
    app=Flask(__name__)
    app.register_blueprint(fluently)
    app.testing=True
    return app.test_client()


def test_hover_api_provides_offsets_and_groups_without_ai(client,monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError("Hover alignment must never call the AI model")
    monkeypatch.setattr("libretranslate.fluently._call_provider",forbidden)
    response=client.post("/fluently/api/align",json={
        "source":"First sentence. Second sentence.",
        "target":"第一句。第二句。", "mode":"heuristic",
    })
    assert response.status_code==200
    payload=response.get_json()
    assert payload["method"]=="heuristic"
    assert len(payload["source"])==2
    assert len(payload["target"])==2
    assert payload["groups"]
    assert all("start" in sentence and "end" in sentence
               for sentence in payload["source"]+payload["target"])


def test_page_includes_non_selection_hover_resources():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    page=(root/"templates/fluently.html").read_text(encoding="utf-8")
    js=(root/"static/js/fluently.js").read_text(encoding="utf-8")
    css=(root/"static/css/fluently.css").read_text(encoding="utf-8")
    hover=(root/"static/js/fluently_sentence_hover.js").read_text(encoding="utf-8")
    assert "fluently_sentence_hover.js" in page
    assert page.index("fluently_sentence_hover.js") < page.index("js/fluently.js")
    assert "鼠标悬停一句话" in page
    assert "sentenceHover?.update" in js
    assert "FluentlySentenceHover.mount" in js
    assert "source-sentence-mirror" in css
    assert "source-sentence-highlights" in css
    assert "hover-translation-sentence.is-matched" in css
    assert "selectionStart" not in hover[hover.index("function onSourceMove("):
                                        hover.index("function onSourceKey(")]
