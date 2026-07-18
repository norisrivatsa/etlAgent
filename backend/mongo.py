import os

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

MONGO_DB = os.getenv("MONGO_DB", "kafka_orchestrator")

client = MongoClient(
    MONGO_URI,
    maxPoolSize=100,
    minPoolSize=5,
)

db = client[MONGO_DB]

pipeline_sessions = db["pipeline_sessions"]
tasks = db["tasks"]
messages = db["messages"]
context_messages = db["context_messages"]
