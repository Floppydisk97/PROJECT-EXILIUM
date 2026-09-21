-- L'energia, e il modo di dire "non adesso" a un impianto.
--
-- L'energia NON e' una colonna di magazzino, e non lo sara' mai: e' un flusso. Se si potesse
-- accumulare, una colonia ne banchereb­be di notte e il vincolo sparirebbe. Quello che il
-- database conserva e' l'ATTITUDINE del luogo a produrne -- quattro numeri, come gli altri --
-- e quanta ne serva lo dicono gli impianti costruiti.
ALTER TABLE cities
    ADD COLUMN site_wind  smallint CHECK (site_wind  BETWEEN 0 AND 100),
    ADD COLUMN site_sun   smallint CHECK (site_sun   BETWEEN 0 AND 100),
    ADD COLUMN site_water smallint CHECK (site_water BETWEEN 0 AND 100),
    ADD COLUMN site_heat  smallint CHECK (site_heat  BETWEEN 0 AND 100);

ALTER TABLE cities DROP CONSTRAINT cities_site_complete;
ALTER TABLE cities ADD CONSTRAINT cities_site_complete CHECK (
    num_nulls(site_food, site_timber, site_stone, site_ore,
              site_wind, site_sun, site_water, site_heat,
              site_effort, site_room) IN (0, 10)
);

-- Le opere spente. `idle` non puo' superare `count`: una colonia non puo' mettere in pausa
-- piu' impianti di quanti ne abbia, e un vincolo che lo impedisce e' piu' onesto di un
-- massimo applicato solo dal codice.
ALTER TABLE city_works
    ADD COLUMN idle integer NOT NULL DEFAULT 0 CHECK (idle >= 0),
    ADD CONSTRAINT city_works_idle_fits CHECK (idle <= count);

-- Le centrali. Il vincolo elencava un solo tipo di opera perche' ce n'era uno solo.
ALTER TABLE city_works DROP CONSTRAINT city_works_kind_check;
ALTER TABLE city_works ADD CONSTRAINT city_works_kind_check
    CHECK (kind IN ('smelter', 'windfarm', 'solar', 'hydro', 'geothermal'));
ALTER TABLE orders DROP CONSTRAINT orders_check;
ALTER TABLE orders ADD CONSTRAINT orders_check CHECK (
    (kind = 'upgrade' AND choice IS NULL)
    OR (kind = 'policy_vote' AND choice IN ('balanced', 'industrial'))
    OR (kind = 'work' AND choice IN ('smelter', 'windfarm', 'solar', 'hydro', 'geothermal'))
);
