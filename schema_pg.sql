-- PostgreSQL schema for MAX Sender (Sprint 6 — staged migration)
-- Apply: psql $DATABASE_URL -f schema_pg.sql
-- Note: app runtime in v1.5 still uses SQLite by default.

CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    label TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    messages_sent_today INTEGER DEFAULT 0,
    sent_day TEXT,
    last_error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    max_chat_id TEXT,
    invite_link TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS group_profiles (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    order_index INTEGER DEFAULT 0,
    is_enabled INTEGER DEFAULT 1,
    role_day TEXT,
    day_role TEXT,
    day_order INTEGER,
    PRIMARY KEY (group_id, profile_id)
);

CREATE TABLE IF NOT EXISTS message_pool (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queue_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    running INTEGER DEFAULT 0,
    profile_idx INTEGER DEFAULT 0,
    message_idx INTEGER DEFAULT 0,
    group_idx INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS send_log (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER,
    group_id INTEGER,
    message_idx INTEGER,
    status TEXT,
    error TEXT DEFAULT '',
    sent_text TEXT DEFAULT '',
    sent_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app_log (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    msg TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings_audit (
    id SERIAL PRIMARY KEY,
    key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    messages_total INTEGER DEFAULT 0,
    messages_sent INTEGER DEFAULT 0,
    messages_failed INTEGER DEFAULT 0,
    reason TEXT DEFAULT '',
    scheduled_for TEXT,
    config_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS campaign_schedule (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    start_at TEXT,
    enabled INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO queue_state (id) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO campaign_schedule (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_send_log_status ON send_log(status);
CREATE INDEX IF NOT EXISTS idx_send_log_sent_at ON send_log(sent_at);
CREATE INDEX IF NOT EXISTS idx_profiles_status ON profiles(status);

-- Multi-tenant SaaS (server mode)
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    institution_name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    granted_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS impersonation_log (
    id SERIAL PRIMARY KEY,
    admin_user_id INTEGER NOT NULL REFERENCES users(id),
    target_tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_expires ON subscriptions(expires_at);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
