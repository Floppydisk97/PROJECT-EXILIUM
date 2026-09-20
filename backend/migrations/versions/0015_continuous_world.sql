-- Via il tick: il mondo diventa continuo.
--
-- COSA TENEVA INSIEME IL TICK, e dove va a finire.
--
--   decideva QUANDO un ordine si risolve      -> ora un ordine occupa tempo e si completa da se'
--   UNIQUE(city_id, target_tick, kind)        -> indice parziale: una sola cosa in corso per citta'
--   elezione della politica a maggioranza     -> voto permanente per citta', maggioranza continua
--   tabella ticks (quale ruleset, riassunto)  -> il ledger, che ha gia' effective_at, piu' ruleset
--   barriera globale `world FOR UPDATE`       -> SPARISCE. Era il muro di scala dichiarato.
--   require_current                           -> SPARISCE, e con lui l'attrito del mondo veloce.
--
-- IL FRENO. L'unico limite alla velocita' d'azione era quel vincolo di unicita' per tick.
-- Toglierlo e basta renderebbe il gioco piu' degenere, non meno: con la lega che si accumula,
-- una sola richiesta porterebbe una citta' su di centinaia di livelli. Il freno di un mondo
-- continuo non e' una quota artificiale: e' che LE AZIONI OCCUPANO TEMPO. Una citta' si
-- impegna in una cosa sola, e mentre e' impegnata non puo' fare altro. La decisione smette di
-- essere "quando premere" e diventa "a cosa impegnarsi adesso".
--
-- LA POLITICA DIVENTA UNA LINEA DEL TEMPO, ed e' la parte che costa.
--
-- `production_amount` prende UNA politica per tutto l'intervallo, e finora era il tick a
-- garantirlo: ogni citta' veniva liquidata al confine con la politica uscente, prima che la
-- nuova entrasse in vigore -- "un giorno di produzione non e' mai pagato a una tariffa che
-- quel giorno non aveva". Senza tick, una politica che cambia a meta' intervallo pagherebbe
-- retroattivamente tutto l'intervallo alla tariffa nuova.
--
-- Si poteva risolvere liquidando TUTTE le citta' al momento del cambio. Sarebbe stata di
-- nuovo una barriera globale -- piu' rara, ma la stessa cosa, e con migliaia di citta' uno
-- stallo di secondi. Quindi la politica e' un registro di periodi, e la produzione si integra
-- sui periodi che l'intervallo attraversa. Ogni citta' calcola la propria storia da sola,
-- quando qualcuno la guarda, e nessuno blocca nessun altro.
--
-- Esattamente un periodo aperto alla volta: l'indice parziale lo impone.
--
-- DISTRUTTIVA, in modo limitato e dichiarato: gli ordini in sospeso e la storia dei tick
-- vengono cancellati, perche' `target_tick` non ha piu' significato e un ordine accodato a un
-- confine che non esiste piu' non e' traducibile. Citta', giocatori e ledger restano intatti:
-- la lega guadagnata non si tocca.

CREATE TABLE policy_periods (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    policy text NOT NULL CHECK (policy IN ('balanced', 'industrial')),
    from_at timestamptz NOT NULL UNIQUE,
    to_at timestamptz,
    CHECK (to_at IS NULL OR to_at > from_at),
    -- Secondi interi, e non e' pedanteria. Il cursore di una citta' e' troncato al secondo
    -- (database_now), quindi un confine con i microsecondi cade DOPO un cursore che dovrebbe
    -- coprire, e la produzione viene rifiutata per un intervallo scoperto di mezzo millesimo.
    -- Costato un test verde che non lo era.
    CHECK (date_trunc('second', from_at) = from_at),
    CHECK (to_at IS NULL OR date_trunc('second', to_at) = to_at)
);
CREATE UNIQUE INDEX policy_periods_one_open ON policy_periods((to_at IS NULL)) WHERE to_at IS NULL;
CREATE INDEX policy_periods_span ON policy_periods(from_at);

-- Il periodo iniziale parte dalla citta' piu' vecchia, o da adesso se non ce n'e' nessuna:
-- deve coprire ogni intervallo che una citta' possa ancora dover liquidare.
INSERT INTO policy_periods (policy, from_at)
SELECT w.policy,
       date_trunc('second', COALESCE((SELECT min(settled_at) FROM cities), clock_timestamp()))
FROM world w WHERE w.id = 1;

-- Il voto e' permanente, non un ordine: e' una preferenza che una citta' tiene, e la
-- maggioranza si ricalcola quando cambia.
ALTER TABLE cities ADD COLUMN policy_vote text
    CHECK (policy_vote IS NULL OR policy_vote IN ('balanced', 'industrial'));

-- Gli ordini diventano impegni: hanno un inizio, una fine e un costo gia' pagato.
DELETE FROM orders;
ALTER TABLE orders
    DROP CONSTRAINT orders_city_id_target_tick_kind_key,
    DROP COLUMN target_tick,
    ADD COLUMN completes_at timestamptz,
    ADD COLUMN cost_milli bigint NOT NULL DEFAULT 0 CHECK (cost_milli >= 0);
ALTER TABLE orders
    ALTER COLUMN completes_at SET NOT NULL,
    ADD CONSTRAINT orders_completes_after_submission CHECK (completes_at > submitted_at);
-- IL FRENO, in una riga: una citta' fa una cosa alla volta.
CREATE UNIQUE INDEX orders_one_in_flight ON orders(city_id) WHERE status = 'pending';

-- Il ledger si fa carico di cio' che la tabella ticks registrava: con quali regole e' stato
-- prodotto il mondo. Per riga, perche' non c'e' piu' un confine a cui appenderlo.
ALTER TABLE resource_ledger ADD COLUMN ruleset smallint NOT NULL DEFAULT 1 CHECK (ruleset > 0);

DROP TABLE ticks;
ALTER TABLE world
    DROP COLUMN last_tick,
    DROP COLUMN next_tick_at,
    DROP COLUMN policy;
