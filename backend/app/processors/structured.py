from __future__ import annotations

import json
import os
import re
import time
import traceback
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.processors.structured_keys import ALLOWED_KEYS

MAX_CHARS_TO_MODEL = int(os.getenv("STRUCTURED_MAX_CHARS", "12000"))
MAX_MODEL_ATTEMPTS = int(os.getenv("STRUCTURED_LLM_ATTEMPTS", "2"))

_llm_singleton = None


@dataclass
class ExtractedClaim:
    key: str
    value: Any
    unit: Optional[str] = None
    confidence: float = 0.5
    evidence: Optional[str] = None


# --- Public helpers (used by discovery + NL search) ---

def get_llm():
    return _get_llm()


def run_llm(llm, prompt: str) -> str:
    return _run_llm(llm, prompt)


def parse_json_loose(text: str) -> dict[str, Any]:
    return _parse_json_loose(text)


# --- Main entrypoint ---

def extract_claims_from_text(db: Session, artifact: models.Artifact) -> None:
    segments = (
        db.query(models.ArtifactTextSegment)
        .filter(models.ArtifactTextSegment.artifact_id == artifact.id)
        .order_by(models.ArtifactTextSegment.segment_index.asc())
        .all()
    )
    raw_text = "\n".join((s.text or "") for s in segments).strip()

    if not raw_text:
        _overwrite_claims(db, artifact, [])
        return

    text = raw_text[:MAX_CHARS_TO_MODEL]
    print(f"[structured] START artifact={artifact.id} segs={len(segments)} chars={len(raw_text)}", flush=True)

    llm = _get_llm()
    prompt = _build_prompt(text)
    print(f"[structured] prompt_chars={len(prompt)}", flush=True)



    claims: list[ExtractedClaim] = []
    last_err: Optional[Exception] = None

    for _attempt in range(1, MAX_MODEL_ATTEMPTS + 1):
        try:
            print(f"[structured] attempting to run model")
            out_text = _run_llm(llm, prompt)
            print(f"[structured] llm returned out_chars={len(out_text)}", flush=True)
            data = _parse_json_loose(out_text)

            raw_claims = data.get("claims", [])
            if not isinstance(raw_claims, list):
                raise ValueError("JSON 'claims' must be a list")

            cleaned: list[ExtractedClaim] = []
            for item in raw_claims:
                ec = _coerce_claim(item)
                ec2 = _validate_and_normalize(ec)
                if ec2 is not None:
                    cleaned.append(ec2)

            claims = _dedupe_claims(cleaned)
            last_err = None
            break
        except Exception as e:
            last_err = e
            prompt = _build_repair_prompt(text, bad_output=str(e))

    if last_err is not None and not claims:
        _overwrite_claims(db, artifact, [])
        return

    _overwrite_claims(db, artifact, claims)


def _overwrite_claims(db: Session, artifact: models.Artifact, claims: list[ExtractedClaim]) -> None:
    db.query(models.Claim).filter(models.Claim.artifact_id == artifact.id).delete()

    claim_cols = set(models.Claim.__table__.columns.keys())

    for c in claims:
        kwargs = {
            "artifact_id": artifact.id,
            "building_id": artifact.building_id,
            "field_key": c.key,
            "value_json": json.dumps(c.value),
            "unit": c.unit,
            "confidence": float(c.confidence),
            "source_ref": "structured:llamacpp",
        }
        if "evidence" in claim_cols:
            kwargs["evidence"] = c.evidence

        db.add(models.Claim(**kwargs))

    db.commit()


# --- llama-cpp backend ---

def _get_llm():
    global _llm_singleton
    if _llm_singleton is not None:
        return _llm_singleton

    gguf_path = os.getenv("LLAMA_GGUF_PATH")
    if not gguf_path:
        raise RuntimeError("LLAMA_GGUF_PATH is not set (path to .gguf model file).")

    try:
        from llama_cpp import Llama
    except Exception as e:
        raise RuntimeError("llama-cpp-python is not installed. Run: pip install llama-cpp-python") from e

    n_ctx = int(os.getenv("LLAMA_N_CTX", "4096"))
    n_threads = int(os.getenv("LLAMA_THREADS", "8"))
    n_gpu_layers = int(os.getenv("LLAMA_GPU_LAYERS", "0"))

    _llm_singleton = Llama(
        model_path=gguf_path,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
        logits_all=False,
        vocab_only=False,
        verbose=True,
    )
    return _llm_singleton


