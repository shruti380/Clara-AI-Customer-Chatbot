from flask import Blueprint, render_template, request, jsonify, send_file
from .models import SupportSession, Message, Ticket
from .database import db
from .utils import load_faqs, find_best_faq_match, replace_placeholders_in_reply
from .llm_engine import generate_response, summarize_session

import csv
import io
import re

main = Blueprint("main", __name__)

# load faqs once
faqs = load_faqs()


@main.route("/")
def index():
    return render_template("chat.html")


@main.route("/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    user_query = (data.get("message") or "").strip()
    session_id = data.get("session_id")

    if not user_query:
        return jsonify({"error": "Empty message"}), 400

    # get or create session
    if session_id:
        session = SupportSession.query.get(session_id)
        if session is None:
            session = SupportSession(user_label="guest")
            db.session.add(session)
            db.session.commit()
    else:
        session = SupportSession(user_label="guest")
        db.session.add(session)
        db.session.commit()

    # Save user message
    user_msg = Message(session_id=session.id, sender="user", text=user_query)
    db.session.add(user_msg)
    db.session.commit()

    # -------------------
    # Quick follow-up / intent handling (before general FAQ/LLM path)
    # -------------------
    # Load fresh FAQs in case they changed on disk
    faqs_all = load_faqs()

    # Fetch last Clara bot message to understand context
    last_bot = (
        Message.query.filter_by(session_id=session.id, sender="clara")
        .order_by(Message.timestamp.desc())
        .first()
    )
    last_bot_text = last_bot.text.lower() if last_bot and last_bot.text else ""

    # --- Explicit check: user asked about cloud offerings (exact intent) ---
    uq_lower = user_query.lower()
    if "cloud offering" in uq_lower or "cloud offerings" in uq_lower or ("tell me about" in uq_lower and "cloud" in uq_lower):
        offering = next((f for f in faqs_all if f.get("question", "").lower().startswith("what cloud")), None)
        if offering:
            reply = offering.get("answer")
            try:
                reply = replace_placeholders_in_reply(reply, faqs_all)
            except Exception:
                pass
            bot_msg = Message(session_id=session.id, sender="clara", text=reply)
            db.session.add(bot_msg)
            db.session.commit()
            return jsonify({"reply": reply, "session_id": session.id})

    # 1) If user said "yes" (simple confirmation) and last Clara asked about cloud offerings,
    #    return the offerings FAQ directly. Avoid repeating the same paragraph on consecutive 'yes'.
    short_yes = {"yes", "y", "sure", "ok", "okay"}
    if user_query.lower() in short_yes and "would you like to know about our specific cloud" in last_bot_text:
        offering = next(
            (f for f in faqs_all if f.get("question", "").lower().startswith("what cloud offerings")), None
        )
        if offering:
            # Look up the previous user message to detect repeated "yes"
            prev_user = (
                Message.query.filter_by(session_id=session.id, sender="user")
                .order_by(Message.timestamp.desc())
                .offset(1)
                .first()
            )
            prev_user_text = prev_user.text.lower() if prev_user and prev_user.text else ""

            # If this is the second consecutive "yes", prompt user to choose a service instead of repeating.
            if prev_user_text in short_yes:
                selection_prompt = (
                    "I listed several cloud solutions. Please choose which you'd like to explore:\n\n"
                    "1. Managed Cloud Hosting\n"
                    "2. Virtual Private Servers (VPS)\n"
                    "3. Public Cloud Services\n\n"
                    'Reply with "service 1", "service 2", or "service 3" to get details.'
                )
                bot_msg = Message(session_id=session.id, sender="clara", text=selection_prompt)
                db.session.add(bot_msg)
                db.session.commit()
                return jsonify({"reply": selection_prompt, "session_id": session.id})
            else:
                # First "yes" -> return the full offerings list
                reply = offering.get("answer")
                try:
                    reply = replace_placeholders_in_reply(reply, faqs_all)
                except Exception:
                    pass

                bot_msg = Message(session_id=session.id, sender="clara", text=reply)
                db.session.add(bot_msg)
                db.session.commit()
                return jsonify({"reply": reply, "session_id": session.id})

    # 2) Handle "service N" patterns like "service 1", "service 2"
    lowered = user_query.lower()
    if lowered.startswith("service"):
        m = re.match(r"service\s*(\d+)", lowered)
        if m:
            idx = int(m.group(1))
            mapping = {
                1: "Tell me about Managed Cloud Hosting",
                2: "Tell me about Virtual Private Servers (VPS)",
                3: "Tell me about Public Cloud Services"
            }
            target_q = mapping.get(idx)
            if target_q:
                faq_match = next((f for f in faqs_all if f.get("question","").lower() == target_q.lower()), None)
                if faq_match:
                    reply = faq_match.get("answer")
                    try:
                        reply = replace_placeholders_in_reply(reply, faqs_all)
                    except Exception:
                        pass
                    bot_msg = Message(session_id=session.id, sender="clara", text=reply)
                    db.session.add(bot_msg)
                    db.session.commit()
                    return jsonify({"reply": reply, "session_id": session.id})

    # 3) Keyword mapping for quick natural replies
    quick_keyword_map = {
        "managed": "Tell me about Managed Cloud Hosting",
        "managed hosting": "Tell me about Managed Cloud Hosting",
        "managed cloud": "Tell me about Managed Cloud Hosting",
        "vps": "Tell me about Virtual Private Servers (VPS)",
        "virtual private server": "Tell me about Virtual Private Servers (VPS)",
        "public": "Tell me about Public Cloud Services",
        "public cloud": "Tell me about Public Cloud Services",
        "cloud offering": "What cloud offerings do you have",
        "cloud offerings": "What cloud offerings do you have"
    }
    for kw, target_q in quick_keyword_map.items():
        if kw in lowered:
            faq_match = next((f for f in faqs_all if f.get("question","").lower() == target_q.lower()), None)
            if faq_match:
                reply = faq_match.get("answer")
                try:
                    reply = replace_placeholders_in_reply(reply, faqs_all)
                except Exception:
                    pass
                bot_msg = Message(session_id=session.id, sender="clara", text=reply)
                db.session.add(bot_msg)
                db.session.commit()
                return jsonify({"reply": reply, "session_id": session.id})

    # -------------------
    # End quick intent handling
    # -------------------

    # First try FAQ exact/fuzzy match
    faq_match = find_best_faq_match(user_query, faqs_all)
    if faq_match:
        reply = faq_match.get("answer", "Sorry, I don't have an answer for that.")
    else:
        # Build context from last N messages for LLM
        recent = Message.query.filter_by(session_id=session.id).order_by(Message.timestamp.asc()).all()
        context_text = "\n".join([f"{m.sender}: {m.text}" for m in recent[-10:]])  # last 10 messages
        reply = generate_response(context_text, user_query)

    # Replace placeholders (e.g., [Service 1], Service 1) using KB/FAQs before saving/display
    try:
        reply = replace_placeholders_in_reply(reply, faqs_all)
    except Exception:
        # If replacement helper fails, keep original reply
        pass

    # Save Clara's reply
    bot_msg = Message(session_id=session.id, sender="clara", text=reply)
    db.session.add(bot_msg)
    db.session.commit()

    return jsonify({"reply": reply, "session_id": session.id})


@main.route("/summarize", methods=["POST"])
def summarize():
    """
    POST JSON: { session_id: <id> }
    Returns JSON: { summary, next_actions }
    """
    data = request.get_json() or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    session = SupportSession.query.get(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404

    messages = Message.query.filter_by(session_id=session.id).order_by(Message.timestamp.asc()).all()
    messages_text = "\n".join([f"{m.sender}: {m.text}" for m in messages])
    result = summarize_session(messages_text)
    return jsonify(result)


@main.route("/escalate", methods=["POST"])
def escalate():
    """
    Simulate creating a human ticket.
    POST JSON: { session_id: <id>, summary: optional }
    Returns JSON: { ticket_id, status }
    """
    data = request.get_json() or {}
    session_id = data.get("session_id")
    summary = data.get("summary")

    session = SupportSession.query.get(session_id) if session_id else None
    if session_id and session is None:
        return jsonify({"error": "session not found"}), 404

    # If no summary provided, auto-summarize
    if not summary and session is not None:
        messages = Message.query.filter_by(session_id=session.id).order_by(Message.timestamp.asc()).all()
        messages_text = "\n".join([f"{m.sender}: {m.text}" for m in messages])
        summary_obj = summarize_session(messages_text)
        summary = summary_obj.get("summary", "")

    ticket = Ticket(session_id=session.id if session else None, summary=summary, status="open")
    db.session.add(ticket)
    db.session.commit()

    # In a real system, here you'd notify a human (email/Slack). We just return the ticket info.
    return jsonify({"ticket_id": ticket.id, "status": ticket.status, "summary": ticket.summary})


@main.route("/admin/sessions.csv", methods=["GET"])
def export_sessions_csv():
    """
    Export all sessions and messages as CSV (admin endpoint).
    """
    # Build CSV in-memory
    proxy = io.StringIO()
    writer = csv.writer(proxy)
    writer.writerow(["session_id", "user_label", "created_at", "message_id", "sender", "text", "timestamp"])

    sessions = SupportSession.query.order_by(SupportSession.created_at.asc()).all()
    for s in sessions:
        messages = Message.query.filter_by(session_id=s.id).order_by(Message.timestamp.asc()).all()
        if not messages:
            writer.writerow([s.id, s.user_label, s.created_at.isoformat(), "", "", "", ""])
        else:
            for m in messages:
                writer.writerow([s.id, s.user_label, s.created_at.isoformat(), m.id, m.sender, m.text.replace("\n", " "), m.timestamp.isoformat()])

    # Create response
    mem = io.BytesIO()
    mem.write(proxy.getvalue().encode("utf-8"))
    mem.seek(0)
    proxy.close()
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="clara_sessions.csv")
