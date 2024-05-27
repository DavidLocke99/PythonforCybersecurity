#!/usr/bin/env python3
import requests
import json

def get_random_user():
    requestUri = "https://randomuser.me/api/"
    response = requests.get(requestUri)

    if response.status_code == 200:
        data = response.json()
        user = data['results'][0]

        name = user['name']
        location = user['location']
        login = user['login']
        dob = user['dob']
        registered = user['registered']
        phone = user['phone']
        cell = user['cell']
        id_info = user['id']
        picture = user['picture']
        nat = user['nat']

        print(f"Name: {name['title']} {name['first']} {name['last']}")
        print(f"Gender: {user['gender']}")
        print(f"Email: {user['email']}")
        print("Address:")
        print(f"    Street: {location['street']['number']} {location['street']['name']}")
        print(f"    City: {location['city']}")
        print(f"    State: {location['state']}")
        print(f"    Country: {location['country']}")
        print(f"    Postcode: {location['postcode']}")
        print(f"Coordinates: {location['coordinates']['latitude']}, {location['coordinates']['longitude']}")
        print(f"Timezone: {location['timezone']['offset']} {location['timezone']['description']}")
        print(f"Username: {login['username']}")
        print(f"Password: {login['password']}")
        print(f"Date of Birth: {dob['date']} (Age: {dob['age']})")
        print(f"Registered: {registered['date']} (Age: {registered['age']})")
        print(f"Phone: {phone}")
        print(f"Cell: {cell}")
        print(f"ID: {id_info['name']} {id_info['value']}")
        print(f"Picture: {picture['large']}")
        print(f"Nationality: {nat}")
    else:
        print(f"Error, status code: {response.status_code} - {response.content}")

if __name__ == "__main__":
    get_random_user()
