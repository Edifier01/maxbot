-- JWT revocation (logout). ponytail: без Redis; строки с expires_at можно чистить вручную.

CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti TEXT PRIMARY KEY,
    revoked_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires ON revoked_tokens(expires_at);

INSERT INTO schema_migrations (version) VALUES ('002_revoked_tokens') ON CONFLICT DO NOTHING;
