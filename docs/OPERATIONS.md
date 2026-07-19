# Operations: backup, restore, upgrade

Everything Nexus knows lives in two places:

1. **Postgres** — all conversations, tasks, goals, notes, embeddings, and
   encrypted provider keys.
2. **`NEXUS_MASTER_KEY`** — the envelope-encryption master key (env var,
   never stored in the database).

A database dump without the master key restores everything *except* the
ability to decrypt provider keys — you'd re-enter those in settings. Keep
both, keep them separately.

## Backup

```bash
# Database (compressed, custom format):
docker compose exec db pg_dump -U nexus -Fc nexus > nexus-$(date +%F).dump

# Master key: store your .env (or at minimum NEXUS_MASTER_KEY) in your
# password manager. It is 32 bytes of hex; losing it means re-entering
# provider keys after a restore.
```

Automate the dump with cron; dumps are consistent snapshots, safe to take
while Nexus runs.

## Restore

```bash
docker compose up -d db
docker compose exec -T db pg_restore -U nexus --clean --if-exists -d nexus < nexus-YYYY-MM-DD.dump
# Put the ORIGINAL NEXUS_MASTER_KEY in .env, then:
docker compose up -d
```

With the original master key, provider keys decrypt and everything resumes.
With a new key, delete and re-add provider keys in Settings; all memory,
tasks, and history are unaffected.

## Upgrading

```bash
git pull
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
```

Migrations are forward-only in normal operation; take a dump first.

## Health

- `GET /healthz` — liveness (unauthenticated).
- Settings → Background jobs — recent worker runs and errors.
- Settings → Sources — last-synced per source.
