"""The license collector of the desktop build (L2): texts come from the installed packages, and a gap stops the build."""

import json
import runpy
import sys
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    return runpy.run_path(str(ROOT / "packaging" / "collect_licenses.py"))


def make_dist(site: Path, name: str, version: str, license_expr: str, files: dict[str, str], requires=()):
    """A minimal installed distribution: `<name>-<version>.dist-info` with METADATA and RECORD."""
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"  # wheel spelling
    info.mkdir(parents=True)
    head = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if license_expr:
        head.append(f"License-Expression: {license_expr}")
    head += [f"Requires-Dist: {r}" for r in requires]
    (info / "METADATA").write_text("\n".join(head) + "\n", encoding="utf-8")
    record = []
    for rel, text in files.items():
        target = info / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        record.append(f"{info.name}/{rel},,")
    (info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
    return metadata.PathDistribution(info)


def test_license_files_of_each_package_are_copied_and_indexed(mod, tmp_path):
    site = tmp_path / "site"
    dists = {
        "alpha": make_dist(site, "alpha", "1.0", "MIT", {"licenses/LICENSE": "alpha MIT text", "LICENSE": "root text"}),
        "beta": make_dist(site, "beta", "2.1", "Apache-2.0", {"licenses/LICENSE.txt": "beta text", "licenses/NOTICE": "n"}),
        "gamma": make_dist(site, "gamma", "0.3", "", {"top_level.txt": "gamma"}),
    }
    out = mod["python_licenses"](tmp_path / "out", dists)
    by_name = {r["name"]: r for r in out}
    assert set(by_name["alpha"]["files"].split(", ")) == {"licenses/LICENSE", "LICENSE"}
    assert (tmp_path / "out/python/alpha-1.0/licenses__LICENSE").read_text(encoding="utf-8") == "alpha MIT text"
    assert (tmp_path / "out/python/alpha-1.0/LICENSE").read_text(encoding="utf-8") == "root text"  # not overwritten
    assert by_name["beta"]["license"] == "Apache-2.0" and "licenses/NOTICE" in by_name["beta"]["files"]
    assert by_name["gamma"]["files"] == "none shipped by the package" and by_name["gamma"]["license"] == "not declared"
    assert not (tmp_path / "out/python/gamma-0.3").exists()


def test_the_notices_of_the_program_playwright_embeds_travel_with_it(mod, tmp_path):
    site = tmp_path / "site"
    dists = {"playwright": make_dist(site, "playwright", "1.56.0", "Apache-2.0", {"licenses/LICENSE": "apache"})}
    (site / "playwright/driver/package").mkdir(parents=True)
    (site / "playwright/driver/LICENSE").write_text("Node.js is licensed for use as follows", encoding="utf-8")
    (site / "playwright/driver/package/ThirdPartyNotices.txt").write_text("notices", encoding="utf-8")
    rows = mod["python_licenses"](tmp_path / "out", dists)
    assert rows[0]["files"] == "licenses/LICENSE, playwright/driver/LICENSE, playwright/driver/package/ThirdPartyNotices.txt"
    folder = tmp_path / "out/python/playwright-1.56.0"
    assert (folder / "playwright__driver__LICENSE").read_text(encoding="utf-8").startswith("Node.js")
    assert (folder / "playwright__driver__package__ThirdPartyNotices.txt").is_file()


def test_the_python_closure_follows_pyproject_and_stops_at_a_missing_requirement(mod, tmp_path, monkeypatch):
    site = tmp_path / "site"
    make_dist(site, "app-dep", "1", "MIT", {"licenses/LICENSE": "x"}, requires=["sub-dep>=1", "extra-only; extra == 'docs'",
                                                                             "never; sys_platform == 'plan9'"])
    make_dist(site, "sub-dep", "1", "BSD-3-Clause", {"LICENSE": "y"})
    make_dist(site, "doc-dep", "1", "MIT", {"LICENSE": "z"})
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "app"\ndependencies = ["app-dep>=1"]\n'
                       '[project.optional-dependencies]\ndocs = ["doc-dep"]\ndev = ["not-installed"]\n', encoding="utf-8")
    monkeypatch.setattr(sys, "path", [str(site), *sys.path])
    closure = mod["python_closure"](project, extras=("docs",), optional=())
    assert sorted(closure) == ["app-dep", "doc-dep", "sub-dep"]  # dev extra not asked for; marker never-true skipped

    project.write_text('[project]\nname = "app"\ndependencies = ["app-dep>=1", "not-installed-anywhere"]\n'
                       '[project.optional-dependencies]\ndocs = []\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not-installed-anywhere"):
        mod["python_closure"](project, extras=("docs",), optional=())


def test_collect_writes_the_index_and_replaces_a_stale_folder(mod, tmp_path):
    site = tmp_path / "site"
    dists = {"alpha": make_dist(site, "alpha", "1.0", "MIT", {"LICENSE": "alpha"})}
    web = tmp_path / "web"
    (web / "node_modules/@scope/pkg").mkdir(parents=True)
    (web / "node_modules/@scope/pkg/package.json").write_text(json.dumps({"name": "@scope/pkg", "version": "3.0.0",
                                                                          "license": "ISC"}), encoding="utf-8")
    (web / "node_modules/@scope/pkg/LICENSE").write_text("ISC text", encoding="utf-8")
    (web / "node_modules/devtool").mkdir(parents=True)
    (web / "node_modules/devtool/package.json").write_text(json.dumps({"name": "devtool", "version": "1"}), encoding="utf-8")
    (web / "package-lock.json").write_text(json.dumps({"packages": {
        "": {}, "node_modules/@scope/pkg": {"version": "3.0.0"},
        "node_modules/devtool": {"version": "1", "dev": True}}}), encoding="utf-8")
    dest = tmp_path / "licenses"
    dest.mkdir()
    (dest / "stale.txt").write_text("left from the last build", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "app"\ndependencies = []\n', encoding="utf-8")

    mod["collect"](dest, pyproject, web=web, dists=dists)
    assert not (dest / "stale.txt").exists()
    index = (dest / "INDEX.md").read_text(encoding="utf-8")
    assert "| alpha | 1.0 | MIT | LICENSE |" in index and "| @scope/pkg | 3.0.0 | ISC | LICENSE |" in index
    assert "devtool" not in index  # a development-only npm package is not part of the bundle
    assert (dest / "web/@scope_pkg-3.0.0/LICENSE").read_text(encoding="utf-8") == "ISC text"
    assert "CPython" in index and "PSF-2.0" in index


def test_an_uninstalled_web_package_stops_the_build(mod, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "package-lock.json").write_text(json.dumps({"packages": {"": {}, "node_modules/x": {"version": "1"}}}),
                                           encoding="utf-8")
    with pytest.raises(ValueError, match="npm ci"):
        mod["npm_licenses"](web, tmp_path / "out")


def test_the_real_closure_of_this_checkout_has_a_license_file_per_package(mod, tmp_path):
    """Every bundled Python package of the development install ships a license file (no gap for the bundle)."""
    try:
        closure = mod["python_closure"](ROOT / "pyproject.toml", extras=("docs",), optional=())
    except ValueError:
        pytest.skip("the docs extra is not installed here")
    rows = mod["python_licenses"](tmp_path / "out", closure)
    assert len(rows) >= 20
    assert [r["name"] for r in rows if r["files"].startswith("none shipped")] == []


def test_the_spec_bundles_notice_and_the_collected_texts():
    spec = (ROOT / "packaging" / "spike.spec").read_text(encoding="utf-8")
    for needed in ('"NOTICE"', '"THIRD_PARTY.md"', "collect_licenses.py", "licenses/third-party"):
        assert needed in spec
