-- Saldo materializzato per città. Non è una nuova regola economica: il ledger
-- resta l'unica fonte di verità e resta immutabile. balance_milli è un cursore
-- ricostruibile, mantenuto atomicamente dal trigger di inserimento del ledger e
-- SEMPRE uguale a SUM(resource_ledger.amount) della stessa città (test di
-- equivalenza obbligatori). Rimuove il costo O(n) della somma del ledger sia in
-- lettura (saldo città) sia in scrittura (controllo scoperto per ogni entry).

ALTER TABLE cities
    ADD COLUMN balance_milli bigint NOT NULL DEFAULT 0 CHECK (balance_milli >= 0);

-- Riconciliazione iniziale dal ledger esistente: il cursore parte esatto.
UPDATE cities c
SET balance_milli = COALESCE(
    (SELECT SUM(amount) FROM resource_ledger WHERE city_id = c.id), 0);

-- Il controllo di scoperto e l'avanzamento del cursore avvengono nella stessa
-- transazione dell'inserimento, sotto lock di riga della città. Il ledger è
-- immutabile (nessun UPDATE/DELETE), quindi il cursore non può divergere.
CREATE OR REPLACE FUNCTION validate_ledger_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    city_created timestamptz;
    current_balance bigint;
BEGIN
    SELECT created_at, balance_milli INTO city_created, current_balance
        FROM cities WHERE id = NEW.city_id FOR UPDATE;
    IF NEW.effective_at < city_created THEN
        RAISE EXCEPTION 'ledger entry precedes city' USING ERRCODE = '23514';
    END IF;
    IF current_balance + NEW.amount < 0 THEN
        RAISE EXCEPTION 'insufficient balance' USING ERRCODE = '23514';
    END IF;
    UPDATE cities SET balance_milli = current_balance + NEW.amount WHERE id = NEW.city_id;
    RETURN NEW;
END;
$$;
