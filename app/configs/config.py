"""Environment values. No factories live here — see app/llms and app/db for those."""

import os

from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("ENV", "DEV").strip().upper()
IS_PROD = ENV == "PROD"

DATABASE_URL = os.getenv("DATABASE_URL")

GROQ_MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

ALLOWED_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv( "CORS_ORIGINS").split(",")
    if origin.strip()
]
