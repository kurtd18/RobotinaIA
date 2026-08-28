---
name: run-tests
description: Run RobotinaIA's full pytest suite, the gate every epic in the reliability-foundation blueprint ends with. Use before tagging any Checkpoint and before starting the next task.
---

# Run the full test suite

RobotinaIA's every epic ends with a clean full-suite run — this is the repeatable check behind every
epic's "Epic acceptance" section in `blueprints/robotinaia-reliability-foundation/`.

## When to use

- Before tagging any step's `Checkpoint` in the reliability-foundation blueprint.
- After any change to `app/database/schema.py`, `app/database/connection.py`, or any `app/services/`
  module.
- Any time you are unsure whether a change broke an earlier step's `Verify` gate (see the "no
  retroactive breakage" rule in `blueprint.md` §9).

## Steps

1. Confirm dependencies are installed: `pip install -r requirements.txt`.
2. Run the full suite: `pytest tests/ -q`.
3. If a specific file needs isolation while debugging: `pytest tests/test_X.py -v`.
4. Confirm `robotinaia.db` was not modified by the run (every DB-touching test uses the isolated
   `db_path` fixture from `tests/conftest.py` — if `robotinaia.db`'s hash changed, a test leaked
   outside its fixture and must be fixed before proceeding):
   ```bash
   sha1sum robotinaia.db > /tmp/before.sha1 2>/dev/null || echo no-db-yet > /tmp/before.sha1
   pytest tests/ -q
   sha1sum robotinaia.db > /tmp/after.sha1 2>/dev/null || echo no-db-yet > /tmp/after.sha1
   diff /tmp/before.sha1 /tmp/after.sha1
   ```

## Verify

`pytest tests/ -q` exits 0. The `diff` in step 4 produces no output (files identical).

## Do not

- Do not run tests against the real `robotinaia.db` directly — always through the `db_path` fixture.
- Do not skip this gate between tasks in `tasks.json` — a passing individual test file does not prove
  an earlier step's gate still holds.
