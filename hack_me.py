def main():
    # Ask for user information
    name = input("What is your name? ")
    color = input("What is your favorite color? ")
    pet_name = input("What was your first pet's name? ")
    maiden_name = input("What is your mother's maiden name? ")
    school = input("What elementary school did you attend? ")

    # Create a dictionary to store the information
    user_info = {
        "Name": name,
        "Favorite Color": color,
        "First Pet's Name": pet_name,
        "Mother's Maiden Name": maiden_name,
        "Elementary School": school
    }

    # Save the information to a file
    filename = "hackme.txt"
    with open(filename, "w") as file:
        for key, value in user_info.items():
            file.write(f"{key}: {value}\n")

    print(f"User information has been saved to {filename}.")

if __name__ == "__main__":
    main()
def read_dont_hack_me_file(filename):
    try:
        with open(filename, 'r') as file:
            data = file.read()
            print("Here is someone to hack - information\n")
            print(data)
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")

if __name__ == "__main__":
    read_dont_hack_me_file("hackme.txt")
