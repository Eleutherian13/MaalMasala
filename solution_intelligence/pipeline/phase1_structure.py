import os
import json
import logging
import hashlib
import re
from typing import Optional
from tqdm import tqdm
from config import BATCH_SIZE
from utils.llm import ask_llm
from utils.schema import SolutionExtraction
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# Dedicated loggers
success_logger = logging.getLogger('extraction_success')
success_logger.setLevel(logging.INFO)
success_logger.addHandler(logging.FileHandler('extraction_success.log'))

failure_logger = logging.getLogger('extraction_failure')
failure_logger.setLevel(logging.ERROR)
failure_logger.addHandler(logging.FileHandler('extraction_failure.log'))

CACHE_DIR = "cache/extraction"
os.makedirs(CACHE_DIR, exist_ok=True)

def extract_solution_features(solution_id: str, team_name: str, solution_text: str, problem_text: str) -> Optional[SolutionExtraction]:
    """
    Transforms raw solution text to SolutionExtraction schema.
    Returns the parsed Pydantic object or None if validation/extraction fails.
    """
    cache_key = hashlib.sha256(solution_text.encode('utf-8')).hexdigest()
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    
    # Cache check
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Add solution metadata from function parameters
            data['solution_id'] = solution_id
            data['team_name'] = team_name
            return SolutionExtraction(**data)
        except Exception as e:
            logger.warning(f"Cache read failed for {cache_key}: {e}")

    prompt = f"""SYSTEM:
You are a strict information extraction engine. You NEVER infer missing data.
If a piece of information is missing, output a null or empty list as appropriate.
Return ONLY valid JSON strictly matching the schema below. No explanation, no markdown blocks around the JSON.

JSON Schema:
{{
  "problem_id": "string",
  "summary": "string (5-300 chars)",
  "approach_type": "string (must be one of: 'rule-based', 'ml', 'dl', 'system', 'hybrid')",
  "tech_stack": ["string"],
  "key_steps": ["string"],
  "optimization_claims": ["string"],
  "constraints_addressed": ["string"],
  "missing_components": ["string"]
}}

USER:
Problem Statement:
{problem_text}

Solution Text:
{solution_text}
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response_text = ask_llm(prompt, expect_json=True, force_rerun=True)
            
            # Handle both dict and string responses
            if isinstance(response_text, dict):
                parsed_json = response_text
            else:
                # JSON repair/parse
                try:
                    parsed_json = json.loads(response_text)
                except json.JSONDecodeError:
                    # Regex cleanup for common JSON issues (e.g. trailing commas, markdown blocks)
                    cleaned = re.sub(r'```json\s*|\s*```', '', response_text)
                    cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
                    parsed_json = json.loads(cleaned)

            # Add solution metadata
            parsed_json['solution_id'] = solution_id
            parsed_json['team_name'] = team_name
            
            # Output validation
            extraction = SolutionExtraction(**parsed_json)
            
            # Save to cache
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(extraction.model_dump_json())
                
            success_logger.info(f"Successfully extracted features for solution {solution_id}")
            return extraction
            
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                failure_logger.error(f"Failed to extract features for {solution_id} after {max_retries} attempts. Error: {e}")
                return None
                
    return None

def phase1_structure(problems_dict: dict, solutions_by_problem: dict, problem_id: str, force_rerun: bool, output_dir: str):
    structured_dir = os.path.join(output_dir, "structured")
    os.makedirs(structured_dir, exist_ok=True)
    logger.info("Phase 1: Setting up structured extraction...")

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())
    total_processed = 0
    total_failed = 0

    for pid in tqdm(pids_to_process, desc="Processing Problems"):
        if pid not in problems_dict:
            logger.warning(f"Problem ID {pid} not found in inputs. Skipping.")
            continue
            
        problem = problems_dict[pid]
        solutions = solutions_by_problem.get(pid, [])
        
        prob_dir = os.path.join(structured_dir, pid)
        os.makedirs(prob_dir, exist_ok=True)
        
        if not solutions:
            continue
            
        problem_text = f"Title: {problem['title']}\nDescription: {problem['description']}"
        if 'constraints' in problem:
            problem_text += f"\nConstraints: {problem['constraints']}"

        for sol in solutions:
            sid = sol['solution_id']
            team = sol.get('team_name', 'UNKNOWN')
            out_file = os.path.join(prob_dir, f"{sid}.json")
            
            if not force_rerun and os.path.exists(out_file):
                continue
                
            extraction = extract_solution_features(sid, team, sol['solution_text'], problem_text)
            
            if extraction is None:
                total_failed += 1
                logger.error(f"Skipping {sid} due to extraction failure.")
                continue
                
            # If extraction is successful, ensure problem_id matches
            if extraction.problem_id != pid:
                extraction.problem_id = pid
                
            with open(out_file, 'w', encoding='utf-8') as f:
                f.write(extraction.model_dump_json(indent=2))
            
            total_processed += 1

        # Generate Problem Summary
        summary_file = os.path.join(prob_dir, "_summary.json")
        all_structured = []
        for sol in solutions:
            sid = sol['solution_id']
            out_file = os.path.join(prob_dir, f"{sid}.json")
            if os.path.exists(out_file):
                with open(out_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['solution_id'] = sid # ensure we keep track 
                    all_structured.append(data)
                    
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(all_structured, f, indent=2)

    logger.info(f"Phase 1 Completed. Structured {total_processed} solutions. Failed {total_failed}.")
