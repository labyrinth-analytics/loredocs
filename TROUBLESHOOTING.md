# LoreDocs TROUBLESHOOTING

## Half-migrated injection_cap_tokens schema

**Symptom:** Server fails to start with:

```
[LOREDOCS-MIGRATE-ERROR] vaults.injection_cap_tokens exists WITHOUT its CHECK
constraint (half-migrated schema, likely from a crashed migration). Manual
recovery required.
```

**Cause:** A prior migration attempt crashed after adding the
`injection_cap_tokens` column but before the `CHECK` constraint was applied
(or a manual `ALTER TABLE` added the column without the constraint). The
idempotent migration guard sees the column already exists and skips the
ALTER -- but the missing CHECK means invalid values (0, negative, non-integer)
could be stored.

**Recovery steps:**

1. **Back up the database:**
   ```bash
   cp ~/.loredocs/loredocs.db ~/.loredocs/loredocs.db.bak.$(date +%Y%m%d)
   ```

2. **Recreate the vaults table with the CHECK constraint.** SQLite does not
   support `ALTER TABLE ... ADD CONSTRAINT`, so you must rebuild the table:

   ```bash
   sqlite3 ~/.loredocs/loredocs.db <<'SQL'
   BEGIN TRANSACTION;
   CREATE TABLE vaults_new (
       id TEXT PRIMARY KEY,
       name TEXT NOT NULL UNIQUE,
       description TEXT,
       created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
       updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
       workspace_path TEXT DEFAULT NULL,
       injection_cap_tokens INTEGER DEFAULT NULL
           CHECK(injection_cap_tokens IS NULL OR injection_cap_tokens > 0)
   );
   INSERT INTO vaults_new SELECT * FROM vaults;
   DROP TABLE vaults;
   ALTER TABLE vaults_new RENAME TO vaults;
   CREATE INDEX IF NOT EXISTS idx_vaults_workspace ON vaults(workspace_path);
   COMMIT;
   SQL
   ```

3. **Verify the constraint is present:**
   ```bash
   sqlite3 ~/.loredocs/loredocs.db ".schema vaults"
   # Should show: CHECK(injection_cap_tokens IS NULL OR injection_cap_tokens > 0)
   ```

4. **Restart the LoreDocs MCP server.** The migration guard will now see the
   column with the CHECK constraint and skip the ALTER cleanly.

**Prevention:** This state only occurs if the migration is interrupted between
the `ALTER TABLE` and the next `conn.commit()`. The migration runs in a single
transaction, so a crash before commit rolls back both the column and the
constraint. The half-migrated state requires an external factor (manual ALTER,
disk full mid-commit, filesystem corruption).