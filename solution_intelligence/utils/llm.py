import requests
import json
import logging
import time
from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, LLM_MAX_RETRIES, CACHE_DB_PATH
from utils.cache import LLMCache

logger = logging.getLogger(__name__)

def call(prompt: str, system: str = "", force: bool = False) -> str:
    cache = LLMCache(CACHE_DB_PATH)
    full_prompt = f"SYSTEM:\n{system}\n\nUSER:\n{prompt}" if system else prompt
    
    if not force:
        cached = cache.get(full_prompt, OLLAMA_MODEL)
        if cached:
            logger.debug("[CACHE HIT]")
            return cached
    
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
                timeout=OLLAMA_TIMEOUT
            )
            r.raise_for_status()
            response = r.json()["response"]
            cache.set(full_prompt, OLLAMA_MODEL, response)
            return response
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt == LLM_MAX_RETRIES:
                raise

def ask_llm(prompt: str, system: str = "", expect_json: bool = False, force_rerun: bool = False) -> str | dict | list:
    """Wrapper to maintain backwards compatibility with existing pipelines while using new methods."""
    if not expect_json:
        return call(prompt, system, force=force_rerun)
        
    """Call LLM and parse JSON. Retry with correction prompt on failure."""
    current_prompt = prompt
    for attempt in range(LLM_MAX_RETRIES):
        raw = call(current_prompt, system, force=force_rerun if attempt == 0 else True)
        try:
            cleaned = raw.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"JSON formatting failed on attempt {attempt+1}. Retrying with correction.")
            current_prompt = f"Your response was not valid JSON. Return ONLY JSON, no markdown text:\n{raw}"
            
    raise ValueError("LLM failed to return valid JSON after retries")
