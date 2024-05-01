#!/usr/bin/env python3
# Script that encrypts/decrypts text using ROT13
# By David Locke 4/30

#get message
message = input("what is the message? ")
#for each letter
message = message.lower()
for letter in message:
    #rotate 13 letters
        #change to number
    letter_number = ord(letter)
    #is this a letter
    if letter_number >= 97 and letter_number <= 122:
            #add 13
            letter_number = letter_number +13
            #GTR than 26?
            if letter_number>122:
                #sub 26
                letter_number -=26
    print (letter_number)
    #change to letter

#print (new message)