-- Il segno di un azzeramento gia' fatto.
--
-- Su un'istanza del piano gratuito non c'e' una shell, quindi l'azzeramento della partita si
-- chiede con una variabile d'ambiente. Una variabile pero' si DIMENTICA addosso a un
-- servizio, e un servizio gratuito si riavvia da solo ogni volta che si risveglia: senza
-- memoria di cio' che e' gia' stato fatto, il mondo verrebbe azzerato a ogni risveglio.
--
-- Qui si conserva l'ultimo valore onorato. La stessa parola non fa niente due volte, quindi
-- una variabile lasciata li' e' innocua, e per azzerare di nuovo si cambia parola.
ALTER TABLE world ADD COLUMN last_reset_token text;
