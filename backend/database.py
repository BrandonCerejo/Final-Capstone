from pymongo import MongoClient
from dotenv import load_dotenv
import certifi
import os

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME   = os.getenv("DATABASE_NAME")

client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())

db = client[DB_NAME]

users_collection   = db["users"]
reports_collection = db["reports"]
label_corrections_collection = db["label_corrections"]