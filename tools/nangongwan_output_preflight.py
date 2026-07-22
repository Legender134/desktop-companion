"""Fail-closed path checks shared by retained Nangong Wan asset CLIs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def validate_planned_outputs(
    *,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    protected_roots: Iterable[Path],
) -> None:
    """Reject protected destinations and every resolved input/output collision."""

    resolved_inputs = {path.resolve(strict=False) for path in inputs}
    resolved_outputs = tuple(path.resolve(strict=False) for path in outputs)
    resolved_roots = tuple(path.resolve(strict=False) for path in protected_roots)

    for output in resolved_outputs:
        if any(output == root or output.is_relative_to(root) for root in resolved_roots):
            raise ValueError("output must not be inside a protected archive or live pet tree")

    collisions = resolved_inputs.intersection(resolved_outputs)
    if collisions:
        paths = ", ".join(str(path) for path in sorted(collisions, key=str))
        raise ValueError(f"planned output collides with input: {paths}")

    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise ValueError("planned outputs must resolve to distinct paths")
