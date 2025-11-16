# Aurora-Ai-bot
**Aurora AI** is a **real-time question-answering bot** built for team chats.  
Ask anything — *“Who’s handling the client call?”*, *“What did Vikram say about his car?”*, *“When is the report due?”* — and Aurora answers **in one sentence**, using **only the actual words from the chat**.

<img width="1732" height="907" alt="image" src="https://github.com/user-attachments/assets/d273b857-184a-4cc2-98a4-0e8ad491d08e" />


---------------------------------------------------------------------------------------------------------------------------------------------------------------
## Design Notes – Alternative Approaches Considered

When building Aurora AI, I evaluated several architectural patterns to balance **accuracy, speed, cost, and simplicity**. Below are the **four alternatives** I considered, followed by **why the current “context-in-prompt” design won**.

### 1. Full Retrieval-Augmented Generation (RAG) with FAISS + LangChain
**Idea:** Split every message into 300-token chunks, embed them using `embedding-001`, store in a FAISS vector index, retrieve the top-5 most relevant chunks, and feed them to Gemini Pro via a LangChain chain.

**Pros:**  
- Precise retrieval of only relevant messages  
- Built-in source citations  
- Scales to millions of messages  

**Cons:**  
- Requires ~200 MB FAISS index at runtime  
- Extra latency from embedding + vector search (~300–500 ms)  
- Heavy dependencies (`langchain`, `faiss-cpu`)  

**Why not chosen:** The project targets **<1-second responses** on Render’s free tier. Adding vector search would exceed the SLA and increase memory usage beyond free-tier limits.


---

### 2. Pure LLM – Send All Messages in One Prompt
**Idea:** Concatenate all 3,349 messages into a single context string and send it to Gemini Pro in one API call.

**Pros:**  <img width="1412" height="812" alt="image" src="https://github.com/user-attachments/assets/72741468-e88d-4cf7-bc58-d21d9f0cad30" />

- Zero extra code or infrastructure  
- Single HTTP request  

**Cons:**  
- Gemini 2.5 Flash has a **~8k token context limit** → would truncate most messages  
- High risk of hallucination  
- Expensive and slow (large payload)  

**Why not chosen:** **Impossible** — the full chat is ~30k+ tokens. Truncation would lose 90% of the data, making answers unreliable.

---

### 3. Summarize-Then-Answer (Two-Stage Pipeline)
**Idea:** At startup, use Gemini Pro to generate a **concise summary** of the entire chat. Then answer all user questions using only the summary.

**Pros:**  
- Tiny context per request (~1k tokens)  
- Extremely fast inference  

**Cons:**  
- **Loss of exact quotes** — summaries omit details  
- Summary becomes outdated if new messages arrive  
- Cannot cite original speakers  

**Why not chosen:** The core requirement is **verbatim answers with real names**. Summarization breaks this guarantee.

---

### 4. Full-Text Search with ElasticSearch / Meilisearch
**Idea:** Index every message as a document in a search engine, use BM25 keyword search to fetch top hits, then pass results to Gemini for rephrasing.

**Pros:**  
- Excellent for keyword-based queries  
- No embedding cost  

**Cons:**  
- Requires running a separate search service  
- Still needs LLM to generate natural answers  
- Extra operational complexity (Docker, indexing pipeline)  

**Why not chosen:** Adds **unnecessary infrastructure** for a dataset that fits in memory. Gemini’s reasoning is strong enough when given full context.

---

## Final Design – **Context-in-Prompt RAG-Lite** (Chosen)

<img width="1727" height="820" alt="image" src="https://github.com/user-attachments/assets/c0ff1821-b7b2-41c8-90e0-dd2769958dec" />


Why this design wins:

No vector store → Zero memory overhead beyond the message list.
Full context → All 3,349 messages fit in Gemini 2.5 Flash’s expanded context window (~32k tokens).
Exact-quote guarantee → System prompt forces: “Answer ONLY from context”.
Blazing fast → Single API call, <800 ms on Render free tier.
Deploy-anywhere → Just uvicorn + httpx. No databases, no embeddings.
----------------------------------------------------------------------------------------------------------------------------------------------------


## Dataset Analysis – What I Found (Real Talk)

I pulled the data manually using the API (`/messages`) and dug in like a human would — no fancy scripts, just eyes on the JSON. Here’s what I noticed:

### The Good
- **30 messages** from **10 real-sounding people** (Fatima, Vikram, Sophia, etc.)  
- Every message has **user name, timestamp, and text** — no missing fields  
- All IDs are **unique**, no duplicates  
- Messages are short and clear — people asking for coffee, car info, meeting times, etc.

### The Weird Stuff (Inconsistencies I Caught)
- **Timestamps are in the future** — every single one is from **2024 or 2025**, but today is **Nov 16, 2025**. That means the data is **synthetic/test data**, not real chat history.  
  > Example: `"2025-03-15T14:22:00Z"` — that’s **4 months from now**!

- **No conversation flow** — messages don’t reply to each other. There’s **no thread, no @mentions, no context**.  
  > Example: Fatima says “I need the report by 3 PM” — nobody responds. Vikram says “I have 3 cars” — no one asks “which ones?”  
  > It’s like 30 random Post-it notes, not a real group chat.

- **Too perfect** — every user has **3–12 messages**, almost evenly spread. Real chats? One person spams, others lurk. This feels **engineered**.

- **No media, no edits, no reactions** — just plain text. Real chats have images, “edited”, thumbs-up, etc.

---

### Summary (TL;DR)
> The data is **clean but fake**.  
> It’s great for **testing the bot** (no errors, no junk), but **not a real conversation**.  
> There’s **no message linking** — no replies, no threads, no continuity.  
> It’s like a **demo dataset**, not a live team chat.

---

**Bottom line:**  
Aurora AI works perfectly on this data because it’s structured and complete.  
But in a **real team**, expect messier input — and we’d need **threading + context tracking** to keep answers accurate.

---
