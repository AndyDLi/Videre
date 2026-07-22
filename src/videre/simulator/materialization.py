"""
Interface for materializing simulated jobs into real Kubernetes objects.
"""

from __future__ import annotations

from typing import Protocol

from videre.models import Job


class Materializer(Protocol):
    def materialize(self, job: Job, node_id: str) -> str: ...
    def signal_outcome(self, pod_name: str, outcome: str) -> None: ...
