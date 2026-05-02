# Backup

One-shot PostgreSQL backup container for the main compose stack.

Run:

```bash
./scripts/deploy.sh backup
```

Required deployment env:

```dotenv
BACKUP_HOST_DIR=/tmp
```

Result:

```text
${BACKUP_HOST_DIR}/water-meter-<db>-<timestamp>.dump
```
