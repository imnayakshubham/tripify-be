"""Environment values. No factories live here — see app/llms and app/db for those."""

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Used by app/llms/groq.py to build the model, and recorded on every audit row
# so a run can be traced back to the model that produced it.
GROQ_MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

ALLOWED_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173"
        ",http://localhost:5174,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]
