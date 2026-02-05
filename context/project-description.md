## Project overview

You’re building a **localhost web app** for MacBook Air (M3, 24GB) that you can start at the beginning of class and mostly ignore until later. It will:

1. **Record audio (offline)** while class runs.
2. **Transcribe continuously in ~1-minute chunks** using Whisper (offline).
3. **Generate live-evolving lecture notes** (outline + bullets) from the rolling transcript.
4. **Ingest slides (PDF or PPTX) before recording**, treat them as the **authoritative structure**, and later **merge** transcript-derived notes into that structure.
5. Extract a **small, curated set of slide images** (screenshots of diagrams/figures) and embed them into the final markdown notes.
6. After class, provide “post-processing” workflows using an API LLM:

   * Clean up / reorganize notes
   * Generate study guides / exam reviews from selected sessions or selected note ranges
   * Generate quizzes (MCQs) from chosen content
7. Save everything locally as **course directories** with **one markdown file per lecture**, plus generated artifacts, with **time-based citations** (hoverable tooltips tied to timestamps in the audio/video).

The key design principle is: **Whisper runs offline and reliably**; “smart” study features can be **cloud/API** and can happen concurrently or later.

---

## User workflows

### A) In-class “Start and forget”

1. Open `http://localhost:xxxx`
2. Select **Course**
3. Enter **Session number** (e.g., “Session 4”)
4. Upload slides (PDF/PPTX)
5. Hit **Start**
6. App records audio and:

   * transcribes every ~60s
   * updates a “live notes” view (rough, evolving)
7. Hit **Stop** at the end

### B) If you only have iPhone video

1. Later, create a session (Course + Session number)
2. Upload **MP4** from iPhone
3. App extracts audio and transcribes the same way (chunked), then generates notes
4. Merge with slides and export final markdown

### C) Later that day: post-process + study tools

1. Open a completed session
2. Review transcript segments and notes
3. Click:

   * “Merge into slide outline”
   * “Polish notes”
   * “Generate study guide”
   * “Generate MCQ quiz”
4. Export/save artifacts into the course/session folder

---

## Core features (detailed)

### 1) Session + course organization

* **Course directory** per class (e.g., `courses/CS101/`)
* **Session directory** per lecture (e.g., `courses/CS101/session_04/`)
* Stored assets:

  * `audio/` (recorded WAV/FLAC; or extracted from MP4)
  * `transcript/` (chunk JSON + combined transcript)
  * `slides/` (original PDF/PPTX + extracted text + extracted images)
  * `notes/` (live notes draft, merged notes, polished notes)
  * `study/` (study guide markdown, quiz JSON/markdown)
  * `index.json` (metadata: date, session number, slide file hash, model versions)

### 2) Offline transcription (semi-live)

* Record audio continuously, buffer and finalize **1-minute chunks**.
* Each chunk is transcribed and appended to the session transcript.
* Store each chunk with:

  * start time (seconds)
  * end time (seconds)
  * text
  * optional word timestamps (if enabled)
  * confidence/metadata
* A rolling view shows:

  * “Latest transcript”
  * “Running notes draft” that can be messy initially (since the professor revisits topics)

### 3) Slide ingestion (authoritative structure)

Before recording starts, you attach slides:

* **PDF**:

  * extract text per page (and headings if possible)
  * render page images and/or extract embedded images
* **PPTX**:

  * extract text per slide (titles, bullets)
  * render slide images
  * extract images/shapes if available

Then build a **slide outline object** like:

* Section headings (slide titles / inferred headings)
* Key concepts (bullets)
* Page/slide references

This outline becomes the “skeleton” that transcript notes get merged into later.

### 4) Image extraction for notes (not too many)

You want screenshots of slide diagrams/figures, but selectively. A good approach:

* Extract all candidate images (per slide/page), then score them:

  * size/resolution threshold (avoid icons)
  * uniqueness (deduplicate near-identical images)
  * optionally: “diagram-likeness” heuristics (edge density / text ratio) or an API vision model *later*
* Cap by rules:

  * max N per lecture (e.g., 8–12)
  * max 1–2 per major section
* Save images to `slides/images/` and embed in markdown:

  * `![](../slides/images/slide_07_fig_01.png)`

