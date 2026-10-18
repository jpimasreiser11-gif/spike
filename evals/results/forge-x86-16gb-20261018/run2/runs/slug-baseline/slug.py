def slugify(texto):
    # Convertir a minúsculas
    texto = texto.lower()
    
    # Reemplazar caracteres no alfanuméricos con guion
    texto = ''.join(['-' if not (c.isalnum()) else c for c in texto])
    
    # Quitar guiones del principio y final
    texto = texto.strip('-')
    
    # Reemplazar tildes
    traducciones = {
        'á': 'a', 'ä': 'a', 'å': 'a', 'à': 'a', 'â': 'a', 'ã': 'a',
        'æ': 'ae', 'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
        'ì': 'i', 'í': 'i', 'ï': 'i', 'î': 'i', 'ï': 'i',
        'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o', 'ø': 'o',
        'ù': 'u', 'ú': 'u', 'û': 'u', 'ü': 'u',
        'ñ': 'n'
    }
    
    for caracter, reemplazo in traducciones.items():
        texto = texto.replace(caracter, reemplazo)
    
    return texto
