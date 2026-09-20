-- Le opere e i filoni. Ruleset 3: la produzione smette di essere una moltiplicazione.
--
-- `site_ore` e' l'unica grandezza del terreno che non sta in superficie: la decide la quota,
-- non il bioma, quindi una foresta in montagna puo' avere minerale e una macchia arida in
-- pianura puo' non averne. E' cio' che la rende un asse NUOVO invece della pietra riscritta.
ALTER TABLE cities ADD COLUMN site_ore smallint CHECK (site_ore BETWEEN 0 AND 100);

ALTER TABLE cities DROP CONSTRAINT cities_site_complete;
ALTER TABLE cities ADD CONSTRAINT cities_site_complete CHECK (
    (site_food IS NULL AND site_timber IS NULL AND site_stone IS NULL AND site_ore IS NULL
     AND site_effort IS NULL AND site_room IS NULL)
    OR (site_food IS NOT NULL AND site_timber IS NOT NULL AND site_stone IS NOT NULL
        AND site_ore IS NOT NULL AND site_effort IS NOT NULL AND site_room IS NOT NULL)
);

-- E il minerale va ammesso nel LEDGER, non solo sulla riga della citta'. La 0019 aveva
-- fissato l'elenco delle risorse ammesse; aggiungere una grandezza del terreno senza
-- estenderlo significa poterla produrre e non poterla scrivere -- un difetto che non si vede
-- finche' qualcuno non estrae il primo grammo.
ALTER TABLE resource_ledger DROP CONSTRAINT resource_ledger_resource_check;
ALTER TABLE resource_ledger ADD CONSTRAINT resource_ledger_resource_check
    CHECK (resource IN ('alloy', 'food', 'timber', 'stone', 'ore'));

-- E la produzione puo' essere NEGATIVA, cosa che prima non poteva succedere.
--
-- Il vincolo diceva: genesis e production aggiungono, upgrade toglie. Era vero finche' le
-- risorse si limitavano a salire. Una catena consuma: una colonia che fonde piu' minerale di
-- quanto ne scavi ha, alla fine dell'intervallo, meno minerale di prima -- e quel movimento
-- e' esattamente cio' che il ledger deve registrare, non un'anomalia da rifiutare.
--
-- Genesis resta positivo e upgrade resta negativo: quelli non hanno cambiato natura.
ALTER TABLE resource_ledger DROP CONSTRAINT resource_ledger_check;
ALTER TABLE resource_ledger ADD CONSTRAINT resource_ledger_check CHECK (
    (reason = 'genesis' AND amount > 0)
    OR (reason = 'upgrade' AND amount < 0)
    OR reason = 'production'
);

-- Le opere costruite. Un conteggio per tipo, non una riga per edificio: finche' un'opera non
-- va piazzata su una casella, di una fonderia interessa QUANTE ce ne sono, e una tabella di
-- oggetti identici sarebbe stata una riga per niente.
CREATE TABLE city_works (
    city_id uuid NOT NULL REFERENCES cities(id),
    kind text NOT NULL CHECK (kind IN ('smelter')),
    count integer NOT NULL DEFAULT 0 CHECK (count >= 0 AND count <= 8),
    PRIMARY KEY (city_id, kind)
);

-- Un'opera si costruisce come un avanzamento: occupa la colonia, una cosa alla volta. Il
-- vincolo che lo impone e' gia' li' -- `orders_one_in_flight` guarda la citta', non il tipo
-- di lavoro -- quindi qui basta ammettere il nuovo genere di ordine.
--
-- DUE vincoli, non uno: il secondo lega il tipo alla colonna `choice`, e dimenticarlo
-- avrebbe fatto rifiutare ogni ordine "work" da un CHECK che parlava d'altro. Per un'opera
-- `choice` porta QUALE opera, che e' esattamente cio' per cui quella colonna esiste.
ALTER TABLE orders DROP CONSTRAINT orders_kind_check;
ALTER TABLE orders ADD CONSTRAINT orders_kind_check
    CHECK (kind IN ('upgrade', 'policy_vote', 'work'));
ALTER TABLE orders DROP CONSTRAINT orders_check;
ALTER TABLE orders ADD CONSTRAINT orders_check CHECK (
    (kind = 'upgrade' AND choice IS NULL)
    OR (kind = 'policy_vote' AND choice IN ('balanced', 'industrial'))
    OR (kind = 'work' AND choice IN ('smelter'))
);
