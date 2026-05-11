"""Singularity detection and smooth-through interpolation.

Per reviewer guidance (ARCHITECTURE.md §7 item 2): when tilt is near zero
(|tilt| < `singularity_threshold_rad`, default 2°), the swivel axis is
operationally degenerate — varying it doesn't meaningfully change the tool
orientation in the part frame. Naively commanding sharp swivel changes
through this band wastes time and disturbs the bath kerf.

The smooth-through transform identifies contiguous runs of joint samples in
the singular band and replaces each run's swivel values with a linear
interpolation from the swivel value at entry to the swivel value at exit.
Path geometry (part-frame positions) is unchanged; only the swivel command
is rewritten.

This is a transform on `list[JointAngles]`, not a refusal mode. There is no
"reject" — the user explicitly chose smooth-through over avoid because the
A ≈ 0 rest pose is on the critical path of essentially every print and a
refuse mode is a footgun.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

from bioslice5x.kinematics.canonical import JointAngles

DEFAULT_SINGULARITY_THRESHOLD_DEG = 2.0


@dataclass(frozen=True)
class SingularitySpan:
    """One contiguous run of joint samples within the singular band."""

    start_index: int  # inclusive
    end_index: int  # exclusive
    entry_swivel_rad: float  # swivel value just before the span (or first value if at start)
    exit_swivel_rad: float  # swivel value just after the span (or last value if at end)


def is_in_singular_band(
    joints: JointAngles,
    *,
    threshold_rad: float = math.radians(DEFAULT_SINGULARITY_THRESHOLD_DEG),
) -> bool:
    """True if the joint configuration's tilt is within the singular band."""
    return abs(joints.tilt_rad) < threshold_rad


def find_singularity_spans(
    sequence: list[JointAngles],
    *,
    threshold_rad: float = math.radians(DEFAULT_SINGULARITY_THRESHOLD_DEG),
) -> list[SingularitySpan]:
    """Identify contiguous spans of samples inside the singular band.

    Spans at the start or end of the sequence use the first/last sample's
    own swivel as both entry and exit — no interpolation across an
    out-of-band neighbour is possible there.
    """
    if not sequence:
        return []
    in_band = [is_in_singular_band(j, threshold_rad=threshold_rad) for j in sequence]
    spans: list[SingularitySpan] = []
    i = 0
    while i < len(sequence):
        if not in_band[i]:
            i += 1
            continue
        start = i
        while i < len(sequence) and in_band[i]:
            i += 1
        end = i
        entry = sequence[start - 1].swivel_rad if start > 0 else sequence[start].swivel_rad
        exit_ = sequence[end].swivel_rad if end < len(sequence) else sequence[end - 1].swivel_rad
        spans.append(
            SingularitySpan(
                start_index=start, end_index=end, entry_swivel_rad=entry, exit_swivel_rad=exit_
            )
        )
    return spans


def smooth_through_singularity(
    sequence: list[JointAngles],
    *,
    threshold_rad: float = math.radians(DEFAULT_SINGULARITY_THRESHOLD_DEG),
    warn: bool = True,
) -> list[JointAngles]:
    """Return a new sequence with swivel linearly interpolated across singular spans.

    Tilt is left unchanged. Out-of-band samples are passed through verbatim.

    Anchoring rules:

    - **Interior span** (out-of-band neighbours on both sides): the
      neighbours' swivels are the entry/exit anchors, and every in-band
      sample is rewritten by linear interpolation.
    - **Span touches the start of the sequence**: the first in-band sample
      is itself the entry anchor (its swivel is preserved); samples after
      it are rewritten.
    - **Span touches the end of the sequence**: the last in-band sample is
      itself the exit anchor (its swivel is preserved); earlier samples are
      rewritten.
    - **Entire sequence in-band**: first and last samples anchor; only the
      interior is rewritten.

    The interpolation parameter at sample index k is
    `t = (k - entry_index) / (exit_index - entry_index)`, where
    `entry_index` and `exit_index` are the sequence indices of the anchor
    samples. Samples at those indices are skipped (no self-rewrite).

    Emits `RuntimeWarning` per span if `warn=True`.
    """
    spans = find_singularity_spans(sequence, threshold_rad=threshold_rad)
    if not spans:
        return list(sequence)
    out = list(sequence)
    for span in spans:
        entry_index = span.start_index - 1 if span.start_index > 0 else span.start_index
        exit_index = span.end_index if span.end_index < len(sequence) else span.end_index - 1
        if entry_index == exit_index:
            # Degenerate: single in-band sample with no out-of-band anchors.
            # Nothing to interpolate; leave the sample alone.
            continue
        entry_swivel = sequence[entry_index].swivel_rad
        exit_swivel = sequence[exit_index].swivel_rad
        denominator = float(exit_index - entry_index)
        for k in range(span.start_index, span.end_index):
            if k in (entry_index, exit_index):
                continue
            t = (k - entry_index) / denominator
            new_swivel = (1.0 - t) * entry_swivel + t * exit_swivel
            original = out[k]
            out[k] = JointAngles(tilt_rad=original.tilt_rad, swivel_rad=new_swivel)
        if warn:
            warnings.warn(
                f"smooth-through applied to singular span "
                f"[{span.start_index}:{span.end_index}] "
                f"(swivel {entry_swivel:.4f} → {exit_swivel:.4f} rad)",
                RuntimeWarning,
                stacklevel=2,
            )
    return out


__all__ = [
    "DEFAULT_SINGULARITY_THRESHOLD_DEG",
    "SingularitySpan",
    "find_singularity_spans",
    "is_in_singular_band",
    "smooth_through_singularity",
]
