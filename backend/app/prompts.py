"""System prompts and stage messages. The craft (storyboard rules, drawing API, style grammar cards, the reviewer's
criteria) is Frametell's own, read at runtime from the fetched prompts/ and engine/styles/; this file adds what this app
does differently: no tools, answers come back as text and the server writes the files."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import config, styles


@lru_cache(maxsize=16)
def _read(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text("utf-8")


def grammar(style: str) -> str:
    f = config.ENGINE_DIR / "styles" / style / "GRAMMAR.md"
    return f.read_text("utf-8") if f.exists() else f"Style: {style} ({styles.name(style)}). Quiet paper, ink lines, light washes; one accent colour at a time."


def preferences_section(p: str) -> str:
    p = (p or "").strip()
    return (f"---\n# The user's standing preferences\n\nThe user wrote these for every film they make. Follow them wherever they "
            f"bear on your part of the work; the technical rules above always hold.\n\n<preferences>\n{p}\n</preferences>") if p else ""


# ── component docs (signatures + doc comments, from the component sources) ──

_DOC = re.compile(r"/\*\*((?:(?!\*/)[\s\S])*)\*/\s*(?:B|Builder\.prototype)\.(\w+)\s*=\s*function\s*\(([^)]*)\)")
_HANDLE = re.compile(r"/\*\*\s*([A-Z]\w*\.\w+)\(((?:(?!\*/)[^)])*)\)\s*(?:→[^:]*)?:?((?:(?!\*/)[\s\S])*)\*/")


def _clean(doc: str) -> str:
    return " ".join(l.strip().lstrip("*").strip() for l in doc.splitlines() if l.strip().lstrip("*").strip())


def component_docs(f: Path) -> list[str]:
    src = f.read_text("utf-8")
    out = []
    for m in _DOC.finditer(src):
        doc = re.sub(r"^\w+\([^)]*\)\s*[—:-]?\s*", "", _clean(m.group(1)))
        out.append(f"- `P.{m.group(2)}({m.group(3).strip()})` — {doc}")
    for m in _HANDLE.finditer(src):
        out.append(f"  - `{m.group(1)}({m.group(2).strip()})` — {_clean(m.group(3))}")
    if not out:
        head = re.match(r"\s*/\*([\s\S]*?)\*/", src)
        if head:
            out.append(f"- {_clean(head.group(1))[:600]}")
    return out


@lru_cache(maxsize=1)
def lib_docs() -> str:
    parts = ["# The component library: signatures", "Every file of engine/lib/ with its components' signatures and notes "
             "(what LIB.md lists, in full). To use one, name its file on the first line of the page (see the end of this prompt)."]
    for f in sorted((config.ENGINE_DIR / "lib").glob("*.js")):
        d = component_docs(f)
        if d:
            parts += [f"## {f.name}", *d]
    return "\n".join(parts)


def _example_page(style: str) -> tuple[str, str] | None:
    d = config.ENGINE_DIR / "styles" / style / "example" / "pages"
    if not d.exists():
        return None
    pages = [(f.stem, f.read_text("utf-8")) for f in sorted(d.glob("*.js"))]
    short = [p for p in pages if p[1].count("\n") <= 30]
    if not short:
        return None
    return max(short, key=lambda p: len(re.findall(r"P\.c\w?\(", p[1])))


def page_pack(style: str) -> str:
    parts = ["# This film's components and worked example (ready for you)",
             "These components are already registered for this film: call them directly as `P.xxx(...)`."]
    for e in styles.extras(style):
        f = config.ENGINE_DIR / e.removeprefix("engine/")
        if f.exists():
            d = component_docs(f)
            if d:
                parts += [f"## {f.name}", *d]
    ex = _example_page(style)
    if ex:
        parts += [f"## Worked example: {ex[0]} of the benchmark film",
                  "One complete page. Organise your page the way it does (objects, actions, timing to cues, camera, numbers "
                  "landing on objects); don't copy its content.", "```js", ex[1].strip(), "```"]
    return "\n".join(parts)


# ── what this app changes: no tools ──

PAGE_NO_TOOLS = """---
# How you work in this studio (this overrides any mention of tools above)

