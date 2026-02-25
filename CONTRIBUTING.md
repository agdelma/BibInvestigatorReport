# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Lint

```bash
ruff check .
```

## Pull requests

- Keep changes focused and incremental.
- If you change CLI behavior, update `README.md` and `examples/`.
