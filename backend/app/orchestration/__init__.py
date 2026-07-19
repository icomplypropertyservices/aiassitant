"""Canonical multi-agent orchestration: finalize, review, workflow run, acceptance."""
from .acceptance import (
    extract_checklist,
    task_requires_review,
    merge_labels,
    pack_acceptance,
    unpack_acceptance,
    evaluate_skill_evidence,
)
from .finalize import finalize_task_after_run, apply_task_result

__all__ = [
    "extract_checklist",
    "task_requires_review",
    "merge_labels",
    "pack_acceptance",
    "unpack_acceptance",
    "evaluate_skill_evidence",
    "finalize_task_after_run",
    "apply_task_result",
]
