import re

# Mapeo de caracteres con tildes
ACCENTS = {
    # Voz alta (con tilde aguda)
    'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
    # Voz grave (con tilde grave)
    'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
    # Voz cerrada (con tilde cerrada)
    'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'ü': 'u',
    # Ñ
    'ñ': 'n',
    # Carácter especial
    'ç': 'c'
}


def slugify(texto):
    """
    Transforma texto a slug.
    
    Args:
        texto: Texto a convertir
        
    Returns:
        Texto en formato slug (minúsculas, sin tildes, sin caracteres especiales)
    """
    # Convertir a minúsculas
    texto = texto.lower()
    
    # Aplicar mapeo para quitar tildes
    for key, value in ACCENTS.items():
        texto = texto.replace(key, value)
    
    # Reemplazar cualquier carácter no alfanumérico por un guion
    texto = re.sub(r'[^a-z0-9]', '-', texto)
    
    # Eliminar múltiples guiones consecutivos
    texto = re.sub(r'-+', '-', texto)
    
    # Eliminar guiones del principio y del final usando re.sub
    texto = re.sub(r'^-+|-+$', '', texto)
    
    return texto
