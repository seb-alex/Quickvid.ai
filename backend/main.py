from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple
import logging
import os
import shutil
import subprocess
import tempfile
import uuid

from fastapi import APIRouter, BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from gradio_client import Client as GradioClient, handle_file
from imageio_ffmpeg import get_ffmpeg_exe
from pydantic import BaseModel, Field

try:
    from supabase import Client as SupabaseClient, create_client
except Exception:  # pragma: no cover
    SupabaseClient = Any  # type: ignore
    create_client = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="QuickVid AI API")
api_router = APIRouter()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
VIDEO_DIR = STATIC_DIR / "videos"
UPLOAD_DIR = STATIC_DIR / "uploads"
FE_DIST = BASE_DIR.parent / "frontend" / "dist"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

HF_SPACE_ID = os.getenv("HF_SPACE_ID", "ByteDance/AnimateDiff-Lightning")
HF_API_NAME = os.getenv("HF_API_NAME", "/generate_image")

# Image-to-Video space (Wan2.1 recommended by research)
IMG2VID_SPACE_ID = os.getenv("IMG2VID_SPACE_ID", "multimodalart/Wan2.1-Fast")
IMG2VID_API_NAME = os.getenv("IMG2VID_API_NAME", "/predict")

# Optional enhancement models
MUSIC_SPACE_ID = os.getenv("MUSIC_SPACE_ID", "facebook/MusicGen")
MUSIC_API_NAME = os.getenv("MUSIC_API_NAME", "/predict_batched")
UPSCALER_SPACE_ID = os.getenv("UPSCALER_SPACE_ID", "Nick088/RealESRGAN_Pytorch")
UPSCALER_API_NAME = os.getenv("UPSCALER_API_NAME", "/predict")

# Supabase storage (production)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

MAX_LIST_LIMIT = 50

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount frontend dist for production SPA serving
if FE_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FE_DIST / "assets")), name="frontend_assets")


class VideoRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=500)
    add_music: bool = False
    music_prompt: Optional[str] = Field(default=None, max_length=300)
    upscale: bool = False
    upscale_factor: str = Field(default="2x", pattern="^(2x|4x)$")


class VideoResponse(BaseModel):
    job_id: str
    status: str
    video_url: Optional[str] = None
    error: Optional[str] = None
    music_added: bool = False
    upscaled: bool = False
    warnings: List[str] = Field(default_factory=list)


class VideoListItem(BaseModel):
    filename: str
    video_url: str
    created_at: str


class VideoListResponse(BaseModel):
    videos: List[VideoListItem]


# In-memory storage for current/previous job status
jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = Lock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_job(job_id: str, **fields: Any) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(fields)


def extract_local_path(payload: Any, allowed_suffixes: Set[str]) -> Optional[Path]:
    """Walk nested Gradio output and return first existing local file matching suffixes."""
    if isinstance(payload, str):
        path = Path(payload)
        if path.exists() and path.suffix.lower() in allowed_suffixes:
            return path
        return None

    if isinstance(payload, dict):
        priority_keys = ("video", "audio", "path", "name", "value")
        for key in priority_keys:
            if key in payload:
                found = extract_local_path(payload[key], allowed_suffixes)
                if found:
                    return found
        for value in payload.values():
            found = extract_local_path(value, allowed_suffixes)
            if found:
                return found
        return None

    if isinstance(payload, (list, tuple)):
        for item in payload:
            found = extract_local_path(item, allowed_suffixes)
            if found:
                return found

    return None


def run_ffmpeg(args: List[str], err_ctx: str) -> None:
    ffmpeg = get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{err_ctx}: {proc.stderr[-300:]}")


def create_silent_audio(path: Path, duration_sec: int = 2) -> Path:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(duration_sec),
            str(path),
        ],
        "Failed to create silent conditioning audio",
    )
    return path


def create_fallback_tone(path: Path, duration_sec: int = 45) -> Path:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=180:sample_rate=44100:duration={duration_sec}",
            "-filter:a",
            "volume=0.07",
            str(path),
        ],
        "Failed to create fallback tone",
    )
    return path


def get_supabase_client() -> Optional[SupabaseClient]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    if create_client is None:
        logger.warning("Supabase package not available; falling back to local storage")
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as exc:
        logger.warning("Failed to initialize Supabase client: %s", exc)
        return None


supabase: Optional[SupabaseClient] = get_supabase_client()