You have no tools here: you cannot read files, run commands, call edit, write or flag. Everything you need is in this
prompt and in the server's message. The server writes your file, registers components, builds logos, runs the checker
and the reviewer, and sends you the results.

**Answer with the complete file** `pages/<id>.js` in one ```js code block — always the whole file, never a diff or a
fragment, also when you fix it — then one plain sentence (in the user's language, no code words) saying what is on screen.

- To use components from the library, put this on the file's first line: `// @extras gauges.js, meters.js`
  (file names from the library). The style's own components are always loaded: don't list them.
- For real brand logos, put `// @logos anthropic, openai` on a line at the top and draw them with `P.logo(name, …)`.
  If you're unsure a logo exists, write the name as text.
- `P.tex` formulas work as they are (the server loads KaTeX when a page uses it).
- When a reported problem should stay as it is (intended, or a false alarm), answer with one line
  `@flag <the reason>` and no code.
- Keep the file to about 300 lines; answers have a length limit.

## Pitfalls that pass the checker but break the picture
- Centred text needs **both** `w` and `align:'c'`: without `w`, `x` is the left edge, not the centre.
- `P.check(x, y, size, o)` / `P.cross(x, y, size, o)`: the third argument is a **number**. Passing the options there
  draws nothing (NaN).
- In `P.liveRough((lt, R) => …)` the second argument shadows any variable you called `R`. Name it `rough`, and keep
  coordinates in other names. It has only `box / circle / line / path`.
- `P.mark()` is a highlighter drawn over the text: keep it about 0.4× the font size tall, just under the baseline,
  or it hides the words.
- A camera `push` / `slam` enlarges the frame: text near the edges or low on the page is pushed off the canvas or into
  the subtitle band. Keep key text in the middle (x 400–1500, y 300–700), or use `pan`.
"""

PLANNER_NO_TOOLS = """---
# How you work in this studio (this overrides any mention of files, tools or commands above)

You have no tools here: you cannot read or write files or run commands. The material is pasted into the server's
message. You answer in text and the server writes the files and runs the checks:

- **Stage 1 (storyboard)**: answer with the whole storyboard as one ```json code block (the object described for
  storyboard.json), then 2–4 plain sentences for the user.
- **Stage 2 (narration)**: answer with one ```json code block:
  `{ "title": "the film's title", "pages": [ { "id": "p01", "section": "…", "title": "…", "cues": ["…", { "t": "…", "hold": 0.6 }] } ] }`
  — every page of the storyboard, in order, with the same ids. The server turns it into script.js and estimates the
  length itself, then tells you if anything must change. Then 1–3 plain sentences for the user.
- When the server sends issues or the user asks for changes, answer with the **whole** corrected JSON again, never a diff.
- Leave `look` out of the storyboard: every style here brings its own look.
"""

REVIEW_NO_TOOLS = """---
# How you answer in this studio

