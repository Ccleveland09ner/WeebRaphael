from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from pydantic import BaseModel
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import os
import requests
import spacy
import httpx

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(MONGO_URI)
db = client["WeebRaphael"]  
users_collection = db["users"]  

app = FastAPI()

@app.get("/test-db")
async def test_db_connection():
    try:
        await db.command("ping")  
        return {"message": "✅ MongoDB is connected successfully!"}
    except Exception as e:
        return {"error": str(e)}

nlp = spacy.load("en_core_web_sm")

ANILIST_API_URL = os.getenv("ANILIST_API_URL")

GENRE_MAPPING = {
    "action": "Action",
    "adventure": "Adventure",
    "comedy": "Comedy",
    "drama": "Drama",
    "fantasy": "Fantasy",
    "horror": "Horror",
    "romance": "Romance",
    "scifi": "Sci-Fi",
    "science": "Sci-Fi",
    "fiction": "Sci-Fi",
    "slice": "Slice of Life",
    "life": "Slice of Life",
    "sports": "Sports",
    "thriller": "Thriller",
    "mystery": "Mystery",
    "psychological": "Psychological",
    "supernatural": "Supernatural",
    "magic": "Magic"
}

def extract_keywords(user_input: str):
    doc = nlp(user_input)
    
    adjectives = []
    nouns = []

    for token in doc:
        if token.pos_ == "ADJ":
            adjectives.append(token.text)
        elif token.pos_ == "NOUN":
            nouns.append(token.text)

    return adjectives, nouns

def map_to_genres(keywords):
    genres = []
    for keyword in keywords:
        if keyword in GENRE_MAPPING:
            genres.append(GENRE_MAPPING[keyword])
    if not genres:
        genres = ["Action", "Adventure"]
    return genres

async def fetch_anime_recommendations(genre: list):
    query = """
    query ($genres: [String], $perPage: Int) {
        Page(page: 1, perPage: $perPage) {
            media (genre_in: $genres, type: ANIME, sort: POPULARITY_DESC) {
                title {
                    romaji
                    english
                }
                description
                genres
                coverImage {
                    large
                }
                siteUrl
                averageScore
            }
        }
    }
    """

    variables = {
        "genres": genre, 
        "perPage": 10
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ANILIST_API_URL, json={"query": query, "variables": variables})
        if response.status_code == 200:
            data = response.json()
            if "data" in data and "Page" in data["data"] and "media" in data["data"]["Page"]:
                return data["data"]["Page"]["media"]
        return []

@app.get("/recommend")
async def get_recommendations(genre: str):
    adjectives, nouns = extract_keywords(genre)

    all_keywords = adjectives + nouns

    mapped_genres = map_to_genres(all_keywords)

    anime_list = await fetch_anime_recommendations(mapped_genres)
    if anime_list:
        return [
            {
                "title": anime["title"]["romaji"],
                "description": anime["description"],
                "genres": anime["genres"],
                "coverImage": anime["coverImage"]["large"],
                "siteUrl": anime["siteUrl"]
            }
            for anime in anime_list
        ]
    raise HTTPException(status_code=404, detail="No recommendations found")

async def fetch_anime_search(query: str):
    search_query = """
    query ($search: String, $perPage: Int) {
        Page(page: 1, perPage: $perPage) {
            media(search: $search, type: ANIME) {
                title {
                    romaji
                    english
                }
                description
                genres
                coverImage {
                    large
                }
                siteUrl
                averageScore
            }
        }
    }
    """
    variables = {
        "search": query,
        "perPage": 5 
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ANILIST_API_URL, json={"query": search_query, "variables": variables})
        if response.status_code == 200:
            data = response.json()
            if "data" in data and "Page" in data["data"] and "media" in data["data"]["Page"]:
                return data["data"]["Page"]["media"]
        return []

@app.get("/search")
async def search_anime(query: str):
    adjectives, nouns = extract_keywords(query)

    search_query = " ".join(nouns)

    anime_list = await fetch_anime_search(search_query)
    if anime_list:
        return [
            {
                "title": anime["title"]["romaji"],
                "description": anime["description"],
                "genres": anime["genres"],
                "coverImage": anime["coverImage"]["large"],
                "siteUrl": anime["siteUrl"]
            }
            for anime in anime_list
        ]
    raise HTTPException(status_code=404, detail="No anime found matching that query")

class UserCreate(BaseModel):
    username: str
    email: str
    preferences: list[str] = []

class FavoriteAnime(BaseModel):
    anime_id: str
    title: str

class WatchHistory(BaseModel):
    anime_id: str
    title: str

async def create_user(user: UserCreate):
    existing_user = await users_collection.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    user_data = {
        "username": user.username,
        "email": user.email,
        "preferences": user.preferences,
        "watch_history": [],
        "favorites": []
    }
    await users_collection.insert_one(user_data)
    return {"message": "User created successfully"}

@app.get("/users/{username}")
async def get_user(username: str):
    user = await users_collection.find_one({"username": username}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.post("/users/{username}/favorites")
async def add_favorite(username: str, anime: FavoriteAnime):
    user = await users_collection.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    anime_entry = {"anime_id": anime.anime_id, "title": anime.title, "added_at": datetime.utcnow().isoformat()}
    await users_collection.update_one(
        {"username": username}, {"$push": {"favorites": anime_entry}}
    )
    return {"message": "Anime added to favorites"}

async def add_watch_history(username: str, anime: WatchHistory):
    user = await users_collection.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    history_entry = {"anime_id": anime.anime_id, "title": anime.title, "watched_at": datetime.utcnow().isoformat()}
    await users_collection.update_one(
        {"username": username}, {"$push": {"watch_history": history_entry}}
    )
    return {"message": "Anime added to watch history"}