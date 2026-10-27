"""Local marketplace integrity, offline validation and workspace confinement, without network access."""

import hashlib
import json
import zipfile

import pytest

from spike.cli import main
from spike.skills.marketplace import MarketplaceError, install, read_index


@pytest.fixture
def catalog(tmp_path):
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("sample/SKILL.md", "---\nname: sample\ndescription: Sample instructions\nlicense: MIT\n---\nDo it.\n")
        z.writestr("sample/example.py", "raise RuntimeError('must never execute during install')\n")
    entry = {"id": "sample", "license": "MIT", "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
             "path": "sample.zip"}
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"packs": [entry]}), encoding="utf-8")
    return index, archive, entry


def test_index_and_install_validate_without_executing_resources(catalog, tmp_path):
    index, _, entry = catalog
    assert read_index(index, tmp_path) == [entry]
    target = tmp_path / "skills"
    assert install(index, "sample", target, tmp_path, approved=True) == ["sample"]
    assert (target / "sample/SKILL.md").is_file()
    assert "must never execute" in (target / "sample/example.py").read_text(encoding="utf-8")
    with pytest.raises(MarketplaceError, match="exists"):
        install(index, "sample", target, tmp_path, approved=True)


def test_hash_mismatch_refused_without_writing(catalog, tmp_path):
    index, archive, _ = catalog
    archive.write_bytes(b"changed")
    with pytest.raises(MarketplaceError, match="sha256"):
        install(index, "sample", tmp_path / "skills", tmp_path, approved=True)
    assert not (tmp_path / "skills").exists()


