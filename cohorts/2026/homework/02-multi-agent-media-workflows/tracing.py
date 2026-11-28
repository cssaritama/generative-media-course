"""JSONL trace for Homework 2 matching the Module 2 trace contract."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

RUNS = Path(__file__).resolve().parent / "runs"

Kind = Literal["model_request", "tool_call", "judge", "check", "ticket", "budget", "node"]
STOP_REASONS = (
    "done",
    "attempts_exhausted",
    "budget_exhausted",
    "judge_unparseable",
    "weak",
    "needs_reconcile",
    "poll_timeout",
    "unchanged_retry",
    "video_denied",
)


class Event(BaseModel):
    """One line of events.jsonl adhering to the Module 2 trace contract."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    parent_id: str | None = None
    run_id: str
    framework_run_id: str | None = None
    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    kind: Kind
    name: str
    call_id: str | None = None
    tool_call_ids: list[str] | None = None
    workload: Literal["endpoint", "job", "llm", "none"] = "none"
    workload_id: str | None = None
    request_id: str | None = None
    attempt: int | None = None
    verdict: Literal["PASS", "RETRY", "WEAK"] | None = None
    rubric_version: str | None = None
    judge_model: str | None = None
    reasons: list[str] | None = None
    cache_hit: bool = False
    possible_duplicate: bool = False
    stop_reason: str | None = None
    t_gen_s: float | None = None
    wall_s: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float = 0.0
    asset_ref: str | None = None


class LLMPrice(BaseModel):
    """USD per 1M tokens on Nebius Token Factory."""

    input_per_m: float
    output_per_m: float

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.input_per_m + tokens_out * self.output_per_m) / 1e6


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]


def run_folder(run_id: str) -> Path:
    folder = RUNS / run_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def read_events(path: str | Path) -> list[Event]:
    path = Path(path)
    if not path.exists():
        return []
    return [Event.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class Tracer:
    """Append events to hw2/runs/<run_id>/events.jsonl."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.folder = run_folder(run_id)
        self.path = self.folder / "events.jsonl"
        self.framework_run_id: str | None = None
        self._parents: dict[str, str] = {}
        for event in self.events():
            for call_id in event.tool_call_ids or []:
                self._parents[call_id] = event.event_id

    def emit(self, kind: Kind, name: str, **fields: Any) -> Event:
        call_id = fields.get("call_id")
        if call_id and "parent_id" not in fields:
            fields["parent_id"] = self._parents.get(call_id)
        event = Event(
            run_id=self.run_id,
            framework_run_id=self.framework_run_id,
            kind=kind,
            name=name,
            **fields,
        )
        for issued in event.tool_call_ids or []:
            self._parents[issued] = event.event_id
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event

    def stop(self, reason: str, **fields: Any) -> Event:
        assert reason in STOP_REASONS, reason
        return self.emit("check", "run_end", stop_reason=reason, **fields)

    def events(self) -> list[Event]:
        return read_events(self.path)


def save_messages(folder: Path, messages: list) -> Path:
    path = folder / "messages.json"
    path.write_bytes(ModelMessagesTypeAdapter.dump_json(messages, indent=2))
    return path


def load_messages(folder: Path) -> list:
    return ModelMessagesTypeAdapter.validate_json((folder / "messages.json").read_bytes())


def last_tool_return(messages: list[ModelMessage]) -> Any:
    for message in reversed(messages):
        for part in reversed(message.parts):
            if isinstance(part, ToolReturnPart):
                return part.content
    return None


def model_request_event(
    tracer: Tracer, response: ModelResponse, wall_s: float, price: LLMPrice | None
) -> Event:
    calls = [p for p in response.parts if isinstance(p, ToolCallPart)]
    tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
    return tracer.emit(
        "model_request",
        ",".join(c.tool_name for c in calls) or "text",
        tool_call_ids=[c.tool_call_id for c in calls],
        workload="llm",
        workload_id=response.model_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=price.cost(tokens_in, tokens_out) if price else 0.0,
        wall_s=round(wall_s, 3),
    )


async def run_traced(
    agent: Agent,
    prompt: Any = None,
    *,
    tracer: Tracer,
    deps: Any = None,
    price: LLMPrice | None = None,
    **run_kwargs: Any,
):
    started = time.perf_counter()
    async with agent.iter(prompt, deps=deps, **run_kwargs) as run:
        async for node in run:
            if Agent.is_call_tools_node(node):
                response = node.model_response
                tracer.framework_run_id = getattr(response, "run_id", None)
                model_request_event(tracer, response, time.perf_counter() - started, price)
                save_messages(tracer.folder, run.all_messages())
            started = time.perf_counter()
    save_messages(tracer.folder, run.all_messages())
    return run.result


def step_of(event: Event) -> str:
    if event.kind == "model_request":
        return "llm"
    if event.kind == "judge":
        return "judge"
    if event.kind == "ticket" or event.name == "generate_video":
        return "video"
    if event.name == "generate_image":
        return "keyframe"
    return event.name


def summarize(events: list[Event]) -> dict[str, Any]:
    judged = [e for e in events if e.kind == "judge" and e.name == "judge" and e.verdict]
    passed = {e.attempt for e in judged if e.verdict == "PASS"}
    keyframes = [
        e for e in events if e.name == "generate_image" and e.kind == "tool_call" and e.t_gen_s
    ]
    videos = [e for e in events if e.kind == "ticket" and e.t_gen_s is not None]
    all_gen_s = sum(e.t_gen_s for e in events if e.t_gen_s is not None)
    rejected_s = sum(e.t_gen_s for e in keyframes if e.attempt not in passed)

    cost_by_step: dict[str, float] = {}
    for e in events:
        if e.cost_usd:
            cost_by_step[step_of(e)] = cost_by_step.get(step_of(e), 0.0) + e.cost_usd
    stops = [e.stop_reason for e in events if e.stop_reason]
    return {
        "steps": sum(e.kind in ("model_request", "tool_call") for e in events),
        "judge_calls": sum(e.kind == "judge" for e in events),
        "attempts": {
            "keyframe": len(keyframes),
            "video": len({e.request_id for e in events if e.kind == "ticket" and e.request_id}),
        },
        "accept_rate": len(passed) / len(judged) if judged else None,
        "rejected_share": rejected_s / all_gen_s if judged and all_gen_s else None,
        "llm_tokens": sum(
            (e.tokens_in or 0) + (e.tokens_out or 0)
            for e in events
            if e.kind in ("model_request", "judge")
        ),
        "latency_s": [e.t_gen_s for e in keyframes],
        "video_latency_s": [e.t_gen_s for e in videos],
        "cost_by_step": cost_by_step,
        "marginal_cost_usd": sum(e.cost_usd for e in events),
        "possible_duplicates": sum(e.possible_duplicate for e in events),
        "stop_reason": stops[-1] if stops else None,
    }


def write_metrics(tracer: Tracer, **extra: Any) -> dict[str, Any]:
    metrics = {"schema_version": 1, "run_id": tracer.run_id, **summarize(tracer.events())}
    metrics.update(extra)
    (tracer.folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics
