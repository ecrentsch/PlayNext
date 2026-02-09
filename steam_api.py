import os
import requests
from dotenv import load_dotenv

# Load the API key from .env file
load_dotenv()
STEAM_API_KEY = os.getenv("STEAM_API_KEY")


class SteamAPI:
    def __init__(self):
        self.api_key = STEAM_API_KEY
        self.base_url = "https://api.steampowered.com"

    def get_steam_id(self, vanity_url):
        """Convert a Steam vanity URL to Steam ID"""
        url = f"{self.base_url}/ISteamUser/ResolveVanityURL/v1/"
        params = {"key": self.api_key, "vanityurl": vanity_url}
        response = requests.get(url, params=params)
        data = response.json()

        if data["response"]["success"] == 1:
            return data["response"]["steamid"]
        return None

    def get_owned_games(self, steam_id):
        """Get all games owned by a user"""
        url = f"{self.base_url}/IPlayerService/GetOwnedGames/v1/"
        params = {
            "key": self.api_key,
            "steamid": steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
        }
        response = requests.get(url, params=params)
        data = response.json()

        if "response" in data and "games" in data["response"]:
            return data["response"]["games"]
        return []

    def get_game_details(self, app_id):
        """Get detailed information about a game from the Steam store"""
        url = f"https://store.steampowered.com/api/appdetails"
        params = {
            "appids": app_id,
            "cc": "us",  # Force US country code for USD pricing
            "l": "english",  # English language
        }

        try:
            response = requests.get(url, params=params)
            data = response.json()

            if str(app_id) in data and data[str(app_id)]["success"]:
                game_data = data[str(app_id)]["data"]

                # DEBUG: Print raw price data from API
                if "price_overview" in game_data:
                    print(f"\n=== RAW API DATA for {game_data.get('name', app_id)} ===")
                    print(f"Full price_overview: {game_data['price_overview']}")

                return game_data
        except Exception as e:
            print(f"Error fetching game {app_id}: {e}")

        return None
