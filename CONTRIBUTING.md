# Contributing to TTR Bot

Thanks for your interest in contributing! This guide covers the development
workflow, coding standards, and how to submit changes.

## Getting Started

```bash
git clone https://github.com/shanmufti/TTR_Bot.git
cd TTR_Bot
uv sync          # install deps + dev tools
```

## Development Tools

All dev tools run through `uv run` so they use the project's virtual environment:

| Tool   | Command                    | Purpose                        |
|--------|----------------------------|--------------------------------|
| ruff   | `uv run ruff check src/`   | Linting and import sorting     |
| ruff   | `uv run ruff format src/`  | Code formatting                |
| ty     | `uv run ty check src/`     | Static type checking           |
| pytest | `uv run pytest tests/`     | Unit tests                     |

CI runs all three on every push and pull request (see `.github/workflows/ci.yml`).

## Code Style

- **Formatter/linter**: ruff with `line-length = 99`, targeting Python 3.13.
- **Imports**: sorted by ruff (`I` rules). Run `ruff check --fix` to auto-sort.
- **Type hints**: all public functions and methods should have type annotations.
  The codebase ships a `py.typed` marker for PEP 561.
- **Docstrings**: every public module, class, and function needs a docstring.
  One-liner is fine for simple items; use Google-style for complex ones.
- **No magic numbers**: thresholds and tuning constants live in
  `config/settings.py`. Add new ones there, not inline.

## Project Layout

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed walkthrough of the
module structure, data flow, and design decisions.

## Making Changes

1. **Create a branch** off `main`:
   ```bash
   git checkout -b feature/my-change
   ```

2. **Write code** following the style guidelines above.

3. **Add tests** for new logic. Pure-computation modules in `vision/` and
   `core/` are the easiest to test — see `tests/` for examples using synthetic
   numpy frames.

4. **Run checks locally**:
   ```bash
   uv run ruff check src/ tools/
   uv run ruff format --check src/
   uv run ty check src/
   uv run pytest tests/
   ```

5. **Commit** with a concise message explaining *why*, not just *what*.

6. **Open a pull request** against `main`. CI must pass before merge.

## Configuration Overrides

Users can override any `settings.py` constant via `data/config.toml` without
editing source code. If you add a new setting, make sure the name matches the
module-level variable exactly (case-sensitive) and document it in the settings
module docstring.

## Thread Safety

The bot runs vision processing and UI on separate threads. If you touch shared
mutable state, protect it with a `threading.Lock`. See `template_matcher.py`
and `window_manager.py` for examples.

## macOS-Only

This project targets macOS exclusively (Quartz screen capture, AppKit window
management). There are no plans for cross-platform support, but contributions
that reduce macOS-specific coupling are welcome.

## Reporting Issues

When filing a bug, please include:

- macOS version and display setup (Retina / external monitor)
- The log file from `logs/` (contains timestamps and vision pipeline state)
- If applicable, debug frames (`TTR_DEBUG_FRAMES=1 uv run ttr-bot` saves
  annotated screenshots to `data/_debug/`)
