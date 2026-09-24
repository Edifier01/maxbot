-- Resolve public invite tokens to the tenant database that owns the invite.
CREATE TABLE IF NOT EXISTS onboarding_invite_tenants (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_invite_tenant
    ON onboarding_invite_tenants(tenant_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_invite_expiry
    ON onboarding_invite_tenants(expires_at);
