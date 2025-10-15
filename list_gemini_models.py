# list_gemini_models.py
import os
import google.generativeai as genai
from config import Config

API_KEY = Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise SystemExit("GEMINI_API_KEY missing. Set GEMINI_API_KEY in .env or env vars.")

genai.configure(api_key=API_KEY)

print("Attempting to list available models via SDK...")

# Try several variants depending on SDK surface
try:
    # newer SDKs may provide genai.list_models()
    lm = genai.list_models()
    print("genai.list_models() output:")
    for m in lm:
        try:
            # print model id/name and supported methods if available
            print(" -", getattr(m, "name", m))
        except Exception:
            print(" -", m)
    raise SystemExit(0)
except Exception as e:
    print("genai.list_models() failed:", e)

try:
    # Client-style
    client = genai.Client()
    resp = client.models.list()
    print("client.models.list() output:")
    # resp may be a dict or object list
    if hasattr(resp, "models"):
        models = resp.models
    elif isinstance(resp, (list, tuple)):
        models = resp
    else:
        # try dict
        models = resp.get("models", resp)
    for m in models:
        # attempt various display attributes
        name = getattr(m, "name", None) or getattr(m, "model", None) or (m.get("name") if isinstance(m, dict) else None)
        print(" -", name or m)
    raise SystemExit(0)
except Exception as e:
    print("client.models.list() failed:", e)

print("Could not list models using known SDK calls. Check your SDK version or consult Google GenAI docs.")
