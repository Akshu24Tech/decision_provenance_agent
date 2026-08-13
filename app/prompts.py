"""
LLM prompt templates for Decision Provenance Agent.

Two core prompts:
  1. Extraction: raw text → structured DecisionRecord candidate
  2. Diff: compare new claim vs existing record → classify change

Both use Gemini 2.5 Flash via langchain-google-genai.
"""

import json
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def _get_llm() -> ChatGoogleGenerativeAI:
    """Get the Gemini LLM instance."""
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.1,  # Low temp for reliable structured output
    )


# ──────────────────────────────────────────────
#  Stage 1: Extraction — raw text → candidate
# ──────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a decision extraction engine. Given raw text input, extract the decision/conclusion being stated.

Rules:
- topic_key: a short, normalized, snake_case label for the BROAD CATEGORY of this decision. Use the most general applicable label. Examples: "database_choice" (not "user_service_database"), "auth_strategy" (not "jwt_token_decision"), "deployment_method" (not "kubernetes_setup"). The topic_key should be reusable if the same type of decision is revisited later.
- claim: the conclusion/decision itself, one clear sentence
- reasoning: why this conclusion was reached, one to two sentences
- evidence: a list of traceable sources, facts, or inputs that support this claim. Extract at least one.
- confidence: 0-1, how certain the source seems about this decision

Input text:
{raw_input}

Respond ONLY with valid JSON, no markdown, no explanation:
{{"topic_key": "", "claim": "", "reasoning": "", "evidence": [""], "confidence": 0.0}}"""


async def extract_decision(raw_input: str) -> dict:
    """
    Extract a structured decision candidate from raw text.
    
    Returns dict with: topic_key, claim, reasoning, evidence, confidence
    """
    llm = _get_llm()
    prompt = EXTRACTION_PROMPT.format(raw_input=raw_input)

    response = await llm.ainvoke(prompt)
    content = response.content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError(f"LLM returned invalid JSON: {content[:200]}")

    # Validate required fields
    required = ["topic_key", "claim", "reasoning", "evidence", "confidence"]
    for field in required:
        if field not in result:
            raise ValueError(f"LLM response missing required field: {field}")

    # Ensure evidence is a list
    if isinstance(result["evidence"], str):
        result["evidence"] = [result["evidence"]]

    return result


# ──────────────────────────────────────────────
#  Stage 3: Diff — compare new vs existing
# ──────────────────────────────────────────────

DIFF_PROMPT = """You are a decision diff engine. Compare a new decision against an existing one and determine if the conclusion actually changed.

Existing decision:
  Claim: {old_claim}
  Reasoning: {old_reasoning}

New input:
  Claim: {new_claim}
  Reasoning: {new_reasoning}

Questions to answer:
1. Did the CONCLUSION actually change, or is this the same decision restated differently?
2. If changed, classify the trigger as EXACTLY one of: "new evidence", "correction", "constraint change"
3. Provide a brief diff summary explaining what changed and why.

Definitions:
- "new evidence": The conclusion changed because new information was discovered
- "correction": The previous conclusion was wrong/flawed and is being fixed
- "constraint change": External constraints changed (budget, timeline, team, requirements)

Respond ONLY with valid JSON, no markdown, no explanation:
{{"changed": true, "change_trigger": "new evidence", "diff_summary": "..."}}

If NOT genuinely changed (just restated/rephrased):
{{"changed": false, "change_trigger": null, "diff_summary": "Same decision, different wording"}}"""


async def diff_decisions(
    old_claim: str,
    old_reasoning: str,
    new_claim: str,
    new_reasoning: str,
) -> dict:
    """
    Compare new claim against an existing record.
    
    Returns dict with: changed (bool), change_trigger (str|null), diff_summary (str)
    """
    llm = _get_llm()
    prompt = DIFF_PROMPT.format(
        old_claim=old_claim,
        old_reasoning=old_reasoning,
        new_claim=new_claim,
        new_reasoning=new_reasoning,
    )

    response = await llm.ainvoke(prompt)
    content = response.content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError(f"LLM returned invalid JSON for diff: {content[:200]}")

    # Validate required fields
    if "changed" not in result:
        raise ValueError("Diff response missing 'changed' field")

    # Normalize change_trigger
    valid_triggers = {"new evidence", "correction", "constraint change"}
    if result.get("change_trigger") and result["change_trigger"] not in valid_triggers:
        # LLM might return close variations — try to match
        trigger = result["change_trigger"].lower().strip()
        if "evidence" in trigger:
            result["change_trigger"] = "new evidence"
        elif "correct" in trigger:
            result["change_trigger"] = "correction"
        elif "constraint" in trigger:
            result["change_trigger"] = "constraint change"
        else:
            result["change_trigger"] = "new evidence"  # safe default

    return result
