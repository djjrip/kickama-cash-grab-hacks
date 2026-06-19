# Data Directory

This directory contains data files used by the Tent of Trials platform.

## Contents

| File/Directory | Description | Format | Update Frequency |
|---------------|-------------|--------|-----------------|
| `schema.sql` | Database schema definition | SQL | Per migration |
| `seed.sql` | Seed data for development | SQL | Per release |
| `migration.sql` | Pending database migrations | SQL | Per deployment |
| `reference/` | Reference data (instruments, exchanges) | JSON | Weekly |
| `test/` | Test data for development | JSON | Manual |
| `backup/` | Database backup snapshots | SQL | Daily |

## Schema Files

The `schema.sql` file contains the complete database schema. It is auto-generated
from the migration files and may not reflect the current state of the database
if migrations have been applied manually. For the authoritative schema, query
the `information_schema` tables directly.

## Seed Data

The `seed.sql` file contains seed data for development environments only.
It creates sample users, instruments, and configuration that make the
application usable immediately after deployment.

WARNING: The seed data includes test API keys and passwords that are publicly
visible in this repository. Do NOT use these credentials in production.
The seed data is intended for local development only.

## Deterministic Test Data

`tools/data_generator.py` can generate reproducible market test data for
fixtures, benchmark datasets, and debugging sessions. Use `--seed` when the
output must be byte-for-byte identical across runs:

```bash
python3 tools/data_generator.py --seed 2026 --output-dir data/test/seed-2026
python3 tools/data_generator.py --seed 2026 --output-dir data/test/seed-2026-copy
```

Each generated dataset includes `metadata.json` with the seed, generation
parameters, and deterministic timestamp base. Keep that metadata with the
dataset so another developer can reproduce the same files later.

For exploratory runs, omit `--seed` and use `--print-seed` to record the random
seed chosen for that run:

```bash
python3 tools/data_generator.py --print-seed --output-dir data/test/random-run
```

To validate deterministic behavior locally:

```bash
python3 tools/validate_data_generator_seed.py
```

## Migration Files

Migration files follow the naming convention: `{YYYYMMDDHHMMSS}_{description}.sql`
Migration files are applied in order by the migration tool. The migration state
is tracked in the `_migrations` table in the database.

Pending migrations that have not yet been applied to production:
- 20240701000000_add_analytics_rollups.sql (in review)
- 20240715000000_add_user_activity_indexes.sql (in review)

## Backup Files

Database backup snapshots are stored in the `backup/` directory. These are
created by the automated backup system and are retained for 30 days. The
backup files are compressed with gzip and encrypted with GPG.

To restore a backup:
```bash
gpg -d backup/tent_production_20240101.sql.gz | gunzip | psql -h localhost tent_production
```

The GPG key ID is stored in the team vault under `secret/database/backup-key`.
