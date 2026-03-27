"""Target risk classification and UI presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.core.enums import SessionTargetKind, TargetRiskLevel


@dataclass(slots=True, frozen=True)
class RiskPresentation:
    label: str
    background: str
    color: str


_PROD_MARKERS = ("prod", "production", "live")
_STAGE_MARKERS = ("stage", "staging", "preprod")


def classify_target_risk(
    *,
    target_kind: SessionTargetKind,
    target_ref: str | None,
    workspace_name: str,
    workspace_root: str,
) -> TargetRiskLevel:
    haystack = " ".join(
        part.strip().lower()
        for part in (target_ref or "", workspace_name, workspace_root)
        if part
    )
    if any(marker in haystack for marker in _PROD_MARKERS):
        return TargetRiskLevel.PROD
    if any(marker in haystack for marker in _STAGE_MARKERS):
        return TargetRiskLevel.STAGE
    if target_kind is SessionTargetKind.SSH:
        return TargetRiskLevel.STAGE
    return TargetRiskLevel.DEV


def risk_presentation(level: TargetRiskLevel) -> RiskPresentation:
    if level is TargetRiskLevel.PROD:
        return RiskPresentation(label="PROD", background="#7a1f1f", color="#ffffff")
    if level is TargetRiskLevel.STAGE:
        return RiskPresentation(label="STAGE", background="#8a6d1d", color="#111111")
    return RiskPresentation(label="DEV", background="#1e5f3b", color="#ffffff")
