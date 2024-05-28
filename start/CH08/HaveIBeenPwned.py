#!/usr/bin/env python3
# Script that checks passwords agains haveibeenpwned.com API
# https://haveibeenpwned.com/API/v3#PwnedPasswords
# By 5/28 david

#what we know
    # how the api works 
import requests

url = "https://api.pwnedpasswords.com/range/range/b1b27"

payload={}
headers = {}

response = requests.request("GET", url, headers=headers, data=payload)

print(response.text)
# function for haveibeenpwned


# ask for passwword


# generate sha-1 hash


# call api


# search though results


# report found or not found


# what we don't know
    # how to split strings into 2 parts
