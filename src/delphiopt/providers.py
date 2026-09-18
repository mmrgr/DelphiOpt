from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .models import AgentResponse


class ModelProvider(Protocol):
    name: str

    async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.2) -> AgentResponse: ...

    async def probe(self, model: str) -> dict[str, object]: ...


def _tokens(text: str) -> int:
    return max(1, len(text.split()))


class MockModelProvider:
    name = "mock"

    async def probe(self, model: str) -> dict[str, object]:
        await asyncio.sleep(0)
        return {
            "provider": self.name,
            "model": model,
            "configured": True,
            "reachable": True,
            "structured_json": True,
            "reason": "mock provider is available",
        }

    async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.2) -> AgentResponse:
        started = time.perf_counter()
        lower = prompt.lower()
        if "revision" in lower or "feedback" in lower:
            proposal = {
                "hypothesis": "The evidence favors the highest-upside low-risk transformation.",
                "bottleneck": "Repeated linear membership checks remain measurable.",
                "transformation": "materialize membership candidates as a set before the hot loop",
                "expected_speedup": 1.35,
                "confidence": 0.78,
                "implementation_cost": 0.18,
                "correctness_risk": 0.08,
                "memory_risk": 0.12,
                "evidence_required": ["existing tests", "multiple input sizes", "repeated benchmark samples"],
                "category": "data-structure",
                "novelty": 0.62,
            }
        elif "skeptic" in lower:
            proposal = {
                "hypothesis": "The apparent gain may be benchmark-sensitive; validate semantics and workload scaling.",
                "bottleneck": "Potentially biased membership benchmark.",
                "transformation": "validate membership optimization against duplicate and empty inputs",
                "expected_speedup": 1.02,
                "confidence": 0.83,
                "implementation_cost": 0.15,
                "correctness_risk": 0.05,
                "memory_risk": 0.04,
                "evidence_required": ["held-out workload", "correctness tests"],
                "category": "validation",
                "novelty": 0.48,
            }
        else:
            proposal = {
                "hypothesis": "Repeated membership checks dominate the hot loop.",
                "bottleneck": "A list membership lookup is repeated for every input value.",
                "transformation": "materialize membership candidates as a set before the hot loop",
                "expected_speedup": 1.35,
                "confidence": 0.75,
                "implementation_cost": 0.2,
                "correctness_risk": 0.1,
                "memory_risk": 0.12,
                "evidence_required": ["existing tests", "multiple input sizes", "repeated benchmark samples"],
                "category": "data-structure",
                "novelty": 0.6,
            }
        text = json.dumps(proposal)
        await asyncio.sleep(0)
        return AgentResponse(
            text=text,
            input_tokens=_tokens(prompt),
            output_tokens=_tokens(text),
            cost_usd=0.0,
            latency_seconds=time.perf_counter() - started,
            model=model,
            provider=self.name,
        )


