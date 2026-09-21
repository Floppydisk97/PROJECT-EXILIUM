-- Il magazzino. Da una risorsa a quattro, e da una colonna a una tabella.
--
-- `cities.balance_milli` era un cursore materializzato sempre uguale a SUM(ledger) della
-- citta'. Resta esattamente quello -- stessa invariante, stessi test -- solo per (citta',
-- risorsa) invece che per citta'. Il ledger resta l'unica fonte di verita' e resta immutabile.
CREATE TABLE city_stock (
    city_id uuid NOT NULL REFERENCES cities(id),
    resource text NOT NULL,
    amount_milli bigint NOT NULL DEFAULT 0 CHECK (amount_milli >= 0),
    PRIMARY KEY (city_id, resource)
);

-- Le risorse di base. La lega resta perche' non si confisca cio' che e' stato guadagnato:
-- e' ancora spendibile, semplicemente non se ne conia piu'. Tornera' come primo PRODOTTO
-- della prima catena, che e' il posto in cui avrebbe dovuto stare dall'inizio.
ALTER TABLE resource_ledger DROP CONSTRAINT resource_ledger_resource_check;
ALTER TABLE resource_ledger ADD CONSTRAINT resource_ledger_resource_check
    CHECK (resource IN ('alloy', 'food', 'timber', 'stone'));

-- Quello che c'era passa di la' intatto.
INSERT INTO city_stock (city_id, resource, amount_milli)
SELECT id, 'alloy', balance_milli FROM cities;

CREATE OR REPLACE FUNCTION validate_ledger_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    city_created timestamptz;
    current_amount bigint;
BEGIN
    SELECT created_at INTO city_created FROM cities WHERE id = NEW.city_id FOR UPDATE;
    IF city_created IS NULL THEN
        RAISE EXCEPTION 'ledger entry for unknown city' USING ERRCODE = '23503';
    END IF;
    IF NEW.effective_at < city_created THEN
        RAISE EXCEPTION 'ledger entry precedes city' USING ERRCODE = '23514';
    END IF;
    -- Il lock sulla riga della citta' serializza ogni movimento di QUELLA citta', quindi la
    -- riga di scorta non puo' essere letta e riscritta da due transazioni insieme.
    SELECT amount_milli INTO current_amount FROM city_stock
        WHERE city_id = NEW.city_id AND resource = NEW.resource;
    current_amount := COALESCE(current_amount, 0);
    IF current_amount + NEW.amount < 0 THEN
        -- Messaggio composto invece che formattato: il segno di percentuale, nel corpo della
        -- funzione, il driver lo legge come segnaposto e la migrazione non parte nemmeno --
        -- anche quando sta dentro un commento come questo.
        RAISE EXCEPTION USING MESSAGE = 'insufficient ' || NEW.resource, ERRCODE = '23514';
    END IF;
    INSERT INTO city_stock (city_id, resource, amount_milli)
        VALUES (NEW.city_id, NEW.resource, current_amount + NEW.amount)
        ON CONFLICT (city_id, resource)
        DO UPDATE SET amount_milli = EXCLUDED.amount_milli;
    RETURN NEW;
END;
$$;

ALTER TABLE cities DROP COLUMN balance_milli;
