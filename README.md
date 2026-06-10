# QuickVid AI

A streamlined internal tool for generating AI videos from simple text prompts.

## Project Structure

- `backend/`: FastAPI API for video generation, post-processing, and Supabase/local video storage
- `frontend/`: React + Vite UI for prompt input, enhancement toggles, and history

## Backend API

### `POST /generate`
Starts a new generation job.

Request example:

```json
{
  "prompt": "A neon cyberpunk city timelapse",
  "add_music": true,
  "music_prompt": "cinematic ambient synthwave",
  "upscale": true,
  "upscale_factor": "2x"
}
```

### `GET /status/{job_id}`
Returns job state (`processing`, `completed`, `failed`) plus:
- `video_url`
- `music_added`
- `upscaled`
- `warnings` (fallback notes if external Spaces are unavailable)

### `GET /videos?limit=12`
Returns latest generated videos from Supabase storage (`videos` bucket) when configured, otherwise local fallback (`backend/static/videos`).

## Post-Processing Pipeline

When enabled from UI/API:
1. **Music step** tries `facebook/MusicGen` via `gradio_client`.
2. **Upscale step** tries `Nick088/RealESRGAN_Pytorch` via `gradio_client`.
3. If those Spaces are unavailable, backend falls back to local processing (tone track + ffmpeg-based upscale) so generation still completes.

## Setup

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Optional environment variables:

- Base generation
  - `HF_SPACE_ID` (default: `ByteDance/AnimateDiff-Lightning`)
  - `HF_API_NAME` (default: `/generate_image`)
- Music
  - `MUSIC_SPACE_ID` (default: `facebook/MusicGen`)
  - `MUSIC_API_NAME` (default: `/predict_batched`)
- Upscaling
  - `UPSCALER_SPACE_ID` (default: `Nick088/RealESRGAN_Pytorch`)
  - `UPSCALER_API_NAME` (default: `/predict`)
- Storage (production)
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_BUCKET` (default: `videos`)

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Set frontend environment variable:

- `VITE_API_BASE_URL` = public backend URL (for production deployments)

If `VITE_API_BASE_URL` is not set, local development uses Vite proxy (`/api/*` and `/static/*`) to backend on port `8000`.

## Tech Stack

- **Backend:** Python, FastAPI, gradio_client, imageio-ffmpeg, supabase-py
- **Frontend:** React, TypeScript, Vite
