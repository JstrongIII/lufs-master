"""
LUFS Master Backend
FastAPI server for audio loudness normalization to -8 LUFS
"""
import os
import re
import json
import uuid
import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

# Configuration
TARGET_LUFS = float(os.getenv("TARGET_LUFS", "-8"))
TEMP_DIR = Path("./temp")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit

# Ensure temp directory exists
TEMP_DIR.mkdir(exist_ok=True)


def cleanup_files(*paths):
    """Remove temp files."""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def normalize_audio(input_path: str, output_path: str, target_lufs: float) -> dict:
    """
    Two-pass loudness normalization using FFmpeg loudnorm filter.
    First pass measures, second pass applies normalization.
    """
    # First pass — measure input loudness
    measure_cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    
    result = subprocess.run(measure_cmd, capture_output=True, text=True)
    
    # Parse JSON output from stderr
    json_match = re.search(r'\{[^}]+\}', result.stderr, re.DOTALL)
    if not json_match:
        raise ValueError("Could not measure audio loudness. Is FFmpeg installed?")
    
    measured = json.loads(json_match.group())
    
    measured_i = measured["input_i"]
    measured_tp = measured["input_tp"]
    measured_lra = measured["input_lra"]
    measured_thresh = measured["input_thresh"]
    offset = measured["target_offset"]
    
    # Second pass — apply normalization
    apply_cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", (
            f"loudnorm="
            f"I={target_lufs}:"
            f"TP={measured_tp}:"
            f"LRA={measured_lra}:"
            f"measured_I={measured_i}:"
            f"measured_TP={measured_tp}:"
            f"measured_LRA={measured_lra}:"
            f"measured_thresh={measured_thresh}:"
            f"offset={offset}:"
            f"linear=true"
        ),
        "-ar", "48000",
        "-c:a", "libmp3lame",
        "-b:a", "320k",
        output_path
    ]
    
    subprocess.run(apply_cmd, capture_output=True, text=True)
    
    return {
        "target_lufs": target_lufs,
        "measured_lufs": float(measured_i),
        "true_peak": float(measured_tp),
        "loudness_range": float(measured_lra)
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    # Cleanup old temp files on startup
    for f in TEMP_DIR.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    yield


app = FastAPI(
    title="LUFS Master",
    description="Audio loudness normalization to -8 LUFS",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for Telegram Mini App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Health check."""
    return {
        "status": "ok",
        "target_lufs": TARGET_LUFS,
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "target_lufs": TARGET_LUFS}


@app.post("/master")
async def master_track(
    file: UploadFile = File(...),
    target_lufs: Optional[float] = Form(None)
):
    """
    Master an audio file to target LUFS.
    
    Args:
        file: Audio file (MP3, WAV, FLAC, OGG, M4A)
        target_lufs: Optional override for target LUFS (default: -8)
    
    Returns:
        Mastered audio file as MP3
    """
    # Use provided target or default
    target = target_lufs if target_lufs is not None else TARGET_LUFS
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())[:8]
    
    # Determine input extension
    ext = Path(file.filename).suffix.lower().lstrip(".") or "mp3"
    allowed_extensions = {"mp3", "wav", "flac", "ogg", "m4a", "aac", "wma"}
    
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Supported: {', '.join(allowed_extensions)}"
        )
    
    input_path = TEMP_DIR / f"{job_id}_input.{ext}"
    output_path = TEMP_DIR / f"{job_id}_output.mp3"
    
    # Save uploaded file
    try:
        content = await file.read()
        
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
        
        with open(input_path, "wb") as f:
            f.write(content)
        
        # Normalize audio
        stats = normalize_audio(str(input_path), str(output_path), target)
        
        # Verify output exists
        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Processing failed")
        
        output_filename = f"mastered_{abs(target)}lufs_{job_id}.mp3"
        
        return FileResponse(
            path=str(output_path),
            media_type="audio/mpeg",
            filename=output_filename,
            background=cleanup_files(str(input_path), str(output_path))
        )
        
    except HTTPException:
        cleanup_files(str(input_path), str(output_path))
        raise
    except Exception as e:
        cleanup_files(str(input_path), str(output_path))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/info")
async def get_audio_info(file: UploadFile = File(...)):
    """Get loudness info for an audio file without normalizing."""
    job_id = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix.lower().lstrip(".") or "mp3"
    input_path = TEMP_DIR / f"{job_id}_input.{ext}"
    
    try:
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)
        
        # Measure only
        measure_cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", "loudnorm=print_format=json",
            "-f", "null", "-"
        ]
        
        result = subprocess.run(measure_cmd, capture_output=True, text=True)
        json_match = re.search(r'\{[^}]+\}', result.stderr, re.DOTALL)
        
        if json_match:
            measured = json.loads(json_match.group())
            return {
                "filename": file.filename,
                "integrated_loudness": float(measured.get("input_i", 0)),
                "true_peak": float(measured.get("input_tp", 0)),
                "loudness_range": float(measured.get("input_lra", 0)),
                "shortterm_max": float(measured.get("input_thresh", 0))
            }
        
        return {"error": "Could not analyze audio"}
        
    finally:
        cleanup_files(str(input_path))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)