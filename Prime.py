def is_prime(number):
    # Check if the number is less than 2
    if number < 2:
        return False
    # Check if the number is divisible by any integer from 2 to the square root of the number
    for i in range(2, int(number**0.5) + 1):
        if number % i == 0:
            return False
    return True

def main():
    # Prompt the user for a number
    number = int(input("Enter a number: "))

    # Check if the number is prime using the is_prime function
    if is_prime(number):
        print(f"{number} is a prime number.")
    else:
        print(f"{number} is not a prime number.")

if __name__ == "__main__":
    main()
