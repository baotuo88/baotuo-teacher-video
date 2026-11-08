"""Opt-in, local SVG assets. Only a small passive SVG subset reaches the browser.

The generated extras embed the cleaned source: the engine hashes extras for its
render cache, so asset contents (not just filenames) participate in invalidation.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_NODES = 2000
SVG_NS = 'http://www.w3.org/2000/svg'
TAGS = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'text', 'tspan', 'title', 'desc'}
ATTRS = set(('viewBox preserveAspectRatio x y x1 x2 y1 y2 cx cy r rx ry width height d points transform '
             'fill stroke stroke-width stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray '
             'stroke-dashoffset fill-rule fill-opacity stroke-opacity opacity font-size font-family '
             'font-weight text-anchor dominant-baseline dx dy').split())
STYLE_ATTRS = ATTRS - {'viewBox', 'd', 'points', 'transform', 'preserveAspectRatio'}
DATA_FILE = 'extras/btv-vector-assets.js'
COMPONENT_FILE = 'extras/btv-vector.js'


def sanitize(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError('SVG 最大 2MB')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        raise ValueError('SVG 必须是 UTF-8 编码') from e
    if re.search(r'<!\s*(DOCTYPE|ENTITY)', text, re.I):
        raise ValueError('SVG 不允许 DTD 或实体声明')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError('SVG XML 格式不正确') from e
    if root.tag not in ('svg', f'{{{SVG_NS}}}svg'):
        raise ValueError('文件不是 SVG')
    if sum(1 for _ in root.iter()) > MAX_NODES:
        raise ValueError('SVG 太复杂（最多 2000 个元素）')

    def clean(node: ET.Element, depth: int = 0) -> ET.Element | None:
        if depth > 40:
            raise ValueError('SVG 嵌套太深')
        tag = node.tag.removeprefix(f'{{{SVG_NS}}}')
        if tag not in TAGS or (tag == 'svg' and depth):
            return None
        out = ET.Element(tag)
        attrs = dict(node.attrib)
        # Convert a restricted set of inline presentation rules; never preserve CSS.
        for rule in attrs.pop('style', '').split(';'):
            key, sep, value = rule.partition(':')
            if sep and key.strip() in STYLE_ATTRS:
                attrs[key.strip()] = value.strip()
        for key, value in attrs.items():
            # No namespaces, links, events, CSS functions, escape sequences or URLs.
            if key not in ATTRS or len(value) > 100000:
                continue
            if key in ('d', 'points', 'transform'):
                allowed = r'[a-zA-Z0-9\s.,+()\-]*'
            else:
                allowed = r'[a-zA-Z0-9\s.,#%+\-]*'
            if re.fullmatch(allowed, value) and not re.search(r'url|javascript|expression', value, re.I):
                out.set(key, value)
        if tag in ('text', 'tspan', 'title', 'desc'):
            out.text = node.text
        for child in node:
            kept = clean(child, depth + 1)
            if kept is not None:
                out.append(kept)
                if tag in ('text', 'tspan'):
                    kept.tail = child.tail
        return out

    cleaned = clean(root)
    assert cleaned is not None
    cleaned.set('xmlns', SVG_NS)
    if not any(n.tag in TAGS - {'svg', 'g', 'title', 'desc'} for n in cleaned.iter()):
        raise ValueError('SVG 没有可用图形；请转换为基本路径，不要使用图片、外链或 use 引用')
    if 'viewBox' not in cleaned.attrib:
        def dimension(key: str) -> float:
            value = root.get(key, '').removesuffix('px')
            try:
                n = float(value)
            except ValueError:
                n = 0
            if not 0 < n <= 100000:
                raise ValueError('SVG 需要有效的 viewBox，或正数 width / height')
            return n
        cleaned.set('viewBox', f'0 0 {dimension("width"):g} {dimension("height"):g}')
    box = re.split(r'[\s,]+', cleaned.get('viewBox', '').strip())
    try:
        nums = [float(v) for v in box]
    except ValueError:
        nums = []
    if len(nums) != 4 or not all(abs(v) <= 100000 for v in nums) or nums[2] <= 0 or nums[3] <= 0:
        raise ValueError('SVG viewBox 无效或过大')
    return ET.tostring(cleaned, encoding='unicode')


def prepare(d: Path, names: list[str]) -> list[str]:
    """Rebuild only explicitly opted-in assets; never scan or migrate old projects."""
    if not names:
        return []
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError('SVG 素材列表无效')
    if len(names) > 50:
        raise ValueError('每个项目最多 50 个 SVG 素材')
    assets = {}
    for name in sorted(set(names)):
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.svg'):
            raise ValueError('SVG 素材名称无效')
        f = d / 'assets' / name
        if f.is_symlink() or not f.is_file():
            raise ValueError(f'SVG 素材不存在：{name}')
        with f.open('rb') as src:
            assets[name] = sanitize(src.read(MAX_BYTES + 1))
    extras = d / 'extras'
    extras.mkdir(exist_ok=True)
    content = 'window.BTV_VECTORS = ' + json.dumps(assets, ensure_ascii=True).replace('<', '\\u003c') + ';\n'
    for path, text in [(d / DATA_FILE, content),
                       (d / COMPONENT_FILE, (Path(__file__).parent / 'js' / 'vector.js').read_text('utf-8'))]:
        if not path.exists() or path.read_text('utf-8') != text:
            tmp = path.with_suffix('.tmp')
            tmp.write_text(text, 'utf-8')
            tmp.replace(path)
    return [DATA_FILE, COMPONENT_FILE]