### 5) Notes generation pipeline

You effectively maintain three layers of notes:

**(a) Live notes (during class)**

* Generated periodically from the most recent transcript window (e.g., last 5–10 minutes + existing note state).
* Focus: capture key points without over-structuring too early.

**(b) Merge notes with slide outline (after class)**

* Use the slide outline as headings.
* Place transcript-derived bullets under the best matching headings.
* Track citations: each bullet links back to time ranges.

**(c) Polish / clean notes (optional, API)**

* Rewrite for clarity, remove redundancy, keep your preferred style.
* Keep citations intact.

### 6) Time-based citations with hover metadata

You want citations “time-wise” with hover behavior.

* Store citations as structured metadata for each bullet:

  * `(start_time, end_time, chunk_id)`
* Render in markdown as a lightweight marker like `[^t12]`
* In the web UI, show the marker as a hoverable element:

  * Tooltip: “12:10–12:42”
  * Click: jump audio playback to that timestamp
* When exporting markdown, you can either:

  * keep footnotes at bottom, or
  * keep inline superscripts, with a companion `citations.json` for the web UI

### 7) Study guide + quiz generation (API-enabled)

From selected sessions (or selected sections within notes):

* **Study guide**

  * condensed outline
  * key definitions
  * “common confusions”
  * example questions
* **MCQ quiz**

  * question, options A–D, correct answer, explanation
  * tag each question to note sections (and time ranges if desired)
* These are generated artifacts saved under `study/`.

---

## Tech stack proposal

### Localhost app structure

* **Backend (Python)**

  * FastAPI (REST + WebSockets for live updates)
  * Uvicorn for serving
  * Background task queue (simple in-process worker or Redis/Celery optional)

* **Frontend (Web UI)**

  * React + Vite (fast dev, simple deployment)
  * Tailwind CSS for layout
  * WebSocket client for “live transcript / live notes” updates
  * Audio player component with timestamp jumping

* **Storage**

  * Filesystem-first (your course/session directory layout)
  * SQLite for indexes/search (sessions, chunks, slide headings, embeddings if you later add them)

### Offline transcription

* **Whisper small** via one of:

  * `faster-whisper` (CTranslate2; very practical on Apple Silicon)
  * or `whisper.cpp` (excellent performance, simple binary)
* **Audio handling**

  * Record mic audio: `sounddevice` / `pyaudio` (CoreAudio)
  * MP4 ingestion: `ffmpeg` to extract audio to WAV/FLAC
* Optional: **diarization** is probably too heavy locally; skip initially.

### Slide parsing + image extraction

* **PDF**

  * Text: `PyMuPDF` or `pdfplumber`
  * Render page images / extract embedded images: `PyMuPDF`
* **PPTX**

  * Text: `python-pptx`
  * Render slides to images: LibreOffice headless (`soffice --convert-to png`) or `unoconv`
* **OCR (only if needed)**

  * macOS Vision framework (native) or `tesseract` (but images-only OCR can be slow)
  * You can defer OCR until you actually encounter scanned PDFs.

### Notes + study features (LLM)

* **During class**

  * You said you’re fine paying tokens, so live note updates can be API-based while Whisper is running offline.
* **After class**

  * Higher-quality merge + polishing + study guide + quiz generation via API.
* Implementation details:

  * Use structured prompts and JSON schemas for:

    * slide outline objects
    * merged note trees
    * quiz objects

### Search / retrieval (optional but useful)

* For better merging transcript → slide headings:

  * lightweight embeddings (API) stored in SQLite
  * or purely heuristic matching (keywords + cosine over TF-IDF) to start
* Start simple: slide title keyword matching + section windowing; add embeddings later.

### Packaging / running

* `uv` or `poetry` for Python deps
* A single `run_local.sh` that starts:

  * backend server
  * frontend dev server (or builds static assets served by FastAPI)
* “One-click” local usage: `make start` or a small macOS launcher later.

---

## Performance and “one local model” constraint

Your offline model is **Whisper small**. Everything else can be:

* API-based (recommended for quality and speed), or
* delayed batch processing after class

This keeps the laptop cool and reliable during lectures.