"""Creator (C8): the "Crear" screen's templates. A template is a ready Forge blueprint (steps, the files they save,
acceptance criteria) filled from a few answers, plus the skills its steps follow and whether a design system
applies. It is not a new engine: the user reviews the blueprint in Forge, and Forge runs and checks it. Building
the blueprint here, instead of asking the model to draft one, keeps it reliable on a small local model and skips a
slow drafting call on a CPU."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from spike.analytics.engine import FORMATS
from spike.forge.blueprint import Blueprint, clean_path
from spike.orchestrator.planner import Subtask

MAX_FIELD = 600
MAX_LISTED = 200
LANGS = ("es", "en")


@dataclass
class Field:
    id: str
    label: dict[str, str]
    kind: str = "text"  # text | textarea | number | choice | file (a data file in the workspace or project)
    required: bool = False
    placeholder: dict[str, str] = field(default_factory=dict)
    default: str = ""
    options: list[str] = field(default_factory=list)  # a choice's values

    def public(self, lang: str) -> dict[str, Any]:
        return {"id": self.id, "label": self.label[lang], "kind": self.kind, "required": self.required,
                "placeholder": self.placeholder.get(lang, ""), "default": self.default,
                **({"options": self.options} if self.kind == "choice" else {})}


@dataclass
class Step:
    specialist: str
    role: str
    instruction: dict[str, str]  # a format string over the answers (and {extra_*} lines built from optional ones)
    deliverables: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Template:
    id: str
    icon: str
    name: dict[str, str]
    description: dict[str, str]
    fields: list[Field]
    steps: list[Step]
    criteria: dict[str, list[str]]
    task: dict[str, str]  # the chat's message, e.g. "Crear una página web: {about}"
    skills: list[str] = field(default_factory=list)
    design: bool = False  # a design system applies (HTML deliverables)
    extras: dict[str, dict[str, str]] = field(default_factory=dict)  # optional answer -> sentence that adds it

    def public(self, lang: str) -> dict[str, Any]:
        return {"id": self.id, "icon": self.icon, "name": self.name[lang], "description": self.description[lang],
                "fields": [f.public(lang) for f in self.fields], "skills": self.skills, "design": self.design,
                "deliverables": [p for s in self.steps for p in s.deliverables]}


ABOUT = Field("about", {"es": "¿De qué trata?", "en": "What is it about?"}, "textarea", True,
              {"es": "Ej.: la panadería de mi barrio, con horarios, productos y cómo llegar",
               "en": "E.g.: my neighbourhood bakery, with opening hours, products and directions"})
DATA_FILE = Field("file", {"es": "Archivo de datos", "en": "Data file"}, "file", True,
                  {"es": "ventas.csv (en la carpeta del proyecto o del espacio de trabajo)",
                   "en": "sales.csv (in the project's or the workspace folder)"})
SINGLE_FILE = {"es": "Todo en ese único archivo: sin librerías, imágenes, fuentes ni nada que cargue de internet.",
               "en": "Everything in that one file: no libraries, images, fonts or anything loaded from the internet."}

TEMPLATES: list[Template] = [
    Template(
        "web", "globe", {"es": "Página web", "en": "Web page"},
        {"es": "Una página de una sola pieza, lista para abrir o publicar.", "en": "A one-page site, ready to open or publish."},
        [ABOUT, Field("sections", {"es": "Secciones (opcional)", "en": "Sections (optional)"},
                      placeholder={"es": "Inicio, productos, horarios, contacto", "en": "Home, products, hours, contact"})],
        [Step("code", "execute", {
            "es": "Crea index.html: una página web de una sola página sobre: {about}.{extra_sections} HTML con el CSS "
                  "dentro de <style>. {single} Diseño adaptable a móvil y escritorio, buen contraste y textos reales "
                  "(nada de lorem ipsum). Guárdalo con write_file.",
            "en": "Create index.html: a one-page website about: {about}.{extra_sections} HTML with the CSS inside "
                  "<style>. {single} Responsive on phones and desktops, good contrast and real text (no lorem ipsum). "
                  "Save it with write_file."}, ["index.html"])],
        {"es": ["index.html es un único archivo con el CSS dentro y no carga nada de internet",
                "Trata del tema pedido con textos reales, sin lorem ipsum", "Se adapta a pantallas de móvil"],
         "en": ["index.html is one file with the CSS inside and loads nothing from the internet",
                "It covers the requested topic with real text, no lorem ipsum", "It adapts to phone screens"]},
        {"es": "Crear una página web: {about}", "en": "Create a web page: {about}"},
        skills=["frontend-design"], design=True,
        extras={"sections": {"es": " Secciones: {sections}.", "en": " Sections: {sections}."}}),
    Template(
        "app", "app", {"es": "Aplicación", "en": "App"},
        {"es": "Una herramienta interactiva que funciona en el navegador, sin servidor.",
         "en": "An interactive tool that runs in the browser, with no server."},
        [Field("about", {"es": "¿Qué debe hacer?", "en": "What should it do?"}, "textarea", True,
               {"es": "Ej.: llevar la lista de la compra por pasillos y marcar lo comprado",
                "en": "E.g.: keep a shopping list by aisle and tick off what I bought"}),
         Field("features", {"es": "Detalles (opcional)", "en": "Details (optional)"},
               placeholder={"es": "Modo oscuro, exportar a CSV", "en": "Dark mode, export to CSV"})],
        [Step("code", "execute", {
            "es": "Crea app.html: una aplicación web que permita {about}.{extra_features} HTML, CSS y JavaScript en el "
                  "mismo archivo, que funcione al abrirlo en el navegador sin servidor. {single} Guarda los datos del "
                  "usuario en localStorage. Botones y campos con etiquetas claras. Guárdalo con write_file.",
            "en": "Create app.html: a web app that lets the user {about}.{extra_features} HTML, CSS and JavaScript in "
                  "the same file, working when opened in the browser with no server. {single} Keep the user's data in "
                  "localStorage. Buttons and fields with clear labels. Save it with write_file."}, ["app.html"])],
        {"es": ["app.html funciona al abrirlo, sin servidor ni nada de internet", "Hace lo que se pidió",
                "Los datos del usuario se guardan en localStorage"],
         "en": ["app.html works when opened, with no server and nothing from the internet", "It does what was asked",
                "The user's data is kept in localStorage"]},
        {"es": "Crear una aplicación: {about}", "en": "Create an app: {about}"},
        skills=["frontend-design"], design=True,
        extras={"features": {"es": " Además: {features}.", "en": " Also: {features}."}}),
    Template(
        "dashboard", "chart", {"es": "Dashboard", "en": "Dashboard"},
        {"es": "Indicadores y gráficos de un archivo de datos, con cifras calculadas por SQL.",
         "en": "Indicators and charts from a data file, with figures computed by SQL."},
        [DATA_FILE, Field("focus", {"es": "¿Qué quieres ver? (opcional)", "en": "What do you want to see? (optional)"},
                          placeholder={"es": "Ventas por mes y por región", "en": "Sales by month and by region"})],
        [Step("data", "research", {
            "es": "Usa data_describe y data_sql sobre {file} para calcular los indicadores clave{extra_focus}: totales, "
                  "evolución en el tiempo y reparto por categoría. Da cada indicador con su valor exacto y la consulta "
                  "que lo produjo.",
            "en": "Use data_describe and data_sql on {file} to compute the key indicators{extra_focus}: totals, change "
                  "over time and split by category. Give each indicator with its exact value and the query that "
                  "produced it."}),
         Step("code", "execute", {
             "es": "Crea dashboard.html con los indicadores del paso t1: tarjetas con las cifras y gráficos de barras o "
                   "líneas dibujados en SVG dentro del archivo. {single} Usa solo las cifras del paso t1, sin inventar "
                   "ni redondear ninguna. Guárdalo con write_file.",
             "en": "Create dashboard.html with the indicators from step t1: cards with the figures and bar or line "
                   "charts drawn as SVG inside the file. {single} Use only the figures from step t1, without inventing "
                   "or rounding any. Save it with write_file."}, ["dashboard.html"], ["t1"])],
        {"es": ["Cada cifra de dashboard.html sale de una consulta data_sql del paso t1",
                "dashboard.html tiene al menos un gráfico SVG y no carga nada de internet"],
         "en": ["Every figure in dashboard.html comes from a data_sql query of step t1",
                "dashboard.html has at least one SVG chart and loads nothing from the internet"]},
        {"es": "Crear un dashboard de {file}", "en": "Create a dashboard of {file}"},
        skills=["frontend-design"], design=True,
        extras={"focus": {"es": " ({focus})", "en": " ({focus})"}}),
    Template(
        "data_app", "table", {"es": "De datos a aplicación", "en": "Data to app"},
        {"es": "Convierte un archivo de datos en una aplicación con búsqueda, filtros y gráfico.",
         "en": "Turns a data file into an app with search, filters and a chart."},
        [DATA_FILE, Field("about", {"es": "¿Para qué es la aplicación?", "en": "What is the app for?"}, "textarea", True,
                          {"es": "Ej.: consultar el stock por almacén y ver qué productos reponer",
                           "en": "E.g.: check stock per warehouse and see which products to reorder"})],
        [Step("data", "research", {
            "es": "Con data_describe y data_sql sobre {file}, prepara los datos para una aplicación para {about}: "
                  "devuelve una tabla de como mucho 50 filas con las columnas que necesita, con su consulta.",
            "en": "With data_describe and data_sql on {file}, prepare the data for an app to {about}: return a table "
                  "of at most 50 rows with the columns it needs, with its query."}),
         Step("code", "execute", {
             "es": "Crea app.html: una aplicación para {about}, con los datos del paso t1 incrustados como JSON, una "
                   "tabla con búsqueda y filtros y un gráfico SVG que cambia con los filtros. {single} Usa exactamente "
                   "los datos del paso t1. Guárdalo con write_file.",
             "en": "Create app.html: an app to {about}, with the data from step t1 embedded as JSON, a table with "
                   "search and filters and an SVG chart that follows the filters. {single} Use exactly the data from "
                   "step t1. Save it with write_file."}, ["app.html"], ["t1"])],
        {"es": ["Los datos de app.html coinciden con el resultado del paso t1", "La búsqueda o los filtros funcionan",
                "app.html no carga nada de internet"],
         "en": ["The data in app.html matches the result of step t1", "Search or filters work",
                "app.html loads nothing from the internet"]},
        {"es": "Crear una aplicación con {file}: {about}", "en": "Create an app from {file}: {about}"},
        skills=["frontend-design"], design=True),
    Template(
        "document", "doc", {"es": "Documento", "en": "Document"},
        {"es": "Un documento de Word con estructura: informe, guía, propuesta…", "en": "A structured Word document: report, guide, proposal…"},
        [Field("about", {"es": "Tema", "en": "Topic"}, "textarea", True,
               {"es": "Ej.: propuesta para digitalizar las reservas del restaurante",
                "en": "E.g.: a proposal to move the restaurant's bookings online"}),
         Field("audience", {"es": "Para quién (opcional)", "en": "Audience (optional)"},
               placeholder={"es": "El equipo directivo", "en": "The management team"}),
         Field("pages", {"es": "Páginas aproximadas", "en": "Approximate pages"}, "number", default="3")],
        [Step("writing", "execute", {
            "es": "Escribe un documento sobre: {about}.{extra_audience} Unas {pages} páginas, con título, introducción, "
                  "secciones con encabezados y conclusiones. Guárdalo con create_docx en documento.docx.",
            "en": "Write a document about: {about}.{extra_audience} About {pages} pages, with a title, an "
                  "introduction, sections with headings and conclusions. Save it with create_docx as documento.docx."},
            ["documento.docx"])],
        {"es": ["documento.docx tiene título, introducción, secciones con encabezados y conclusiones",
                "Trata del tema pedido"],
         "en": ["The document has a title, an introduction, sections with headings and conclusions",
                "It covers the requested topic"]},
        {"es": "Crear un documento: {about}", "en": "Create a document: {about}"},
        extras={"audience": {"es": " Para: {audience}.", "en": " For: {audience}."}}),
    Template(
        "presentation", "slides", {"es": "Presentación", "en": "Presentation"},
        {"es": "Diapositivas de PowerPoint, una idea por diapositiva.", "en": "PowerPoint slides, one idea per slide."},
        [Field("about", {"es": "Tema", "en": "Topic"}, "textarea", True,
               {"es": "Ej.: resultados del trimestre y plan para el siguiente",
                "en": "E.g.: this quarter's results and next quarter's plan"}),
         Field("audience", {"es": "Para quién (opcional)", "en": "Audience (optional)"},
               placeholder={"es": "Inversores", "en": "Investors"}),
         Field("slides", {"es": "Diapositivas", "en": "Slides"}, "number", default="8")],
        [Step("business", "execute", {
            "es": "Crea una presentación de {slides} diapositivas sobre: {about}.{extra_audience} Portada, una idea por "
                  "diapositiva con 3 a 5 puntos breves y un cierre con los siguientes pasos. Guárdala con create_pptx "
                  "en presentacion.pptx.",
            "en": "Create a {slides}-slide presentation about: {about}.{extra_audience} A title slide, one idea per "
                  "slide with 3 to 5 short points, and a closing slide with next steps. Save it with create_pptx as "
                  "presentacion.pptx."}, ["presentacion.pptx"])],
        {"es": ["presentacion.pptx tiene unas {slides} diapositivas, cada una con título y como mucho 5 puntos",
                "Trata del tema pedido y termina con los siguientes pasos"],
         "en": ["presentacion.pptx has about {slides} slides, each with a title and at most 5 points",
                "It covers the requested topic and ends with next steps"]},
        {"es": "Crear una presentación: {about}", "en": "Create a presentation: {about}"},
        extras={"audience": {"es": " Para: {audience}.", "en": " For: {audience}."}}),
    Template(
        "video", "film", {"es": "Vídeo animado", "en": "Animated video"},
        {"es": "Un vídeo corto hecho con código: textos, formas y gráficos animados, en MP4.",
         "en": "A short video made with code: animated text, shapes and charts, as MP4."},
        [Field("about", {"es": "¿De qué trata?", "en": "What is it about?"}, "textarea", True,
               {"es": "Ej.: presentar mi app de recetas en tres ideas y terminar con el logo",
                "en": "E.g.: introduce my recipe app in three ideas and end with the logo"}),
         Field("seconds", {"es": "Duración (segundos)", "en": "Length (seconds)"}, "number", default="10"),
         Field("size", {"es": "Formato", "en": "Format"}, "choice", default="16:9", options=["16:9", "9:16", "1:1"])],
        [Step("code", "execute", {
            "es": "Crea escena.html, una escena animada de {seconds} segundos en formato {size} sobre {about}. Sigue "
                  "la skill motion-scene: un único archivo con <meta name=\"spike-duration\" content=\"{seconds}\">, "
                  "animaciones CSS o SVG con tiempos fijos y nada que cargue de internet. Guárdala con write_file y "
                  "conviértela en video.mp4 con render_video (size {size}, fps 30). Si render_video avisa de errores, "
                  "corrige la escena y vuelve a renderizar.",
            "en": "Create escena.html, an animated scene of {seconds} seconds in {size} format about {about}. Follow "
                  "the motion-scene skill: one file with <meta name=\"spike-duration\" content=\"{seconds}\">, CSS or "
                  "SVG animations with fixed timings and nothing loaded from the internet. Save it with write_file and "
                  "turn it into video.mp4 with render_video (size {size}, fps 30). If render_video reports errors, fix "
                  "the scene and render again."}, ["escena.html", "video.mp4"])],
        {"es": ["video.mp4 dura unos {seconds} segundos en formato {size}",
                "Trata de lo pedido, con textos legibles el tiempo suficiente",
                "render_video no informó de errores de JavaScript"],
         "en": ["video.mp4 lasts about {seconds} seconds in {size} format",
                "It covers the request, with text readable for long enough",
                "render_video reported no JavaScript errors"]},
        {"es": "Crear un vídeo animado: {about}", "en": "Create an animated video: {about}"},
        skills=["motion-scene"], design=True),
    Template(
        "automation", "bolt", {"es": "Automatización", "en": "Automation"},
        {"es": "Un script de Python que hace por ti una tarea repetitiva.", "en": "A Python script that does a repetitive task for you."},
        [Field("about", {"es": "¿Qué debe hacer?", "en": "What should it do?"}, "textarea", True,
               {"es": "Ej.: renombrar las fotos de una carpeta con su fecha", "en": "E.g.: rename the photos in a folder with their date"}),
         Field("inputs", {"es": "Entradas y salidas (opcional)", "en": "Inputs and outputs (optional)"},
               placeholder={"es": "Una carpeta; deja un CSV con los cambios", "en": "A folder; leaves a CSV of the changes"})],
        [Step("code", "execute", {
            "es": "Escribe automatizacion.py, un script de Python 3 que {about}.{extra_inputs} Solo la biblioteca "
                  "estándar salvo que sea imprescindible; argumentos con argparse y --help; no borra ni sobrescribe "
                  "nada sin una opción explícita (por defecto, simula y muestra lo que haría); errores claros. Escribe "
                  "también LEEME.md con cómo usarlo y un ejemplo. Guarda ambos con write_file.",
            "en": "Write automatizacion.py, a Python 3 script that will {about}.{extra_inputs} Standard library only "
                  "unless something is essential; argparse arguments with --help; it deletes or overwrites nothing "
                  "without an explicit option (by default it simulates and shows what it would do); clear errors. Also "
                  "write LEEME.md with how to use it and an example. Save both with write_file."},
            ["automatizacion.py", "LEEME.md"])],
        {"es": ["automatizacion.py tiene --help (argparse)", "Por defecto no borra ni sobrescribe nada",
                "LEEME.md explica cómo usarlo con un ejemplo"],
         "en": ["automatizacion.py has --help (argparse)", "By default it deletes or overwrites nothing",
                "LEEME.md explains how to use it with an example"]},
        {"es": "Crear una automatización: {about}", "en": "Create an automation: {about}"},
        skills=["verification-before-completion"],
        extras={"inputs": {"es": " Entradas y salidas: {inputs}.", "en": " Inputs and outputs: {inputs}."}}),
]
BY_ID = {t.id: t for t in TEMPLATES}


class CreatorError(ValueError):
    pass


def templates(lang: str) -> list[dict[str, Any]]:
    lang = lang if lang in LANGS else "en"
    return [t.public(lang) for t in TEMPLATES]


def _answers(template: Template, given: Any, lang: str) -> dict[str, str]:
    given = given if isinstance(given, dict) else {}
    out: dict[str, str] = {}
    for f in template.fields:
        value = " ".join(str(given.get(f.id) or "").split())[:MAX_FIELD] or f.default
        if f.required and not value:
            raise CreatorError(f"'{f.label[lang]}' is required")
        if value and f.kind == "number" and not (value.isdigit() and 1 <= int(value) <= 40):
            raise CreatorError(f"'{f.label[lang]}' must be a whole number from 1 to 40")
        if value and f.kind == "choice" and value not in f.options:
            raise CreatorError(f"'{f.label[lang]}' must be one of {', '.join(f.options)}")
        if value and f.kind == "file":
            value = clean_path(value)
            if PurePosixPath(value).suffix.lower() not in FORMATS:
                raise CreatorError(f"'{value}' is not a data file (CSV, TSV, Parquet, JSON, .xlsx or SQLite)")
        out[f.id] = value.replace("{", "(").replace("}", ")")  # answers never become format fields
    return out


def build(template_id: str, given: Any, lang: str = "es") -> dict[str, Any]:
    """The Forge blueprint of a template filled with the user's answers, with its skills and design flag."""
    template = BY_ID.get(template_id)
    if template is None:
        raise CreatorError(f"unknown template '{template_id}'")
    lang = lang if lang in LANGS else "en"
    answers = _answers(template, given, lang)
    values = {**answers, "single": SINGLE_FILE[lang]}
    for key, sentence in template.extras.items():
        values[f"extra_{key}"] = sentence[lang].format(**answers) if answers.get(key) else ""
    for f in template.fields:  # placeholders an instruction might use for optional fields left empty
        values.setdefault(f"extra_{f.id}", "")
    steps = [Subtask(id=f"t{i + 1}", specialist=s.specialist, role=s.role, instruction=s.instruction[lang].format(**values),
                     depends_on=list(s.depends_on), deliverables=list(s.deliverables))
             for i, s in enumerate(template.steps)]
    blueprint = Blueprint(goal=template.task[lang].format(**values), requirements=[], steps=steps,
                          criteria=[c.format(**values) for c in template.criteria[lang]], method="template")
    return {"task": blueprint.goal, "blueprint": blueprint.to_dict(), "skills": template.skills,
            "design": template.design, "template": template.id}


def data_files(root: Path, depth: int = 3) -> list[dict[str, Any]]:
    """Data files a dashboard or data app can start from: in the folder the file tools use, a few levels deep,
    hidden folders skipped."""
    out: list[dict[str, Any]] = []

    def walk(folder: Path, level: int) -> None:
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for entry in entries:
            if len(out) >= MAX_LISTED or entry.name.startswith(".") or entry.is_symlink():
                continue
            if entry.is_dir() and level < depth:
                walk(entry, level + 1)
            elif entry.is_file() and entry.suffix.lower() in FORMATS:
                out.append({"path": entry.relative_to(root).as_posix(), "bytes": entry.stat().st_size})

    if root.is_dir():
        walk(root, 1)
    return out
