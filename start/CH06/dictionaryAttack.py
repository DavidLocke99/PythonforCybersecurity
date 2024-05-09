#!/usr/bin/env python3
# Script that performs a dictionary attack against known password hashes
# Needs a dictionary file, suggested to use https://github.com/danielmiessler/SecLists/tree/master/Passwords/Common-Credentials
# By 5/6 David

import crypt
import os

file_path=os.path.dirname(__file__)

# ask for ID and Salt
id_salt = input("what is the ID and Salt?")
# ask for fully salted hash
salted_pass = input("what is the fully salted and hash ") 
# open pw file
f=open(file_path+ "/10-million-password-list-top-1000000.txt","r")
# for each guess in pass file
for guess in f:
    guess=guess.strip()

    # hash the guess
    hashed_guess=crypt.crypt(guess,id_salt)
    
    # is guess = to target?
    if hashed_guess==salted_pass:
        # print guess and quit
        print(guess)
        exit()
