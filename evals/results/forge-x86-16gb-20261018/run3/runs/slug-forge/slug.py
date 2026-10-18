import re


# Diccionario de mapeo de caracteres con tildes/acento a caracteres base
ACENTOS = {
    'á': 'a', 'Á': 'a',
    'é': 'e', 'É': 'e',
    'í': 'i', 'Í': 'i',
    'ó': 'o', 'Ó': 'o',
    'ú': 'u', 'Ú': 'u',
    'ñ': 'n', 'Ñ': 'n',
    'à': 'a', 'À': 'a',
    'è': 'e', 'È': 'e',
    'ì': 'i', 'Ì': 'i',
    'ò': 'o', 'Ò': 'o',
    'ù': 'u', 'Ù': 'u',
    'â': 'a', 'Â': 'a',
    'ê': 'e', 'Ê': 'e',
    'î': 'i', 'Î': 'i',
    'ô': 'o', 'Ô': 'o',
    'û': 'u', 'Û': 'u',
    'ä': 'a', 'Ä': 'a',
    'ë': 'e', 'Ë': 'e',
    'ï': 'i', 'Ï': 'i',
    'ö': 'o', 'Ö': 'o',
    'ü': 'u', 'Ü': 'u',
    'ç': 'c', 'Ç': 'c',
    'æ': 'ae', 'Æ': 'ae',
    'œ': 'oe', 'Œ': 'oe',
}


def slugify(texto):
    """
    Convierte el texto a un slug:
    - Minúsculas
    - Sin tildes (usando un diccionario de mapeo)
    - Separadores de palabras: guiones (-)
    - Sin guiones iniciales o finales
    """
    # Paso 1: Convertir a minúsculas
    texto = texto.lower()

    # Paso 2: Aplicar mapeo para quitar tildes/acento
    for accented, base in ACCENTOS.items():
        texto = texto.replace(accented, base)

    # Paso 3: Reemplazar caracteres no alfanuméricos por guion
    # [^a-z0-9] coincide con cualquier carácter que no sea letra o dígito
    texto = re.sub(r'[^a-z0-9]', '-', texto)

    # Paso 4: Eliminar guiones del principio y del final
    texto = texto.strip('-')

    return texto
