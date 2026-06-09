# migrations

**Purpose:** Alembic database schema migrations.

**What belongs here:** the hand-authored Alembic environment (`env.py`), the
revision template (`script.py.mako`), and `versions/` (the generated migration
scripts). `versions/` is machine-authored and is **excluded** from the
per-package README guard (`tests/test_folder_docs.py`); its `__init__.py` is a
0-byte import anchor.

**What does NOT belong here:** runtime storage code (`storage/`), domain models
(`domain/`), or anything other than schema-evolution scripts and the Alembic
harness.

**Update this README when** you change the migration harness or conventions —
not for every new revision in `versions/`.