You have no verdict tool here. Answer with one ```json code block and nothing else:
`{ "pass": true, "problems": [] }` or
`{ "pass": false, "problems": [ { "at": 3.2, "what": "what the viewer sees wrong", "fix": "the concrete change" } ] }`
— at most 5 problems, the most visible first.
"""


def planner_system(style: str, prefs: str = "") -> str:
    return "\n\n".join(x for x in [
        _read("PLANNER.md"),
        "---\n# This film's style (the page agent draws to it, so the storyboard must be drawable in it)\n\n" + grammar(style),
        "---\n" + _read("LIB.md"),
        PLANNER_NO_TOOLS,
        preferences_section(prefs),
    ] if x)


def page_system(style: str, prefs: str = "") -> str:
    return "\n\n".join(x for x in [
        _read("PAGE.md"),
        "---\n# This film's style\n\n" + grammar(style),
        "---\n" + _read("API.md"),
        "---\n" + page_pack(style),
        "---\n" + _read("LIB.md"),
        "---\n" + lib_docs(),
        PAGE_NO_TOOLS,
        preferences_section(prefs),
    ] if x)


def reviewer_system(style: str, lang: str = "zh") -> str:
    # the user reads "what" in the interface; "fix" goes to the artist (a model) and may stay in any language
    note = ('Write each "what" in Simplified Chinese (the user reads it).' if lang != "en" else 'Write each "what" in English.')
    return "\n\n".join([_read("REVIEW.md"), "---\n# This film's style\n\n" + grammar(style), REVIEW_NO_TOOLS + note])


# ── language and voice ──

def reply_note(lang: str) -> str:
    return "Write everything you say to the user in Simplified Chinese." if lang != "en" else "Write everything you say to the user in English."


LANG_NOTES = {
    "zh": {
        "storyboard": 'Film language: **Chinese**. In the storyboard write `"lang": "zh"`; write title, summary, section, say and each beat\'s object / action / camera / text in Simplified Chinese (camera: 固定、推近、拉远、横移…): on-screen text at most 8 characters per element, and a beat tied to a word names the Chinese word as spoken (`c2:三十年`).',
        "script": "Film language: **Chinese**. A cue is one short spoken sentence in Simplified Chinese, at most 16 characters, 3–8 per page, ending with its punctuation (。？！ pause longer than ，、；). Write numbers in Arabic digits and units as they are spoken (年, 元).",
        "page": "This is a Chinese film: all text on screen (titles, labels, units) is in Simplified Chinese, matching the narration.",
    },
    "en": {
        "storyboard": 'Film language: **English**. In the storyboard write `"lang": "en"`; write title, summary, section, say and each beat\'s object / action / text in English: on-screen text at most 5 English words per element, and a beat tied to a word names the English word (`c2:thirty`).',
        "script": "Film language: **English**. A cue is one short spoken English sentence, at most 12 words, 3–8 per page; write numbers in Arabic digits (1,000, 30%) and units as they are spoken.",
        "page": "This is an English film: all text on screen (titles, labels, units) is in English, matching the narration. English runs longer than Chinese, so leave enough width for text.",
    },
}


def lang_note(stage: str, lang: str) -> str:
    return "\n" + LANG_NOTES["en" if lang == "en" else "zh"][stage] + "\n" + reply_note(lang)


def voice_note(stage: str, voiced: bool) -> str:
    if voiced:
        return ""
    return {
        "storyboard": "\nThis film has no voice, and may be watched without subtitles: the picture alone must tell the story, so key words and numbers go on screen as text.",
        "script": "\nThis film has no voice: nobody hears the cues. They time the picture and become the subtitles, so write each as a short caption that reads well on its own.",
    }.get(stage, "")


def budget(duration: int) -> dict:
    return {"pages": int(-(-duration * 6 // 60)) + 1, "estimate": round(duration * 4 / 3)}


# ── stage messages ──

def materials_block(materials: list[tuple[str, str]], limit: int = 60000) -> str:
    out, used = [], 0
    for name, text in materials:
        room = limit - used
        if room <= 500:
            out.append(f"(… {name} and later material left out: too long)")
            break
        t = text if len(text) <= room else text[:room] + "\n(… cut here: too long)"
        used += len(t)
        out.append(f'<material name="{name}">\n{t}\n</material>')
    return "\n\n".join(out)


def assets_note(assets: dict[str, str], for_page: bool = False) -> str:
    if not assets:
        return ""
    rows = "\n".join(f"- `assets/{n}`" + (f": {desc}" if desc else "") for n, desc in assets.items())
    if for_page:
        return ("\n\n## The user's own pictures\nThe user gave these pictures for the film. When this page's storyboard "
                "uses one, place it with `P.img('assets/<file>', x, y, w, h, { fit: 'contain', at })`; never draw it "
                f"from memory.\n{rows}")
    return ("\nThe user gave these pictures for the film; plan beats that show them where they help (name the file in "
            f"the beat's object, e.g. \"the screenshot assets/home.png\"):\n{rows}")


GITHUB_NOTE = """This film introduces an open-source project. Hard rules:
- The **last page is the repository page**: the repository name large, the full URL, the owner, and how to find it —
  shown as an action (a browser address bar typing the URL, a search box filling in the name), not a centred card.
- Copy the repository name exactly as it appears in the material (case, dashes, underscores); never guess it from a
  file name. The repository: {repo}
- Show what the project does with its real output, commands or screenshots from the material; no invented numbers
  (stars, users) unless the material says them."""


def storyboard_prompt(p: dict, materials: list[tuple[str, str]], voiced: bool) -> str:
    dur = int(p.get("duration") or 90)
    b = budget(dur)
    lines = [
        "Stage 1: storyboard.",
        f"The request: {'turn the material into' if materials else 'make'} an explainer film of about {round(dur / 60, 1)} minutes "
        f"(durationSec: {dur}; at most {b['pages']} pages)." + (f" Topic: {p['topic']}." if p.get("topic") else "")
        + (f" Audience: {p['audience']}." if p.get("audience") else ""),
        "" if materials else "There is no material: explain it from your own knowledge. Use only well-established, checkable facts and numbers; when unsure, leave the number out. Every number on screen must also appear in that page's say (the server checks where numbers come from against say).",
        f"Further notes from the user: {p['notes']}" if p.get("notes") else "",
        GITHUB_NOTE.format(repo=p.get("repo") or "(see the material)") if p.get("kind") == "github" else "",
        f'Style: {p["style"]} (write "{p["style"]}" as the style in the storyboard).',
        assets_note(p.get("assets") or {}),
        ("The material:\n\n" + materials_block(materials)) if materials else "",
        "Answer with the storyboard JSON, then your short report." + voice_note("storyboard", voiced) + lang_note("storyboard", p.get("lang", "zh")),
    ]
    return "\n".join(x for x in lines if x)


def storyboard_fix_prompt(issues: list[dict], lang: str) -> str:
    rows = [f"- [{'red' if i.get('level') == 'red' else 'yellow'}] {i.get('page') or 'whole film'}"
            f"{(' beat ' + str(i['beat'] + 1)) if i.get('beat') is not None else ''}: {i.get('msg')}" for i in issues]
    return "\n".join(["The server checked the storyboard; fix the issues below (red must be fixed, yellow at your judgement):",
                      *rows, "Answer with the whole corrected storyboard JSON, then one sentence on what you changed. " + reply_note(lang)])


def storyboard_revise_prompt(sb_json: str, feedback: str, p: dict, materials: list[tuple[str, str]]) -> str:
    return "\n".join(x for x in [
        "The storyboard so far:", "```json", sb_json, "```",
        ("The material, for reference:\n\n" + materials_block(materials, 40000)) if materials else "",
        f"The user asks for these changes:\n{feedback}",
        f"Keep everything else. The style stays {p['style']}; the length budget stays about {p.get('duration', 90)} seconds "
        f"(at most {budget(int(p.get('duration') or 90))['pages']} pages).",
        "Answer with the whole revised storyboard JSON, then 1–3 sentences on what you changed." + lang_note("storyboard", p.get("lang", "zh")),
    ] if x)


def script_prompt(sb_json: str, p: dict, voiced: bool, feedback: str = "") -> str:
    dur = int(p.get("duration") or 90)
    return "\n".join(x for x in [
        "The approved storyboard:", "```json", sb_json, "```",
        f"The user's notes on it: {feedback}" if feedback else "The user approved the storyboard without changes.",
        f"Stage 2: write the narration. The target is about {dur} seconds; the server's estimate may run up to "
        f"{budget(dur)['estimate']} seconds (it runs long), no more. Shorter is fine when the material is short: never pad.",
        "Every beat tied to a word (`c2:三十`) needs that word verbatim in cue 2 of its page; a beat at `cN` needs the page to have at least N+1 cues.",
        "Answer with the narration JSON, then your short report." + voice_note("script", voiced) + lang_note("script", p.get("lang", "zh")),
    ] if x)


def script_fix_prompt(problems: list[str], lang: str) -> str:
    return "\n".join(["The server checked the narration; change it so these hold:", *[f"- {x}" for x in problems],
                      "Answer with the whole corrected narration JSON, then one sentence on what you changed. " + reply_note(lang)])


def sheet_times(sb_page: dict | None, t: dict, last: bool) -> list[dict]:
    """Moments worth a still: right after the page turns in, each beat in progress, and the settled end."""
    beats = (sb_page or {}).get("beats") or []
    cues = t["cues"]

    def cue_at(at: str) -> float:
        m = re.match(r"^c(\d+)", str(at or ""))
        i = min(int(m.group(1)) if m else 0, max(0, len(cues) - 1))
        return t["start"] + cues[i]["at"] if cues else t["start"]

    settled = max(t["speechEnd"], t["end"] - 1.2) if last else t["end"] - 0.35
    hi = settled if last else t["end"] - 0.2
    raw = sorted(min(hi, max(t["start"] + 0.4, x)) for x in [t["start"] + 0.6, *(cue_at(b.get("at")) + 1.0 for b in beats), settled])
    out: list[float] = []
    for x in raw:
        if not out or x - out[-1] > 0.6:
            out.append(x)
    while len(out) > 6:
        out.pop(len(out) // 2)
    return [{"t": x, "local": x - t["start"]} for x in out]


def _beats(p: dict | None, camera: bool = True) -> str:
    return "\n".join(f"  {i + 1}. [{b.get('at')}] {b.get('object')} — {b.get('action')}"
                     + (f" (camera: {b['camera']})" if camera and b.get("camera") else "")
                     + (f', on-screen text "{b["text"]}"' if b.get("text") else "")
                     for i, b in enumerate((p or {}).get("beats") or []))


def page_prompt(sb: dict, pid: str, t: dict, p: dict) -> str:
    page = next((x for x in sb.get("pages", []) if x.get("id") == pid), None)
    outline = "\n".join(f"- {x.get('id')} {x.get('section', '')}" for x in sb.get("pages", []))
    last = sb.get("pages") and sb["pages"][-1].get("id") == pid
    cues = "\n".join(f"- c{c['i']}: at {c['at']}s in the page, \"{c['text']}\"" for c in t["cues"])
    ending = ""
    if last:
        ending = (f"\n\n## The film ends on this page\nNothing comes after it: after its last line the film holds "
                  f"{t['end'] - t['speechEnd']:.1f}s on this page, then fades out by itself in its final second.\n"
                  "- Land the close with the last line: the last change arrives as it is spoken, and the main object ends resolved and whole in the frame, not mid-move.\n"
                  "- After `P.endT` the picture holds still: no new element, no text, no camera move. Never clear, fade or empty the picture yourself, and add no \"the end\" card.")
    return f"""You own page **{pid}**.

The film: {sb.get('title', '')} — {sb.get('summary', '')}
Its structure:
{outline}

## This page's storyboard
- Section: {(page or {}).get('section', '')}
- What it says: {(page or {}).get('say', '')}
- Key page: {'yes' if (page or {}).get('core') else 'no'}
- Beats:
{_beats(page)}

## This page's narration and timing ({'real voice' if t.get('voiced') else 'estimated; the real voice may run a little shorter'})
The page lasts {t['end'] - t['start']:.2f}s; its narration ends at {t['speechEnd'] - t['start']:.2f}s (P.endT).
{cues}{ending}{assets_note(p.get('assets') or {}, True)}

Answer with the complete pages/{pid}.js.{lang_note('page', p.get('lang', 'zh'))}"""


def revise_prompt(pid: str, code: str, change: str) -> str:
    return f"""pages/{pid}.js as it is now:
```js
{code}
```

The user asks for this change to the page: {change}

Make the change and keep the rest. Answer with the complete updated file in one ```js block, then one sentence on what you changed."""


def _lint_lines(issues: list[dict]) -> str:
    return "\n".join(f"- {float(i.get('local') or 0):.1f}s: {i.get('msg')}" for i in issues)


def sheet_line(times: list[dict]) -> str:
    return ("The attached sheet shows the page at these moments within it (left to right, top to bottom): "
            + ", ".join(f"{x['local']:.1f}s" for x in times) + ".")


def fix_prompt(rnd: int, errors: list[dict], problems: list[dict], times: list[dict], crash: str = "",
               change: str = "", with_sheet: bool = False) -> str:
    parts = [f"Check round {rnd}: the page needs changes.", ""]
    if crash:
        parts += ["The page does not run, so it could not be checked:", "```", crash[:2500], "```", ""]
    if errors:
        parts += ["The checker, must fix:", _lint_lines(errors), ""]
    if problems:
        parts += ["The reviewer, looking at the sheet:" if with_sheet else "The reviewer:",
                  "\n".join(f"- {float(x.get('at') or 0):.1f}s: {x.get('what')} → {x.get('fix')}" for x in problems), ""]
    if change:
        parts += [f"The user asked for this change to the page: {change}", "If the pictures don't show it yet, make it now.", ""]
    if with_sheet and times:
        parts.append(sheet_line(times))
    parts.append("Fix each problem only where it is (a size, a position, a moment) and keep the rest of the page. "
                 "Answer with the complete corrected file in one ```js block, or with `@flag <reason>` if the problems should stay as they are.")
    return "\n".join(parts)


def reviewer_prompt(sb: dict, pid: str, t: dict, rnd: int, issues: list[dict], times: list[dict], change: str = "") -> str:
    page = next((x for x in sb.get("pages", []) if x.get("id") == pid), None)
    must = [i for i in issues if i.get("level") == "error"]
    advice = [i for i in issues if i.get("level") == "warn"]
    last = sb.get("pages") and sb["pages"][-1].get("id") == pid
    cues = "\n".join(f"  - c{c['i']} at {c['at']:.1f}s: \"{c['text']}\"" for c in t["cues"])
    return f"""{f'Round {rnd}: the artist has changed the page since you last saw it.{chr(10)}{chr(10)}' if rnd > 1 else ''}## The page ({pid} of {len(sb.get('pages', []))}, in the film "{sb.get('title', '')}")
