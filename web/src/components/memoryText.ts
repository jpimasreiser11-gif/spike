import { lang } from "../i18n";

// Memory's texts, apart from the Memory view so the chat can use them without loading that view (G25).
export const M = lang === "es"
  ? {
      intro: "SPIKE recuerda lo importante de tus chats y de los archivos de tus proyectos, y lo usa cuando viene al caso. Todo se guarda en tu ordenador; puedes verlo, corregirlo, exportarlo y borrarlo aquí.",
      enabled: "Usar la memoria en los chats", learn: "Guardar lo que le pides recordar («recuerda que…», «a partir de ahora…») y proponer reglas cuando lo corriges", summaries: "Resumir los chats en la memoria (solo con el modelo local, sin coste)",
      search: "Búsqueda", semanticOn: "por palabras y por significado", wordsOnly: "por palabras", installHint: "Para buscar también por significado, instala el modelo de memoria:",
      semanticOff: "Buscar solo por palabras", failed: "El modelo de memoria no arrancó; se busca por palabras",
      memories: "recuerdos", title: "Memoria", kind: "Tipo", scope: "Alcance", add: "Añadir", addPlaceholder: "Algo que SPIKE debe recordar…", filter: "Buscar en la memoria…",
      all: "Todo", global: "Global", project: "Proyecto", allKinds: "Todos los tipos",
      kinds: { fact: "Dato", decision: "Decisión", preference: "Preferencia", rule: "Regla", summary: "Resumen de chat", document: "Archivo" } as Record<string, string>,
      ruleHint: "Las reglas se aplican siempre; el resto se usa cuando es relevante.",
      edit: "Editar", save: "Guardar", cancel: "Cancelar", remove: "Eliminar", exportAll: "Exportar (.json)", importFile: "Importar",
      clear: "Borrar toda la memoria", confirmClear: "Sí, borrarla", imported: "Importados", empty: "Todavía no hay recuerdos.",
      byWords: "palabras", byMeaning: "significado",
      glossary: "Glosario", sub: { notes: "Recuerdos", folders: "Carpetas", glossary: "Glosario", tutor: "Tutor", graph: "Grafo" },
    }
  : {
      intro: "SPIKE remembers what matters from your chats and your project files, and uses it when relevant. Everything stays on your computer; see, correct, export and delete it here.",
      enabled: "Use memory in chats", learn: "Save what you ask it to remember (\"remember that…\", \"from now on…\") and suggest rules when you correct it", summaries: "Summarise chats into memory (local model only, no cost)",
      search: "Search", semanticOn: "by words and by meaning", wordsOnly: "by words", installHint: "To also search by meaning, install the memory model:",
      semanticOff: "Search by words only", failed: "The memory model did not start; searching by words",
      memories: "memories", title: "Memory", kind: "Kind", scope: "Scope", add: "Add", addPlaceholder: "Something SPIKE should remember…", filter: "Search memory…",
      all: "All", global: "Global", project: "Project", allKinds: "All kinds",
      kinds: { fact: "Fact", decision: "Decision", preference: "Preference", rule: "Rule", summary: "Chat summary", document: "File" } as Record<string, string>,
      ruleHint: "Rules always apply; everything else is used when relevant.",
      edit: "Edit", save: "Save", cancel: "Cancel", remove: "Delete", exportAll: "Export (.json)", importFile: "Import",
      clear: "Delete all memory", confirmClear: "Yes, delete it", imported: "Imported", empty: "No memories yet.",
      byWords: "words", byMeaning: "meaning",
      glossary: "Glossary", sub: { notes: "Memories", folders: "Folders", glossary: "Glossary", tutor: "Tutor", graph: "Graph" },
    };