def rewrite(catalog, entries):
    index, archive, entry = catalog
    with zipfile.ZipFile(archive, "w") as z:
        for name, text in entries.items():
            z.writestr(name, text)
    entry["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    index.write_text(json.dumps({"packs": [entry]}), encoding="utf-8")
    return index


@pytest.mark.parametrize("entries", [
    {"sample/SKILL.md": "invalid"},
    {"sample/SKILL.md": "---\nname: sample\ndescription: d\nlicense: GPL-3.0\n---\nBody"},
    {"sample/SKILL.md": "---\nname: sample\ndescription: d\nlicense: MIT\n---\n"},
    {"../escape/SKILL.md": "bad"},
    {"sample\\SKILL.md": "bad"},
    {"README.md": "no skills"},
    {"sample/SKILL.md": "---\nname: sample\ndescription: d\nlicense: MIT\n---\nBody",
     "sample/key.txt": "sk-" + "x" * 32},
])
def test_invalid_pack_leaves_destination_untouched(catalog, tmp_path, entries):
    index = rewrite(catalog, entries)
    target = tmp_path / "skills"
    with pytest.raises(MarketplaceError):
        install(index, "sample", target, tmp_path, approved=True)
    assert not target.exists()


@pytest.mark.parametrize("patch", [{"license": "GPL-3.0"}, {"sha256": "bad"}, {"id": "../bad"},
                                   {"path": "../outside.zip"}, {"path": "https://example.org/pack.zip"}])
def test_invalid_index(catalog, tmp_path, patch):
    index, _, entry = catalog
    index.write_text(json.dumps({"packs": [entry | patch]}), encoding="utf-8")
    with pytest.raises(MarketplaceError):
        read_index(index, tmp_path)


def test_permission_and_workspace_required(catalog, tmp_path):
    index, _, _ = catalog
    with pytest.raises(MarketplaceError, match="Permission"):
        install(index, "sample", tmp_path / "skills", tmp_path)
    with pytest.raises(MarketplaceError):
        install(index, "sample", tmp_path.parent / "outside", tmp_path, approved=True)
    try:
        (tmp_path / "link").symlink_to(tmp_path.parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem symlinks unavailable")
    with pytest.raises(MarketplaceError):
        install(index, "sample", tmp_path / "link/skills", tmp_path, approved=True)


def test_cli_list_install_and_localized_errors(catalog, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    index, _, _ = catalog
    assert main(["skills", "list", str(index)]) == 0
    assert "sample" in capsys.readouterr().out
    args = ["skills", "install", str(index), "sample", "--destination", "skills"]
    assert main(args + ["--lang", "es"]) == 1
    assert "Permiso" in capsys.readouterr().err
    assert main(args + ["--yes"]) == 0
    assert "sample" in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["[", "[]", "{}", '{"packs": [42]}'])
def test_malformed_index_is_a_safe_error(tmp_path, raw):
    index = tmp_path / "index.json"
    index.write_text(raw, encoding="utf-8")
    with pytest.raises(MarketplaceError):
        read_index(index, tmp_path)


def test_duplicate_pack_unknown_id_and_license_disagreement(catalog, tmp_path):
    index, _, entry = catalog
    with pytest.raises(MarketplaceError, match="Unknown"):
        install(index, "unknown", tmp_path / "skills", tmp_path, approved=True)
    index.write_text(json.dumps({"packs": [entry, entry]}), encoding="utf-8")
    with pytest.raises(MarketplaceError):
        read_index(index, tmp_path)
    index.write_text(json.dumps({"packs": [entry | {"license": "Apache-2.0"}]}), encoding="utf-8")
    with pytest.raises(MarketplaceError, match="validation"):
        install(index, "sample", tmp_path / "skills", tmp_path, approved=True)
    assert not (tmp_path / "skills").exists()


def test_multi_skill_pack_is_validated_before_any_publication(catalog, tmp_path):
    valid = "---\nname: sample\ndescription: d\nlicense: MIT\n---\nInstructions"
    index = rewrite(catalog, {"sample/SKILL.md": valid, "other/SKILL.md": "bad"})
    with pytest.raises(MarketplaceError):
        install(index, "sample", tmp_path / "skills", tmp_path, approved=True)
    assert not (tmp_path / "skills").exists()
    index = rewrite(catalog, {"sample/SKILL.md": valid, "other/SKILL.md": valid.replace("sample", "other")})
    assert install(index, "sample", tmp_path / "skills", tmp_path, approved=True) == ["other", "sample"]


def test_zip_symlink_is_rejected(catalog, tmp_path):
    index, archive, entry = catalog
    with zipfile.ZipFile(archive, "w") as z:
        link = zipfile.ZipInfo("sample/SKILL.md")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        z.writestr(link, "../../secret")
    entry["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    index.write_text(json.dumps({"packs": [entry]}), encoding="utf-8")
    with pytest.raises(MarketplaceError):
        install(index, "sample", tmp_path / "skills", tmp_path, approved=True)
    assert not (tmp_path / "skills").exists()


def test_index_and_archive_size_limits(catalog, tmp_path, monkeypatch):
    from spike.skills import marketplace

    index, _, _ = catalog
    monkeypatch.setattr(marketplace, "MAX_INDEX", 1)
    with pytest.raises(MarketplaceError):
        read_index(index, tmp_path)
    monkeypatch.setattr(marketplace, "MAX_INDEX", 1024**2)
    monkeypatch.setattr(marketplace, "MAX_BYTES", 1)
    with pytest.raises(MarketplaceError):
        install(index, "sample", tmp_path / "skills", tmp_path, approved=True)
    monkeypatch.setattr(marketplace, "MAX_BYTES", 50 * 1024**2)
    monkeypatch.setattr(marketplace, "MAX_ENTRIES", 0)
    with pytest.raises(MarketplaceError):
        install(index, "sample", tmp_path / "skills", tmp_path, approved=True)


def test_publication_failure_rolls_back_only_new_skills(catalog, tmp_path, monkeypatch):
    from spike.skills import marketplace

    index, _, _ = catalog
    target = tmp_path / "skills"
    target.mkdir()
    (target / "existing.txt").write_text("keep", encoding="utf-8")

    def fail_move(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(marketplace.shutil, "move", fail_move)
    with pytest.raises(MarketplaceError):
        install(index, "sample", target, tmp_path, approved=True)
    assert sorted(p.name for p in target.iterdir()) == ["existing.txt"]
    assert not list(tmp_path.glob(".skills-*"))
