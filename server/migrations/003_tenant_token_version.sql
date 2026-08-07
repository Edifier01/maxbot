-- Invalidate all JWTs for a tenant without tracking individual jti values.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;

INSERT INTO schema_migrations (version) VALUES ('003_tenant_token_version') ON CONFLICT DO NOTHING;
