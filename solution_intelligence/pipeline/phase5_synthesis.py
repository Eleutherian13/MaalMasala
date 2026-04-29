import os
import json
import logging
from tqdm import tqdm
from utils.llm import ask_llm
from pipeline.phase3_score import score_solution
from utils.schema import SolutionExtraction, SolutionScores, FinalEvaluation

logger = logging.getLogger(__name__)

def get_high_score_inputs(structured_dir: str, pid: str) -> list:
    """Extracts valid SolutionExtraction objects with FinalEvaluation score > 70."""
    high_score_solutions = []
    
    summary_file = os.path.join(structured_dir, pid, "_summary.json")
    if not os.path.exists(summary_file):
        return []
        
    with open(summary_file, 'r', encoding='utf-8') as f:
        structured_data = json.load(f)
        
    for s in structured_data:
        if s.get("parse_error"):
            continue
            
        try:
            extraction = SolutionExtraction(**s)
            evaluation = score_solution(extraction)
            
            if evaluation and evaluation.final_score > 70.0:
                high_score_solutions.append({
                    "score": evaluation.final_score,
                    "features": extraction.model_dump()
                })
        except Exception:
            continue
            
    # Sort descending by score
    high_score_solutions.sort(key=lambda x: x["score"], reverse=True)
    return high_score_solutions

def phase5_synthesis(problems_dict: dict, problem_id: str, force_rerun: bool, output_dir: str):
    scores_dir = os.path.join(output_dir, "scores")
    patterns_dir = os.path.join(output_dir, "patterns")
    structured_dir = os.path.join(output_dir, "structured")
    synthesis_dir = os.path.join(output_dir, "synthesis")
    os.makedirs(synthesis_dir, exist_ok=True)

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())

    logger.info("Phase 5: Synthesizing Optimal Solutions (High Score Strict Only)...")

    for pid in tqdm(pids_to_process, desc="Processing Synthesis"):
        problem = problems_dict.get(pid)
        if not problem:
            continue
            
        scores_file = os.path.join(scores_dir, f"{pid}.json")
        patterns_file = os.path.join(patterns_dir, f"{pid}.json")

        if not os.path.exists(scores_file) or not os.path.exists(patterns_file):
            logger.warning(f"Missing required Phase 3/4 outputs for {pid}. Skipping Synthesis.")
            continue

        with open(scores_file, 'r', encoding='utf-8') as f:
            scores_data = json.load(f)

        with open(patterns_file, 'r', encoding='utf-8') as f:
            patterns_data = json.load(f)
            
        ranked_clusters = scores_data.get("ranked_clusters", [])
        winning_patterns = patterns_data.get("winning_patterns", [])
        tradeoffs = patterns_data.get("tradeoffs", [])
        
        # 1. Fetch Top K solutions (score > 70)
        high_score_solutions = get_high_score_inputs(structured_dir, pid)
        top_k_solutions = high_score_solutions[:5] # Bound to top 5 to prevent context limits
        
        # 1b. Fetch ELITE Clusters metadata
        elite_clusters = [c for c in ranked_clusters if c.get("tier") == "ELITE"]
        
        if not top_k_solutions and not elite_clusters and not winning_patterns:
            logger.warning(f"No high-score inputs or ELITE clusters for {pid}. Cannot synthesize strictly.")
            continue

        json_top_k = json.dumps(top_k_solutions, indent=2)
        json_elite_clusters = json.dumps(elite_clusters, indent=2)
        json_winning_patterns = json.dumps(winning_patterns, indent=2)
        json_tradeoffs = json.dumps(tradeoffs, indent=2)

        problem_title = problem['title']
        problem_description = problem['description']
        
        # Format constraints if available
        constraints = problem.get('constraints', "")
        constraints_str = f"Constraints:\n{constraints}" if constraints else ""

        # LLM Prompt MUST force structured output, step-by-step pipeline, and explicit reasoning
        synthesis_prompt = f"""SYSTEM:
You are a world-class solution architect combining verified highest-scoring approaches.
You MUST output ONLY a valid JSON object strictly matching the exact requested schema.
You MUST provide explicit, step-by-step pipeline details and optimization reasoning.
Do NOT use vague language like 'robust approach' or 'various tools'. Be explicit.
Do NOT skip any steps in the pipeline.

JSON SCHEMA:
{{
  "architecture": "string (Detailed macro-architecture of the synthesized solution)",
  "tech_stack": ["string (Specific tool/framework)"],
  "pipeline": [
    {{
      "step": "integer",
      "name": "string",
      "action": "string (Explicit technical action)",
      "validation": "string (How this step is verified)"
    }}
  ],
  "optimizations": [
    {{
      "target": "string",
      "mechanism": "string",
      "impact": "string"
    }}
  ],
  "tradeoffs_resolved": [
    {{
      "conflict": "string",
      "chosen_path": "string",
      "justification": "string"
    }}
  ],
  "justification": "string (Why this synthesized approach yields the absolute highest score based on inputs)"
}}

USER:
Problem: {problem_title}
{problem_description}
{constraints_str}

INPUT 1: TOP 5 HIGH-SCORING INDIVIDUAL SOLUTIONS (Score > 70)
{json_top_k}

INPUT 2: ELITE CLUSTERS OVERVIEW
{json_elite_clusters}

INPUT 3: WINNING PATTERNS (Score-weighted frequency > 75)
{json_winning_patterns}

INPUT 4: DETECTED TRADEOFFS
{json_tradeoffs}

Perform the synthesis and output the optimal schema JSON."""

        try:
            response_text = ask_llm(synthesis_prompt, expect_json=True, force_rerun=force_rerun)
            
            # Additional safety check against LLM markdown wrapping
            if isinstance(response_text, str):
                import re
                cleaned = re.sub(r'```json\s*|\s*```', '', response_text)
                synthesized_solution = json.loads(cleaned)
            else:
                synthesized_solution = response_text
                
            if isinstance(synthesized_solution, dict):
                synthesized_solution["problem_id"] = pid
                
            # Write to output
            out_file = os.path.join(synthesis_dir, f"{pid}.json")
            with open(out_file, 'w', encoding='utf-8') as f:
                json.dump(synthesized_solution, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed synthesis LLM call for {pid}: {e}")
            continue

    logger.info("Phase 5 Completed.")