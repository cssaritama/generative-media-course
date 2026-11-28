"""Offline stand-ins for Module 2: a scripted model and placeholder GPU backends."""

from __future__ import annotations

import asyncio
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

import pydantic_ai.models
from PIL import Image, ImageDraw
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel


def block_real_models() -> None:
    """Make any request to a real LLM fail, so a fake run cannot spend tokens by accident."""
    pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


def call(tool: str, **args: Any) -> ToolCallPart:
    """One tool call for a script."""
    return ToolCallPart(tool_name=tool, args=args)


def scripted_model(*turns: Any) -> FunctionModel:
    """A model that answers with the given turns, in order, whatever it is asked."""
    script = list(turns)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not script:
            raise RuntimeError("The scripted model ran out of turns")
        turn = script.pop(0)
        if isinstance(turn, str):
            parts = [TextPart(turn)]
        elif isinstance(turn, dict):
            parts = [ToolCallPart(info.output_tools[0].name, turn)]
        elif callable(turn):
            parts = [TextPart(turn(messages))]
        elif isinstance(turn, ToolCallPart):
            parts = [turn]
        else:
            parts = list(turn)
        return ModelResponse(parts=parts)

    return FunctionModel(respond, model_name="scripted")


def placeholder_png(text: str, width: int, height: int, seed: int = 0) -> bytes:
    """A flat-colour PNG with the prompt written on it. Same inputs, same bytes."""
    shade = (seed * 47) % 200
    img = Image.new("RGB", (width, height), (40 + shade // 4, 60, 90 + shade // 2))
    draw = ImageDraw.Draw(img)
    for i in range(0, len(text), 60):
        draw.text((16, 16 + 14 * (i // 60)), text[i : i + 60], fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class PlaceholderImages:
    """Stands in for the Sana Endpoint: same arguments, a placeholder PNG after sleep_s."""

    workload = "none"
    workload_id = "placeholder-image"

    def __init__(self, sleep_s: float = 0.05):
        self.sleep_s = sleep_s
        self.requests = 0

    async def generate(self, prompt: str, *, seed: int, width: int, height: int) -> bytes:
        self.requests += 1
        await asyncio.sleep(self.sleep_s)
        return placeholder_png(prompt, width, height, seed)


FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


class PlaceholderVideos:
    """Stands in for the Videos API on the Wan2.2 Endpoint."""

    workload = "none"
    workload_id = "placeholder-video"

    def __init__(self, state_dir: Path, render_s: float = 0.5):
        self.path = Path(state_dir) / "fake_endpoint.json"
        self.render_s = render_s

    def _load(self) -> dict[str, dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _save(self, videos: dict[str, dict]) -> None:
        self.path.write_text(json.dumps(videos, indent=2), encoding="utf-8")

    def create(self, prompt: str, image: bytes, *, user: str, params: dict) -> dict:
        videos = self._load()
        video = {"id": f"video-{uuid.uuid4().hex[:8]}", "user": user, "created_at": time.time()}
        videos[video["id"]] = video
        self._save(videos)
        return {**video, "status": "queued"}

    def get(self, video_id: str) -> dict:
        video = self._load()[video_id]
        age = time.time() - video["created_at"]
        status = "queued" if age < 0.1 else "in_progress" if age < self.render_s else "completed"
        return {**video, "status": status}

    def list(self) -> list[dict]:
        return [self.get(video_id) for video_id in self._load()]

    def content(self, video_id: str) -> bytes:
        assert self.get(video_id)["status"] == "completed"
        return FAKE_MP4

    def delete(self, video_id: str) -> None:
        videos = self._load()
        videos.pop(video_id, None)
        self._save(videos)
