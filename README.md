# QuickVid AI

A streamlined internal tool for teams to generate AI-driven videos from simple text prompts.

## Project Structure

- `backend/`: FastAPI-based Python backend for handling API requests and AI integration.
- `frontend/`: React + Vite (TypeScript) frontend for the user interface.

## Setup Instructions

### Backend

1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the development server:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### Frontend

1. Navigate to the `frontend/` directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev -- --host 0.0.0.0
   ```

## Tech Stack

- **Backend:** Python, FastAPI
- **Frontend:** React, TypeScript, Vite
- **Database:** SQLite (shared via `team-db`)
