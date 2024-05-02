
# Function to collect user information
def collect_user_info():
    name = input("What is your name? ")
    color = input("What is your favorite color? ")
    pet_name = input("What was your first pet's name? ")
    mother_maiden_name = input("What is your mother's maiden name? ")
    elementary_school = input("What elementary school did you attend? ")
    
    return name, color, pet_name, mother_maiden_name, elementary_school

# Function to save information to a file
def save_to_file(info):
    with open("hackme.txt", "w") as file:
        file.write(f"Name: {info[0]}\n")
        file.write(f"Favorite Color: {info[1]}\n")
        file.write(f"First Pet's Name: {info[2]}\n")
        file.write(f"Mother's Maiden Name: {info[3]}\n")
        file.write(f"Elementary School: {info[4]}\n")

# Main function
def main():
    print("Please answer the following questions:")
    user_info = collect_user_info()
    save_to_file(user_info)
    print("Your information has been saved to hackme.txt")

if __name__ == "__main__":
    main()
# =======
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
