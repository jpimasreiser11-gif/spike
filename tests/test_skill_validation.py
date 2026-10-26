"""Offline validation of distributable skills/catalogs and bilingual routing of the A1 instruction profiles."""

from pathlib import Path

import pytest
import yaml

from spike.cli import main
from spike.skills.engine import BUNDLED, SkillError, SkillLibrary, parse_skill
from tests.test_skills import write_skill

ROUTING = [
    ("decision-simulator", "business", ["Simula esta decisión empresarial", "Compara escenarios de decisión",
                                         "Simulate this business decision", "Compare decision scenarios"]),
    ("test-inventor", "code", ["Inventa casos de prueba límite", "Genera pruebas de propiedades",
                               "Invent edge case tests", "Generate property tests"]),
    ("migration-architect", "code", ["Diseña una migración de base de datos", "Necesito un plan de migración",
                                      "Design a database migration", "Create a migration plan"]),
    ("performance-profiler", "code", ["Perfila el rendimiento con cProfile", "Analiza cuellos de botella",
                                       "Profile performance with cProfile", "Find performance bottlenecks"]),
    ("localization", "writing", ["Localiza estos textos al catalán", "Traduce usando el glosario",
                                  "Localize these strings into Spanish", "Translate using the glossary"]),
    ("experiment-designer", "science", ["Diseña un experimento controlado", "Define hipótesis y controles",
                                         "Design a controlled experiment", "Define hypotheses and controls"]),
    ("synthetic-data", "data", ["Genera datos sintéticos", "Crea datos ficticios reproducibles",
                                 "Generate synthetic data", "Create reproducible fake data"]),
    ("vector-designer", "design", ["Diseña un icono SVG", "Crea una ilustración vectorial",
                                    "Design an SVG icon", "Create a vector illustration"]),
    ("system-diagnostic", "core", ["Diagnostica SPIKE con doctor", "Revisa el diagnóstico del sistema",
                                     "Diagnose SPIKE with doctor", "Check system diagnostics"]),
]


@pytest.mark.parametrize("name, specialist, prompts", ROUTING)
def test_new_skills_route_in_both_languages(name, specialist, prompts):
    library = SkillLibrary([(BUNDLED, "bundled")])
    skill = library.get(name)
    assert skill is not None and skill.license == "Apache-2.0"
    for prompt in prompts:
        assert [s.name for s in library.select(prompt, specialist)] == [name], prompt
    assert name not in [s.name for s in library.select("Hola, ¿qué tal estás?", specialist)]
    if name == "vector-designer":
        assert library.select("Design an SVG icon", "writing")[0].name == name


@pytest.mark.parametrize("front", ["[]", "a string", "42"])
def test_loader_reports_non_mapping_front_matter(tmp_path, front):
    folder = write_skill(tmp_path, "sample")
    (folder / "SKILL.md").write_text(f"---\n{front}\n---\nBody", encoding="utf-8")
    with pytest.raises(SkillError):
        parse_skill(folder)


@pytest.mark.parametrize("extra, body", [
    ("license: GPL-3.0\n", "Instructions"),
    ("", "Instructions"),
    ("license: Apache-2.0\nallowed-tools: nonexistent\n", "Instructions"),
    ("license: MIT\nallowed-tools: [python, 42]\n", "Instructions"),
    ("license: MIT\n", ""),
    ("license: MIT\n", "x" * 60_001),
    ("license: MIT\n", "api_key = '" + "x" * 32 + "'"),
    ("license: MIT\n", "-----BEGIN PRIVATE KEY-----"),
])
def test_skill_validation_failures(tmp_path, extra, body, capsys):
    folder = write_skill(tmp_path, "sample", extra=extra, body=body)
    assert main(["skills", "validate", str(folder)]) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("case", ["missing", "yaml", "shape", "utf8", "front"])
def test_skill_validation_input_errors(tmp_path, case, capsys):
    path = tmp_path / "sample"
    if case != "missing":
        path.mkdir()
        data = {"yaml": b"---\n[\n---\nbody", "shape": b"---\n[]\n---\nbody",
                "utf8": b"\xff", "front": b"no front matter"}[case]
        (path / "SKILL.md").write_bytes(data)
    assert main(["skills", "validate", str(path)]) == 1
    assert capsys.readouterr().err


def test_skill_validation_accepts_root_folder_file_and_multiple_paths(tmp_path, capsys):
    a = write_skill(tmp_path, "alpha", extra="license: CC0\nallowed-tools: python read_file\n")
    b = write_skill(tmp_path, "beta", extra="license: BSD-3-Clause\nallowed-tools: [calculator]\n")
    for paths in ([tmp_path], [a, b / "SKILL.md"]):
        assert main(["skills", "validate", *map(str, paths)]) == 0
    assert not capsys.readouterr().err


def entry():
    return {"id": "sample", "name": "Sample", "description": "Local tool", "transport": "stdio",
            "command": "uvx", "args": ["sample==1.2.3"], "license": "MIT", "source": "https://example.org/repo"}


