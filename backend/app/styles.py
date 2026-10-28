"""The engine's style packs, with display names."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from . import config

# the five original styles carry no meta.json
CLASSIC = {
    "study": {"zh": "安静书卷", "tag": "暖纸底、墨色手绘、淡彩，拿不准就用它", "fit": ["通用", "读书", "历史", "方法"],
              "swatch": ["#F5EFE3", "#2B2622", "#3B6EA8", "#C8553D"]},
    "whiteboard": {"zh": "白板马克笔", "tag": "白板上边讲边画，黑笔为主、彩笔强调", "fit": ["概念拆解", "流程", "数学推导"],
                   "swatch": ["#FBFBF8", "#1E1E1E", "#D33A2C", "#2F6FD0"]},
    "chalkboard": {"zh": "黑板粉笔", "tag": "深绿板岩上的粉笔板书", "fit": ["公式", "物理", "课堂讲解"],
                   "swatch": ["#24392F", "#F1EFE6", "#F2A2A2", "#9FD3F0"]},
    "warm-story": {"zh": "暖色插画", "tag": "暖色扁平插画 + 贯穿全片的比喻物体", "fit": ["理财", "生活", "心理成长"],
                   "swatch": ["#FBF3E4", "#3A2E28", "#E0A33A", "#7FA27A"]},
    "tech-dark": {"zh": "科技深色", "tag": "石墨深色底上的架构图与代码，青色强调", "fit": ["软件", "AI", "系统原理"],
                  "swatch": ["#16191D", "#E9E6DF", "#3FC1C9", "#E8A33D"]},
}
# needs its own designed look in the storyboard: not offered here
HIDDEN = {"free"}
# styles whose components extend the page agent (warm-story's lives in lib/)
STYLE_EXTRAS = {"warm-story": ["engine/lib/warm.js"]}


@lru_cache(maxsize=1)
def all_styles() -> list[dict]:
    out = []
    d = config.ENGINE_DIR / "styles"
    if not d.exists():
        return out
    for s in sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if s in HIDDEN:
            continue
        info = {"id": s, "name": s, "tagline": "", "fit": [], "swatch": [], "webgl": is_webgl(s),
                "example": (d / s / "example" / "script.js").exists(), "classic": s in CLASSIC}
        meta = d / s / "meta.json"
        if meta.exists():
            try:
                m = json.loads(meta.read_text("utf-8"))
                info.update(name=m.get("name", {}).get("zh") or s, name_en=m.get("name", {}).get("en", s),
                            tagline=m.get("tagline", {}).get("zh", ""), fit=m.get("fit", {}).get("zh", []),
                            swatch=m.get("swatch", []))
            except json.JSONDecodeError:
                pass
        elif s in CLASSIC:
            c = CLASSIC[s]
            info.update(name=c["zh"], tagline=c["tag"], fit=c["fit"], swatch=c["swatch"])
        out.append(info)
    # the classic five first
    order = list(CLASSIC)
    out.sort(key=lambda x: (order.index(x["id"]) if x["id"] in order else 99, x["id"]))
    return out


def exists(style: str) -> bool:
    return bool(re.match(r"^[a-z0-9-]+$", style or "")) and (config.ENGINE_DIR / "styles" / style / "style.css").exists() \
        and style not in HIDDEN


def name(style: str) -> str:
    return next((s["name"] for s in all_styles() if s["id"] == style), style)


def is_webgl(style: str) -> bool:
    k = config.ENGINE_DIR / "styles" / style / "kit.js"
    try:
        return bool(re.search(r"\bTHREE\b", k.read_text("utf-8")))
    except OSError:
        return False


def extras(style: str) -> list[str]:
    if style in STYLE_EXTRAS:
        return STYLE_EXTRAS[style]
    return [f"engine/styles/{style}/kit.js"] if (config.ENGINE_DIR / "styles" / style / "kit.js").exists() else []
