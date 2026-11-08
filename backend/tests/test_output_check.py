import asyncio

import pytest

from app import output_check

LOG = '''Duration: 00:00:12.50, start: 0.000000, bitrate: 123 kb/s
Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1920x1080, 24 fps
Stream #0:1(und): Audio: aac (LC), 24000 Hz, mono
'''


def test_probe_valid_and_silent():
    r = output_check.parse_probe(LOG, 12.5, True)
    assert r == {'duration': 12.5, 'width': 1920, 'height': 1080, 'audio': True}
    assert not output_check.parse_probe(LOG.split('Stream #0:1')[0], 12.5, False)['audio']


@pytest.mark.parametrize('log,duration,audio', [
    ('', 12.5, False), (LOG, 50, True), (LOG.replace('1920x1080', '320x240'), 12.5, True),
    (LOG.split('Stream #0:1')[0], 12.5, True),
])
def test_probe_failures(log, duration, audio):
    with pytest.raises(ValueError):
        output_check.parse_probe(log, duration, audio)


def test_check_decodes_all_current_outputs(monkeypatch, tmp_path):
    f = tmp_path / 'current.mp4'
    f.write_bytes(b'video')
    calls = []
    async def run(cmd, cwd, timeout):
        calls.append(cmd)
        return 0, '', LOG
    monkeypatch.setattr(output_check.engine, 'run', run)
    results = asyncio.run(output_check.check(tmp_path, [f], 12.5, True))
    assert len(results) == 1
    assert '-xerror' in calls[0] and '-f' in calls[0]
    (tmp_path / 'out').mkdir()
    output_check.write_report(tmp_path, results)
    assert '1920×1080' in (tmp_path / 'out' / '成片检查.md').read_text()
    async def fail(*args):
        return 1, '', 'corrupt'
    monkeypatch.setattr(output_check.engine, 'run', fail)
    with pytest.raises(ValueError, match='解码检查失败'):
        asyncio.run(output_check.check(tmp_path, [f], 12.5, True))
    with pytest.raises(ValueError, match='没有产出成片'):
        asyncio.run(output_check.check(tmp_path, [tmp_path / 'missing.mp4'], 12.5, True))


def test_render_checks_exact_outputs_before_recording(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import produce
    (tmp_path / 'out').mkdir()
    meta = {'name': 'current', 'lang': 'en'}
    monkeypatch.setattr(produce.store, 'pdir', lambda pid: tmp_path)
    monkeypatch.setattr(produce.store, 'get', lambda pid: {'style': 'whiteboard'})
    monkeypatch.setattr(produce.settings, 'load', lambda: {'render': {'fps': 24, 'workers': 1}})
    monkeypatch.setattr(produce.styles, 'is_webgl', lambda style: False)
    async def pages(*args): return [{'id': 'p01'}]
    async def ensure(*args): pass
    async def apply(*args): return {'META': meta}
    async def timeline(*args): return {'duration': 12.5}
    async def node(*args, **kwargs): return 0, '', ''
    monkeypatch.setattr(produce.film, 'read_pages', pages)
    monkeypatch.setattr(produce, 'ensure_voice', ensure)
    monkeypatch.setattr(produce.film, 'apply_meta', apply)
    monkeypatch.setattr(produce.film, 'page_code', lambda *args: 'page')
    monkeypatch.setattr(produce.engine, 'timeline', timeline)
    monkeypatch.setattr(produce.engine, 'node', node)
    calls = []
    async def check(d, files, duration, expect_audio):
        calls.append(([f.name for f in files], expect_audio))
        return []
    monkeypatch.setattr(produce.output_check, 'check', check)
    monkeypatch.setattr(produce.output_check, 'write_report', lambda *args: None)
    monkeypatch.setattr(produce.store, 'update', lambda *args: None)
    job = SimpleNamespace(pid='p', log=lambda *args: None, set_progress=lambda **kwargs: None)
    asyncio.run(produce.render_job(job, subs=False))
    assert calls == [(['current-no-subtitles.mp4'], False)]
    calls.clear()
    meta['voice'] = {'speaker': 'x'}
    asyncio.run(produce.render_job(job, subs=True))
    assert calls == [(['current-no-subtitles.mp4', 'current-with-subtitles.mp4'], True)]
