# app/llm_engine.py
import os
import time
import google.generativeai as genai
from config import Config
import re

API_KEY = Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY not set. Please set it in .env or env var.")

genai.configure(api_key=API_KEY)

MODEL_NAME = os.getenv("GEMINI_MODEL", Config.GEMINI_MODEL)

# Try to initialize model object and client fallback
model = None
client = None
_initialization_error = None

try:
    # Preferred: GenerativeModel wrapper (SDK v0.8+)
    model = genai.GenerativeModel(MODEL_NAME)
except Exception as e:
    _initialization_error = e
    try:
        # fallback: client
        client = genai.Client()
        model = None
    except Exception as e2:
        print("Failed to initialize genai.Client() fallback:", e2)
        # leave client None and let call functions handle it


def _build_prompt(context, user_input):
    """
    Build clear instruction + context for Clara with strict response-format rules.
    """
    system_instructions = (
        "You are Clara, a friendly and professional AI customer support assistant. "
        "Follow these STRICT formatting and style rules for every reply:\n\n"
        "1) Do NOT start with filler interjections such as 'Excellent!', 'Great!', 'Okay', "
        "'Sure' or 'Thanks' at the very beginning. If you want a short acknowledgement, "
        "it must be a single line of at most eight words (e.g., 'Thanks — here are the details:') followed by a blank line.\n\n"
        "2) Provide a concise direct answer in 1–3 sentences.\n\n"
        "3) If you present multiple items (features, steps, options), format them as a numbered list (1., 2., 3.) or short bullets. "
        "Keep list items short (one sentence each).\n\n"
        "4) End with a short, clear follow-up question offering next actions (e.g., 'Would you like setup steps?' or 'Should I escalate this?').\n\n"
        "5) Use neutral, professional language. Do not add unnecessary enthusiastic exclamations or filler words.\n\n"
        "6) If uncertain or the issue needs a human, reply exactly: "
        "'I'm escalating this issue to a human support agent. Please wait while I connect you.'\n\n"
        "Now answer the user's query using the conversation context below. Keep the response tightly focused and formatted as instructed."
    )

    parts = [
        system_instructions,
        "\nConversation context:\n" + (context or "No prior context."),
        f"\nCustomer: {user_input}",
        "\nClara:"
    ]
    return "\n\n".join(parts)
# list of common filler prefixes to remove if they start the reply
_FILLER_PREFIXES = [
    r"^\s*excellent[!.,]?\s*", r"^\s*great[!.,]?\s*", r"^\s*okay[!.,]?\s*",
    r"^\s*sure[!.,]?\s*", r"^\s*thanks[!.,]?\s*", r"^\s*thank you[!.,]?\s*",
    r"^\s*perfect[!.,]?\s*", r"^\s*alright[!.,]?\s*"
]

def postprocess_reply(raw_reply: str) -> str:
    """
    Clean up the model reply:
      - Remove leading filler interjections.
      - Normalize whitespace.
      - Ensure numbered/bulleted items are on separate lines.
      - Turn inline '*' or '•' bullets into separate lines prefixed by '- '.
      - Ensure a blank line before the first list for readability.
      - Append a short follow-up question if none exists.
    """
    if not raw_reply:
        return raw_reply

    reply = raw_reply.strip()

    # Remove a single leading filler interjection if it exists
    for pattern in _FILLER_PREFIXES:
        new_reply = re.sub(pattern, "", reply, flags=re.IGNORECASE)
        if new_reply != reply:
            reply = new_reply.strip()
            break

    # Normalize any carriage returns
    reply = reply.replace("\r\n", "\n").replace("\r", "\n")

    # Turn inline asterisk or bullet markers into line-start bullets.
    # Example: " * A * B * C" or "* A * B" -> "\n- A\n- B\n- C"
    # We replace occurrences of optional whitespace + bullet char + optional whitespace with '\n- '
    reply = re.sub(r'\s*[\*\u2022]\s*', r'\n- ', reply)

    # Ensure numbered items start on their own line: insert newline before "1.", "2.", etc. if needed
    reply = re.sub(r'(?<!\n)(\b\d+\.)\s*', r'\n\1 ', reply)

    # Ensure there is a blank line before the first list item (either '- ' or numbered) for readability.
    # If a list directly follows text on same line, add a blank line.
    reply = re.sub(r'([^\n])\n(-\s|(\d+\.\s))', r'\1\n\n\2', reply)

    # Normalize multiple newlines to at most one blank line
    reply = re.sub(r'\n{3,}', '\n\n', reply)

    # Trim spaces at line starts/ends and remove empty lines
    lines = [line.strip() for line in reply.splitlines()]
    lines = [ln for ln in lines if ln != ""]
    reply = "\n".join(lines)

    # If the reply uses "- item1 - item2" with no separator (edge-case), ensure splitting (fallback)
    # (very defensive) — split on ' - ' occurrences that don't start line
    reply = re.sub(r'(?<!\n)\s-\s', r'\n- ', reply)

    # If reply is explanatory and doesn't contain a question, append a concise follow-up.
    if "?" not in reply[-200:]:
        lower = reply.lower()
        if "escalat" not in lower and not re.match(r"i'm having trouble", lower) and len(reply) > 20:
            reply = reply.rstrip() + "\n\nWould you like instructions to set this up or should I escalate this?"

    return reply






