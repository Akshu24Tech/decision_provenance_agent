"""
LLM prompt templates and structured output engines for Decision Provenance Agent.

Two core operations:
  1. Extraction: raw text -> structured DecisionRecord candidate
  2. Diff: compare new claim vs existing record -> classify change and trigger

Powered by Gemini native structured JSON output via langchain-google-genai.
"""

import json
from typing import Optional, Literal
from pydantic import BaseModel, Field

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


class ExtractedDecision(BaseModel):
    """Structured decision candidate extracted from raw text."""
    topic_key: str = Field(
        description="Normalized snake_case label for the BROAD CATEGORY of this decision (e.g., 'database_choice', 'auth_strategy', 'deployment_method'). Must be reusable if revisited."
    )
    claim: str = Field(
        description="The primary conclusion or decision reached, stated concisely in one clear sentence."
    )
    reasoning: str = Field(
        description="The core rationale or justification for why this conclusion was reached."
    )
    evidence: list[str] = Field(
        min_length=1,
        description="List of traceable sources, facts, benchmarks, meeting notes, or inputs supporting this claim."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0 reflecting how certain the source is."
    )


class DiffClassification(BaseModel):
    """Classification of change between an existing decision and a new input."""
    changed: bool = Field(
        description="True if the conclusion/architecture actually changed; False if it is the same decision restated or reworded."
    )
    change_trigger: Optional[Literal["new evidence", "correction", "constraint change"]] = Field(
        default=None,
        description="Why the decision was revised: 'new evidence' (new findings/benchmarks), 'correction' (previous stance was wrong), 'constraint change' (external budget, timeline, team change)."
    )
    diff_summary: str = Field(
        description="A concise summary of the delta between old and new decisions."
    )


def _get_llm() -> ChatGoogleGenerativeAI:
    """Get the configured Gemini LLM instance."""
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.1,  # Low temp for deterministic, high-accuracy reasoning
    )


# ──────────────────────────────────────────────
#  Stage 1: Extraction - raw text -> candidate
# ──────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an expert decision extraction engine. Given raw text input, extract the core decision/conclusion being stated into structured format.

Rules:
- topic_key: a short, normalized, snake_case label for the BROAD CATEGORY of this decision. Use the most general applicable label. Examples: "database_choice" (not "user_service_database"), "auth_strategy" (not "jwt_token_decision"), "deployment_method" (not "kubernetes_setup"). The topic_key should be reusable if the same type of decision is revisited later.
- claim: the conclusion/decision itself, one clear sentence.
- reasoning: why this conclusion was reached, one to two sentences.
- evidence: a list of traceable sources, facts, benchmarks, or inputs that support this claim (at least one).
- confidence: 0.0 to 1.0, how certain and grounded the source seems about this decision.

Input text:
{raw_input}"""


async def extract_decision(raw_input: str) -> dict:
    """
    Extract a structured decision candidate from raw text using native structured output.
    
    Returns dict with: topic_key, claim, reasoning, evidence, confidence
    """
    llm = _get_llm()
    prompt = EXTRACTION_PROMPT.format(raw_input=raw_input)

    try:
        structured_llm = llm.with_structured_output(ExtractedDecision)
        result_obj: ExtractedDecision = await structured_llm.ainvoke(prompt)
        return result_obj.model_dump()
    except Exception:
        # Fallback to direct raw prompt and json parsing if structured output fails
        response = await llm.ainvoke(
            prompt + "\n\nRespond ONLY with valid JSON:\n"
            '{"topic_key": "", "claim": "", "reasoning": "", "evidence": [""], "confidence": 0.0}'
        )
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        result = json.loads(content)
        if isinstance(result.get("evidence"), str):
            result["evidence"] = [result["evidence"]]
        return result


# ──────────────────────────────────────────────
#  Stage 3: Diff - compare new vs existing
# ──────────────────────────────────────────────

DIFF_PROMPT = """You are an expert decision diff and lineage classification engine. Compare a new decision against an existing one and determine if the conclusion actually changed.

Existing decision:
  Claim: {old_claim}
  Reasoning: {old_reasoning}

New input:
  Claim: {new_claim}
  Reasoning: {new_reasoning}

Questions to evaluate:
1. Did the CONCLUSION actually change, or is this the same decision restated differently?
2. If changed, classify the trigger as EXACTLY one of:
   - "new evidence": The conclusion changed because new data, benchmarks, or findings were discovered.
   - "correction": The previous conclusion was flawed/incorrect and is being fixed.
   - "constraint change": External constraints changed (budget, timeline, scale, compliance, team).
3. Provide a brief diff summary explaining what changed and why."""


async def diff_decisions(
    old_claim: str,
    old_reasoning: str,
    new_claim: str,
    new_reasoning: str,
) -> dict:
    """
    Compare new claim against an existing record using native structured output.
    
    Returns dict with: changed (bool), change_trigger (str|null), diff_summary (str)
    """
    llm = _get_llm()
    prompt = DIFF_PROMPT.format(
        old_claim=old_claim,
        old_reasoning=old_reasoning,
        new_claim=new_claim,
        new_reasoning=new_reasoning,
    )

    try:
        structured_llm = llm.with_structured_output(DiffClassification)
        result_obj: DiffClassification = await structured_llm.ainvoke(prompt)
        data = result_obj.model_dump()
        return data
    except Exception:
        # Fallback to direct raw prompt and json parsing
        response = await llm.ainvoke(
            prompt + '\n\nRespond ONLY with valid JSON: {"changed": true, "change_trigger": "new evidence", "diff_summary": "..."}'
        )
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        result = json.loads(content)
        valid_triggers = {"new evidence", "correction", "constraint change"}
        if result.get("change_trigger") and result["change_trigger"] not in valid_triggers:
            trigger = result["change_trigger"].lower().strip()
            if "evidence" in trigger:
                result["change_trigger"] = "new evidence"
            elif "correct" in trigger:
                result["change_trigger"] = "correction"
            elif "constraint" in trigger:
                result["change_trigger"] = "constraint change"
            else:
                result["change_trigger"] = "new evidence"
        return result
