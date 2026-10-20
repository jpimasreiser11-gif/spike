def fizzbuzz(n):
    """
    Returns a list of strings from 1 to n:
    - 'Fizz' for multiples of 3
    - 'Buzz' for multiples of 5
    - 'FizzBuzz' for multiples of both 3 and 5
    - Number as string for other cases
    """
    result = []
    for i in range(1, n + 1):
        if i % 15 == 0:  # Multiple of both 3 and 5 (LCM is 15)
            result.append('FizzBuzz')
        elif i % 3 == 0:
            result.append('Fizz')
        elif i % 5 == 0:
            result.append('Buzz')
        else:
            result.append(str(i))
    return result
