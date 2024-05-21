#!/usr/bin/env python3
# Script that tells us how many people there are in space
#By 05/21/2024 David

# Import things
import requests

# get people in space function
def get_people_in_space(): 
    url = "http://api.open-notify.org/astros.json"
    payload={}
    headers = {}
    response = requests.request("GET", url, headers=headers, data=payload)
    items = response.json()
    return items

# print basics
astronauts = get_people_in_space()
# print(astronauts)

# print only the number of people in space
ast_num=(astronauts["number"])
print( "There are currently {0} people in space".format(ast_num))

#print first persons name
# Astronaut, People, Number, Name
first_name = astronauts["people"][0]['name']
print("The first astronaut is {0}".format(first_name))
#print loop
print("Full list of astronauts")
for person in astronauts["people"]:
    print("{0} is aboard {1}".format( person["name"],person["craft"]))