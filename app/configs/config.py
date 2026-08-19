import os

from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("ENV", "DEV").strip().upper()
IS_PROD = ENV == "PROD"

DATABASE_URL = os.getenv("DATABASE_URL")

MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

ALLOWED_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
