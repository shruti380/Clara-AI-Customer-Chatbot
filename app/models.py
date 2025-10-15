from .database import db
from datetime import datetime

class SupportSession(db.Model):
    __tablename__ = "support_session"
    id = db.Column(db.Integer, primary_key=True)
    user_label = db.Column(db.String(100), default="guest")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    messages = db.relationship("Message", backref="session", lazy="dynamic")
    tickets = db.relationship("Ticket", backref="session", lazy="dynamic")

class Message(db.Model):
    __tablename__ = "message"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("support_session.id"))
    sender = db.Column(db.String(20))  # "user" or "clara"
    text = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Ticket(db.Model):
    __tablename__ = "ticket"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("support_session.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default="open")
    summary = db.Column(db.Text)
    assignee = db.Column(db.String(100), nullable=True)
