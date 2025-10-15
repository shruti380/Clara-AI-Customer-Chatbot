# Clara — AI Customer Support Bot (Gemini)

Clara is a demo AI customer support chatbot built with Flask + SQLite, using Google Gemini as the LLM.

## Features

- FAQ-first fallback (fuzzy match)
- Gemini-powered responses when FAQs don't match
- Conversation context (last messages) is sent to Gemini
- Escalation heuristic: Clara escalates to human support if uncertain
- Summarization of sessions & suggested next actions
- Simulated escalation that creates a ticket record
- Admin endpoint to export sessions as CSV

## Requirements

- Python 3.9+
- A Gemini API key

## Setup

1. Clone repo
2. Create virtual environment & install:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
