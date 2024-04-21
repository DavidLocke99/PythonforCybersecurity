def main():
    # Ask for the user's name
    name = input("What's your name? ")

    # Ask if today is a good day
    response = input("Is today a good day? (y/n): ")

    # Process the response
    if response.lower() == "y":
        print(f"{name}, Yes it is.")
    elif response.lower() == "n":
        print(f"Sorry to hear that, {name}.")
    else:
        print("Invalid input. Please enter 'y' or 'n'.")

if __name__ == "__main__":
    main()