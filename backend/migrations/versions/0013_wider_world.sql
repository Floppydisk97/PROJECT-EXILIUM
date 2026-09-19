-- Geografia rivista su cinque richieste: laghi e mari interni piu' piccoli, continenti
-- lontani dai poli, il 15 per cento di terre emerse in piu', piu' isole e arcipelaghi.
-- Stesso seme (Erebo-01) e stessa dimensione (231.042 caselle): cambia il disegno, non
-- il mondo di partenza.
--
--                                     prima     dopo
--   terre emerse                       27,0      31,0  per cento (un quinto in piu')
--   terra utilizzabile                 19,6      25,3  per cento
--   massa maggiore                     28,1      27,6  per cento (resta frammentato)
--   isolotti sotto le 20 caselle         38        90
--   masse di terra distinte              62       107
--   lago maggiore                       388       198  caselle
--   corpi d'acqua oltre 100 caselle       3         1
--   terra oltre il circolo polare       si'      zero  (massimo 65 gradi)
--
-- LE MANOPOLE, e perche' non bastava girarne una.
--
-- 1. Terra al 31 per cento: SEA_PERCENTILE da 0,73 a 0,69. Essendo un percentile,
--    decide quanta terra c'e' qualunque cosa faccia il resto del campo.
-- 2. Poli liberi: una maschera nuova (_polar_pull) toglie quota al campo continentale fra
--    51 e 82 gradi, con uno smoothstep perche' la costa si assottigli invece di finire su
--    una riga dritta. Non dice nulla sul clima: la temperatura ha gia' il suo profilo.
-- 3. Ma abbassare il mare ha SALDATO i continenti -- la massa maggiore era schizzata dal
--    28 al 58 per cento e il mondo era diventato un blocco unico. I rift sono l'unico
--    meccanismo che decide cosa resta attaccato a cosa, quindi RIFT_STRENGTH da 0,85 a
--    1,30 per ritagliare quello che il mare non copre piu'.
-- 4. Laghi: BASIN_RADIUS_MAX da 0,052 a 0,038; i mari interni da 0,072-0,100 a 0,066-0,090.
--    Buona parte della riduzione, pero', e' venuta dalla geografia stessa: con meno mare e
--    piu' rift resta meno terreno chiuso da allagare.
-- 5. Isole: gli archi da 10 a 54. E qui e' saltato fuori un difetto vecchio ma invisibile
--    finche' gli archi erano pochi: le isole erano poste a index/(n-1), cioe' a spaziatura
--    ESATTAMENTE uniforme, con un sussulto solo perpendicolare di mezzo grado su archi
--    venti volte piu' lunghi. A dieci archi passava per catena; a cinquantaquattro il
--    pianeta era infilzato di collane di perline, linee punteggiate dritte che nessun mare
--    ha mai disegnato. Ora la posizione lungo l'arco e' sparpagliata fino a mezzo passo, la
--    deriva laterale e' in proporzione all'arco, e ogni arco ha da tre a sette isole.
--
-- Una correzione alla radice, trovata perche' un test e' caduto: la soglia dei fiumi era
-- rapportata alle caselle del PIANETA, ma un bacino lo fa la TERRA, e l'oceano non
-- contribuisce. Finche' la frazione di terra non si muoveva la differenza non si vedeva;
-- portandola da 27 a 31 per cento, il 15 per cento di caselle in piu' ha superato una
-- soglia rimasta ferma e i corsi paralleli sono tornati. Ora la soglia e' per casella di
-- terra (133 qui, contro 116 di prima) e i paralleli per tratto restano a 0,19.
--
-- Anche la definizione del campo continentale era scritta due volte, identica, in due
-- punti: costruire il pianeta e chiedersi dove si puo' scavare un bacino. Due cose che
-- devono concordare e nessun modo di accorgersi quando smettono. Ora e' una sola.
--
-- Come le precedenti: una geografia nuova e' un mondo nuovo, quindi la mappa viene azzerata
-- e il primo avvio successivo la rigenera -- ora in sottofondo, senza tenere chiusa la
-- porta del servizio.
--
-- PERCORSO DISTRUTTIVO, invariato rispetto a 0008-0012:
--   Reset         DELETE di world_tiles e world_map con i trigger di immutabilita'
--                 disabilitati per la sola durata della transazione.
--   Backup        NON esiste ancora un modo per farlo. Sesta volta che questa riga viene
--                 scritta, ed e' il debito piu' vecchio del progetto.
--   Ripopolamento app.mapcli rigenera dal seme nel codice; 11 s e 360 MB di picco su una
--                 macchina intera, qualche minuto a 0,15 di core -- ma fuori dal percorso
--                 di avvio, quindi il servizio resta vivo e risponde 404 finche' non c'e'.
--   Prerequisito  nessuna citta' e' legata a una casella, e questa migrazione tocca solo
--                 world_tiles e world_map: players, cities, resource_ledger, orders e ticks
--                 restano intatti.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
