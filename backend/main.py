from fastapi import FastAPI

app = FastAPI(title="QuickVid AI API")

@app.get("/")
async def root():
    return {"message": "Welcome to QuickVid AI API"}
