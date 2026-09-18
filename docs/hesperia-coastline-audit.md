# Audit coste Hesperia v4

## Definizioni e metodo

Una **massa** è una componente connessa di tile con elevazione `>= 0` sul grafo geodetico.
Un **continente** è una massa con almeno lo 0,5% di tutte le tile di terra. Il perimetro di
una massa è il numero di archi geodetici terra-acqua; il report conserva sia
`perimetro/area` sia `perimetro/sqrt(area)` per ogni massa.

Lo spettro costiero non usa latitudine/longitudine come piano. Ogni arco terra-acqua viene
proiettato nel piano tangente al suo punto medio sulla sfera; l'orientamento assiale locale,
rispetto a nord/est geografici, alimenta 18 intervalli da 10 gradi e le armoniche 2, 4, 6 e
8, pesate per lunghezza geodetica. `peak/mean` vale 1 per uno spettro uniforme.

## Hesperia-01, f=139

| fase | terra | continenti | masse | massa maggiore | arido+deserto | isole <20 | terra <=3 vicini | peak/mean | H2 / H4 / H6 / H8 | tempo | RSS picco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| baseline v3 | 46.378 (24,0037%) | 11 | 51 | 39,8982% | 21,0272% | **34** | 3,1049% | 1,6671 | .0756 / .0226 / .0817 / .0411 | 16,068 s | 335,4 MB |
| fase 1, centri seminati | 46.383 (24,0063%) | 11 | 47 | 40,7800% | 22,6419% | **34** | 2,1409% | 1,4342 | .0379 / .0039 / .0466 / .0119 | 12,017 s | 335,3 MB |
| fase 2, rift isotropo | 46.381 (24,0052%) | 11 | 64 | 31,6703% | 18,6628% | 49 | 2,4256% | 1,3751 | .0192 / .0324 / .0349 / .0192 | 13,922 s | 335,6 MB |

La baseline dichiarata sull'ambiente di riferimento è 10,1 s e circa 328 MB. I numeri sopra
sono RSS assoluto e wall clock di Windows con campionamento ogni 20 ms: anche la baseline
supera 330 MB su questa macchina. La candidata non aumenta materialmente la memoria rispetto
alla stessa baseline (+0,2 MB) e resta molto sotto il tempo della baseline locale, ma il
limite assoluto di 330 MB deve essere riconfermato nell'ambiente Linux del piano free.

A `f=60`, la baseline misura 8.642 tile terra (24,0042%), 11 continenti, massa maggiore
39,7593%, arido 18,4679%, 30 isole sotto 20 tile e 7,1974% di terra con <=3 vicini.
La candidata misura 24,0042% terra, 11 continenti, massa maggiore 31,7519%, arido 15,7602%,
35 isole sotto 20 tile e 5,2997% di terra con <=3 vicini.

La fase 3 non è stata applicata: dopo la fase 2 sia la frazione di terra sottile sia il picco
direzionale sono inferiori alla baseline. Una passata sperimentale sul campo continuo ha
peggiorato la quota arida e non è parte della modifica.

## Stabilità seed a f=60

| seed | continenti | massa maggiore | arido+deserto | terra <=3 vicini |
|---|---:|---:|---:|---:|
| Hesperia-02 | 10 | 39,4146% | 19,4354% | 5,8306% |
| Hesperia-03 | 10 | 57,3412% | 22,8971% | 4,6512% |
| Hesperia-04 | 5 | 46,5687% | 21,2244% | 3,9000% |

Tutti i seed restano divisi in almeno tre continenti. Hesperia-03 è un caso limite e supera
il tetto del 55% a questa risoluzione; il vincolo di produzione è validato per Hesperia-01,
il seed autoritativo. Non va promosso un seed alternativo senza la stessa misura a f=139.

I JSON completi e le tre coppie di viste ortografiche (`0°`, `120°`, `240°`) sono generati
in `artifacts/` e restano fuori da Git.

## Reset 0008 e rollback

`0008_coastline_v4` è distruttiva: elimina `world_tiles` e `world_map`. Prima del deploy:

1. fermare API e worker e creare un dump completo con `pg_dump -Fc`;
2. verificare il dump con `pg_restore --list` e conservarlo fuori dal servizio;
3. applicare `alembic upgrade head`;
4. ripopolare con `python -m app.mapcli Hesperia-01 --frequency 139`;
5. verificare seed, versione 4, 193.212 tile e le metriche sopra prima di riaprire il traffico.

Non esiste downgrade dati: per tornare a v3 si fermano i servizi e si ripristina integralmente
il dump pre-0008 in un database vuoto. Un semplice `alembic downgrade` non ricrea la mappa.
