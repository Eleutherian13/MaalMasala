import os
import json
import logging
from tqdm import tqdm
from config import BATCH_SIZE
from utils.llm import ask_llm

logger = logging.getLogger(__name__)

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
            logger.info(f"No solutions found for problem {pid}. Skipping.")
            continue
            
        problem_text = f"Title: {problem['title']}\nDescription: {problem['description']}"
        if 'constraints' in problem:
            problem_text += f"\nConstraints: {problem['constraints']}"
            
        # 1.1 Group and filter by cache
        solutions_to_process = []
        for sol in solutions:
            sid = sol['solution_id']
            out_file = os.path.join(prob_dir, f"{sid}.json")
            if not force_rerun and os.path.exists(out_file):
                logger.debug(f"Skipping {sid}, already structured.")
                continue
            solutions_to_process.append(sol)

        # 1.2 Batching and LLM call
        for i in range(0, len(solutions_to_process), BATCH_SIZE):
            batch = solutions_to_process[i:i + BATCH_SIZE]
            n = len(batch)
            
            # Serialize batch payload
            batch_json = json.dumps([{"solution_id": s["solution_id"], "solution_text": s["solution_text"]} for s in batch], indent=2)

            prompt = f"""SYSTEM:
You are a structured data extraction engine. You receive batches of competition solutions. For each solution, extract structured information and return ONLY a valid JSON array. No explanation, no markdown, no preamble. Return raw JSON only.

USER:
Problem Statement:
{problem_text}

Extract structured data for each of the following {n} solutions. Return a JSON array of exactly {n} objects in the same order as input.

Each object must have these exact keys:
- "solution_id": string (copy from input)
- "core_idea": string (1-2 sentences: the central concept)
- "approach": string (method or algorithm used)
- "tools_and_techniques": array of strings
- "strengths": array of strings (max 3)
- "weaknesses": array of strings (max 3)
- "novelty_score": integer 1-10 (10=highly original, 1=common/basic)
- "quality_score": integer 1-10 (10=excellent execution, 1=poor)
- "summary": string (3-4 sentences synthesizing the above)

Solutions:
{batch_json}"""

            try:
                responses = ask_llm(prompt, expect_json=True, force_rerun=force_rerun)
                if not isinstance(responses, list):
                    raise ValueError(f"Expected a JSON array, got {type(responses).__name__}")
            except Exception as e:
                logger.error(f"Batch LLM call failed entirely: {e}")
                responses = []  # Empty list triggers per-solution failover

            # 1.3 Validation & 1.5 Sentinel object extraction
            # Map LLM responses by ID
            response_map = {r["solution_id"]: r for r in responses if isinstance(r, dict) and "solution_id" in r}

            for idx, sol in enumerate(batch):
                sid = sol["solution_id"]
                raw_extracted = response_map.get(sid)
                
                # Positional fallback if ID was lost or mapped wrong
                if not raw_extracted and len(responses) == n and isinstance(responses[idx], dict):
                    raw_extracted = responses[idx]
                    raw_extracted["solution_id"] = sid

                extracted = None
                if raw_extracted:
                    # 1.3 validate keys and score types
                    required_keys = {"solution_id", "core_idea", "approach", "tools_and_techniques", "strengths", "weaknesses", "novelty_score", "quality_score", "summary"}
                    missing_keys = required_keys - set(raw_extracted.keys())
                    n_score = raw_extracted.get("novelty_score")
                    q_score = raw_extracted.get("quality_score")
                    
                    if missing_keys:
                        extracted = {"solution_id": sid, "parse_error": True, "error_details": f"Missing keys: {missing_keys}"}
                    elif not isinstance(n_score, int) or not (1 <= n_score <= 10):
                        extracted = {"solution_id": sid, "parse_error": True, "error_details": f"Invalid novelty_score: {n_score}"}
                    elif not isinstance(q_score, int) or not (1 <= q_score <= 10):
                        extracted = {"solution_id": sid, "parse_error": True, "error_details": f"Invalid quality_score: {q_score}"}
                    else:
                        extracted = raw_extracted

                if not extracted:
                    extracted = {"solution_id": sid, "parse_error": True, "error_details": "Missing from LLM response or completely invalid."}

                if extracted.get("parse_error"):
                    total_failed += 1
                else:
                    total_processed += 1

                # 1.6 Save individual structured output
                out_file = os.path.join(prob_dir, f"{sid}.json")
                with open(out_file, 'w', encoding='utf-8') as f:
                    json.dump(extracted, f, indent=2)

        # 1.7 Generate Problem Summary
        summary_file = os.path.join(prob_dir, "_summary.json")
        all_structured = []
        for sol in solutions:
            sid = sol['solution_id']
            out_file = os.path.join(prob_dir, f"{sid}.json")
            if os.path.exists(out_file):
                with open(out_file, 'r', encoding='utf-8') as f:
                    all_structured.append(json.load(f))
                    
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(all_structured, f, indent=2)

    logger.info(f"Phase 1 Completed. Structured {total_processed} solutions. Sentinels/Failed {total_failed}.")
