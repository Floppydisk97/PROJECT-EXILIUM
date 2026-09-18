# Validazione correttiva Hesperia v4

Questo documento integra, senza sostituirlo, il report baseline
`hesperia-coastline-audit.md`. Gli artefatti e gli screenshot precedenti restano invariati.

## Matrice finale

| seed | f | terra | continenti | massa maggiore | arido+deserto | isole <20 | terra <=3 vicini | peak/mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Hesperia-01 | 60 | 24,0014% | 12 | 29,7419% | 13,6095% | 21 | 5,4392% | 1,3472 |
| Hesperia-02 | 60 | 24,0070% | 12 | 39,1994% | 16,9270% | 23 | 6,1553% | 1,8851 |
| Hesperia-03 | 60 | 24,0042% | 12 | 49,6297% | 22,3328% | 32 | 5,6006% | 1,4476 |
| Hesperia-04 | 60 | 24,0014% | 6 | 50,9200% | 21,7683% | 21 | 3,8421% | 1,7348 |
| Hesperia-01 | 139 | 24,0026% | 12 | 29,6856% | 16,3770% | **34** | 2,3374% | 1,3545 |
| Hesperia-02 | 139 | 24,0120% | 13 | 39,1645% | 20,6600% | 27 | 2,6146% | 1,9187 |
| Hesperia-03 | 139 | 24,0032% | 12 | 49,5806% | 24,8291% | 38 | 2,3331% | 1,4363 |
| Hesperia-04 | 139 | 24,0047% | 6 | 50,9185% | 24,0125% | 32 | 1,7313% | 1,7718 |

Il seed autoritativo migliora entrambi gli indici di filamentosità rispetto alla baseline
`f=139`: terra sottile 2,3374% contro 3,1049%, `peak/mean` 1,3545 contro 1,6671. Non è stata
applicata erosione.

## PostgreSQL 17.11 reale

- migrazione pulita `base -> 0008`: riuscita, head unico `0008`;
- upgrade `0007 -> 0008`: riuscito, `world_map=0`, `world_tiles=0`;
- ripopolamento in due database separati: 36.002 tile, generator version 4;
- fingerprint dei campi autoritativi in entrambi: `58ed04b36dcbaa9c4a046f00458f2d17`;
- dump custom verificato con `pg_restore --list`;
- restore in database vuoto: revisione `0007`, seed `Hesperia-01`, 36.002 tile;
- regressione completa: 48 test passati, nessuno saltato.

Le prove hanno usato database isolati usa-e-getta. La migrazione non è stata applicata a un
database applicativo.

## Benchmark Linux ancora richiesto

La workstation non dispone di Docker, Podman, WSL o altro runtime Linux. I valori Windows
non sono usati come sostituto. Prima dell'approvazione servono tre esecuzioni pulite della
baseline e tre del candidato nell'immagine Linux del piano free con `/usr/bin/time -v`, con
cold start, mediana, massimo e RSS massimo; il candidato deve restare entro 330 MB.
