"""
config.py - Central configuration settings for the Sentinel backend.
"""
import os

RETENTION_MINUTES = int(os.getenv("RETENTION_MINUTES", "15"))
