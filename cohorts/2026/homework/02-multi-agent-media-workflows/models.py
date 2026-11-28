"""Pinned model specs, brief, plan, rubric, and verdict models for Homework 2."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

TOKEN_FACTORY_URL = "https://api.tokenfactory.nebius.com/v1/"


class LLMSpec(BaseModel):
    """An LLM on an OpenAI-compatible API (Nebius Token Factory)."""

    model_config = ConfigDict(frozen=True)

    model: str
    base_url: str = TOKEN_FACTORY_URL


class ImageSpec(BaseModel):
    """Text-to-image settings for the keyframe (832x480 16:9 matching Wan2.2-I2V)."""

    model_config = ConfigDict(frozen=True)

    model: str
    model_revision: str | None = None
    width: int = 832
    height: int = 480
    num_inference_steps: int = 20
    guidance_scale: float = 4.5
    seed: int = 7
    gpu: str = "L40S"

    @property
    def size(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def params(self) -> dict[str, int | float]:
        return {
            "width": self.width,
            "height": self.height,
            "num_inference_steps": self.num_inference_steps,
            "guidance_scale": self.guidance_scale,
        }


class VideoSpec(BaseModel):
    """Image-to-video settings for Wan2.2-I2V-A14B."""

    model_config = ConfigDict(frozen=True)

    model: str
    model_revision: str | None = None
    width: int = 832
    height: int = 480
    num_frames: int = 81
    fps: int = 16
    num_inference_steps: int = 20
    guidance_scale: float = 1.0
    seed: int = 0
    gpu: str = "H100"

    @property
    def duration_s(self) -> float:
        return self.num_frames / self.fps

    @property
    def params(self) -> dict[str, int | float]:
        return {
            "width": self.width,
            "height": self.height,
            "num_frames": self.num_frames,
            "fps": self.fps,
            "num_inference_steps": self.num_inference_steps,
            "guidance_scale": self.guidance_scale,
        }


# Pinned models verified in Nebius Token Factory account (2026-11-27)
LLM = LLMSpec(model="google/gemma-3-27b-it")
JUDGE = LLMSpec(model="google/gemma-3-27b-it")

SANA = ImageSpec(
    model="Efficient-Large-Model/Sana_1600M_1024px_diffusers",
    model_revision="ac0da2ff55fbe434795be0dce883042e4d49e2fc",
)
WAN_I2V = VideoSpec(model="Wan-AI/Wan2.2-I2V-A14B-Diffusers")


class Brief(BaseModel):
    """A short video brief matching the Homework 2 brief.yaml schema."""

    product: str
    audience: str
    format: str
    shot: str
    must_show: str
    must_not: str

    @field_validator("format", mode="before")
    @classmethod
    def aspect_ratio(cls, value: object) -> object:
        """YAML 1.1 reads unquoted 16:9 as base-60 int 969; convert back."""
        return f"{value // 60}:{value % 60}" if isinstance(value, int) else value

    @classmethod
    def from_yaml(cls, path: str | Path) -> Brief:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class Plan(BaseModel):
    """Planner output: one prompt per generation step."""

    image_prompt: str = Field(description="Prompt for one keyframe image that shows the shot")
    motion_prompt: str = Field(description="What moves in the 5-second clip made from it")


class Criterion(BaseModel):
    id: str
    brief_field: str
    question: str
    must_have: bool
    scope: Literal["keyframe", "video_only"]
    pass_example: str
    fail_example: str


class Rubric(BaseModel):
    """rubric.yaml: criteria that read Brief fields."""

    version: str
    criteria: list[Criterion]

    @classmethod
    def from_yaml(cls, path: str | Path) -> Rubric:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class CriterionResult(BaseModel):
    id: str
    score: Literal[0, 0.5, 1]
    assessable: bool
    note: str


class Fix(BaseModel):
    change_seed: bool
    prompt_suffix: str | None = None


class JudgeReply(BaseModel):
    """Structured JSON returned by the vision judge model."""

    criteria: list[CriterionResult]
    reasons: list[str]
    fix: Fix


class Verdict(BaseModel):
    """Typed verdict computed deterministically in code from JudgeReply."""

    verdict: Literal["PASS", "RETRY", "WEAK"]
    score: float
    criteria: list[CriterionResult]
    reasons: list[str]
    fix: Fix
    rubric_version: str
    judge_model: str


def map_verdict(reply: JudgeReply, rubric: Rubric, judge_model: str) -> Verdict:
    """Can't assess a keyframe criterion -> WEAK; any must_have < 1 -> RETRY; else PASS."""
    keyframe = {c.id: c for c in rubric.criteria if c.scope == "keyframe"}
    results = [r for r in reply.criteria if r.id in keyframe]
    if len(results) < len(keyframe) or not all(r.assessable for r in results):
        verdict: Literal["PASS", "RETRY", "WEAK"] = "WEAK"
    elif any(r.score < 1 and keyframe[r.id].must_have for r in results):
        verdict = "RETRY"
    else:
        verdict = "PASS"
    avg_score = round(sum(r.score for r in results) / len(results), 3) if results else 0.0
    return Verdict(
        verdict=verdict,
        score=avg_score,
        criteria=results,
        reasons=reply.reasons,
        fix=reply.fix,
        rubric_version=rubric.version,
        judge_model=judge_model,
    )
