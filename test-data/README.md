# Cerefox Test Data

Sample documents for testing Cerefox after installation. They cover five
unrelated domains so that search results are meaningfully differentiated —
useful for verifying that hybrid search, semantic search, and FTS all behave
correctly with a diverse corpus.

## Documents

| File | Topic |
|------|-------|
| `cerefox-overview.md` | Cerefox itself — second brain, chunking, hybrid search, projects |
| `knowledge-management.md` | PKM, Zettelkasten, spaced repetition, digital tools |
| `espresso-guide.md` | Espresso extraction, grind size, milk texturing |
| `ancient-rome.md` | Roman Republic, Caesar, engineering, fall of the empire |
| `python-concurrency.md` | GIL, threading, asyncio, multiprocessing |
| `creative-worldbuilding.md` | Magic systems, iceberg principle, culture, geography |

## Ingest all at once

```bash
uv run cerefox ingest-dir test-data/ --pattern "*.md"
```

This skips `README.md` (it has no meaningful content to index). Ingest each
file individually if you want to assign them to a project:

```bash
uv run cerefox ingest test-data/cerefox-overview.md      --title "Cerefox Overview"
uv run cerefox ingest test-data/knowledge-management.md  --title "Knowledge Management"
uv run cerefox ingest test-data/espresso-guide.md        --title "Espresso Guide"
uv run cerefox ingest test-data/ancient-rome.md          --title "Ancient Rome"
uv run cerefox ingest test-data/python-concurrency.md    --title "Python Concurrency"
uv run cerefox ingest test-data/creative-worldbuilding.md --title "Creative Worldbuilding"
```

## Suggested search tests

Once ingested, open the web UI (`uv run cerefox web`) and try these queries
to verify all three search modes work and return the expected top result:

| Query | Mode | Expected top result |
|---|---|---|
| `hybrid search alpha parameter` | FTS | Cerefox Overview |
| `combining keyword and vector search` | Semantic | Cerefox Overview |
| `second brain zettelkasten` | FTS | Knowledge Management |
| `storing ideas outside your mind` | Semantic | Knowledge Management |
| `espresso extraction grind` | FTS | Espresso Guide |
| `the chemistry of a perfect cup of coffee` | Semantic | Espresso Guide |
| `roman senate julius caesar` | FTS | Ancient Rome |
| `collapse of a republic into empire` | Semantic | Ancient Rome |
| `asyncio event loop coroutine` | FTS | Python Concurrency |
| `running multiple tasks at the same time in python` | Semantic | Python Concurrency |
| `magic system consistency narrative` | FTS | Creative Worldbuilding |
| `building a believable fictional universe` | Semantic | Creative Worldbuilding |

The semantic queries use paraphrased language that does not appear verbatim in
the documents — this is the key test for vector search quality.

## Clean up

```bash
uv run cerefox list-docs
# then for each document ID:
uv run cerefox delete-doc <id> --yes
```
