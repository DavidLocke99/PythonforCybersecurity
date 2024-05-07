#!/usr/bin/env python3
# Script that performs a dictionary attack against known password hashes
# Needs a dictionary file, suggested to use https://github.com/danielmiessler/SecLists/tree/master/Passwords/Common-Credentials
# By 5/6 David

import crypt
import os

file_path=os.path.dirpath(__file__)
print (f"The path of the script is {file_path}")

# ask for ID and Salt
id_salt = input("what is the ID and Salt?")
# ask for fully salted hash
salted_pass = input("what is the fully salted and hash") 
# open pw file
f=open("top10.txt","r")
guesses=f.read()
print(guesses)
# for each guess in pw file
    # hash the guess
    # is guess = to target?
        # print guess then quit