def supabase_public_url(path: str) -> str:
    if not supabase:
        raise RuntimeError("Supabase client not initialized")
    maybe_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(path)
    if isinstance(maybe_url, str):
        return maybe_url
    if isinstance(maybe_url, dict):
        if isinstance(maybe_url.get("data"), dict) and maybe_url["data"].get("publicUrl"):
            return maybe_url["data"]["publicUrl"]
        if maybe_url.get("publicUrl"):
            return maybe_url["publicUrl"]
    raise RuntimeError("Could not resolve Supabase public URL")


def upload_video_to_supabase(local_path: Path, object_name: str) -> str:
    if not supabase:
        raise RuntimeError("Supabase client not initialized")

    with local_path.open("rb") as file_obj:
        file_bytes = file_obj.read()

    supabase.storage.from_(SUPABASE_BUCKET).upload(
        path=object_name,
        file=file_bytes,
        file_options={"content-type": "video/mp4", "upsert": "true"},
    )
    return supabase_public_url(object_name)


def list_supabase_videos(limit: int) -> Optional[List[VideoListItem]]:
    if not supabase:
        return None
    try:
        raw_items = supabase.storage.from_(SUPABASE_BUCKET).list()
        if not isinstance(raw_items, list):
            return None

        parsed: List[VideoListItem] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            filename = item.get("name")
            if not filename or not str(filename).lower().endswith(".mp4"):
                continue

            created_at = (
                item.get("created_at")
                or item.get("updated_at")
                or item.get("last_accessed_at")
                or utc_now_iso()
            )
            parsed.append(
                VideoListItem(
                    filename=str(filename),
                    video_url=supabase_public_url(str(filename)),
                    created_at=str(created_at),
                )
            )

        parsed.sort(key=lambda x: x.created_at, reverse=True)
        return parsed[:limit]
    except Exception as exc:
        logger.warning("Failed to list videos from Supabase: %s", exc)
        return None


def generate_music_track(prompt: str, work_dir: Path) -> Tuple[Path, Optional[str]]:
    """
    Try facebook/MusicGen first. If it fails, generate a lightweight tone fallback
    so videos still get a background track.
    """
    conditioning_path = create_silent_audio(work_dir / "musicgen-conditioning.wav")

    try:
        music_client = GradioClient(MUSIC_SPACE_ID)
        result = music_client.predict(
            texts=prompt,
            melodies=handle_file(str(conditioning_path)),
            api_name=MUSIC_API_NAME,
        )

        audio_path = extract_local_path(result, {".wav", ".mp3", ".flac", ".m4a", ".ogg"})
        if not audio_path:
            raise RuntimeError("MusicGen did not return a local audio path")

        return audio_path, None

    except Exception as exc:
        warning = f"MusicGen unavailable ({exc}); used synthetic background tone fallback."
        logger.warning(warning)
        return create_fallback_tone(work_dir / "fallback-tone.wav"), warning


def merge_audio_into_video(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-stream_loop",
            "-1",
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ],
        "Failed to merge audio into video",
    )
    return output_path


def upscale_with_fallback(video_path: Path, factor: str, work_dir: Path) -> Tuple[Path, Optional[str]]:
    try:
        upscaler_client = GradioClient(UPSCALER_SPACE_ID)
        result = upscaler_client.predict(str(video_path), factor, api_name=UPSCALER_API_NAME)

        upscaled_path = extract_local_path(result, {".mp4", ".mov", ".webm"})
        if not upscaled_path:
            raise RuntimeError("Upscaler did not return a local video path")

        return upscaled_path, None

    except Exception as exc:
        logger.warning("Primary upscaler failed: %s", exc)
        warning = f"Primary upscaler unavailable ({exc}); used local ffmpeg upscale fallback."

        multiplier = "4" if factor == "4x" else "2"
        fallback_path = work_dir / f"upscaled-{factor}.mp4"
        run_ffmpeg(
            [
                "-i",
                str(video_path),
                "-vf",
                f"scale=trunc(iw*{multiplier}/2)*2:trunc(ih*{multiplier}/2)*2:flags=lanczos",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "copy",
                str(fallback_path),
            ],
            "Failed to upscale video",
        )
        return fallback_path, warning


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "Welcome to QuickVid AI API"}


@api_router.post("/generate", response_model=VideoResponse)
async def generate_video(
    request: VideoRequest, background_tasks: BackgroundTasks
) -> VideoResponse:
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "video_url": None,
            "error": None,
            "prompt": prompt,
            "created_at": utc_now_iso(),
            "music_added": False,
            "upscaled": False,
            "warnings": [],
        }

    background_tasks.add_task(
        process_video,
        job_id,
        prompt,
        request.add_music,
        request.music_prompt,
        request.upscale,
        request.upscale_factor,
    )
    return VideoResponse(job_id=job_id, status="processing", video_url=None)


