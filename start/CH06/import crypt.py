import crypt
import os

# Get the directory path of the current script
file_path = os.path.dirname(__file__)
print(f"The path of the script is {file_path}")

# Read the ID and salt from user input
id_salt = input("Enter the ID and Salt: ")
# Read the fully salted hash from user input
salted_pass = input("Enter the fully salted hash: ")

# Open the password file
try:
    with open("top10.txt", "r") as f:
        guesses = f.readlines()
except FileNotFoundError:
    print("Password file not found.")
    exit()

# Iterate over each guess in the password file
for guess in guesses:
    guess = guess.strip()  # Remove leading/trailing whitespace
    hashed_guess = crypt.crypt(guess, id_salt)

    # Compare hashed guess with target hash
    if hashed_guess == salted_pass:
        print(f"Password found: {guess}")
        break
else:
    print("Password not found.")
