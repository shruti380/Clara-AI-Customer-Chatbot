import json
import difflib
import os

FAQ_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "faqs", "faqs.json")

def load_faqs():
    try:
        with open(FAQ_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def find_best_faq_match(user_query, faqs, threshold=0.65):
    """
    Returns matching faq dict or None.
    Uses difflib.get_close_matches on faq questions (simple fuzzy match).
    """
    if not faqs:
        return None
    questions = [faq.get("question", "") for faq in faqs]
    best = difflib.get_close_matches(user_query, questions, n=1, cutoff=threshold)
    if best:
        for faq in faqs:
            if faq.get("question") == best[0]:
                return faq
    return None
import re

def replace_placeholders_in_reply(reply: str, faqs: list) -> str:
    """
    Conservative placeholder replacement:
     - Replaces [Service N] or inline "Service N" with FAQ answers if available.
     - Avoids duplicating content if the replacement is already present.
     - Removes consecutive duplicate sentences (simple dedup).
    """
    if not reply or not faqs:
        return reply

    # Build mapping keys -> answers
    mapping = {}
    for f in faqs:
        q = (f.get("question") or "").lower()
        a = f.get("answer") or ""
        if "managed cloud hosting" in q or "managed cloud" in q:
            mapping["service 1"] = a
            mapping["managed cloud hosting"] = a
        if "virtual private servers" in q or "vps" in q:
            mapping["service 2"] = a
            mapping["vps"] = a
        if "public cloud" in q or "public cloud services" in q:
            mapping["service 3"] = a
            mapping["public cloud services"] = a
        if q.startswith("what cloud"):
            mapping["cloud_offerings_list"] = a

    out = reply

    # Helper to safe-insert: only insert if the replacement text isn't already present
    def safe_insert_replacement(text, key, replacement):
        # If replacement already exists verbatim, skip
        if replacement.strip() and replacement.strip() in text:
            return text
        # Replace bracketed placeholders [Key]
        pattern = re.compile(r"\[" + re.escape(key) + r"\]", flags=re.IGNORECASE)
        new_text = pattern.sub(replacement, text)
        if new_text != text:
            return new_text
        # Replace standalone words (word boundaries) but only if replacement not already present
        pattern2 = re.compile(rf"\b{re.escape(key)}\b", flags=re.IGNORECASE)
        new_text2 = pattern2.sub(replacement, text)
        return new_text2

    # Replace explicit bracketed placeholders first using mapping keys
    for key, val in mapping.items():
        out = safe_insert_replacement(out, key, val)

    # If reply mentions "these include" or "these include:" and offerings exist, ensure list present once
    if ("these include" in out.lower() or "these include:" in out.lower()) and mapping.get("cloud_offerings_list"):
        if mapping["cloud_offerings_list"] not in out:
            out = out + "\n\n" + mapping["cloud_offerings_list"]

    # Deduplicate consecutive duplicate sentences (simple heuristic)
    # Split into sentences by punctuation, remove immediate repeats
    sentences = re.split(r'(?<=[.!?])\s+', out.strip())
    deduped = []
    prev = None
    for s in sentences:
        s_stripped = s.strip()
        if not s_stripped:
            continue
        if prev and s_stripped == prev:
            # skip duplicate
            continue
        deduped.append(s_stripped)
        prev = s_stripped
    out = " ".join(deduped) if deduped else out

    return out


    # Replace explicit bracketed placeholders like [Service 1]
    import re
    def _replace_bracket(match):
        key = match.group(1).strip().lower()
        # normalize common forms
        key_norm = key.replace(" ", " ").lower()
        if key_norm in mapping:
            return mapping[key_norm]
        # if 'service' word only, return the offerings list
        if "service" in key_norm and "1" not in key_norm and "2" not in key_norm and "3" not in key_norm:
            return mapping.get("cloud_offerings_list", match.group(0))
        return match.group(0)  # no change

    out = re.sub(r"\[([^\]]+)\]", _replace_bracket, out)

    # Replace inline mentions like "Service 1" / "service 1" if they are present as text blocks
    for k, v in mapping.items():
        # only replace standalone occurrences to avoid accidental replacement
        out = re.sub(rf"\b{re.escape(k)}\b", v, out, flags=re.IGNORECASE)

    # If the reply mentions "these include" or similar and we have the offerings list, ensure it uses that list
    if ("these include" in out.lower() or "these include:" in out.lower()) and "cloud_offerings_list" in mapping:
        # best effort: append offerings if not already present
        if mapping["cloud_offerings_list"] not in out:
            out = out + "\n\n" + mapping["cloud_offerings_list"]

    return out
