// La geometria della griglia e' il pezzo su cui sbagliare non si vede finche' non si guarda:
// mezzo esagono di scarto fra dove sta il colore e dove sta la linea, e il terreno sembra
// scollato dalle caselle -- ma tutto continua a funzionare e nessun altro test se ne accorge.
// Queste sono le cose che devono essere vere perche' le linee e il terreno siano la stessa
// griglia.
import { describe, expect, it } from "vitest";
import { CORNERS, ROW_RATIO, centreX, centreY, hexAt, mapHeight, neighbours } from "./hexgrid";

const SIZE = 40;

describe("dove sta un esagono", () => {
  it("ritrova sempre l'esagono dal proprio centro", () => {
    // Il giro completo: dall'indice al punto e dal punto all'indice. Se questo non tiene,
    // il puntatore dice una casella e il terreno ne colora un'altra.
    for (let row = 0; row < SIZE; row++) {
      for (let col = 0; col < SIZE; col++) {
        expect(hexAt(centreX(col, row), centreY(row), SIZE)).toEqual([col, row]);
      }
    }
  });

  it("ritrova l'esagono anche da un punto qualunque dentro di esso", () => {
    // Non solo dal centro: un puntatore capita dove capita. Si prova su una corona di punti
    // a meta' del raggio interno, che sono dentro l'esagono da qualunque parte si guardi.
    for (let row = 1; row < 12; row++) {
      for (let col = 1; col < 12; col++) {
        for (let i = 0; i < 12; i++) {
          const angle = (i / 12) * Math.PI * 2;
          const x = centreX(col, row) + Math.cos(angle) * 0.24;
          const y = centreY(row) + Math.sin(angle) * 0.24;
          expect(hexAt(x, y, SIZE)).toEqual([col, row]);
        }
      }
    }
  });

  it("sfalsa le righe dispari di mezzo esagono, e solo quelle", () => {
    // E' TUTTA la differenza fra una griglia esagonale e una scacchiera. Se lo sfalsamento
    // sparisse, ogni singolo test qui sopra continuerebbe a passare.
    expect(centreX(5, 0)).toBeCloseTo(centreX(5, 2), 12);
    expect(centreX(5, 1) - centreX(5, 0)).toBeCloseTo(0.5, 12);
    expect(centreY(1) - centreY(0)).toBeCloseTo(ROW_RATIO, 12);
  });

  it("dice che la mappa e' un rettangolo largo, non un quadrato", () => {
    // Righe distanti 0,866: una mappa di 1536 righe e' alta meno di quanto e' larga, e chi
    // la inquadra deve chiederlo invece di assumerlo.
    expect(mapHeight(1536)).toBeCloseTo(1536 * ROW_RATIO, 9);
    expect(mapHeight(1536)).toBeLessThan(1536);
  });

  it("non risponde per punti fuori dalla mappa", () => {
    expect(hexAt(-3, 5, SIZE)).toBeNull();
    expect(hexAt(5, -3, SIZE)).toBeNull();
    expect(hexAt(SIZE + 3, 5, SIZE)).toBeNull();
    expect(hexAt(5, mapHeight(SIZE) + 3, SIZE)).toBeNull();
  });
});

describe("chi e' vicino a chi", () => {
  it("da' sei vicini, tutti a un esagono di distanza", () => {
    // Su una griglia sfalsata i sei vicini non sono gli stessi per le righe pari e per le
    // dispari. Prenderli dal quadrato e' l'errore classico, e si pagherebbe sulla distanza
    // dalla riva: la schiuma uscirebbe a denti di sega lungo ogni costa obliqua.
    for (const [col, row] of [[6, 4], [6, 5]] as [number, number][]) {
      const around = neighbours(col, row);
      expect(around).toHaveLength(6);
      const spacing = Math.hypot(centreX(col + 1, row) - centreX(col, row), 0);
      for (const [nc, nr] of around) {
        const d = Math.hypot(centreX(nc, nr) - centreX(col, row), centreY(nr) - centreY(row));
        expect(d).toBeCloseTo(spacing, 9);
      }
    }
  });

  it("e' una relazione reciproca", () => {
    // Se A e' vicino di B ma B non lo e' di A, la passata in avanti e quella all'indietro
    // della distanza dalla riva misurerebbero due mappe diverse.
    for (let row = 1; row < 10; row++) {
      for (let col = 1; col < 10; col++) {
        for (const [nc, nr] of neighbours(col, row)) {
          expect(neighbours(nc, nr)).toContainEqual([col, row]);
        }
      }
    }
  });
});

describe("il contorno", () => {
  it("ha sei vertici, con la punta in alto", () => {
    expect(CORNERS).toHaveLength(6);
    // Il primo vertice sta esattamente sopra il centro: e' cio' che rende l'esagono
    // "a punta in alto" invece che "a lato piatto", e da' la disposizione a righe sfalsate.
    expect(CORNERS[0][0]).toBeCloseTo(0, 12);
    expect(CORNERS[0][1]).toBeLessThan(0);
    // Largo uno da piatto a piatto: e' la definizione dell'unita' con cui lavora tutto.
    const width = Math.max(...CORNERS.map(([x]) => x)) - Math.min(...CORNERS.map(([x]) => x));
    expect(width).toBeCloseTo(1, 12);
  });
});
