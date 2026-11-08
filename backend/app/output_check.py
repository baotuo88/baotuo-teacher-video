"""Local post-render validation using the ffmpeg already shipped with the app."""
from __future__ import annotations

import re
from pathlib import Path

from . import config, engine


def parse_probe(log: str, expected_duration: float, expect_audio: bool) -> dict:
    duration = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', log)
    video = re.search(r'Stream[^\n]*Video:[^\n]*?\b(\d{2,5})x(\d{2,5})\b', log)
    audio = bool(re.search(r'Stream[^\n]*Audio:', log))
    if not duration or not video:
        raise ValueError('成片缺少有效时长或视频轨')
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    if seconds <= 0 or abs(seconds - expected_duration) > max(1.0, expected_duration * 0.02):
        raise ValueError(f'成片时长异常：实际 {seconds:.2f}s，时间轴 {expected_duration:.2f}s')
    if expect_audio and not audio:
        raise ValueError('项目含配音或背景音乐，但成片缺少音轨')
    width, height = int(video[1]), int(video[2])
    if (width, height) != (1920, 1080):
        raise ValueError(f'成片分辨率异常：{width}×{height}，应为 1920×1080')
    return {'duration': seconds, 'width': width, 'height': height, 'audio': audio}


async def check(d: Path, files: list[Path], duration: float, expect_audio: bool) -> list[dict]:
    results = []
    for f in files:
        if not f.is_file() or f.stat().st_size == 0:
            raise ValueError(f'没有产出成片：{f.name}')
        # Decode the complete file, not just its header. -xerror rejects corrupt frames.
        code, _, err = await engine.run([
            config.FFMPEG, '-hide_banner', '-nostdin', '-nostats', '-xerror', '-i', str(f),
            '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], d, 1800)
        if code:
            raise ValueError(f'{f.name} 解码检查失败：{err[-500:]}')
        results.append({'name': f.name, **parse_probe(err, duration, expect_audio)})
    return results


def write_report(d: Path, results: list[dict]) -> None:
    rows = ['# 成片检查', '', '本地 FFmpeg 完整解码通过；不调用付费接口。', '',
            '| 文件 | 时长 | 分辨率 | 音轨 |', '|---|---|---|---|']
    for r in results:
        rows.append(f'| {r["name"]} | {r["duration"]:.2f}s | {r["width"]}×{r["height"]} | {"有" if r["audio"] else "无（无声项目）"} |')
    rows += ['', '检查范围：完整解码、视频轨、时长、分辨率及预期音轨。不会判断文案准确性、画面美观或口型同步。']
    (d / 'out' / '成片检查.md').write_text('\n'.join(rows) + '\n', 'utf-8')
