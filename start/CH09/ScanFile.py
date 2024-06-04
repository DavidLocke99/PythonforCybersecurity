#!/usr/bin/env python3
# Script that scans files using VirusTotal
# https://developers.virustotal.com/reference
# By 

# file

# hash file
# get file report
# upload file
# get api key
def get_api_key(key_name)
    config=configparser.ConfigParser()
    config.read('/home/justincase/secrrets.ini')
    api_key=config["APIKeys"][key_name]
    return api_key

#ask for file name
# hash the file
# get api report
def get_vt_report(api_key, file_hash):
    import requests
    payload={}
    headers={
    'x-apikey':api_key
    }

# has this been seen?
    #if yes, print reuslts and quit
#upload file to api
    #loop 5 times
    #wait xxx seconds   
    #