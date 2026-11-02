"""Reliability tests for skill and pack zip imports (`spike/packs.py`)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import spike.packs as packs
from spike.projects import ProjectError
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def client_and_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AppState]:
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path / "home", provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    return TestClient(create_app(state)), state


def test_macos_finder_zip_metadata_is_ignored_in_skills_and_packs(tmp_path: Path) -> None:
    skill_md = "---\nname: macos-skill\ndescription: Skill comprimida en Finder.\n---\nInstrucciones UTF-8 áéíóú.\n".encode()
    finder_skill_zip = make_zip({
        ".DS_Store": b"\x00\x01finder",
        "macos-skill/.DS_Store": b"\x00\x01finder",
        "macos-skill/._SKILL.md": b"\x00\x05\x16\x07appledouble",
        "macos-skill/SKILL.md": skill_md,
        "macos-skill/guide.md": "Guía".encode(),
        "__MACOSX/._macos-skill": b"\x00\x05\x16\x07appledouble",
        "__MACOSX/macos-skill/._SKILL.md": b"\x00\x05\x16\x07appledouble",
    })
    skills_dir = tmp_path / "skills"
    installed = packs.install_skills_zip(finder_skill_zip, skills_dir)
    assert installed == ["macos-skill"]
    assert not (skills_dir / "__MACOSX").exists()
    assert not (skills_dir / "macos-skill" / ".DS_Store").exists()
    assert not (skills_dir / "macos-skill" / "._SKILL.md").exists()
    assert (skills_dir / "macos-skill" / "guide.md").read_text(encoding="utf-8") == "Guía"

    (skills_dir / "macos-skill" / ".DS_Store").write_bytes(b"finder")
    exported = packs.export_pack([], [], [skills_dir / "macos-skill"])
    with zipfile.ZipFile(io.BytesIO(exported)) as exported_zf:
        assert "skills/macos-skill/.DS_Store" not in exported_zf.namelist()

    manifest = {
        "format": "spike-pack",
        "version": 1,
        "specialists": [],
        "connectors": [],
        "skills": ["macos-skill"],
    }
    finder_pack_zip = make_zip({
        "pack.json": b"\xef\xbb\xbf" + json.dumps(manifest).encode(),
        ".DS_Store": b"finder",
        "._pack.json": b"appledouble",
        "__MACOSX/._pack.json": b"appledouble",
        "skills/macos-skill/SKILL.md": skill_md,
        "__MACOSX/skills/macos-skill/._SKILL.md": b"appledouble",
    })
    pack_skills_dir = tmp_path / "pack_skills"
    parsed_manifest, pack_skills = packs.read_pack(finder_pack_zip, pack_skills_dir)
    assert parsed_manifest["format"] == "spike-pack"
    assert pack_skills == ["macos-skill"]


def test_top_level_skill_front_matter_rejects_non_dict_and_non_utf8_with_400_and_accepts_bom(
    client_and_state: tuple[TestClient, AppState],
) -> None:
    client, _ = client_and_state
    for bad_md in (
        b"---\njust-a-scalar-string\n---\nBody\n",
        b"---\n- list-item\n---\nBody\n",
        b"\xff\xfe---\nname: broken-encoding\ndescription: x\n---\nBody\n",
        b"Not at start\n---\nname: mid-file\ndescription: x\n---\nBody\n",
    ):
        res = client.post("/api/skills/import", content=make_zip({"SKILL.md": bad_md}))
        assert res.status_code == 400

    bom_skill = b"\xef\xbb\xbf---\nname: bom-skill\ndescription: UTF-8 with BOM.\n---\nContenido.\n"
    ok_res = client.post("/api/skills/import", content=make_zip({"SKILL.md": bom_skill}))
    assert ok_res.status_code == 200, ok_res.text
    assert ok_res.json() == {"names": ["bom-skill"]}


@pytest.mark.parametrize("bad_fields", [
    {"specialists": 123, "connectors": [], "skills": []},
    {"specialists": ["not-an-object"], "connectors": [], "skills": []},
    {"specialists": [], "connectors": "invalid", "skills": []},
    {"specialists": [], "connectors": ["not-an-object"], "skills": []},
    {"specialists": [], "connectors": [], "skills": {"not": "a-list"}},
    {"specialists": [], "connectors": [], "skills": [123]},
])
def test_malformed_pack_manifest_fields_return_400_before_installing_any_skills(
    client_and_state: tuple[TestClient, AppState],
    bad_fields: dict[str, object],
) -> None:
    client, state = client_and_state
    manifest = {"format": "spike-pack", "version": 1, **bad_fields}
    blob = make_zip({
        "pack.json": json.dumps(manifest).encode(),
        "skills/sneaky/SKILL.md": b"---\nname: sneaky\ndescription: Should not install.\n---\nBody\n",
    })
    res = client.post("/api/pack/import", content=blob)
    assert res.status_code == 400
    assert not (state.home / "skills" / "sneaky").exists()


def test_spoofed_zip_header_file_size_is_caught_by_streaming_decompression_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import copy

    monkeypatch.setattr(packs, "MAX_BYTES", 1024)
    big_skill = ("---\nname: huge\ndescription: d\n---\n" + ("A" * 4096)).encode()
    blob = make_zip({"huge/SKILL.md": big_skill})

    real_infolist = zipfile.ZipFile.infolist
    calls = 0

    def spoofed_first_infolist(self: zipfile.ZipFile):
        nonlocal calls
        calls += 1
        infos = real_infolist(self)
        if calls == 1:  # _open() header check sees forged 10-byte size; stream decompresses 4135 bytes
            forged = []
            for info in infos:
                clone = copy.copy(info)
                clone.file_size = 10
                forged.append(clone)
            return forged
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", spoofed_first_infolist)
    with pytest.raises(ProjectError, match="too large"):
        packs.install_skills_zip(blob, tmp_path / "skills")
    assert not (tmp_path / "skills" / "huge").exists()


def test_corrupted_crc_deflate_encrypted_and_unsupported_compression_return_400(
    client_and_state: tuple[TestClient, AppState],
) -> None:
    client, _ = client_and_state
    valid = make_zip({"ok/SKILL.md": b"---\nname: ok\ndescription: ok\n---\nBody\n"})

    # 1. Corrupted DEFLATE payload / CRC mismatch inside entry data (after local header)
    zf = zipfile.ZipFile(io.BytesIO(valid))
    info = zf.infolist()[0]
    corrupted = bytearray(valid)
    corrupted[info.header_offset + 30 + len(info.filename)] ^= 0xFF
    assert client.post("/api/skills/import", content=bytes(corrupted)).status_code == 400

    # 2. Password-encrypted entry (general purpose bit 0 = 0x01 in local header & central directory)
    raw_enc = bytearray(valid)
    cd_enc = raw_enc.index(b"PK\x01\x02")
    raw_enc[6] |= 0x01
    raw_enc[cd_enc + 8] |= 0x01
    assert client.post("/api/skills/import", content=bytes(raw_enc)).status_code == 400

    # 3. Unsupported compression method (e.g. WinZip AES = 99 -> NotImplementedError)
    buf_aes = io.BytesIO()
    with zipfile.ZipFile(buf_aes, "w", zipfile.ZIP_STORED) as z_aes:
        z_aes.writestr("aes/SKILL.md", b"---\nname: aes\ndescription: d\n---\nBody\n")
    raw_aes = bytearray(buf_aes.getvalue())
    # Patch compression method (uint16 = 99) in both local header (offset 8) and central directory
    cd_idx = raw_aes.index(b"PK\x01\x02")
    raw_aes[8:10] = (99).to_bytes(2, "little")
    raw_aes[cd_idx + 10 : cd_idx + 12] = (99).to_bytes(2, "little")
    assert client.post("/api/skills/import", content=bytes(raw_aes)).status_code == 400


def test_duplicate_skill_names_and_file_directory_collisions_inside_zip_return_400(
    client_and_state: tuple[TestClient, AppState],
) -> None:
    client, _ = client_and_state
    dup_zip = make_zip({
        "folder-a/SKILL.md": b"---\nname: twin-skill\ndescription: first\n---\nOne\n",
        "folder-b/SKILL.md": b"---\nname: twin-skill\ndescription: second\n---\nTwo\n",
    })
    dup_res = client.post("/api/skills/import", content=dup_zip)
    assert dup_res.status_code == 400

    collision_zip = make_zip({
        "clash/SKILL.md": b"---\nname: clash\ndescription: ok\n---\nBody\n",
        "clash/resource": b"a-regular-file",
        "clash/resource/nested.txt": b"collides-with-file",
    })
    col_res = client.post("/api/skills/import", content=collision_zip)
    assert col_res.status_code == 400
