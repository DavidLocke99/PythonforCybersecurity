#!/usr/bin/env python3
# Script that checks passwords agains haveibeenpwned.com API
# https://haveibeenpwned.com/API/v3#PwnedPasswords
# By 5/28 david

import requests
import hashlib

# function for haveibeenpwned


def check_password(first_five):
    url = "https://api.pwnedpasswords.com/range/"+first_five
    payload={}
    headers = {}
    response = requests.request("GET", url, headers=headers, data=payload)

    return response.text

# ask for passwword

pass_to_test="qwerty"

# generate sha-1 hex digets for some input string
def SHA1(msg:str) -> str:
    encoded_string = msg.encode()
    hash_result = hashlib.sha1(encoded_string)
    return hash_result.hexdigest()

# ask for PW
pass_to_test="qwerty"
# get hash and split
hash_full = SHA1("qwerty")
hash_start=hash_full[0:5]
hash_end=hash_full[5:]

#call api
pwned_results = check_password(hash_start)

#search through results
print(pwned_results)