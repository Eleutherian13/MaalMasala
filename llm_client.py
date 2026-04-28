import logging
import sqlite3
import json
import requests
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OllamaClient:
    """
    Handles LLM interactions via Ollama local API with SQLite caching and robust JSON extraction.
    """
    def __init__(self, db_path="pipeline_cache.db", model_name="mistral", base_url="http://localhost:11434"):
        self.db_path = db_path
        self.model_name = model_name
        self.base_url = base_url
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    prompt TEXT PRIMARY KEY,
                    response TEXT,
                    is_json INTEGER
                )
            """)
            conn.commit()

    def get_completion(self, prompt: str, expect_json: bool = False, max_retries: int = 3) -> str | dict:
        """
        Gets a completion from the local Mistral model.
        Includes caching logic and JSON validation/retry.
        """
        # Check cache
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT response FROM llm_cache WHERE prompt = ?", (prompt,))
            row = cursor.fetchone()
            if row:
                logger.debug("Cache hit for prompt.")
                response_text = row[0]
                if expect_json:
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.warning("Cached response was expected to be JSON but failed parsing. Re-running.")
                else:
                    return response_text

        # If cache miss or JSON parse failed, run generation
        for attempt in range(max_retries):
            current_prompt = prompt
            if expect_json and attempt > 0:
                current_prompt += "\n\nCRITICAL: You failed to provide VALID JSON on the last attempt. You MUST return ONLY valid, parseable JSON text without Markdown wrapping."

            payload = {
                "model": self.model_name,
                "prompt": current_prompt,
                "stream": False
            }
            if expect_json:
                 payload["format"] = "json"

            try:
                response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
                response.raise_for_status()
                response_text = response.json().get("response", "")

                if expect_json:
                    try:
                        parsed_json = json.loads(response_text)
                        # Cache successful JSON
                        with sqlite3.connect(self.db_path) as conn:
                            conn.execute("INSERT OR REPLACE INTO llm_cache (prompt, response, is_json) VALUES (?, ?, ?)", 
                                         (prompt, json.dumps(parsed_json), 1))
                            conn.commit()
                        return parsed_json
                    except json.JSONDecodeError:
                        logger.warning(f"Attempt {attempt + 1}: Failed to parse JSON from response. Retrying...")
                        continue
                else:
                    # Cache normal text
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("INSERT OR REPLACE INTO llm_cache (prompt, response, is_json) VALUES (?, ?, ?)", 
                                     (prompt, response_text, 0))
                        conn.commit()
                    return response_text

            except requests.exceptions.RequestException as e:
                logger.error(f"Ollama API request failed: {e}")
                time.sleep(2)

        raise ValueError("Failed to obtain valid response from LLM after max retries.")
