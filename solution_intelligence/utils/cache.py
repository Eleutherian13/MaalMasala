import sqlite3
import hashlib
import json
import logging
from config import CACHE_DB_PATH

logger = logging.getLogger(__name__)

class LLMCache:
    def __init__(self, db_path=CACHE_DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                prompt_hash TEXT PRIMARY KEY,
                prompt TEXT,
                response TEXT,
                model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def get(self, prompt: str, model: str) -> str | None:
        h = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()
        row = self.conn.execute(
            "SELECT response FROM cache WHERE prompt_hash=?", (h,)
        ).fetchone()
        return row[0] if row else None

    def set(self, prompt: str, model: str, response: str):
        h = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()
        self.conn.execute(
            "INSERT OR REPLACE INTO cache VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
            (h, prompt, response, model)
        )
        self.conn.commit()
