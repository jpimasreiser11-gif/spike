def fizzbuzz(n):
    """
    Genera una lista de FizzBuzz de 1 a n.
    
    Args:
        n: Número entero positivo
        
    Returns:
        Lista de strings: 'Fizz' para múltiplos de 3,
        'Buzz' para múltiplos de 5, 'FizzBuzz' para ambos,
        o el número como texto en otros casos.
    """
    result = []
    for i in range(1, n + 1):
        if i % 3 == 0 and i % 5 == 0:
            result.append('FizzBuzz')
        elif i % 3 == 0:
            result.append('Fizz')
        elif i % 5 == 0:
            result.append('Buzz')
        else:
            result.append(str(i))
    return result

# Ejemplos de uso
if __name__ == "__main__":
    print(fizzbuzz(15))
    print(fizzbuzz(1))
    print(fizzbuzz(10))
