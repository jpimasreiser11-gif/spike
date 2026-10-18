import re


def slugify(texto):
    """
    Convert texto to slug format:
    - Convert to lowercase
    - Remove accents/tildes (á→a, ñ→n, etc.)
    - Replace non-alphanumeric characters with hyphens
    - Remove leading and trailing hyphens
    """
    # Mapping for accented characters to their unaccented equivalents
    acented_chars = {
        'á': 'a', 'Á': 'a',
        'é': 'e', 'É': 'e',
        'í': 'i', 'Í': 'i',
        'ó': 'o', 'Ó': 'o',
        'ú': 'u', 'Ú': 'u',
        'ñ': 'n', 'Ñ': 'n',
        'ü': 'u', 'Ü': 'u',
    }
    
    # Replace accented characters with their unaccented equivalents
    texto = texto
    for key, value in acented_chars.items():
        texto = texto.replace(key, value)
    
    # Convert to lowercase
    texto = texto.lower()
    
    # Replace any character that is not a letter or digit with a hyphen
    texto = re.sub(r'[^a-z0-9]', '-', texto)
    
    # Collapse consecutive hyphens into a single hyphen
    texto = re.sub(r'-+', '-', texto)
    
    # Remove leading and trailing hyphens
    texto = texto.strip('-')
    
    return texto
