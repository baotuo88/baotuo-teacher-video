"""Projects on disk: paths stay inside the project, deletes stay inside the data dir."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import config, store


def test_create_update_delete_leaves_engine_alone():
    p = store.create({"topic": "为什么天空是蓝的", "duration": 60})
    d = store.pdir(p["id"])
    assert p["title"] == "为什么天空是蓝的"
    assert (d / "engine").is_symlink() and (d / "engine_modules").is_symlink()
    store.update(p["id"], {"notes": "x"})
    store.set_page(p["id"], "p01", status="done")
    got = store.get(p["id"])
    assert got["notes"] == "x" and got["pages"]["p01"]["status"] == "done"
    store.delete(p["id"])
    assert not d.exists()
    assert (config.ENGINE_DIR / "node_modules" / "marker" / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("pid", ["", "../etc", "ABCDEFGHIJ", "abc", "aaaaaaaaaa"])
def test_pdir_rejects_bad_or_unknown_ids(pid):
    with pytest.raises(HTTPException):
        store.pdir(pid)


@pytest.mark.parametrize("rel", ["../settings.json", ".studio/project.json", "/etc/passwd", "a\\b", "x\x00",
                                 "engine/boot.js", "engine_modules/marker/keep.txt", "pages/", ""])
def test_safe_path_rejects(rel):
    p = store.create({"topic": "t"})
    with pytest.raises(HTTPException):
        store.safe_path(store.pdir(p["id"]), rel)


def test_safe_path_follows_engine_links_only_when_allowed():
    p = store.create({"topic": "t"})
    d = store.pdir(p["id"])
    (d / "pages" / "p01.js").write_text("x")
    assert store.safe_path(d, "pages/p01.js").name == "p01.js"
    assert store.safe_path(d, "engine_modules/marker/keep.txt", allow_links=True).name == "keep.txt"


def test_safe_path_rejects_symlink_out_of_project(tmp_path):
    p = store.create({"topic": "t"})
    d = store.pdir(p["id"])
    (tmp_path / "secret").write_text("s")
    (d / "assets" / "x.png").symlink_to(tmp_path / "secret")
    with pytest.raises(HTTPException):
        store.safe_path(d, "assets/x.png")


def test_files_route_does_not_serve_settings(client, saved_settings):
    saved_settings({"api_key": "sk-secret-value-123"})
    p = store.create({"topic": "t"})
    r = client.get(f"/files/{p['id']}/..%2Fsettings.json")
    assert r.status_code == 404
    r = client.get(f"/files/{p['id']}/.studio/project.json")
    assert r.status_code == 404
