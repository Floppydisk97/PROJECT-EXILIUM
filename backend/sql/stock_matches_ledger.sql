-- L'invariante del saldo, scritta UNA volta.
--
-- Ogni scorta materializzata deve valere la somma delle righe di ledger di quella citta' per
-- quella risorsa. Lo dicono due posti: il test `test_materialized_balance_equals_ledger_sum`
-- e la verifica dopo un restore. Erano due query diverse, e quella del restore e' rimasta
-- indietro alla migrazione 0019: interrogava `cities.balance_milli`, una colonna che non
-- esiste piu' da quando il saldo e' per risorsa. Cioe' la rete di sicurezza dei backup era
-- rotta, e nessuno poteva accorgersene perche' quello step non girava.
--
-- Restituisce il NUMERO di coppie (citta', risorsa) che divergono: zero vuol dire coerente.
-- Il FULL OUTER JOIN e' voluto: una scorta senza ledger e un ledger senza scorta sono
-- divergenze quanto un numero sbagliato, e un JOIN semplice le nasconderebbe entrambe.
SELECT count(*) FROM (
    SELECT city_id, resource, SUM(amount) AS total
      FROM resource_ledger GROUP BY city_id, resource
) AS ledger
FULL OUTER JOIN city_stock AS stock USING (city_id, resource)
WHERE COALESCE(stock.amount_milli, 0) <> COALESCE(ledger.total, 0);
