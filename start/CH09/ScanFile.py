#!/usr/bin/env python3
# Script that scans files using VirusTotal
# https://developers.virustotal.com/r# ask for file name
# file_name = input"what file do you want to scan? "eference
# By 
import configparser
import requests
import hashlib

#hash file
def sha256sum(filename):
    h  = hashlib.sha256()
    b  = bytearray(128*1024)
    mv = memoryview(b)
    with open(filename, 'rb', buffering=0) as f:
        for n in iter(lambda : f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()
#get file report
#upload file
def upload_vt_file(api_key, file_name):

    url = "https://www.virustotal.com/api/v3/files"

    files = { "file": (file_name, open(file_name, "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document") }
    
    headers = {}

    response = requests.request("GET", url, headers=headers, data=payload)
        
    return response.json()

#get api key
def _get_api_key(key_name):
    config = configparser.configParser()
    config.read('/home/justincase/secrets.ini')
    api_key = ["APIKeys"][key_name]
    return api_key

# get file name
file_name = input("What file do you want to test? ")
print(file_name)


#