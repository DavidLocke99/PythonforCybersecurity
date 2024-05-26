import requests

def get_dad_joke():
    # Define the API endpoint
    url = "https://icanhazdadjoke.com/"

    # Define the headers
    headers = {
        "Accept": "application/json"
    }

    # Send GET request to the API
    response = requests.get(url, headers=headers)

    # Check if request was successful (status code 200)
    if response.status_code == 200:
        # Extract the joke from the JSON response
        joke = response.json()["joke"]
        return joke
    else:
        print("Error: Unable to fetch joke from API")
        return None

def main():
    # Get a random dad joke
    joke = get_dad_joke()

    # Print the joke to the screen
    if joke:
        print("Random Dad Joke:")
        print(joke)

if __name__ == "__main__":
    main()
