"""Shared tools for Homework 2: typed arguments, spec hash cache, and GPU backends."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

import boto3
import requests
from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from models import LLM, SANA, LLMSpec
from tracing import Tracer

CODE_DIR = Path(__file__).resolve().parent
REPO_DIR = CODE_DIR.parent
TRANSPORT_RETRIES = 3


def read_env() -> dict[str, str]:
    """Read KEY=VALUE pairs from repository .env or code .env."""
    values: dict[str, str] = {}
    for candidate in [REPO_DIR / ".env", CODE_DIR / ".env"]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    values[k.strip()] = v.strip()
    return values


def optional_setting(key: str) -> str | None:
    return read_env().get(key) or os.getenv(key) or None


def settings(*keys: str) -> dict[str, str]:
    saved = read_env()
    for key in keys:
        val = saved.get(key) or os.getenv(key)
        if not val:
            raise KeyError(f"{key} is not set in .env or the environment")
        saved[key] = val
    return {k: saved[k] for k in keys}


def token_factory_model(spec: LLMSpec = LLM) -> OpenAIChatModel:
    """Return a PydanticAI model for a Token Factory LLM."""
    key = (
        optional_setting("NEBIUS_TOKEN_FACTORY_API_KEY")
        or optional_setting("NEBIUS_API_KEY")
    )
    if not key:
        raise KeyError("NEBIUS_TOKEN_FACTORY_API_KEY is not configured")
    provider = OpenAIProvider(base_url=spec.base_url, api_key=key)
    return OpenAIChatModel(spec.model, provider=provider)


class Store:
    """Assets of one run: local run folder always; optional S3 bucket."""

    def __init__(self, folder: Path, bucket: str | None = None):
        self.folder = folder
        self.bucket = bucket
        self.prefix = "runs/" + folder.name
        endpoint = optional_setting("S3_ENDPOINT_URL") or "https://storage.eu-north1.nebius.cloud"
        self._s3 = boto3.client("s3", endpoint_url=endpoint) if bucket else None

    def path(self, name: str) -> Path:
        return self.folder / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def uri(self, name: str) -> str:
        return f"s3://{self.bucket}/{self.prefix}/{name}" if self.bucket else str(self.path(name))

    def put(self, name: str, data: bytes) -> str:
        self.path(name).parent.mkdir(parents=True, exist_ok=True)
        self.path(name).write_bytes(data)
        if self._s3:
            self._s3.put_object(Bucket=self.bucket, Key=f"{self.prefix}/{name}", Body=data)
        return self.uri(name)

    def upload_run(self) -> None:
        """Copy the trace, metrics, tickets and messages to the bucket at the end of a run."""
        if not self._s3:
            return
        for path in self.folder.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".jsonl"):
                key = f"{self.prefix}/{path.relative_to(self.folder)}"
                self._s3.upload_file(str(path), self.bucket, key)


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def spec_hash(
    *,
    model: str,
    prompt: str,
    seed: int,
    params: dict[str, Any],
    model_revision: str | None = None,
    image: str | None = None,
    inputs: Sequence[str | Path] = (),
    adapter: str | None = None,
) -> str:
    spec = {
        "model": model,
        "model_revision": model_revision,
        "image": image,
        "prompt": prompt,
        "seed": seed,
        "params": params,
        "inputs": [file_sha256(p) for p in inputs],
        "adapter": adapter,
    }
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class ImageBackend(Protocol):
    workload: str
    workload_id: str

    async def generate(self, prompt: str, *, seed: int, width: int, height: int) -> bytes: ...


class SanaEndpoint:
    """The Sana Endpoint on Nebius Serverless AI."""

    workload = "endpoint"

    def __init__(self, base_url: str, token: str, endpoint_id: str):
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.workload_id = endpoint_id

    async def generate(self, prompt: str, *, seed: int, width: int, height: int) -> bytes:
        body = {
            "model": SANA.model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "n": 1,
            "response_format": "b64_json",
            "num_inference_steps": SANA.num_inference_steps,
            "guidance_scale": SANA.guidance_scale,
            "seed": seed,
        }
        url = f"{self.base_url}/v1/images/generations"
        for attempt in range(TRANSPORT_RETRIES + 1):
            try:
                r = await asyncio.to_thread(
                    requests.post,
                    url,
                    json=body,
                    headers=self.headers,
                    timeout=(10, 300),
                )
            except requests.ConnectTimeout:
                r = None
            if r is not None and r.status_code not in (502, 503):
                break
            if attempt == TRANSPORT_RETRIES:
                raise RuntimeError("Endpoint unreachable or not ready after retries")
            await asyncio.sleep(2**attempt)
        r.raise_for_status()
        return base64.b64decode(r.json()["data"][0]["b64_json"])


def gpu_cost(price_per_hour: float | None, t_gen_s: float) -> float:
    return (price_per_hour or 0.0) / 3600 * t_gen_s


@dataclass
class ToolDeps:
    tracer: Tracer
    images: ImageBackend
    store: Store
    gpu_price_per_hour: float | None = None
    attempt: int | None = None


class AssetRef(BaseModel):
    uri: str
    spec_hash: str
    width: int
    height: int
    workload: str
    workload_id: str
    cache_hit: bool = False
    t_gen_s: float | None = None


Size = Literal["832x480", "480x832", "1024x1024"]
Prompt = Annotated[str, Field(min_length=10, max_length=600)]


async def image_asset(
    images: ImageBackend, store: Store, prompt: str, seed: int, size: Size
) -> AssetRef:
    width, height = (int(side) for side in size.split("x"))
    params = {**SANA.params, "width": width, "height": height}
    key = spec_hash(
        model=SANA.model,
        model_revision=SANA.model_revision,
        prompt=prompt,
        seed=seed,
        params=params,
    )
    name = f"keyframe-{key[:12]}.png"
    ref = {
        "spec_hash": key,
        "width": width,
        "height": height,
        "uri": store.uri(name),
        "workload": images.workload,
        "workload_id": images.workload_id,
    }
    if store.exists(name):
        return AssetRef(cache_hit=True, **ref)

    start = time.perf_counter()
    png = await images.generate(prompt, seed=seed, width=width, height=height)
    t_gen_s = round(time.perf_counter() - start, 3)
    store.put(name, png)
    return AssetRef(t_gen_s=t_gen_s, **ref)


def trace_asset(deps: ToolDeps, call_id: str | None, name: str, asset: AssetRef) -> None:
    deps.tracer.emit(
        "tool_call",
        name,
        call_id=call_id,
        workload=asset.workload,
        workload_id=asset.workload_id,
        attempt=deps.attempt,
        cache_hit=asset.cache_hit,
        t_gen_s=asset.t_gen_s,
        wall_s=asset.t_gen_s or 0.0,
        cost_usd=gpu_cost(deps.gpu_price_per_hour, asset.t_gen_s or 0.0),
        asset_ref=asset.uri,
    )


async def generate_image(
    ctx: RunContext[ToolDeps],
    prompt: Prompt,
    seed: int = SANA.seed,
    size: Size = "832x480",
) -> AssetRef:
    asset = await image_asset(ctx.deps.images, ctx.deps.store, prompt, seed, size)
    trace_asset(ctx.deps, ctx.tool_call_id, "generate_image", asset)
    return asset
