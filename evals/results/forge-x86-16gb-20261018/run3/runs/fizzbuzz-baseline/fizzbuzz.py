def fizzbuzz(n):
    """
    Genera una lista de cadenas de 1 a n:
    - 'Fizz' para los múltiplos de 3
    - 'Buzz' para los múltiplos de 5
    - 'FizzBuzz' para los múltiplos de ambos 3 y 5
    - El número como texto en los demás casos
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

# Ejemplo de uso
if __name__ == '__main__':
    print(fizzbuzz(15))
    # ['1', '2', 'Fizz', '4', 'Buzz', 'Fizz', '7', '8', 'Fizz', 'Buzz', '11', 'Fizz', '13', '14', 'FizzBuzz']
