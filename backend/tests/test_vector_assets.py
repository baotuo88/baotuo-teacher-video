from __future__ import annotations

import asyncio
import json

import pytest

from app import engine, film, prompts, store, vector_assets
from conftest import needs_node
from test_import_jobs import make_zip, post_zip, SCRIPT

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0 L100 100" fill="none" stroke="blue"/></svg>'


def test_sanitize_removes_active_content():
    svg = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" onload="alert(1)">
    <script>alert(1)</script><foreignObject><div>HTML</div></foreignObject>
    <image href="https://example.com/x"/><use href="#x"/><style>path{fill:red}</style>
    <path d="M0 0 L100 100" style="stroke:blue;fill:url(https://evil);animation:x" onclick="bad()">
    <animate attributeName="d"/></path></svg>'''
    result = vector_assets.sanitize(svg)
    for forbidden in ('script', 'foreignObject', 'https:', 'href', 'onclick', 'onload', 'animate', 'style=', '<style'):
        assert forbidden not in result
    assert 'stroke="blue"' in result


@pytest.mark.parametrize('data', [
    b'<!DOCTYPE svg [<!ENTITY x "bad">]><svg/>', b'<html/>', b'<svg>', b'\xff',
    b'<svg viewBox="0 0 NaN 10"><path d="M0 0"/></svg>',
    b'<svg viewBox="0 0 -1 10"><path d="M0 0"/></svg>',
    b'<svg><path d="M0 0"/></svg>', b'<svg viewBox="0 0 10 10"><image href="x"/></svg>',
    b' ' * (vector_assets.MAX_BYTES + 1),
])
def test_invalid_svg(data):
    with pytest.raises(ValueError):
        vector_assets.sanitize(data)


def test_limits_and_width_fallback():
    assert 'viewBox="0 0 100 80"' in vector_assets.sanitize(b'<svg width="100px" height="80"><rect width="10" height="10"/></svg>')
    with pytest.raises(ValueError):
        vector_assets.sanitize(b'<svg viewBox="0 0 1 1">' + b'<g>' * 45 + b'<path/>' + b'</g>' * 45 + b'</svg>')
    with pytest.raises(ValueError):
        vector_assets.sanitize(b'<svg viewBox="0 0 1 1">' + b'<path/>' * 2001 + b'</svg>')


def test_prepare_opt_in_and_cache(tmp_path):
    (tmp_path / 'assets').mkdir()
    f = tmp_path / 'assets' / 'line.svg'
    f.write_bytes(SVG)
    assert vector_assets.prepare(tmp_path, []) == []
    assert not (tmp_path / 'extras').exists()
    assert vector_assets.prepare(tmp_path, ['line.svg']) == [vector_assets.DATA_FILE, vector_assets.COMPONENT_FILE]
    data = tmp_path / vector_assets.DATA_FILE
    before, mtime = data.read_text(), data.stat().st_mtime_ns
    vector_assets.prepare(tmp_path, ['line.svg'])
    assert data.stat().st_mtime_ns == mtime
    f.write_bytes(SVG.replace(b'blue', b'red'))
    vector_assets.prepare(tmp_path, ['line.svg'])
    assert data.read_text() != before
    for names in [['../escape.svg'], ['missing.svg'], [1], 'line.svg']:
        with pytest.raises(ValueError):
            vector_assets.prepare(tmp_path, names)


@needs_node
def test_upload_render_metadata_delete_and_import(client):
    p = store.create({})
    pid = p['id']
    d = store.pdir(pid)
    engine.write_script(d, {'title': 'Vector'}, [{'id': 'p01', 'cues': ['line']}])
    r = client.post(f'/api/projects/{pid}/assets', files={'file': ('line.svg', SVG, 'image/svg+xml')})
    assert r.status_code == 200, r.text
    name = r.json()['name']
    assert store.get(pid)['vector_assets'] == [name]
    meta = asyncio.run(engine.read_script(d))['META']
    assert vector_assets.COMPONENT_FILE in meta['extras']
    assert 'P.vector' in prompts.assets_note({name: ''}, True, [name])
    # Real export/import keeps opted-in assets and rebuilds safe extras.
    exported = client.get(f'/api/projects/{pid}/export')
    assert exported.status_code == 200
    imported = post_zip(client, exported.content)
    assert imported.status_code == 200, imported.text
    other = store.pdir(imported.json()['id'])
    assert (other / vector_assets.DATA_FILE).exists()
    assert (other / 'assets' / name).read_text() == (d / 'assets' / name).read_text()
    (d / 'pages' / 'p01.js').write_text(f"P.vector('{name}',0,0,100,100)")
    assert client.delete(f'/api/projects/{pid}/assets/{name}').status_code == 400
    (d / 'pages' / 'p01.js').unlink()
    assert client.delete(f'/api/projects/{pid}/assets/{name}').status_code == 200
    assert vector_assets.COMPONENT_FILE not in asyncio.run(engine.read_script(d))['META']['extras']


def test_upload_rejects_invalid_and_routes_materials(client):
    p = store.create({})
    url = f'/api/projects/{p["id"]}'
    r = client.post(url + '/assets', files={'file': ('bad.svg', b'<script/>', 'image/svg+xml')})
    assert r.status_code == 400
    assert store.get(p['id'])['assets'] == {}
    r = client.post(url + '/materials/file', files={'file': ('line.svg', SVG, 'image/svg+xml')})
    assert r.status_code == 200, r.text
    assert store.get(p['id'])['vector_assets'] == ['line.svg']


@needs_node
def test_old_projects_not_opted_in():
    p = store.create({})
    d = store.pdir(p['id'])
    (d / 'assets' / 'old.svg').write_bytes(SVG)
    data = asyncio.run(film.apply_meta(d, p['id']))
    assert vector_assets.COMPONENT_FILE not in data['META']['extras']
    assert not (d / vector_assets.DATA_FILE).exists()


@needs_node
def test_import_rejects_missing_opted_in_asset(client):
    r = post_zip(client, make_zip({'script.js': SCRIPT, '.studio/project.json': json.dumps({'vector_assets': ['missing.svg']})}))
    assert r.status_code == 400
    assert store.list_projects() == []


def test_svg_mutations_blocked_during_job(client, monkeypatch):
    from app.routes_projects import manager
    p = store.create({})
    base = f'/api/projects/{p["id"]}/assets'
    r = client.post(base, files={'file': ('line.svg', SVG, 'image/svg+xml')})
    assert r.status_code == 200
    monkeypatch.setattr(manager, 'current', lambda pid: object())
    assert client.post(base, files={'file': ('next.svg', SVG, 'image/svg+xml')}).status_code == 409
    assert client.delete(base + '/line.svg').status_code == 409
    assert (store.pdir(p['id']) / 'assets' / 'line.svg').exists()
