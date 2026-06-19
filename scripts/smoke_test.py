#!/usr/bin/env python3
"""
Pre-merge smoke test — the gate that would have caught the 2026-06-14 outage.

That incident: a commit imported `supabase_insert_table` from `src.api.store`,
but the function wasn't committed → the app raised ImportError on boot → Railway
kept the old build and every deploy silently failed for 5 days. A single
"can the app even import + boot?" check blocks that entire class of failure.

Run locally:  python scripts/smoke_test.py
CI runs it on every push/PR to main (.github/workflows/ci-smoke.yml).
Exits non-zero (fails the build) on any import or boot error.
"""
import os
import sys
import traceback

# Ensure the repo root is importable regardless of CWD (so `import src...` works
# when run as `python scripts/smoke_test.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dummy env so config reads at import time never hard-fail in CI.
os.environ.setdefault("INTERNAL_TOKEN", "ci-smoke")
os.environ.setdefault("ENVIRONMENT", "ci")

FAILURES = []


def check(label, fn):
    try:
        fn()
        print(f"  ✓ {label}")
    except Exception as e:
        print(f"  ✗ {label}: {e}")
        traceback.print_exc()
        FAILURES.append(label)


def _import_app():
    # Importing main transitively imports every router + data module, so a
    # missing symbol (like the store.py one) surfaces right here.
    import src.api.main  # noqa: F401


def _boot_and_probe():
    # Real ASGI startup via TestClient — proves routes resolve and startup
    # event handlers don't throw. Background loops only create_task + sleep,
    # so nothing network-bound runs during the test.
    from fastapi.testclient import TestClient
    from src.api.main import app
    with TestClient(app) as client:
        r = client.get("/internal/build-state")
        assert r.status_code == 200, f"/internal/build-state → {r.status_code}"


def main():
    print("Smoke test — import + boot")
    check("import src.api.main", _import_app)
    # Only attempt boot if import succeeded (avoids a confusing second trace).
    if "import src.api.main" not in FAILURES:
        check("boot app + GET /internal/build-state", _boot_and_probe)

    if FAILURES:
        print(f"\nSMOKE FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nSMOKE OK")


if __name__ == "__main__":
    main()
