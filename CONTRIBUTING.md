# Contributing

Bug reports and focused improvements are welcome.

1. Create a branch from `main`.
2. Install the development environment with `python -m pip install -e ".[dev]"`.
3. Run `ruff check .`, `ruff format --check .`, and `pytest`.
4. Open a pull request that explains the operational problem and the chosen behavior.

Keep changes small, add tests for monitoring behavior, and avoid adding a runtime dependency when the standard library is sufficient.
