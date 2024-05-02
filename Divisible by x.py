def is_divisible(number, divisor):
    # Check if the number is cleanly divisible by the divisor
    return number % divisor == 0

def main():
    # Prompt the user for a number
    number = int(input("Enter a number: "))

    # Prompt the user for a divisor
    divisor = int(input("Enter a divisor: "))

    # Check if the number is divisible by the divisor
    if is_divisible(number, divisor):
        print(f"{number} is cleanly divisible by {divisor}.")
    else:
        print(f"{number} is not cleanly divisible by {divisor}.")

if __name__ == "__main__":
    main()
