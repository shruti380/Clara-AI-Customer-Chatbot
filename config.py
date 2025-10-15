import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    # SQLite DB file for Clara sessions
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///clara_sessions.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # LLM / Gemini settings
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
