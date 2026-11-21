"""Entry point for the production server:  gunicorn wsgi:app"""
from app import app

__all__ = ["app"]