- Section: {(page or {}).get('section', '')}
- What it says: {(page or {}).get('say', '')}
- Beats:
{_beats(page, camera=False)}
- The page lasts {t['end'] - t['start']:.1f}s. Narration:
{cues}
{f'{chr(10)}This page ends the film: after its last line it holds {t["end"] - t["speechEnd"]:.1f}s, then the film fades out by itself. Fail it if the film ends mid-move, on a half-drawn picture, or on an emptied frame.{chr(10)}' if last else ''}{f'{chr(10)}The user asked for this change to the page: {change}{chr(10)}Fail the page if the pictures do not show it.{chr(10)}' if change else ''}
## The checker
{('Must-fix (already sent to the artist):' + chr(10) + _lint_lines(must)) if must else 'Nothing must be fixed.'}
{('Advice (a measurement; fail on it only if the picture shows a problem):' + chr(10) + _lint_lines(advice)) if advice else ''}

{sheet_line(times)}
Answer with the verdict JSON."""


def publish_prompt(title: str, summary: str, sections: list[str], narration: str, lang: str) -> str:
    zh = lang != "en"
    return f"""Write the publishing notes for this explainer film.

Title: {title}
Summary: {summary}
Chapters: {' / '.join(sections)}
Narration:
{narration[:6000]}

Answer with one ```json block:
{{ "titles": {{ "bilibili": "≤ 80 characters", "youtube": "≤ 100", "douyin": "≤ 30", "shipinhao": "≤ 16", "xiaohongshu": "≤ 20" }},
  "description": "3–6 sentences: what the film covers and what the viewer takes away",
  "tags": ["5–10 tags"] }}
Titles are concrete and curious (a question or a surprising fact from the film), no clickbait, no emoji spam.
Write it all in {'Simplified Chinese' if zh else 'English'}."""
