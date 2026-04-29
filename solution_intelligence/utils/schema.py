import json
import logging
from pydantic import BaseModel, Field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Pydantic Models for Strict Schema Validation

class SolutionScores(BaseModel):
    """Individual scoring criteria (1-5 scale)."""
    problem_fit: int = Field(ge=1, le=5)
    feasibility: int = Field(ge=1, le=5)
    optimization: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    scalability: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)

class Penalty(BaseModel):
    """Penalty structure."""
    missing_core: int = Field(default=0, ge=0, le=20)
    overclaim: int = Field(default=0, ge=0, le=10)

class FinalEvaluation(BaseModel):
    """Complete evaluation with scores, penalties, and reasoning."""
    solution_id: str
    scores: SolutionScores
    penalties: Penalty
    base_score: float = Field(ge=0, le=100)
    final_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str

class SolutionExtraction(BaseModel):
    """Extracted structured solution data."""
    solution_id: Optional[str] = None
    problem_id: str
    team_name: Optional[str] = None
    summary: str
    approach_type: str  # rule-based, ml, dl, system, hybrid
    tech_stack: List[str] = Field(default_factory=list, alias="tools_and_techniques")
    key_steps: List[str] = Field(default_factory=list, alias="pipeline_steps")
    optimization_claims: List[str] = Field(default_factory=list, alias="optimization_techniques")
    constraints_addressed: List[str] = Field(default_factory=list)
    missing_components: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    
    class Config:
        populate_by_name = True  # Allow both field name and alias

def validate_inputs(problems_path: str, solutions_path: str):
    """
    Validates problems.json and solutions.json according to strict schemas.
    Returns:
        problems_dict: dict mapping problem_id -> problem object
        solutions_by_problem: dict mapping problem_id -> list of solution objects
    Raises:
        ValueError for any validation failure (duplicates, missing keys, orphans, etc.)
    """
    # 1. Load JSON files
    try:
        with open(problems_path, 'r', encoding='utf-8') as f:
            problems_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in problems file: {e}")
    except FileNotFoundError:
        raise ValueError(f"Problems file not found at {problems_path}")

    try:
        with open(solutions_path, 'r', encoding='utf-8') as f:
            solutions_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in solutions file: {e}")
    except FileNotFoundError:
        raise ValueError(f"Solutions file not found at {solutions_path}")

    # 2. Validate Problems
    if "problems" not in problems_data or not isinstance(problems_data["problems"], list):
        raise ValueError("problems.json must contain a top-level 'problems' array.")

    problems_dict = {}
    problem_required_keys = {"problem_id", "title", "description"}

    for idx, prob in enumerate(problems_data["problems"]):
        if not isinstance(prob, dict):
            raise ValueError(f"Problem at index {idx} is not an object.")
        
        # Check missing or null required fields
        for key in problem_required_keys:
            if key not in prob or prob[key] is None:
                raise ValueError(f"Problem missing required or non-null key '{key}' at index {idx}.")
        
        pid = prob["problem_id"]
        if not isinstance(pid, str) or not pid.strip():
            raise ValueError(f"Problem at index {idx} has empty or invalid problem_id.")
        
        # Check duplicates
        if pid in problems_dict:
            raise ValueError(f"Duplicate problem_id found: {pid}")

        problems_dict[pid] = prob

    # 3. Validate Solutions
    if "solutions" not in solutions_data or not isinstance(solutions_data["solutions"], list):
        raise ValueError("solutions.json must contain a top-level 'solutions' array.")

    solutions_by_problem = {pid: [] for pid in problems_dict.keys()}
    solution_required_keys = {"solution_id", "problem_id", "team_name", "solution_text"}
    seen_solution_ids = set()

    for idx, sol in enumerate(solutions_data["solutions"]):
        if not isinstance(sol, dict):
            raise ValueError(f"Solution at index {idx} is not an object.")

        # Check missing or null required fields
        for key in solution_required_keys:
            if key not in sol or sol[key] is None:
                raise ValueError(f"Solution missing required or non-null key '{key}' at index {idx}.")

        sid = sol["solution_id"]
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError(f"Solution at index {idx} has empty or invalid solution_id.")
        
        if sid in seen_solution_ids:
            raise ValueError(f"Duplicate solution_id found: {sid}")
        seen_solution_ids.add(sid)

        pid = sol["problem_id"]
        if pid not in problems_dict:
            raise ValueError(f"Orphan solution found: solution '{sid}' references unknown problem_id '{pid}'.")

        text = sol["solution_text"]
        if not isinstance(text, str) or len(text.strip()) < 30:
            raise ValueError(f"Solution '{sid}' must have a solution_text of at least 30 characters.")

        solutions_by_problem[pid].append(sol)

    logger.info(f"Successfully validated {len(problems_dict)} problems and {len(seen_solution_ids)} solutions.")
    return problems_dict, solutions_by_problem
