# Contributing to Cerefox

Cerefox is designed to be extended. This guide explains the common extension points.

---

## Adding a new embedder

All embedders implement the `Embedder` protocol in `src/cerefox/embeddings/base.py`:

```python
from cerefox.embeddings.base import Embedder

class MyEmbedder:
    @property
    def dimensions(self) -> int:
        return 768  # must match vector_dimensions in settings

    @property
    def model_name(self) -> str:
        return "my-model"

    def embed(self, text: str) -> list[float]:
        # Return a list of `dimensions` floats.
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Return one embedding per text.
        return [self.embed(t) for t in texts]
```

**Requirements:**
1. Output dimension must match `CEREFOX_VECTOR_DIMENSIONS` (default: 768).
2. `embed_batch` must return embeddings in the same order as `texts`.
3. Import any heavy dependencies lazily (inside methods) to avoid import-time cost.

**Add a config option** in `src/cerefox/config.py`:
```python
embedder: Literal["openai", "fireworks", "mymodel"] = "openai"
```

**Wire it up** in `src/cerefox/cli.py` in `_get_embedder()` and in `src/cerefox/api/routes.py` in `_cached_embedder()`.

**Write tests** in `tests/embeddings/` following the pattern in `test_embedders.py`.

---

## Adding a new document converter

Converters live in `src/cerefox/chunking/converters.py`. A converter takes a file path and returns a markdown string:

```python
def myformat_to_markdown(path: str | Path) -> str:
    """Convert a .myformat file to markdown."""
    try:
        import mylib
    except ImportError as exc:
        raise ImportError("mylib is required: uv pip install mylib") from exc
    ...
    return markdown_string
```

Then register it in `convert_to_markdown()`:

```python
elif suffix == ".myformat":
    return myformat_to_markdown(path)
```

And update the `ingest` CLI command to accept the new extension.

---

## Adding a new CLI command

Commands go in `src/cerefox/cli.py` using Click:

```python
@cli.command("my-command")
@click.argument("thing")
@click.option("--flag", is_flag=True)
def my_command(thing: str, flag: bool) -> None:
    """Short description for --help."""
    settings = Settings()
    client = _get_client(settings)
    # ... your logic
```

Test with Click's `CliRunner`:

```python
from click.testing import CliRunner
from cerefox.cli import cli

def test_my_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["my-command", "arg"])
    assert result.exit_code == 0
```

---

## Adding a new web page

The web UI is a React + TypeScript SPA under `frontend/`. The backend JSON API is in
`src/cerefox/api/routes_api.py`.

1. Add an API endpoint in `routes_api.py`:
```python
@api_router.get("/my-data")
def api_my_data(
    client: CerefoxClient = Depends(get_client),
) -> MyDataResponse:
    return MyDataResponse(...)
```

2. Add a TypeScript API function in `frontend/src/api/`:
```typescript
export async function fetchMyData(): Promise<MyData> {
  return apiFetch<MyData>("/my-data");
}
```

3. Create a page component in `frontend/src/pages/MyPage.tsx` using Mantine components
   and TanStack Query for data fetching.

4. Add a route in `frontend/src/App.tsx`:
```tsx
<Route path="/my-page" element={<MyPage />} />
```

5. Add a nav link in `frontend/src/components/Layout.tsx` if needed.

6. Build: `cd frontend && npm run build`

---

## Adding a new database RPC

1. Write the SQL function in `src/cerefox/db/rpcs.sql`.
2. Add a Python wrapper in `src/cerefox/db/client.py`.
3. Deploy to Supabase: `python scripts/db_deploy.py`.

All RPCs should be `SECURITY DEFINER` so they work with the anon/service key without exposing raw table access.

---

## Git workflow

### For contributors

1. **Fork** the repository and create a feature branch from `main`
2. Make your changes with clear, focused commits
3. Open a PR against `main`

### Commit messages

```
<verb> <what changed>

<optional body: why, context, trade-offs>
```

- **Imperative mood**: "Add", "Fix", "Update", "Remove"
- **First line under 72 characters**
- **Body explains why**, not what — the diff shows what changed
- **One logical change per commit**

### PR conventions

- Title: short, imperative, under 70 chars
- Body: Summary (bullet points) + Test plan (checklist)
- Merge style: **Squash and merge** by default

---

## Code style

- **Formatter/linter**: `uv run ruff check . && uv run ruff format .`
- **Line length**: 100 characters
- **Type hints**: required on all public functions
- **Tests**: every new module in `src/cerefox/` gets tests in `tests/`
- **Imports**: lazy-import heavy deps (pypdf, docx) inside functions

---

## Running tests

```bash
uv run pytest              # all unit tests
uv run pytest -k search    # tests matching "search"
uv run pytest --co         # just list what would run (collect only)
```

Integration tests (require live Supabase) are skipped by default:
```bash
uv run pytest -m integration  # run integration tests
```
