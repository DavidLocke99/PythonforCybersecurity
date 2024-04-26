def send_message(name):
    for _ in range(10):
        print(name + ", Yes it is")

def main():
    # Ask for the user's name
    name = input("What is your name? ")

    # Ask if today is a good day
    response = input("Is today a good day? (y/n) ")

    if response.lower() == 'y':
        # If it's a good day, call the send_message function
        send_message(name)
    elif response.lower() == 'n':
        # If it's not a good day, print "Sorry to hear that" followed by the name
        print("Sorry to hear that, " + name)
    else:
        # If the input is neither 'y' nor 'n', print an error message
        print("Invalid input. Please enter 'y' or 'n'.")

if __name__ == "__main__":
    main()

