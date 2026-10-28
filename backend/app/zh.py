"""Chinese wording for the checkers' messages (engine lints and the server's own), for the interface and the job log.
The English stays in `msg`: it is what goes back to the model."""

from __future__ import annotations

import re

# storyboard-lint.mjs and plan.own_storyboard_issues: (pattern on msg, Chinese with \1 … for the groups)
_STORYBOARD = [
    (r"the storyboard has no pages", "分镜里没有页面"),
    (r"missing style.*", "缺少风格（整部片只用一种风格）"),
    (r'style "(.+)" does not exist', r"风格「\1」不存在"),
    (r"missing cast.*", "缺少 cast（none / hands / silhouette）：没有插画素材时，人物不能露脸"),
    (r"only (\d+) beat\(s\).*", r"只有 \1 拍：每页至少要有 2 处可见的变化"),
    (r"at least 2 beats per page", "每页至少要有 2 拍"),
    (r'two beats at "(.+?)".*', r"两拍都落在「\1」：把这一拍绑到它发生的那个词上，或挪到别的句子，或合并"),
    (r"the object is empty", "「画什么」是空的"),
    (r'the object is only a layout word: "(.+?)".*', r"「画什么」只写了版式词「\1」：要写画面里一个具体的东西（雪球、存钱罐、山路）"),
    (r"the action is empty", "「怎么动」是空的"),
    (r'the action is only a catch-all word: "(.+?)".*', r"「怎么动」只写了笼统的「\1」：要写清怎么动（滚下来、长大、落进去、裂开）"),
    (r'on-screen text "(.+?)" has (\d+) (\S+) \(each element ≤ (\d+)\)', r"上屏文字「\1」有 \2 个字（每处不超过 \4 个）"),
    (r'the object is a character with a face \("(.+?)"\).*', r"「\1」是有脸的人物：只画手、背影或剪影，或让物体当主角"),
    (r'on-screen number "(.+?)" has no source in the material', r"上屏数字「\1」在素材和口播里找不到出处"),
    (r"the first page is text-led.*", "第一页以文字为主：开场要用一个物体加一个问题"),
    (r"the last page is text-led.*", "最后一页以文字为主：结尾要落在主角物体的动作上，不要用金句卡"),
    (r"the last beat is text.*", "最后一拍是文字：结尾要让主角物体完成一个动作"),
    (r"text-led beats are (\d+)% of all beats.*", r"以文字为主的拍占了 \1%（不超过 30%）"),
    (r'three beats in a row use the same camera move "(.+?)"', r"连续三拍都用同一个镜头「\1」"),
    (r"(\d+) pages is more than the (\d+) this length allows.*", r"\1 页超过了这个时长允许的 \2 页：请压缩"),
]
_STORYBOARD = [(re.compile(p), z) for p, z in _STORYBOARD]


CAMERA = {"fixed": "固定", "static": "固定", "push in": "推近", "push": "推近", "zoom in": "推近", "pull back": "拉远",
          "pull out": "拉远", "zoom out": "拉远", "pan": "横移", "tilt": "上下摇", "follow": "跟随", "slam": "猛推", "orbit": "环绕"}


def storyboard(msg: str) -> str:
    for p, z in _STORYBOARD:
        m = p.fullmatch(msg.strip())
        if m:
            out = m.expand(z)
            return re.sub(r"「(.+?)」$", lambda c: f"「{CAMERA.get(c[1].lower(), c[1])}」", out) if "镜头" in out else out
    return msg


def page(i: dict) -> str:
    """A page check's issue (checks.mjs) by its kind and data."""
    k, x, msg = i.get("kind"), i.get("data") or {}, i.get("msg") or ""
    if k == "off-canvas":
        return f"出界/贴边：「{x.get('text', '')}」"
    if k == "subtitle-band":
        return f"压到字幕区：「{x.get('text', '')}」"
    if k == "small-text":
        return f"字太小（{x.get('px')}px，至少 {x.get('min')}px）：「{x.get('text', '')}」"
    if k == "overlap":
        return f"文字重叠：「{x.get('a', '')}」和「{x.get('b', '')}」（较小者的 {x.get('percent')}%）"
    if k == "raw-markup":
        return f"屏幕上出现了原始标记「{x.get('markup', '')}」：直接写字符（λ、≈、²、→），公式用 P.tex"
    if k == "runtime":
        return f"运行出错：{x.get('message', msg)}"
    if k == "palette":
        return f"未知颜色名「{x.get('name', '')}」：这个风格的调色板只有 {x.get('palette', '')}"
    m = re.match(r"unknown API: (\S+) does not exist", msg)
    if m:
        return f"不存在的接口：{m[1]}" + (f"（是不是 {msg.split('did you mean ')[1].rstrip('?')}？）" if "did you mean" in msg else "")
    m = re.match(r"wrong API use: (\S+) is not a function", msg)
    if m:
        return f"接口用错了：{m[1]} 不是函数"
    return msg


def add(issues: list[dict], kind: str) -> list[dict]:
    """Each issue with a `zh` beside its `msg`."""
    f = storyboard if kind == "storyboard" else None
    return [{**i, "zh": f(i.get("msg") or "") if f else page(i)} for i in issues or []]
