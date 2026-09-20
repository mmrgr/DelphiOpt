from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "models": {"cheap": {"provider": "mock", "model": "mock-cheap"}, "strong": {"provider": "mock", "model": "mock-strong"}},
    "model_priority": ["cheap", "strong"],
    "model_priority_enabled": False,
    "experts": {
        "algorithm": {"persona": "Algorithm Expert", "model_pool": ["cheap", "strong"]},
        "compiler": {"persona": "Compiler Expert", "model_pool": ["cheap"]},
        "systems": {"persona": "Systems Expert", "model_pool": ["cheap"]},
        "memory": {"persona": "Memory Expert", "model_pool": ["cheap"]},
        "skeptic": {"persona": "Skeptic Agent", "model_pool": ["strong"]},
    },
    "scheduler": {"strategy": "adaptive_voi", "base_tokens": 900, "tool_budget": 2, "max_parallel": 4},
    "collaboration": {"mode": "delphi"},
    "seed": 0,
    "budget": {
        "max_cost_usd": 1.0,
        "max_tokens": 150000,
        "max_latency_seconds": 900,
        "max_llm_calls": 30,
        "max_benchmark_runs": 40,
        "max_tool_calls": 120,
    },
    "delphi": {
        "max_rounds": 3,
        "disagreement_threshold": 0.08,
        "meaningful_speedup": 1.05,
        "max_coefficient_of_variation": 0.15,
        "marginal_gain_threshold": 0.02,
        "min_utility_per_usd": 0.1,
        "no_improvement_rounds": 2,
        "minority_bonus": 0.12,
        "candidate_weights": {
            "consensus": 0.25,
            "expected_gain": 0.25,
            "confidence": 0.2,
            "novelty": 0.12,
            "reputation": 0.1,
            "implementation_cost": 0.05,
            "correctness_risk": 0.03,
        },
    },
    "benchmark": {
        "warmups": 2,
        "repetitions": 7,
        "bootstrap_resamples": 2000,
        "cpu_affinity": [],
        "metric": "median",
        "test_command": "pytest -q",
        "benchmark_command": "python benchmark.py",
        "timeout_seconds": 120,
    },
    "project": {
        "test_command": "pytest -q",
        "benchmark_command": "python benchmark.py",
        "lint_command": None,
        "type_command": None,
        "max_modified_files": 3,
    },
    "sandbox": {"type": "local", "network": False, "cpu_limit": 2, "memory_mb": 2048, "image": "python:3.12-slim"},
}


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge without sharing mutable state with either input."""
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def validate_config(config: dict[str, Any]) -> None:
    strategy = str(config.get("scheduler", {}).get("strategy", "adaptive_voi"))
    if strategy not in {"fixed", "difficulty", "difficulty_router", "adaptive_voi", "voi"}:
        raise ValueError(f"unknown scheduler strategy: {strategy}")
    mode = str(config.get("collaboration", {}).get("mode", "delphi"))
    if mode not in {"single", "best_of_n", "debate", "delphi"}:
        raise ValueError(f"unknown collaboration mode: {mode}")
    for section, names in {
        "budget": ("max_cost_usd", "max_tokens", "max_latency_seconds", "max_llm_calls", "max_benchmark_runs", "max_tool_calls"),
        "benchmark": ("repetitions", "bootstrap_resamples", "timeout_seconds"),
        "delphi": ("max_rounds",),
    }.items():
        values = config.get(section, {})
        for name in names:
            if float(values.get(name, 0)) <= 0:
                raise ValueError(f"{section}.{name} must be positive")
    if int(config.get("benchmark", {}).get("warmups", 0)) < 0:
        raise ValueError("benchmark.warmups cannot be negative")
    if int(config.get("scheduler", {}).get("max_parallel", 1)) <= 0:
        raise ValueError("scheduler.max_parallel must be positive")
    if not config.get("models") or not config.get("experts"):
        raise ValueError("models and experts must not be empty")
    model_names = set(config["models"])
    priority = config.get("model_priority", [])
    if not isinstance(priority, list):
        raise TypeError("model_priority must be a list")
    if len(priority) != len(set(priority)):
        raise ValueError("model_priority must not contain duplicates")
    unknown_priority = set(priority) - model_names
    if unknown_priority:
        raise ValueError(f"model_priority references unknown models: {sorted(unknown_priority)}")
    for expert_id, values in config["experts"].items():
        pool = values.get("model_pool", [])
        if not pool:
            raise ValueError(f"experts.{expert_id}.model_pool must not be empty")
        unknown = set(pool) - model_names
        if unknown:
            raise ValueError(f"experts.{expert_id}.model_pool references unknown models: {sorted(unknown)}")


def load_config_overrides(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    raw = file_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError:
        try:
            override = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Install PyYAML or provide JSON-compatible YAML config") from exc
    else:
        override = yaml.safe_load(raw) or {}
    if not isinstance(override, dict):
        raise TypeError("configuration root must be a mapping")
    return override


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        config = merge_config({}, DEFAULT_CONFIG)
        validate_config(config)
        return config
    override = load_config_overrides(path)
    config = merge_config(DEFAULT_CONFIG, override)
    validate_config(config)
    return config
