import re
import unicodedata


def slugify(texto):
    """
    Convierte un texto a slug:
    - a minúsculas
    - quita las tildes (á→a, ñ→n, é→e, etc.)
    - reemplaza caracteres no alfanuméricos con guiones
    - quita guiones de principio y final
    """
    # Convertir a minúsculas
    texto = texto.lower()
    
    # Normalizar Unicode para quitar tildes (complejo -> simple)
    texto = unicodedata.normalize('NFKD', texto)
    
    # Quitar tildes y caracteres especiales - solo mantener letras y dígitos
    # La normalización NFKD convierte caracteres con tildes en sus formas base
    texto = ''.join(caracter for caracter in texto 
                    if unicodedata.category(caracter) != 'Mn' or 
                       caracter in 'áàâãäåæçèéêëìíîïòóôõöùúûüýþÿ')
    
    # Más simple: solo mantener alfanuméricos
    texto = re.sub(r'[^a-z0-9]+', '-', texto)
    
    # Quitar guiones de principio y final
    texto = texto.strip('-')
    
    return texto

