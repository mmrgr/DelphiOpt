from __future__ import annotations

from enum import StrEnum

from .models import Proposal


class CollaborationMode(StrEnum):
    SINGLE = "single"
    DEBATE = "debate"
    DELPHI = "delphi"


def visible_peer_feedback(proposals: list[Proposal]) -> str:
    """Debate mode exposes peer proposals; Delphi mode never calls this in round one."""
    return "\n".join(
        f"Peer proposal {index}: {item.transformation}; expected={item.expected_speedup:.2f}" for index, item in enumerate(proposals, 1)
    )
