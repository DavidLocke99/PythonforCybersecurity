import random
import string
import requests
import hashlib

# Character sets based on requirements
lowercase = "abcdefghjkmnpqrstuvwxyz"  # Exclude i, l, o
uppercase = "ABCDEFGHJKMNPQRSTUVWXYZ"  # Exclude L, O
numbers = "23456789"  # Exclude 0, 1
symbols = "!\"#$%&'()*+,-./:;<=>?@[]^_`{|}~"

all_chars = lowercase + uppercase + numbers + symbols

# Function to generate a password
def generate_password(length=22):
    password = []
    password.append(random.choice(lowercase + uppercase))  # Ensure it starts with a letter

    # Keep track of used characters to avoid duplicates
    used_chars = set(password)

    while len(password) < length:
        char = random.choice(all_chars)
        # Ensure no duplicate and no sequential characters
        if char not in used_chars and (not password or abs(ord(password[-1]) - ord(char)) != 1):
            password.append(char)
            used_chars.add(char)
    
    random.shuffle(password)
    return ''.join(password)

# Function to check password against 'Have I Been Pwned'
def check_pwned(password):
    sha1_password = hashlib.sha1(password.encode('utf-8')).hexdigest().upper()
    prefix, suffix = sha1_password[:5], sha1_password[5:]
    response = requests.get(f'https://api.pwnedpasswords.com/range/{prefix}')
    
    if response.status_code != 200:
        raise RuntimeError('Error fetching data from Have I Been Pwned API.')

    hashes = (line.split(':') for line in response.text.splitlines())
    return any(suffix == h for h, _ in hashes)

# Generate and check passwords
passwords = [generate_password() for _ in range(5)]
for pw in passwords:
    is_pwned = check_pwned(pw)
    print(f"Password: {pw} - Pwned: {'Yes' if is_pwned else 'No'}")