@dataclass(slots=True)
class HttpModelProvider:
    name: str
    endpoint: str
    api_key_env: str
    style: str
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    timeout_seconds: float = 120.0
    max_retries: int = 3
    backoff_seconds: float = 0.5

    async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.2) -> AgentResponse:
        return await asyncio.to_thread(self._generate_sync, prompt, model, max_tokens, temperature)

    async def probe(self, model: str) -> dict[str, object]:
        configured = bool(os.getenv(self.api_key_env))
        result: dict[str, object] = {
            "provider": self.name,
            "model": model,
            "endpoint": self.endpoint,
            "configured": configured,
            "reachable": False,
            "structured_json": False,
        }
        if not configured:
            result["reason"] = f"missing environment variable {self.api_key_env}"
            return result
        try:
            response = await self.generate('Return only this JSON object: {"ok":true}', model=model, max_tokens=32, temperature=0)
            text = response.text.strip()
            start, end = text.find("{"), text.rfind("}")
            parsed = json.loads(text[start : end + 1]) if start >= 0 and end > start else None
            result.update(
                reachable=True,
                structured_json=isinstance(parsed, dict),
                latency_seconds=response.latency_seconds,
                reason="provider request succeeded",
            )
        except (RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            result["reason"] = str(exc)
        return result

    def _generate_sync(self, prompt: str, model: str, max_tokens: int, temperature: float) -> AgentResponse:
        key = os.getenv(self.api_key_env)
        if not key:
            raise RuntimeError(f"{self.name} requires {self.api_key_env}")
        started = time.perf_counter()
        if self.style == "anthropic":
            payload: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        elif self.style == "gemini":
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
            }
            headers = {"x-goog-api-key": key}
        else:
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"Authorization": f"Bearer {key}"}
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw_body = response.read().decode()
                try:
                    body = json.loads(raw_body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"{self.name} returned invalid JSON") from exc
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:1000]
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise RuntimeError(f"{self.name} HTTP {exc.code}: {detail}") from exc
                time.sleep(self.backoff_seconds * (2**attempt))
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise RuntimeError(f"{self.name} request failed: {exc}") from exc
                time.sleep(self.backoff_seconds * (2**attempt))
        try:
            text = self._extract_text(body)
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"{self.name} response did not contain generated text") from exc
        input_tokens, output_tokens = self._usage(body, prompt, text)
        cost = input_tokens / 1_000_000 * self.input_price_per_million + output_tokens / 1_000_000 * self.output_price_per_million
        return AgentResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_seconds=time.perf_counter() - started,
            model=model,
            provider=self.name,
        )

    def _extract_text(self, body: dict[str, Any]) -> str:
        if self.style == "gemini":
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return str(text)
        if self.style == "anthropic":
            return "".join(part.get("text", "") for part in body.get("content", []))
        return str(body["choices"][0]["message"]["content"])

    def _usage(self, body: dict[str, Any], prompt: str, text: str) -> tuple[int, int]:
        if self.style == "gemini":
            usage = body.get("usageMetadata", {})
            return int(usage.get("promptTokenCount", _tokens(prompt))), int(usage.get("candidatesTokenCount", _tokens(text)))
        usage = body.get("usage", {})
        if self.style == "anthropic":
            return int(usage.get("input_tokens", _tokens(prompt))), int(usage.get("output_tokens", _tokens(text)))
        return int(usage.get("prompt_tokens", _tokens(prompt))), int(usage.get("completion_tokens", _tokens(text)))


def provider_from_config(config: dict[str, Any]) -> ModelProvider:
    provider = str(config.get("provider", "mock")).lower()
    model = str(config.get("model", provider))
    if provider == "mock":
        return MockModelProvider()
    if provider in {"openai", "openai-compatible"}:
        endpoint = str(config.get("endpoint", "https://api.openai.com/v1/chat/completions"))
        return HttpModelProvider(
            provider,
            endpoint,
            str(config.get("api_key_env", "OPENAI_API_KEY")),
            "openai",
            float(config.get("input_price_per_million", 0)),
            float(config.get("output_price_per_million", 0)),
            float(config.get("timeout_seconds", 120)),
            int(config.get("max_retries", 3)),
            float(config.get("backoff_seconds", 0.5)),
        )
    if provider == "anthropic":
        return HttpModelProvider(
            provider,
            str(config.get("endpoint", "https://api.anthropic.com/v1/messages")),
            str(config.get("api_key_env", "ANTHROPIC_API_KEY")),
            "anthropic",
            float(config.get("input_price_per_million", 0)),
            float(config.get("output_price_per_million", 0)),
            float(config.get("timeout_seconds", 120)),
            int(config.get("max_retries", 3)),
            float(config.get("backoff_seconds", 0.5)),
        )
    if provider == "gemini":
        endpoint = str(config.get("endpoint", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"))
        return HttpModelProvider(
            provider,
            endpoint,
            str(config.get("api_key_env", "GEMINI_API_KEY")),
            "gemini",
            float(config.get("input_price_per_million", 0)),
            float(config.get("output_price_per_million", 0)),
            float(config.get("timeout_seconds", 120)),
            int(config.get("max_retries", 3)),
            float(config.get("backoff_seconds", 0.5)),
        )
    raise ValueError(f"unknown provider: {provider}")


async def probe_model_configs(configs: dict[str, Any], *, max_concurrency: int = 4) -> dict[str, dict[str, object]]:
    """Probe configured models concurrently while bounding outbound requests."""

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def probe_one(alias: str, values: dict[str, Any]) -> tuple[str, dict[str, object]]:
        async with semaphore:
            try:
                provider = provider_from_config(values)
                return alias, await provider.probe(str(values.get("model", alias)))
            except (RuntimeError, ValueError, TypeError, KeyError) as exc:
                return alias, {
                    "provider": str(values.get("provider", "unknown")),
                    "model": str(values.get("model", alias)),
                    "configured": False,
                    "reachable": False,
                    "structured_json": False,
                    "reason": str(exc),
                }

    pairs = await asyncio.gather(*(probe_one(str(alias), dict(values)) for alias, values in configs.items() if isinstance(values, dict)))
    return dict(pairs)
