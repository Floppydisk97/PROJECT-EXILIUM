CREATE TABLE world (
    id smallint PRIMARY KEY CHECK (id = 1),
    policy text NOT NULL CHECK (policy IN ('balanced', 'industrial')),
    last_tick bigint NOT NULL DEFAULT 0 CHECK (last_tick >= 0),
    next_tick_at timestamptz NOT NULL,
    CHECK (next_tick_at = date_trunc('day', next_tick_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
);
INSERT INTO world (id, policy, next_tick_at)
VALUES (1, 'balanced', (date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') + interval '1 day') AT TIME ZONE 'UTC');

CREATE TABLE players (
    id uuid PRIMARY KEY,
    token_hash text NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    created_at timestamptz NOT NULL
);
CREATE TABLE cities (
    id uuid PRIMARY KEY,
    world_id smallint NOT NULL DEFAULT 1 REFERENCES world(id),
    owner_id uuid NOT NULL UNIQUE REFERENCES players(id),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    level integer NOT NULL DEFAULT 0 CHECK (level BETWEEN 0 AND 1000000),
    created_at timestamptz NOT NULL,
    settled_at timestamptz NOT NULL CHECK (settled_at >= created_at)
);
CREATE TABLE resource_ledger (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city_id uuid NOT NULL REFERENCES cities(id),
    resource text NOT NULL DEFAULT 'alloy' CHECK (resource = 'alloy'),
    amount bigint NOT NULL,
    reason text NOT NULL CHECK (reason IN ('genesis', 'production', 'upgrade')),
    event_key text NOT NULL UNIQUE,
    effective_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((reason IN ('genesis', 'production') AND amount > 0) OR (reason = 'upgrade' AND amount < 0))
);
CREATE INDEX resource_ledger_city ON resource_ledger(city_id, id);
CREATE TABLE orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city_id uuid NOT NULL REFERENCES cities(id),
    idempotency_key uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('upgrade', 'policy_vote')),
    choice text,
    target_tick bigint NOT NULL CHECK (target_tick > 0),
    submitted_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'rejected')),
    outcome text,
    UNIQUE(city_id, idempotency_key),
    UNIQUE(city_id, target_tick, kind),
    CHECK ((kind = 'upgrade' AND choice IS NULL) OR
           (kind = 'policy_vote' AND choice IS NOT NULL AND choice IN ('balanced', 'industrial'))),
    CHECK ((status = 'pending' AND outcome IS NULL) OR (status <> 'pending' AND outcome IS NOT NULL))
);
CREATE INDEX orders_pending ON orders(target_tick, id) WHERE status = 'pending';
CREATE TABLE ticks (
    number bigint PRIMARY KEY CHECK (number > 0),
    due_at timestamptz NOT NULL UNIQUE,
    ruleset integer NOT NULL CHECK (ruleset = 1),
    summary jsonb NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit records are immutable' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER ledger_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON resource_ledger
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER ticks_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON ticks
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();

CREATE FUNCTION validate_ledger_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE city_created timestamptz;
BEGIN
    SELECT created_at INTO city_created FROM cities WHERE id = NEW.city_id FOR UPDATE;
    IF NEW.effective_at < city_created THEN
        RAISE EXCEPTION 'ledger entry precedes city' USING ERRCODE = '23514';
    END IF;
    IF NEW.amount < 0 AND
       (SELECT COALESCE(SUM(amount), 0) FROM resource_ledger WHERE city_id = NEW.city_id) + NEW.amount < 0 THEN
        RAISE EXCEPTION 'insufficient balance' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ledger_validate BEFORE INSERT ON resource_ledger
FOR EACH ROW EXECUTE FUNCTION validate_ledger_entry();
