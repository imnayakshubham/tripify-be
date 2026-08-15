-- Audit schema for AI interactions.
--
-- Everything here is idempotent so it can run on every boot. The LangGraph
-- checkpoint tables (checkpoints, checkpoint_blobs, ...) are owned by the
-- library and are deliberately NOT referenced by foreign key; the join is by
-- the shared id, since plan_requests.id IS the LangGraph thread id.

-- Keeps updated_at honest without every write path remembering to set it.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- Adding a role is an INSERT, not a migration.
CREATE TABLE IF NOT EXISTS roles (
    name        TEXT PRIMARY KEY,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO roles (name, description) VALUES
    ('user',  'Sees only their own plans.'),
    ('admin', 'Sees all plans and the metrics view.')
ON CONFLICT (name) DO NOTHING;


CREATE TABLE IF NOT EXISTS users (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email             TEXT NOT NULL,
    username          TEXT UNIQUE,
    display_name      TEXT,
    role              TEXT NOT NULL DEFAULT 'user' REFERENCES roles(name),
    status            TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'suspended', 'deleted')),
    email_verified_at TIMESTAMPTZ,
    last_login_at     TIMESTAMPTZ,
    locale            TEXT,
    timezone          TEXT,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Soft delete: audit rows must outlive the user they reference.
    deleted_at        TIMESTAMPTZ
);

-- Login uniqueness lives here rather than in a CITEXT column, so there is no
-- extension dependency. id stays a stable surrogate because email can change.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users (lower(email));
CREATE INDEX IF NOT EXISTS users_role_status_idx ON users (role, status);

DROP TRIGGER IF EXISTS users_set_updated_at ON users;
CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


CREATE TABLE IF NOT EXISTS plan_requests (
    -- Also the LangGraph thread id. One identifier, no alias to keep in sync.
    id               UUID PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES users(id),
    user_query       TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    trip_constraints JSONB,
    model_name       TEXT,
    error_message    TEXT,
    source           TEXT NOT NULL DEFAULT 'web',
    -- Rollups, so "what did this request cost" is one row read.
    llm_calls        INT NOT NULL DEFAULT 0,
    input_tokens     INT NOT NULL DEFAULT 0,
    output_tokens    INT NOT NULL DEFAULT 0,
    duration_ms      INT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS plan_requests_user_created_idx
    ON plan_requests (user_id, created_at DESC);

DROP TRIGGER IF EXISTS plan_requests_set_updated_at ON plan_requests;
CREATE TRIGGER plan_requests_set_updated_at
    BEFORE UPDATE ON plan_requests
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


CREATE TABLE IF NOT EXISTS agent_invocations (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES plan_requests(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    sequence_index  INT  NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    error_message   TEXT,
    llm_calls       INT NOT NULL DEFAULT 0,
    input_tokens    INT NOT NULL DEFAULT 0,
    output_tokens   INT NOT NULL DEFAULT 0,
    duration_ms     INT,
    -- Truncated on purpose: full state already lives in the checkpoint tables
    -- under the same id, and duplicating multi-KB blobs would bloat the log.
    output_summary  TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS agent_invocations_request_seq_idx
    ON agent_invocations (request_id, sequence_index);
CREATE INDEX IF NOT EXISTS agent_invocations_agent_started_idx
    ON agent_invocations (agent_name, started_at DESC);
