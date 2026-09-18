from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .budget import BudgetExhausted, BudgetManager
from .models import Proposal
from .providers import ModelProvider
from .telemetry import RunTracer

PERSONAS: dict[str, str] = {
    "algorithm": "Analyze asymptotic complexity, redundant computation, data structures, and algorithmic bottlenecks.",
    "compiler": "Analyze allocations, vectorization, loop lowering, interpreter overhead, and compiler opportunities.",
    "systems": "Analyze I/O, concurrency, locking, processes, syscalls, and cache behavior.",
    "memory": "Analyze object creation, copies, locality, allocation pressure, RSS, and lifetime.",
    "skeptic": "Try to falsify proposals, find correctness regressions, benchmark bias, and hidden assumptions.",
}


@dataclass(slots=True)
class ExpertAgent:
    expert_id: str
    persona: str
    model_name: str
    provider: ModelProvider
    temperature: float = 0.2

    def _prompt(self, project_context: str, feedback: str = "") -> str:
        # Delphi invariant: feedback is empty in round 1, so experts cannot see peers' answers.
        return f"""You are the {self.persona}.\nFocus: {PERSONAS.get(self.expert_id, self.persona)}\nProject evidence:\n{project_context}\n{feedback}\nReturn only JSON with keys hypothesis, bottleneck, transformation, expected_speedup, confidence, implementation_cost, correctness_risk, memory_risk, evidence_required, category, novelty, and optional unified-diff patch."""

    async def analyze(
        self, project_context: str, budget: BudgetManager, tracer: RunTracer, round_number: int, feedback: str = "", max_tokens: int = 900
    ) -> Proposal | None:
        prompt = self._prompt(project_context, feedback)
        for attempt in range(2):
            current_prompt = (
                prompt if attempt == 0 else prompt + "\nYour prior response was invalid. Repair it and return one valid JSON object only."
            )
            try:
                if not budget.can_afford(tokens=max_tokens):
                    raise BudgetExhausted("global LLM budget cannot cover the requested output allocation")
                response = await self.provider.generate(
                    current_prompt, model=self.model_name, max_tokens=max_tokens, temperature=self.temperature
                )
                budget.record_llm(response)
                data = _parse_json(response.text)
                if not data:
                    raise ValueError("invalid JSON object")
                proposal_id = hashlib.sha1(f"{round_number}:{self.expert_id}:{data.get('transformation', '')}".encode()).hexdigest()[:10]
                proposal = Proposal.from_dict(data, fallback_id=proposal_id)
            except (BudgetExhausted, RuntimeError, ValueError, TypeError, KeyError) as exc:
                tracer.record(
                    "agent_error", round=round_number, expert=self.expert_id, model=self.model_name, attempt=attempt + 1, error=str(exc)
                )
                if isinstance(exc, BudgetExhausted):
                    return None
                continue
            proposal.id = proposal_id
            proposal.author_anonymous_id = hashlib.sha256(self.expert_id.encode()).hexdigest()[:12]
            proposal.source_expert = self.expert_id
            tracer.record(
                "agent_call",
                round=round_number,
                expert=self.expert_id,
                model=response.model,
                provider=response.provider,
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                cost=response.cost_usd,
                latency=response.latency_seconds,
                max_tokens=max_tokens,
                repair_attempt=attempt,
                proposal=proposal.to_dict(),
            )
            return proposal
        return None

    async def revise(
        self, project_context: str, feedback: str, budget: BudgetManager, tracer: RunTracer, round_number: int, max_tokens: int = 900
    ) -> Proposal | None:
        return await self.analyze(project_context, budget, tracer, round_number, feedback, max_tokens)


def _parse_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None
        return None