def _run_llm(llm, prompt: str) -> str:
    print("[structured] ENTER _run_llm", flush=True)

    temp_raw = os.getenv("LLAMA_TEMPERATURE", "0.1")
    max_raw = os.getenv("LLAMA_MAX_TOKENS", "700")
    print(f"[structured] env temp={temp_raw!r} max_tokens={max_raw!r}", flush=True)

    temperature = float(temp_raw)
    max_tokens = int(max_raw)
    stop = ["```", "\n\n\n", "</json>"]

    print("[structured] about to call llm(...)", flush=True)
    t0 = time.time()
    try:
        out = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )
    except Exception as e:
        print("[structured] llm(...) raised:", repr(e), flush=True)
        traceback.print_exc()
        raise

    dt = time.time() - t0
    print(f"[structured] llm(...) returned in {dt:.2f}s; keys={list(out.keys())}", flush=True)

    text = out["choices"][0]["text"]
    print(f"[structured] out_text_chars={len(text)}", flush=True)
    return text.strip()

    # print("[structured] ENTER _run_llm", flush=True)

    # temp_raw = os.getenv("LLAMA_TEMPERATURE", "0.1")
    # max_raw = os.getenv("LLAMA_MAX_TOKENS", "700")

    # print(
    #     f"[structured] env LLAMA_TEMPERATURE={temp_raw!r} "
    #     f"LLAMA_MAX_TOKENS={max_raw!r}",
    #     flush=True,
    # )

    # temperature = float(os.getenv("LLAMA_TEMPERATURE", "0.1"))
    # max_tokens = int(os.getenv("LLAMA_MAX_TOKENS", "700"))
    # stop = ["```", "\n\n\n", "</json>"]

    # chunks: list[str] = []
    # last_log = time.time()
    # print("[structured] calling llama...", flush=True)
    # # stream=True yields partial chunks
    # for part in llm(
    #     prompt,
    #     max_tokens=max_tokens,
    #     temperature=temperature,
    #     stop=stop,
    #     stream=True,
    # ):
    #     delta = part["choices"][0].get("text", "")
    #     if delta:
    #         chunks.append(delta)

    #     # periodic progress log so you can *see* tokens coming
    #     now = time.time()
    #     if now - last_log > 2.0:
    #         total = sum(len(c) for c in chunks)
    #         print(f"[structured] streaming... out_chars={total}", flush=True)
    #         last_log = now

    # return "".join(chunks).strip()
#    temperature = float(os.getenv("LLAMA_TEMPERATURE", "0.1"))
#    max_tokens = int(os.getenv("LLAMA_MAX_TOKENS", "700"))
#    stop = ["```", "\n\n\n", "</json>"]####
#
#    out = llm(prompt, max_tokens=max_tokens, temperature=temperature, stop=stop)
#    return out["choices"][0]["text"].strip()


# --- Prompting ---

def _build_prompt(text: str) -> str:
    key_lines = []
    for k, spec in ALLOWED_KEYS.items():
        if spec.get("unit"):
            key_lines.append(f"- {k} ({spec.get('type')}, unit: {spec['unit']})")
        else:
            key_lines.append(f"- {k} ({spec.get('type')})")
    allowed_block = "\n".join(key_lines)

    return f"""You extract structured facts from a document.

ONLY output claims whose key is one of the allowed keys below.
Do NOT invent new keys. Do NOT guess.

Allowed keys:
{allowed_block}

Return ONLY valid JSON of this form:
{{
  "claims": [
    {{"key":"...", "value": ..., "confidence": 0.0, "evidence":"short exact quote"}}
  ]
}}

Document:
\"\"\"{text}\"\"\"

JSON:
"""


def _build_repair_prompt(text: str, bad_output: str) -> str:
    return f"""The previous output was invalid. Fix it.

Error/context:
{bad_output}

Return ONLY valid JSON with the required schema, no extra text.

Document:
\"\"\"{text}\"\"\"

JSON:
"""


# --- JSON parsing / cleaning ---

def _parse_json_loose(s: str) -> dict[str, Any]:
    s = s.strip()
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output")
    return json.loads(m.group(0))


def _coerce_claim(item: Any) -> ExtractedClaim:
    if not isinstance(item, dict):
        raise ValueError("claim must be an object")
    key = str(item.get("key", "")).strip()
    return ExtractedClaim(
        key=key,
        value=item.get("value"),
        unit=item.get("unit"),
        confidence=float(item.get("confidence", 0.5) or 0.5),
        evidence=(str(item.get("evidence")).strip() if item.get("evidence") else None),
    )


def _validate_and_normalize(c: ExtractedClaim) -> Optional[ExtractedClaim]:
    if not c.key or c.key not in ALLOWED_KEYS:
        return None

    spec = ALLOWED_KEYS[c.key]
    t = spec.get("type")

    if t == "bool":
        if isinstance(c.value, bool):
            pass
        elif isinstance(c.value, str) and c.value.lower() in ("true", "false"):
            c.value = (c.value.lower() == "true")
        else:
            return None

    elif t == "number":
        try:
            c.value = float(c.value)
        except Exception:
            return None

    elif t == "string":
        c.value = str(c.value).strip()

    # canonical unit from schema
    c.unit = spec.get("unit") or c.unit

    c.confidence = max(0.0, min(1.0, float(c.confidence)))
    return c


def _dedupe_claims(claims: list[ExtractedClaim]) -> list[ExtractedClaim]:
    best: dict[str, ExtractedClaim] = {}
    for c in claims:
        if c.key not in best or c.confidence > best[c.key].confidence:
            best[c.key] = c
    return list(best.values())
