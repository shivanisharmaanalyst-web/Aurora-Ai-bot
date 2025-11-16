import httpx
import json
import asyncio
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from contextlib import asynccontextmanager

# --- Configuration ---

# The API key has been placed here to ensure the service is runnable.
# ------------------------------------------------------------------
GEMINI_API_KEY = "AIzaSyAkUc390dVIaIo3hgF_-v3xANjG770hNMY"
# ------------------------------------------------------------------

MODEL_NAME = "gemini-2.5-flash-preview-09-2025"
API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# External API URL (using the stable fallback)
FALLBACK_MEMBER_API_URL = "https://november7-730026606190.europe-west1.run.app/messages"

DATA_FILE = Path("messages_cache_v2.json") # Using a new cache file for V2
messages: List[Dict] = []

# --- Helper Functions ---

async def save_messages_cache():
    """Save messages to cache."""
    if messages:
        # Use a separate thread for blocking I/O
        await asyncio.to_thread(DATA_FILE.write_text, json.dumps(messages, indent=2))

async def load_messages_from_cache() -> bool:
    """Load from cache if exists."""
    global messages
    if DATA_FILE.exists():
        try:
            content = await asyncio.to_thread(DATA_FILE.read_text)
            messages = json.loads(content)
            print(f"Loaded {len(messages)} messages from cache (V2)")
            return True
        except Exception as e:
            print(f"Cache error: {e}")
    return False

# --- API Lifespan (Async Data Fetching) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fetches and caches messages before the server starts."""
    global messages

    if not await load_messages_from_cache():
        print("Cache not found or empty. Fetching messages (paginated)...")
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5)
        ) as client:
            try:
                page = 0
                limit = 100
                total_fetched = 0
                api_total: Optional[int] = None

                while True:
                    resp = await client.get(FALLBACK_MEMBER_API_URL, params={"page": page, "limit": limit})
                    print(f"  Page {page}: {resp.status_code}")

                    if resp.status_code != 200:
                        print(f"    End of data (HTTP {resp.status_code}) – stopping.")
                        break

                    data = resp.json()
                    items = data.get("items", [])
                    if not items:
                        print("    Empty page – stopping.")
                        break

                    if api_total is None and "total" in data:
                        api_total = data["total"]
                        print(f"    API reports total: {api_total}")

                    for it in items:
                        messages.append({
                            "member": it.get("user_name", "Unknown"),
                            "message": it.get("message", "")
                        })

                    total_fetched += len(items)
                    print(f"    → {len(items)} messages (total: {total_fetched})")

                    if api_total is not None and total_fetched >= api_total:
                        print(f"    Reached API total ({api_total}) – stopping.")
                        break

                    page += 1
                    await asyncio.sleep(0.1)

                print(f"Finished – {len(messages)} messages fetched.")
                await save_messages_cache()

            except Exception as e:
                print(f"Async Fetch failed: {e}. Messages list is empty.")
                messages = []
    else:
        print(f"Server started using cached data: {len(messages)} messages.")

    yield

# --- FastAPI Setup ---
app = FastAPI(
    title="Aurora AI – Gemini-Powered Q&A (V2)",
    description="Ask anything using cached member messages + Gemini 2.5 Flash.",
    version="3.1",
    lifespan=lifespan
)

class AskRequest(BaseModel):
    question: str

# --- Core Logic ---

def build_context() -> str:
    """
    Creates a context string from ALL cached messages.
    """
    context_lines = [f"{m['member']}: {m['message']}" for m in messages]
    print(f"Passing {len(context_lines)} messages as context to the LLM.")
    return "\n".join(context_lines)


async def ask_gemini(question: str) -> str:
    """
    Calls the Gemini API asynchronously with context and a system prompt.
    """
    if not GEMINI_API_KEY:
        return "Gemini API key is missing. Please verify the GEMINI_API_KEY variable in the code."

    if not messages:
        return "Message data is not available. Please check the data fetching process."

    context = build_context()

    # --- SIMPLIFIED SYSTEM INSTRUCTION ---
    system_instruction = (
        "You are Aurora AI, a corporate chat analyst. Your job is to analyze the provided corporate chat messages and answer the user's question directly and concisely. "
        "The answer MUST be derived ONLY from the context provided. "
        "If the answer cannot be found, you must respond with: 'The information is not available in the current message context.'\n\n"
        "Messages Context:\n"
        f"{context}"
    )

    # --- SIMPLIFIED PROMPT ---
    prompt = f"Question: {question}\n\nAnswer in 1 short, professional sentence. Use real names found in the context."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
    }

    api_url = f"{API_BASE_URL}/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(3):
            try:
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                result = response.json()

                text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Error: LLM returned no text.")
                return text

            except httpx.HTTPStatusError as e:
                if attempt == 2:
                    raise HTTPException(status_code=502, detail=f"Gemini API Error after 3 retries: {e}")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                if attempt == 2:
                    raise HTTPException(status_code=500, detail=f"LLM Connection Error: {e}")
                await asyncio.sleep(2 ** attempt)

        return "Failed to get response from AI."


# --- API Endpoints ---

@app.get("/")
async def root():
    """Redirects to the interactive API documentation."""
    return RedirectResponse("/docs")

@app.get("/health")
async def health():
    """Returns the server status and message cache details."""
    return {
        "status": "ok",
        "messages_cached": len(messages),
        # The key is considered "set" if the variable is non-empty.
        "api_key_set": bool(GEMINI_API_KEY)
    }

@app.post("/ask")
async def ask(req: AskRequest):
    """Receives a question and returns the AI-inferred answer (now a topic summary)."""
    try:
        answer = await ask_gemini(req.question)
        return {"answer": answer}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")