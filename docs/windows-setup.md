# Running the demo on Windows

Written 2026-11-16 for working on this repo from a Windows PC. The Mac remains the machine
the demo was built and rehearsed on; everything here has been checked against the repo, but
not yet run on Windows. Note anything that differs at the bottom of this file.

## What comes from GitHub, and what doesn't

| Comes with `git clone` | Stays on each machine |
|---|---|
| All code, config, docs, tests | `.env` (your own settings) |
| `data/generated/`: the 54 invoices, answer key, manifest | The database contents |
| `data/live-demo-new/`: the 5 invoices kept back for the live demo | |
| `data/llm_cache/`: the recorded model answers (replay) | Page images, parsed text, exports (`data/bronze`, `silver`, `parsed`, …) |

The database and page images are rebuilt by running the invoices through the pipeline
(step 6), so nothing needs copying by hand.

## 1. Install the tools (once)

Open **PowerShell** and run these. Each one is a normal installer; accept the defaults.

| Tool | What it's for | Install |
|---|---|---|
| Git for Windows | Downloading the code; also gives you **Git Bash** | `winget install --id Git.Git -e` |
| uv | Python and the project's packages | `winget install --id astral-sh.uv -e` |
| Docker Desktop | The database (and Airflow for the full stack) | `winget install --id Docker.DockerDesktop -e` |
| GNU make | The `make …` commands | `winget install --id ezwinports.make -e` |
| Tesseract OCR 5.5 | Reading scanned invoices | Installer from the [UB Mannheim page](https://github.com/UB-Mannheim/tesseract/wiki) (the old `UB-Mannheim.TesseractOCR` winget package stops at 5.4) |
| Ollama | Running the model (optional, see step 6) | `OllamaSetup.exe` from [ollama.com/download](https://ollama.com/download) |

Then:

1. **Restart the PC** (Docker Desktop needs it the first time), and start Docker Desktop once.
2. **Add Tesseract to PATH.** The installer puts it in `C:\Program Files\Tesseract-OCR`.
   Windows search → "Edit the system environment variables" → Environment Variables →
   *Path* → New → `C:\Program Files\Tesseract-OCR`. Check in a new terminal:
   `tesseract --version` should print 5.5.x (the Mac uses 5.5.4).

## 2. Get the code

Use **Git Bash** from here on (Start menu → Git Bash). The Makefile needs bash, and Git Bash
has it.

```bash
cd ~
git clone https://github.com/ZharlieSineFine/kallang-invoice-demo.git
cd kallang-invoice-demo
```

The repository is private: the first time, a browser window asks you to log in to GitHub.

## 3. Settings file

```bash
cp .env.example .env
```

Open `.env` in any editor and replace `change-me` with a password of your choice, in **both**
places (`AP_DB_PASSWORD` and inside `AP_DATABASE_URL`). Never commit `.env`; git ignores it.

## 4. Python packages

```bash
uv sync --all-extras
```

## 5. Database

```bash
make db-dev
```

If this says `docker-compose: command not found`, run it as
`make COMPOSE="docker compose" db-dev` (and add `COMPOSE="docker compose"` to every other
`make` command that uses Docker: `up`, `down`, `export`, `intake`, `reset`).

## 6. Load the invoices

**Without the model (replay):** uses the recorded answers in `data/llm_cache/`. About a
minute.

```bash
LLM_MODE=replay make demo-data RESET=1
```

The 41 digital PDFs always replay. The 13 scans replay only if Tesseract reads them
exactly as on the Mac, because the recorded answer is looked up by the page's text and
image. If a scan is reported as `FAILED  CacheMiss`, Tesseract or the PDF renderer differs
from the Mac's. The rest still load. To fill the gap, run it once with the model (below);
that records Windows' own answers, and replay works from then on.

**With the model (live):** needs Ollama and about 8 GB of free memory (a GPU helps a lot).

```bash
ollama pull gemma4:12b
make demo-data RESET=1
```

About 25–30 minutes for all 54 on the Mac.

## 7. Open the review app

```bash
uv run streamlit run app/main.py
```

Then open <http://localhost:8501>. Stop it with **Ctrl + C** in that window. With watchdog
installed, code changes show "Source file changed" in the page corner; click
**Always rerun** to pick them up without restarting.

## The full stack (Airflow), optional

```bash
make up            # Airflow on http://localhost:8080, review app on http://localhost:8501
make drop-all      # the 50 for the recorded run, in arrival order
make intake        # start now instead of waiting up to 5 minutes
make drop-live     # afterward: the 5 live-demo invoices in data/live-demo-new
make intake
make down          # stop everything
```

Containers reach Ollama on the PC through `host.docker.internal`, as on the Mac.

## Tests

```bash
uv run pytest -m "not ollama and not docker"
```

The invoice generator (`make data`, `tests/unit/generator`, `tests/integration/ws1`) uses
WeasyPrint, which needs the Pango libraries; they are not part of a normal Windows install.
If those tests fail on a WeasyPrint import, skip them:

```bash
uv run pytest -m "not ollama and not docker" --ignore=tests/unit/generator --ignore=tests/integration/ws1
```

You don't need the generator on Windows: the invoices it makes are already in
`data/generated/`.

## Switching between the Mac and Windows

Before you leave one machine:

```bash
git add -A
git commit -m "what you changed"
git push
```

When you sit down at the other one, before changing anything:

```bash
git pull
```

Only code and the shared data travel. Each machine keeps its own `.env` and database; after
a pull that changes the invoices or the pipeline, rerun step 6.

## The live demo, and running it again

`make demo-ready` (with `LLM_MODE=replay`) loads the 54. The 5 invoices in
`data/live-demo-new/` are never loaded by it: upload them during the demo (Upload page, then
`make intake-local`, or `make drop-live` and `make intake` on the full stack). Afterward,
`make erase-live` removes those 5 again and keeps the 54, so the demo can be run again.
`make erase-live DRY=1` only shows what it would remove.

## Differences found on Windows

(Add what you find here.)
