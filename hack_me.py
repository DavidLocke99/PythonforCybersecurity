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
