"""Agentic admin assistant for TinkeraRobot.

This package adds a natural-language admin command layer on top of the existing
moderation/services architecture. It never touches Telegram or the database
directly from AI output: the AI only produces a validated, allowlisted decision
that is then executed through the project's existing services.
"""
