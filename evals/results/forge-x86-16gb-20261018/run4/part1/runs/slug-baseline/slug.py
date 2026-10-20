def slugify(texto):
    """
    Convierte texto a slug (formato de URL amigable).
    
    Args:
        texto: String que se quiere convertir
    
    Returns:
        String en formato slug (minúsculas, sin tildes, con guiones)
    
    Ejemplo:
        >>> slugify('¡Hola, Señor Pérez!')
        'hola-senor-perez'
    """
    # Paso 1: Convertir a minúsculas
    texto = texto.lower()
    
    # Paso 2: Reemplazar tildes por caracteres sin tildes
    # Usamos una lista de reemplazos para los caracteres con acentos
    tildes = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n',
        'Á': 'a', 'É': 'e', 'Í': 'i', 'Ó': 'o', 'Ú': 'u', 'Ñ': 'n'
    }
    
    for caracter, reemplazo in tildes.items():
        texto = texto.replace(caracter, reemplazo)
    
    # Paso 3: Reemplazar cualquier carácter que no sea letra o dígito con un guion
    import re
    # Usar regex para encontrar cualquier carácter que no sea letra o dígito
    texto = re.sub(r'[^a-z0-9]', '-', texto)
    
    # Paso 4: Quitar guiones del principio y final
    texto = texto.strip('-')
    
    # Paso 5: Eliminar guiones duplicados consecutivos
    texto = re.sub(r'-+', '-', texto)
    
    return texto

# Ejemplos de uso
if __name__ == '__main__':
    print(slugify('¡Hola, Señor Pérez!'))  # hola-senor-perez
    print(slugify('Café con ñoño'))        # cafe-con-nono
    print(slugify('123-456'))              # 123-456
    print(slugify('  Hola  '))             # hola
    print(slugify('Título: ¡Qué!'))        # titulo-que