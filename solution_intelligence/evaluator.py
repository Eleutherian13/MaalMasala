#!/usr/bin/env python3
"""
Deterministic Solution Evaluation Engine
Strict technical evaluation without LLM randomness
"""

import json
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class EvaluationScores:
    problem_fit: int
    feasibility: int
    optimization: int
    completeness: int
    scalability: int
    novelty: int
    clarity: int
    
    def __post_init__(self):
        # Validate all scores are 1-5
        for score in [self.problem_fit, self.feasibility, self.optimization,
                      self.completeness, self.scalability, self.novelty, self.clarity]:
            if not (1 <= score <= 5):
                raise ValueError(f"Score must be between 1-5, got {score}")

def evaluate_solution(
    problem_statement: str,
    solution_text: str,
    extracted_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate a STRICT STRUCTURED MARKDOWN REPORT evaluating a solution.
    
    Args:
        problem_statement: Full problem description
        solution_text: Raw solution submission
        extracted_data: Optional pre-extracted structured data
    
    Returns:
        Markdown report following the exact template
    """
    
    # For demo, use extracted_data or create minimal example
    # In production, this would call phase1_structure extraction + phase3 scoring
    
    if not extracted_data:
        extracted_data = {
            "approach_type": "MISSING",
            "tech_stack": [],
            "pipeline_steps": [],
            "optimization_techniques": [],
            "missing_components": []
        }
    
    # Example deterministic scoring (would come from phase3_score in real pipeline)
    scores = EvaluationScores(
        problem_fit=3,
        feasibility=3,
        optimization=2,
        completeness=2,
        scalability=2,
        novelty=3,
        clarity=3
    )
    
    # Deterministic penalty logic
    missing_core_penalty = 0
    overclaim_penalty = 0
    
    if scores.feasibility <= 2 or scores.completeness <= 2:
        missing_core_penalty = 20
    
    if scores.optimization >= 4 and len(extracted_data.get("optimization_techniques", [])) == 0:
        overclaim_penalty = 10
    
    # Calculate final score
    base_score = (
        (0.25 * scores.problem_fit +
         0.20 * scores.feasibility +
         0.20 * scores.optimization +
         0.15 * scores.completeness +
         0.10 * scores.scalability +
         0.05 * scores.novelty +
         0.05 * scores.clarity) * 20
    )
    
    final_score = max(0, min(100, base_score - missing_core_penalty - overclaim_penalty))
    
    # Determine verdict
    if final_score >= 85:
        verdict = "EXCELLENT (85–100)"
    elif final_score >= 70:
        verdict = "STRONG (70–84)"
    elif final_score >= 50:
        verdict = "AVERAGE (50–69)"
    else:
        verdict = "WEAK (<50)"
    
    # Build markdown report
    md = """# 📊 Solution Evaluation Report

## 🧩 Problem Summary

"""
    md += f"* {problem_statement[:100]}...\n\n"
    
    md += """## 💡 Solution Summary

"""
    md += f"* {solution_text[:100]}...\n\n"
    
    md += """---

## 🧠 Extracted Structure

**Approach Type:**
"""
    md += f"{extracted_data.get('approach_type', 'MISSING')}\n\n"
    
    md += """**Tech Stack:**

"""
    if extracted_data.get('tech_stack'):
        for tech in extracted_data['tech_stack']:
            md += f"* {tech}\n"
    else:
        md += "* MISSING\n"
    
    md += """\n**Pipeline Steps:**

"""
    if extracted_data.get('pipeline_steps'):
        for i, step in enumerate(extracted_data['pipeline_steps'], 1):
            md += f"{i}. {step}\n"
    else:
        md += "* MISSING\n"
    
    md += """\n**Optimization Techniques:**

"""
    if extracted_data.get('optimization_techniques'):
        for opt in extracted_data['optimization_techniques']:
            md += f"* {opt}\n"
    else:
        md += "* MISSING\n"
    
    md += """\n**Missing Components:**

"""
    if extracted_data.get('missing_components'):
        for comp in extracted_data['missing_components']:
            md += f"* {comp}\n"
    else:
        md += "* None identified\n"
    
    md += """\n---

## 📈 Scoring Breakdown

| Criterion    | Score (1–5) | Justification  |
| ------------ | ----------- | -------------- |
"""
    
    md += f"| Problem Fit  | {scores.problem_fit}           | Solution partially addresses stated requirements |\n"
    md += f"| Feasibility  | {scores.feasibility}           | Approach is plausible but lacks concrete implementation details |\n"
    md += f"| Optimization | {scores.optimization}           | Minimal optimization strategies identified |\n"
    md += f"| Completeness | {scores.completeness}           | Pipeline is fragmented with missing steps |\n"
    md += f"| Scalability  | {scores.scalability}           | Solution appears limited to small-scale use |\n"
    md += f"| Novelty      | {scores.novelty}           | Some variation from standard approaches |\n"
    md += f"| Clarity      | {scores.clarity}           | Solution description is understandable but could be more structured |\n"
    
    md += """\n---

## ⚠️ Penalties Applied

"""
    md += f"* Missing Core: {'YES' if missing_core_penalty > 0 else 'NO'} (-{missing_core_penalty} if YES)\n"
    md += f"* Overclaim: {'YES' if overclaim_penalty > 0 else 'NO'} (-{overclaim_penalty} if YES)\n"
    
    md += """\n---

## 🧮 Final Score

"""
    md += f"Base Score: {base_score:.1f}\n"
    md += f"Penalties: -{missing_core_penalty} -{overclaim_penalty}\n"
    md += f"**Final Score: {final_score:.0f} / 100**\n"
    
    md += """\n---

## 🔍 Key Strengths

* Clear problem understanding demonstrated
* Reasonable technical approach proposed
* Structured presentation of ideas

## ⚠️ Key Weaknesses

* Lack of concrete implementation steps
* Missing feasibility analysis
* Limited discussion of scalability challenges
* Insufficient justification for technology choices

---

## 🧠 Verdict

* **"""
    md += verdict + """**

The solution shows partial alignment with requirements but lacks the depth, completeness, and technical rigor needed for production implementation. Key gaps in feasibility analysis and missing core architectural components prevent a higher score.

---

"""
    
    return md


def main():
    """Demo evaluation report."""
    
    problem = "Design a layer that propagates service requests both ways between systems using UBID as join key."
    solution = "We propose using a queue-based architecture with transformation microservices..."
    
    report = evaluate_solution(problem, solution)
    print(report)
    
    # Also save to file
    with open("sample_evaluation_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    
    print("\n✅ Report saved to sample_evaluation_report.md")


if __name__ == "__main__":
    main()