@api_router.post("/generate-from-image", response_model=VideoResponse)
async def generate_video_from_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    prompt: str = Form(default=""),
    add_music: bool = Form(default=False),
    music_prompt: Optional[str] = Form(default=None),
    upscale: bool = Form(default=False),
    upscale_factor: str = Form(default="2x"),
) -> VideoResponse:
    # Validate image upload
    if not file.filename:
        raise HTTPException(status_code=400, detail="No image file provided")

    allowed_types = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format '{ext}'. Allowed: {', '.join(allowed_types)}",
        )

    job_id = str(uuid.uuid4())

    # Save uploaded image to temp location
    image_ext = ext or ".png"
    upload_filename = f"{job_id}{image_ext}"
    upload_path = UPLOAD_DIR / upload_filename
    content = await file.read()
    upload_path.write_bytes(content)

    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "video_url": None,
            "error": None,
            "prompt": prompt or "Generate a video from this image",
            "created_at": utc_now_iso(),
            "music_added": False,
            "upscaled": False,
            "warnings": [],
        }

    background_tasks.add_task(
        process_image_video,
        job_id,
        str(upload_path),
        prompt or "Generate a video from this image",
        add_music,
        music_prompt,
        upscale,
        upscale_factor,
    )
    return VideoResponse(job_id=job_id, status="processing", video_url=None)


@api_router.get("/status/{job_id}", response_model=VideoResponse)
async def get_status(job_id: str) -> VideoResponse:
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return VideoResponse(
        job_id=job_id,
        status=job["status"],
        video_url=job.get("video_url"),
        error=job.get("error"),
        music_added=job.get("music_added", False),
        upscaled=job.get("upscaled", False),
        warnings=job.get("warnings", []),
    )