def _list_models_and_print():
    """Try several SDK calls to list available models and print to console for the user."""
    print("\n=== Listing available models (for diagnostics) ===")
    try:
        lm = genai.list_models()
        print("genai.list_models() returned:")
        try:
            for m in lm:
                # try best effort display
                print(" -", getattr(m, "name", m))
        except Exception:
            print(lm)
        return
    except Exception as e:
        print("genai.list_models() failed:", e)

    try:
        if 'client' in globals() and client is not None:
            resp = client.models.list()
            print("client.models.list() returned:")
            # attempt to iterate responsively
            models = getattr(resp, "models", None) or resp
            for m in models:
                name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else None)
                print(" -", name or m)
            return
    except Exception as e:
        print("client.models.list() failed:", e)

    print("Unable to list models programmatically. Please check your SDK docs or cloud console for available models.")


def _call_generate_content(prompt, temperature=0.2, max_output_tokens=256):
    """
    Call whichever generate_content method is available and return text string.
    Raises RuntimeError on fatal failure.
    """
    # Preferred path: model.generate_content(...)
    if model is not None:
        try:
            resp = model.generate_content(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens
                }
            )
            # new SDK usually exposes .text
            if hasattr(resp, "text"):
                return resp.text.strip()
            if isinstance(resp, dict):
                candidates = resp.get("candidates") or resp.get("outputs") or []
                if candidates:
                    first = candidates[0]
                    if isinstance(first, dict):
                        return first.get("content") or first.get("text") or str(first)
                    return str(first)
            return str(resp).strip()
        except Exception as e:
            # If 404 / model-not-found, list models and raise a clear error
            err_str = str(e)
            print("model.generate_content failed:", err_str)
            if "not found" in err_str.lower() or "404" in err_str:
                _list_models_and_print()
                raise RuntimeError(
                    f"Model '{MODEL_NAME}' not found or not supported for generate_content. "
                    "See above for available models and set GEMINI_MODEL accordingly."
                ) from e
            # otherwise fall through to try client fallback

    # Fallback path: client.models.generate_content(...) or client.generate(...)
    if 'client' in globals() and client is not None:
        try:
            # try client.models.generate_content (some SDK variants)
            if hasattr(client, "models") and hasattr(client.models, "generate_content"):
                resp = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens
                )
            else:
                # try client.generate (other variants)
                resp = client.generate(
                    model=MODEL_NAME,
                    prompt=prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens
                )
            if hasattr(resp, "text"):
                return resp.text.strip()
            if isinstance(resp, dict):
                candidates = resp.get("candidates") or resp.get("outputs") or []
                if candidates:
                    first = candidates[0]
                    if isinstance(first, dict):
                        return first.get("content") or first.get("text") or str(first)
                    return str(first)
            return str(resp).strip()
        except Exception as e:
            err_str = str(e)
            print("client generation failed:", err_str)
            if "not found" in err_str.lower() or "404" in err_str:
                _list_models_and_print()
                raise RuntimeError(
                    f"Model '{MODEL_NAME}' not found or not supported by client.generate. "
                    "See above for available models and set GEMINI_MODEL accordingly."
                ) from e

    # If we reach here nothing worked
    raise RuntimeError("No available method to call Gemini generate_content in this environment.")


def generate_response(context, user_input, max_output_tokens=256, temperature=0.2):
    """
    Generate a conversational response for a user_input given context.
    Uses postprocess_reply() to enforce formatting rules.
    """
    prompt = _build_prompt(context, user_input)

    try:
        # Use the internal _call_generate_content(...) helper already present in the file.
        reply = _call_generate_content(prompt, temperature=temperature, max_output_tokens=max_output_tokens)
        # Sanitize/format reply to follow the desired structure
        reply = postprocess_reply(reply)

        # Escalation heuristic (if the model explicitly says low-confidence phrases)
        low_confidence_phrases = [
            "i don't know", "i am not sure", "i'm not sure", "i cannot help with",
            "can't help", "i might be wrong", "please contact support", "escalate"
        ]
        lowered = reply.lower()
        if any(p in lowered for p in low_confidence_phrases) or len(reply.strip()) < 10:
            return "I'm escalating this issue to a human support agent. Please wait while I connect you."

        return reply

    except Exception as e:
        print("Gemini error:", e)
        time.sleep(0.5)
        return "I'm having trouble reaching the support system right now. Please try again later."



def summarize_session(messages_text, max_output_tokens=220, temperature=0.1):
    system = (
        "You are Clara, an assistant that summarizes support conversations. "
        "Produce a compact one-line summary, then give 3 concise next actions as bullets."
    )
    prompt = (
        f"{system}\n\nConversation:\n{messages_text}\n\n"
        "Output format:\nSUMMARY:\n- <one line summary>\nNEXT_ACTIONS:\n- action1\n- action2\n- action3"
    )
    try:
        reply = _call_generate_content(prompt, temperature=temperature, max_output_tokens=max_output_tokens)
        reply = reply.strip()

        summary = ""
        actions = []
        low = reply.lower()
        if "summary:" in low:
            idx = low.find("summary:")
            after_summary = reply[idx + len("summary:"):].strip()
            if "next_actions:" in after_summary.lower():
                parts = after_summary.split("next_actions:", 1)
                summary_part = parts[0].strip()
                actions_part = parts[1].strip()
            else:
                lines = after_summary.splitlines()
                summary_part = lines[0] if lines else after_summary
                actions_part = "\n".join(lines[1:4]) if len(lines) > 1 else ""
        else:
            lines = reply.splitlines()
            summary_part = lines[0] if lines else ""
            actions_part = "\n".join(lines[1:4]) if len(lines) > 1 else ""

        summary = summary_part.strip().lstrip("-").strip()
        for line in actions_part.splitlines():
            l = line.strip().lstrip("-").strip()
            if l:
                actions.append(l)
        actions = actions[:3]

        return {"summary": summary or "No summary available.", "next_actions": actions}
    except Exception as e:
        print("Gemini summarize error:", e)
        return {"summary": "Unable to summarize at this time.", "next_actions": []}