@pytest.mark.parametrize("patch", [
    {"name": ""}, {"id": "BAD ID"}, {"source": ""}, {"license": "GPL-3.0"}, {"transport": "sse"},
    {"command": ""}, {"args": ["sample@latest"]}, {"args": ["sample>=1.0"]}, {"args": ["sample"]},
    {"args": "sample==1.2.3"}, {"secrets": [{"name": "bad-name"}]},
    {"secrets": [{"name": "API_TOKEN", "value": "hidden"}]},
    {"env": {"API_TOKEN": "literal-credential"}}, {"headers": {"Authorization": "Bearer literal"}},
    {"headers": {"Authorization": "Bearer {UNDECLARED_TOKEN}"}}, {"env": []},
    {"note": "api_key='" + "x" * 32 + "'"},
    {"transport": "http", "url": "ftp://example.org"},
    {"transport": "http", "url": "https://user:password@example.org"},
    {"transport": "http", "url": "https://example.org?token=literal"},
])
def test_connector_validation_failures(tmp_path, patch, capsys):
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump([entry() | patch]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("data", ["[", "{}", "[]", "- 42", "- {}", None])
def test_connector_bad_files(tmp_path, data, capsys):
    path = tmp_path / "catalog.yaml"
    if data is not None:
        path.write_text(data, encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 1
    assert capsys.readouterr().err


def test_connector_duplicate_ids(tmp_path):
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump([entry(), entry()]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 1


@pytest.mark.parametrize("args", [["-y", "@scope/sample@1.2.3"], ["sample==2026.10.10"], ["sample@1.2.3"]])
def test_connector_pins_and_secret_references_are_accepted(tmp_path, args):
    path = tmp_path / "catalog.yaml"
    raw = entry() | {"command": "npx" if args[0] == "-y" else "uvx", "args": args,
                     "secrets": [{"name": "API_TOKEN", "label": "Token"}],
                     "env": {"API_TOKEN": "{API_TOKEN}", "CACHE": "{data}/cache"},
                     "headers": {"Authorization": "Bearer {API_TOKEN}"}}
    path.write_text(yaml.safe_dump([raw]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 0


def test_bundled_validators_and_ci():
    assert main(["skills", "validate"]) == 0
    assert main(["connectors", "validate"]) == 0
    workflow = (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "spike skills validate" in workflow and "spike connectors validate" in workflow


@pytest.mark.parametrize("kind", ["skills", "connectors"])
def test_validation_messages_are_localized(tmp_path, kind, capsys):
    assert main([kind, "validate", str(tmp_path / "missing"), "--lang", "es"]) == 1
    assert "Validación fallida" in capsys.readouterr().err
    assert main([kind, "validate", "--lang", "en"]) == 0
    assert "Validation passed" in capsys.readouterr().out


@pytest.mark.parametrize("extra", ["metadata:\n  spike-specialists: 42\n", "metadata:\n  spike-keywords: 42\n"])
def test_malformed_routing_lists_are_reported(tmp_path, extra):
    folder = write_skill(tmp_path, "sample", extra="license: MIT\n" + extra)
    assert main(["skills", "validate", str(folder)]) == 1


def test_skill_resources_are_scanned_without_echoing_secret_values(tmp_path, capsys):
    folder = write_skill(tmp_path, "sample", extra="license: MIT\n")
    credential = "sk-" + "x" * 32
    (folder / "example.py").write_text(f"key = '{credential}'", encoding="utf-8")
    assert main(["skills", "validate", str(folder)]) == 1
    assert credential not in capsys.readouterr().err


@pytest.mark.parametrize("package", ["sample@1", "sample@^1.2.3", "sample@1.2.x", "sample@main"])
def test_connector_rejects_version_ranges(tmp_path, package):
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump([entry() | {"args": [package]}]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 1


@pytest.mark.parametrize("license_", ["MIT", "Apache-2.0", "BSD", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0", "CC0-1.0", "CC-BY", "CC-BY-4.0"])
def test_skill_allowed_licenses(tmp_path, license_):
    folder = write_skill(tmp_path, "sample", extra=f"license: {license_}\n")
    assert main(["skills", "validate", str(folder)]) == 0


def test_hosted_and_installed_connectors_and_non_secret_headers(tmp_path):
    path = tmp_path / "catalog.yaml"
    hosted = entry() | {"transport": "http", "url": "https://example.org/mcp", "headers": {"Accept": "application/json"}}
    installed = entry() | {"id": "local", "command": "local-mcp", "args": []}
    path.write_text(yaml.safe_dump([hosted, installed]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 0


def test_documented_placeholder_is_not_a_secret(tmp_path):
    folder = write_skill(tmp_path, "sample", extra="license: MIT\n", body="export API_KEY=your_api_key_here")
    assert main(["skills", "validate", str(folder)]) == 0


@pytest.mark.parametrize("args", [["sample==1.2.3", "--token", "literal"], ["sample==1.2.3", "--password=literal"]])
def test_connector_rejects_literal_secret_arguments(tmp_path, args):
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump([entry() | {"args": args}]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 1


@pytest.mark.parametrize("command", ["npx.cmd", "uvx.exe", "/usr/bin/npx", "C:\\tools\\uvx.exe"])
def test_download_launchers_need_pins_on_all_platforms(tmp_path, command):
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump([entry() | {"command": command, "args": ["sample@latest"]}]), encoding="utf-8")
    assert main(["connectors", "validate", str(path)]) == 1


def test_exact_body_size_limit_is_accepted(tmp_path):
    folder = write_skill(tmp_path, "sample", extra="license: MIT\n", body="x" * 60_000)
    assert main(["skills", "validate", str(folder)]) == 0