@api_router.get("/videos", response_model=VideoListResponse)
async def list_generated_videos(
    limit: int = Query(default=12, ge=1, le=MAX_LIST_LIMIT)
) -> VideoListResponse:
    supabase_videos = list_supabase_videos(limit)
    if supabase_videos is not None:
        return VideoListResponse(videos=supabase_videos)

    videos: List[VideoListItem] = []
    sorted_files = sorted(
        VIDEO_DIR.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True
    )

    for file_path in sorted_files[:limit]:
        created_at = datetime.fromtimestamp(
            file_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        videos.append(
            VideoListItem(
                filename=file_path.name,
                video_url=f"/static/videos/{file_path.name}",
                created_at=created_at,
            )
        )

    return VideoListResponse(videos=videos)


def process_video(
    job_id: str,
    prompt: str,
    add_music: bool,
    music_prompt: Optional[str],
    upscale: bool,
    upscale_factor: str,
) -> None:
    work_dir = Path(tempfile.mkdtemp(prefix=f"quickvid-{job_id}-"))
    warnings: List[str] = []

    try:
        logger.info("Processing job %s with prompt: %s", job_id, prompt)

        # 1) Base generation
        video_client = GradioClient(HF_SPACE_ID)
        result = video_client.predict(prompt=prompt, api_name=HF_API_NAME)
        logger.info("Gradio result for %s: %s", job_id, result)

        working_video_path = extract_local_path(result, {".mp4", ".webm", ".mov"})
        if not working_video_path:
            raise RuntimeError("Unable to locate generated video file in Gradio output")

        music_added = False
        upscaled = False

        # 2) Optional AI music generation + merge
        if add_music:
            track_prompt = (music_prompt or f"cinematic background music for: {prompt}").strip()
            generated_music_path, music_warning = generate_music_track(track_prompt, work_dir)
            if music_warning:
                warnings.append(music_warning)

            mixed_video = work_dir / "video-with-music.mp4"
            working_video_path = merge_audio_into_video(
                working_video_path, generated_music_path, mixed_video
            )
            music_added = True

        # 3) Optional upscaling
        if upscale:
            working_video_path, upscale_warning = upscale_with_fallback(
                working_video_path, upscale_factor, work_dir
            )
            if upscale_warning:
                warnings.append(upscale_warning)
            upscaled = True

        # 4) Persist final file locally (cache/fallback)
        local_filename = f"{job_id}.mp4"
        destination_path = VIDEO_DIR / local_filename
        shutil.copy(working_video_path, destination_path)

        # 5) Push to Supabase (primary in production)
        final_video_url = f"/static/videos/{local_filename}"
        if supabase:
            try:
                final_video_url = upload_video_to_supabase(destination_path, local_filename)
            except Exception as exc:
                warning = f"Supabase upload failed ({exc}); served from local storage fallback."
                warnings.append(warning)
                logger.warning(warning)

        update_job(
            job_id,
            status="completed",
            video_url=final_video_url,
            music_added=music_added,
            upscaled=upscaled,
            warnings=warnings,
            completed_at=utc_now_iso(),
        )
        logger.info("Job %s completed. Final URL: %s", job_id, final_video_url)

    except Exception as exc:
        logger.error("Error processing job %s: %s", job_id, exc, exc_info=True)
        update_job(job_id, status="failed", error=str(exc), warnings=warnings, completed_at=utc_now_iso())

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def process_image_video(
    job_id: str,
    image_path: str,
    prompt: str,
    add_music: bool,
    music_prompt: Optional[str],
    upscale: bool,
    upscale_factor: str,
) -> None:
    work_dir = Path(tempfile.mkdtemp(prefix=f"quickvid-img-{job_id}-"))
    warnings: List[str] = []

    try:
        logger.info("Processing image-to-video job %s with prompt: %s", job_id, prompt)

        # 1) Base generation via Wan2.1 (image + prompt)
        img_client = GradioClient(IMG2VID_SPACE_ID)
        result = img_client.predict(
            image=handle_file(image_path),
            prompt=prompt,
            negative_prompt="blurry, low quality, distorted",
            seed=42,
            api_name=IMG2VID_API_NAME,
        )
        logger.info("Image-to-video Gradio result for %s: %s", job_id, result)

        working_video_path = extract_local_path(result, {".mp4", ".webm", ".mov"})
        if not working_video_path:
            raise RuntimeError("Unable to locate generated video file in Gradio output")

        music_added = False
        upscaled = False

        # 2) Optional AI music generation + merge
        if add_music:
            track_prompt = (music_prompt or f"cinematic background music for: {prompt}").strip()
            generated_music_path, music_warning = generate_music_track(track_prompt, work_dir)
            if music_warning:
                warnings.append(music_warning)

            mixed_video = work_dir / "video-with-music.mp4"
            working_video_path = merge_audio_into_video(
                working_video_path, generated_music_path, mixed_video
            )
            music_added = True

        # 3) Optional upscaling
        if upscale:
            working_video_path, upscale_warning = upscale_with_fallback(
                working_video_path, upscale_factor, work_dir
            )
            if upscale_warning:
                warnings.append(upscale_warning)
            upscaled = True

        # 4) Persist final file locally (cache/fallback)
        local_filename = f"{job_id}.mp4"
        destination_path = VIDEO_DIR / local_filename
        shutil.copy(working_video_path, destination_path)

        # 5) Push to Supabase (primary in production)
        final_video_url = f"/static/videos/{local_filename}"
        if supabase:
            try:
                final_video_url = upload_video_to_supabase(destination_path, local_filename)
            except Exception as exc:
                warning = f"Supabase upload failed ({exc}); served from local storage fallback."
                warnings.append(warning)
                logger.warning(warning)

        # Clean up uploaded image
        try:
            Path(image_path).unlink(missing_ok=True)
        except Exception:
            pass

        update_job(
            job_id,
            status="completed",
            video_url=final_video_url,
            music_added=music_added,
            upscaled=upscaled,
            warnings=warnings,
            completed_at=utc_now_iso(),
        )
        logger.info("Image-to-video job %s completed. Final URL: %s", job_id, final_video_url)

    except Exception as exc:
        logger.error("Error processing image-to-video job %s: %s", job_id, exc, exc_info=True)
        update_job(job_id, status="failed", error=str(exc), warnings=warnings, completed_at=utc_now_iso())

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# Register API routes (available at /api/*)
app.include_router(api_router, prefix="/api")

# Serve static root files from frontend dist
@app.get("/favicon.svg")
async def favicon():
    return FileResponse(str(FE_DIST / "favicon.svg"))

@app.get("/icons.svg")
async def icons():
    return FileResponse(str(FE_DIST / "icons.svg"))

# SPA catch-all: serve index.html for any unmatched GET route (frontend routing)
SPA_EXCLUDE_PREFIXES = ("api/", "static/", "assets/", "favicon", "icons")


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_frontend(full_path: str) -> str:
    if full_path.startswith(SPA_EXCLUDE_PREFIXES):
        raise HTTPException(status_code=404, detail="Not found")
    index = FE_DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")
    return index.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
