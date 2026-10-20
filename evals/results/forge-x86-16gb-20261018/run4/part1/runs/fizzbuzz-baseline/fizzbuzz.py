def fizzbuzz(n):
    """
    Return a list of strings from 1 to n with:
    - 'Fizz' for multiples of 3
    - 'Buzz' for multiples of 5
    - 'FizzBuzz' for multiples of both 3 and 5
    - The number as a string otherwise
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

# Example usage:
# print(fizzbuzz(15))

if __name__ == "__main__":
    print(fizzbuzz(15))
