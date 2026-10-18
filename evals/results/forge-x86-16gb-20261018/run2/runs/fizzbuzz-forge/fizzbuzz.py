def fizzbuzz(n):
    """
    Returns a list of strings for numbers from 1 to n.
    'Fizz' for multiples of 3, 'Buzz' for multiples of 5,
    'FizzBuzz' for multiples of both, and the number as string otherwise.
    
    For n <= 0, returns [str(n)].
    """
    # Handle edge cases where n <= 0
    if n <= 0:
        return [str(n)]
    
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

if __name__ == "__main__":
    print(fizzbuzz(15))
    
    # Test edge cases
    print(fizzbuzz(0))
    print(fizzbuzz(-5))
