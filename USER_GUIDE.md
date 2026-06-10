# QuickVid AI — User Guide

This guide is for non-technical teammates who want to create videos quickly from text prompts.

---

## What QuickVid AI Does

QuickVid AI turns a text description into a short video clip.

You can also enable enhancements:
- **Add AI background music**: adds a soundtrack to the video
- **Upscale output**: increases visual resolution/clarity (2x or 4x)

---

## How to Generate a Video (Frontend App)

1. Open the QuickVid AI web app.
2. In **Describe your video**, type what you want to see.
3. (Optional) Enable enhancements:
   - **Add AI background music**
   - **Upscale output quality**
4. Click **Generate Video**.
5. Wait for processing to finish (usually ~30–120 seconds).
6. Watch the result and click **Download MP4** if you want to save it.

You can also review previous outputs in the **Recent videos** section.

---

## What the Enhancement Options Do

## 1) Add AI Background Music
- Adds a soundtrack to your video.
- You can provide a **music prompt** (example: `cinematic ambient piano and strings`).
- If the external music service is temporarily unavailable, QuickVid still finishes and shows a notice.

## 2) Upscale Output Quality
- Improves sharpness and resolution.
- **2x** = faster, lighter enhancement
- **4x** = stronger enhancement, usually slower
- If the primary upscaler is unavailable, QuickVid applies a fallback method and shows a notice.

---

## Prompt Tips (Get Better Results)

Use this format:

`[subject] + [action] + [location] + [style/look] + [camera feel]`

Examples:
- `A golden retriever puppy running through fresh snow, cinematic lighting, slow-motion, 4k`
- `A drone flyover of a tropical island at sunrise, realistic, ultra-detailed, smooth camera motion`
- `A futuristic neon city street in the rain, cyberpunk style, night, volumetric lighting`

Tips:
- Be specific (who/what/where).
- Add visual style words: *cinematic, realistic, anime, stylized, watercolor*.
- Add motion words: *slow motion, tracking shot, aerial view, panning shot*.
- If output is too generic, add 2–3 more details and retry.

---

## Understanding Status & Notices

During generation, the app shows progress.

After completion, you may see badges like:
- **🎵 Music added**
- **✨ Upscaled**

You may also see **Enhancement notices**. These are informational and mean QuickVid used a backup path for reliability.

---

## Running QuickVid Locally (Backend + Frontend)

If you need to run the full tool on your machine or VM:

## Backend (API)

```bash
cd /home/team/shared/quickvid-ai/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend (Web UI)

Open a second terminal:

```bash
cd /home/team/shared/quickvid-ai/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Then open the frontend URL (usually shown in terminal) and start generating.

---

## Troubleshooting

- **Generation is slow**: public AI spaces can be busy; retry after a minute.
- **Enhancement notice appears**: output is still valid; a fallback method was used.
- **No video appears**: refresh and check **Recent videos**.
- **Backend/frontend won’t connect**: make sure backend is running on port `8000` and frontend on `5173`.

---

If you want, we can add a one-click “Prompt templates” panel for marketing use cases (product launch, event recap, ad teaser, testimonial, etc.).
