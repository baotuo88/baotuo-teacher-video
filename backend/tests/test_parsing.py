"""What the server reads out of model answers and files."""

from __future__ import annotations

import pytest

from app import draw, film, llm, plan, voice


def test_code_block_picks_longest_of_language():
    text = "thinking\n```js\nshort\n```\nmore\n```js\nthe longer one\n```\n```python\nnot this, even longer text\n```"
    assert llm.code_block(text, ("js",)) == "the longer one"


def test_code_block_unterminated_fence():
    assert llm.code_block("```js\nENGINE.visual('p01', () => {})", ("js",)) == "ENGINE.visual('p01', () => {})"


def test_json_block_tolerates_trailing_commas():
    assert llm.json_block('here:\n```json\n{"a": [1, 2,], "b": 3,}\n```') == {"a": [1, 2], "b": 3}


def test_json_block_bare_object_in_prose():
    assert llm.json_block('The plan is {"pass": true} and that is all.') == {"pass": True}


def test_json_block_none():
    with pytest.raises(ValueError):
        llm.json_block("no json here")


def test_outside_blocks_is_text_after_last_block():
    assert llm.outside_blocks("let me think\n```js\nx\n```\nDone: drew the page.") == "Done: drew the page."


def test_clean_code_strips_fences():
    assert draw.clean_code("```js\nconst a = 1;\n```") == "const a = 1;\n"


def test_must_fix():
    issues = [{"level": "error"}, {"level": "warn", "kind": "small-text"}, {"level": "warn", "kind": "overlap"}]
    assert draw.must_fix(issues) == issues[:2]


def test_parse_declares():
    code = "// @extras gauges, lib/missing.js, ../../etc/x\n// @logos openai, bad name;rm\nENGINE.visual('p01')"
    extras, logos = film.parse_declares(code)
    assert extras == ["engine/lib/gauges.js"]
    assert logos == ["openai", "bad"]


def test_normalize_storyboard_renumbers_and_keeps_project_fields():
    sb = {"storyboard": {"pages": [{"id": "x", "beats": [{"at": "c0"}, "junk"]}, "junk", {"beats": []}],
                         "look": {"x": 1}}}
    out = plan.normalize_storyboard(sb, {"style": "whiteboard", "duration": 60, "lang": "en"})
    assert [p["id"] for p in out["pages"]] == ["p01", "p02"]
    assert out["pages"][0]["beats"] == [{"at": "c0"}]
    assert (out["style"], out["durationSec"], out["lang"]) == ("whiteboard", 60, "en")
    assert "look" not in out


def test_own_storyboard_issues():
    sb = {"pages": [{"id": "p01", "beats": [{}]}]}
    msgs = [i["msg"] for i in plan.own_storyboard_issues(sb, {"duration": 30})]
    assert any("2 beats" in m for m in msgs)
    too_many = {"pages": [{"id": f"p{i:02d}", "beats": [{}, {}]} for i in range(20)]}
    assert any("more than" in i["msg"] for i in plan.own_storyboard_issues(too_many, {"duration": 30}))


def test_script_problems():
    sb = {"pages": [{"beats": [{"at": "c1:光"}, {"at": "c5"}]}, {"beats": []}]}
    pages = plan.normalize_pages({"pages": [{"cues": ["天空是蓝的", "因为散射", {"t": "x", "hold": 9}]}]}, sb)
    assert pages[0]["cues"][2] == {"t": "x", "hold": 3.0}
    probs = plan.script_problems(pages, sb, duration=200, target=60, lang="zh")
    text = "\n".join(probs)
    assert "1 pages but the storyboard has 2" in text
    assert 'must contain the word "光"' in text
    assert "a beat is at c5" in text
    assert "over the 80s limit" in text


def test_voice_js_round_trip(tmp_path):
    data = {"speaker": "x", "provider": "edge", "pages": [[{"t": "你好", "f": "audio/a.wav", "d": 1.2, "o": 0}]]}
    voice.write_voice_js(tmp_path, data)
    assert voice.read_voice_js(tmp_path) == data


@pytest.mark.parametrize("src", [
    "SCRIPT.VOICE = {\"pages\": []}; require('child_process')",
    "SCRIPT.VOICE = (() => ({}))();",
    "window.x = 1",
    "SCRIPT.VOICE = [1, 2];",
])
def test_voice_js_rejects_anything_but_data(tmp_path, src):
    (tmp_path / "voice.js").write_text(src)
    assert voice.read_voice_js(tmp_path) is None
