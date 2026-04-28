import os
import json
import requests
from config import OLLAMA_BASE_URL, CACHE_DB_PATH
from utils.schema import validate_inputs
from utils.cache import LLMCache

def preflight_check(problems_path: str, solutions_path: str, output_dir: str):
    # 1. Ollama is reachable
    try:
        requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
    except requests.exceptions.RequestException:
        raise ConnectionError(f"Ollama is not reachable at {OLLAMA_BASE_URL}")

    # 2. Mistral model is pulled
    tags = requests.get(f"{OLLAMA_BASE_URL}/api/tags").json()
    assert any("mistral" in m["name"] for m in tags.get("models", [])), "Mistral model not found in Ollama"
    
    # 3. Input files exist and parse
    validate_inputs(problems_path, solutions_path)
    
    # 4. Output directories exist (create if not)
    for d in ["structured", "embeddings", "clusters", "scores", "patterns", "synthesis", "reports"]:
        os.makedirs(f"{output_dir}/{d}", exist_ok=True)
        
    # 5. SQLite cache is writable
    LLMCache(CACHE_DB_PATH).set("_test", "mistral", "ok")

def validate_phase1_output(problem_id: str, output_dir: str):
    path = f"{output_dir}/structured/{problem_id}/_summary.json"
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    required = {"solution_id", "core_idea", "approach", "novelty_score", "quality_score", "summary"}
    for item in data:
        if item.get("parse_error"):
            continue
        missing = required - item.keys()
        assert not missing, f"Missing keys: {missing}"
        assert 1 <= item["novelty_score"] <= 10
        assert 1 <= item["quality_score"] <= 10
    return True