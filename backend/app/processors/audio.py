from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.services.storage import get_artifact_path

# Env-configurable defaults
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny/base/small/medium/large-v3
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")  # auto/cpu/cuda
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto")  # auto/int8/float16
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE")  # e.g. "en" or None for auto-detect


def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH. Install with `brew install ffmpeg`."
        )


def _extract_audio_to_wav(src: Path, dst_wav: Path) -> None:
    """
    Convert any audio/video file into 16kHz mono WAV for whisper.
    """
    _ensure_ffmpeg()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vn",                  # no video
        "-ac",
        "1",                    # mono
        "-ar",
        "16000",                # 16kHz
        "-f",
        "wav",
        str(dst_wav),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-2000:]}")  # keep tail


def _upsert_text_segment(db: Session, artifact_id: int, text: str) -> None:
    """
    Store transcript into artifact_text_segments as segment_index=0.
    If segment 0 exists, overwrite; else create.
    """
    seg = (
        db.query(models.ArtifactTextSegment)
        .filter(
            models.ArtifactTextSegment.artifact_id == artifact_id,
            models.ArtifactTextSegment.segment_index == 0,
        )
        .first()
    )

    if seg is None:
        seg = models.ArtifactTextSegment(
            artifact_id=artifact_id,
            segment_index=0,
            text=text,
            source_ref="transcript",  # if you have a 'source' column; otherwise remove this line
        )
        db.add(seg)
    else:
        seg.text = text

    db.commit()


def transcribe_audio_video(db: Session, artifact: models.Artifact) -> None:
    """
    Transcribe an audio or video artifact using faster-whisper and store transcript.

    Expected:
      - artifact.storage_path points to local file (via get_artifact_path())
      - artifact.kind is "audio" or "video" (or mime type indicates it)
    """
    path = get_artifact_path(artifact)
    if not path.exists():
        raise RuntimeError(f"Artifact file does not exist: {path}")

    # Convert to wav (safe format for whisper)
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wav_path = td_path / "audio.wav"
        _extract_audio_to_wav(path, wav_path)

        # Import here to avoid import-time crashes if dependency missing
        try:
            from faster_whisper import WhisperModel
        except Exception as e:
            raise RuntimeError(
                "Missing dependency faster-whisper. Install with `pip install faster-whisper`."
            ) from e

        model_name = os.getenv("WHISPER_MODEL", WHISPER_MODEL)
        device = os.getenv("WHISPER_DEVICE", WHISPER_DEVICE)
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", WHISPER_COMPUTE_TYPE)
        language = os.getenv("WHISPER_LANGUAGE", WHISPER_LANGUAGE)

        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        print(f"[audio] about to transcribe") 
        # segments is a generator of (start,end,text)
        segments, info = model.transcribe(
            str(wav_path),
            language=language,       # None => auto-detect
            vad_filter=True,         # helps for long clips
        )
        print(f"[audio] transcribe returned; iterating segments...", flush=True)
        parts: list[str] = []
        for s in segments:
            # You can include timestamps if you want:
            # parts.append(f"[{s.start:.2f}-{s.end:.2f}] {s.text.strip()}")
            parts.append(s.text.strip())

        transcript = "\n".join([p for p in parts if p]).strip()

        if not transcript:
            transcript = "(no transcript produced)"
        print(f"[audio] transcribe returned; iterating segments...", flush=True)
        # Save transcript in DB
        _upsert_text_segment(db, artifact.id, transcript)

        # Optional: set artifact.text_content too for quick rendering/search
        artifact.text_content = transcript
        artifact.status = "processed"
        artifact.error_message = None
        db.add(artifact)
        db.commit()
