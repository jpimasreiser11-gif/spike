"""Every bundled profile has a routing example; creator templates include a reusable starting document."""

import pytest

from spike.skills.engine import BUNDLED, SkillLibrary
from spike.skills.validation import validate_skills

# Explicit prompts catch routing regressions rather than deriving expectations from skill metadata.
ROUTES = {
    "landing-page": ("code", "Crea una landing page de producto", "Create a product landing page"),
    "report-creator": ("writing", "Crea un informe ejecutivo", "Create an executive report"),
    "deck-creator": ("writing", "Crea una presentación de diapositivas", "Create a slide deck"),
    "dashboard-creator": ("data", "Crea un panel de indicadores", "Create a metrics dashboard"),
    "data-app-creator": ("code", "Crea una aplicación de datos", "Create a data app"),
    "release-notes": ("writing", "Redacta notas de versión", "Write release notes"),
    "incident-review": ("code", "Redacta un postmortem del incidente", "Write an incident postmortem"),
    "dataset-audit": ("data", "Audita la calidad del dataset", "Audit dataset quality"),
    "api-contract": ("code", "Define el contrato de la API", "Define the API contract"),
    "test-driven-development": ("code", "pruebas primero tdd", "test first tdd"),
    "systematic-debugging": ("code", "depurar traceback", "debug traceback"),
    "writing-plans": ("business", "planificar roadmap", "plan roadmap"),
    "verification-before-completion": ("code", "verificar terminado", "verify done"),
    "frontend-design": ("code", "interfaz css", "frontend css"),
    "mcp-builder": ("code", "servidor mcp", "mcp server"),
    "webapp-testing": ("code", "playwright e2e", "playwright e2e"),
    "web-design-guidelines": ("code", "revisar ui accesibilidad", "review ui accessibility"),
    "medical-evidence-summary": ("medicine", "tratamiento guías", "treatment guidelines"),
    "financial-ratio-analysis": ("finance", "margen EBITDA ROE", "EBITDA margin ROE"),
    "campaign-brief": ("marketing", "campaña canales", "campaign channels"),
    "motion-scene": ("core", "vídeo animado", "animated intro clip"),
    "decision-simulator": ("business", "Simula esta decisión empresarial", "Simulate this business decision"),
    "test-inventor": ("code", "Inventa casos de prueba límite", "Invent edge case tests"),
    "migration-architect": ("code", "Diseña una migración de base de datos", "Design a database migration"),
    "performance-profiler": ("code", "Perfila el rendimiento con cProfile", "Profile performance with cProfile"),
    "localization": ("writing", "Traduce usando el glosario", "Translate using the glossary"),
    "experiment-designer": ("science", "Diseña un experimento controlado", "Design a controlled experiment"),
    "synthetic-data": ("data", "Genera datos sintéticos", "Generate synthetic data"),
    "vector-designer": ("design", "Diseña un icono SVG", "Design an SVG icon"),
    "system-diagnostic": ("core", "Diagnostica SPIKE con doctor", "Diagnose SPIKE with doctor"),
}


def test_catalog_count_validation_and_routing_coverage():
    library = SkillLibrary([(BUNDLED, "bundled")])
    assert len(library.all()) >= 30
    assert {s.name for s in library.all()} == set(ROUTES)
    assert validate_skills() == []


@pytest.mark.parametrize("name", ROUTES)
def test_every_bundled_skill_routes_in_spanish_and_english(name):
    library = SkillLibrary([(BUNDLED, "bundled")])
    specialist, *prompts = ROUTES[name]
    for prompt in prompts:
        assert [s.name for s in library.select(prompt, specialist)] == [name], prompt


@pytest.mark.parametrize("name", ["landing-page", "report-creator", "deck-creator", "dashboard-creator", "data-app-creator"])
def test_creator_templates_are_loadable_resources(name):
    skill = SkillLibrary([(BUNDLED, "bundled")]).get(name)
    assert skill is not None
    assert "template.md" in skill.resources()
    assert "template.md" in skill.body()
    assert "{{" in skill.read("template.md")
