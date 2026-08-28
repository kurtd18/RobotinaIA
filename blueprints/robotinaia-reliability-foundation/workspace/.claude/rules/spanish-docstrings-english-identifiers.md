# Rule: Spanish docstrings/comments, English identifiers

Applies to every Python file in this repo, existing or new.

1. **Docstrings and inline comments are written in Spanish**, matching every existing module
   (`app/providers/binance_provider.py`, `app/strategies/rsi2_connors.py`, `app/scheduler/repository.py`,
   and every other file in `app/`).
2. **Identifiers — function names, variable names, class names, module names — are written in
   English**, except where an existing Spanish identifier is already load-bearing and being edited,
   not replaced (e.g. `portfolio.py`'s `registrar_decision`, `actualizar_trailing_stop` —
   these stay as-is when the function is ported into `portfolio_service.py`, since renaming
   call-sites across the codebase is out of scope for this blueprint's reliability work).
3. **New modules follow the existing docstring shape**: a short module-level docstring in Spanish
   explaining what the module does and why, followed by function-level docstrings in Spanish for
   anything non-obvious.
4. **Log messages via `loguru`** may be in Spanish, matching the existing convention
   (`logger.info(f"{symbol}: sin datos suficientes")` etc.).
