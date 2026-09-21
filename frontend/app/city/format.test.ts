// Le due domande a cui la schermata esiste per rispondere -- quando mi fermo, e cosa mi manca
// -- sono aritmetica, e l'aritmetica sbagliata dentro un componente non si vede: si legge
// come un numero plausibile.
import { describe, expect, it } from "vitest";
import { howLong, missingFor, stallNote, stallShort, units } from "./format";

describe("i numeri in parole", () => {
  it("conta in unita', non in milli", () => {
    expect(units("10000000")).toBe("10.000");
    expect(units(999)).toBe("0");       // meno di un'unita' non e' un'unita'
    // L'italiano NON raggruppa le quattro cifre: duemila si scrive 2000, non 2.000. Fissato
    // qui perche' e' il genere di cosa che qualcuno "corregge" credendo sia un difetto.
    expect(units("2000000")).toBe("2000");
  });

  it("dice le durate come le direbbe una persona", () => {
    expect(howLong(30)).toBe("30 s");
    expect(howLong(90)).toBe("2 min");
    expect(howLong(3600 * 4)).toBe("4.0 h");
    expect(howLong(3600 * 72)).toBe("3 giorni");
  });
});

describe("quando la colonia si ferma", () => {
  it("lo dice prima, perche' e' cio' che rende lo stallo una strategia", () => {
    expect(stallNote(7200)).toBe("pieno fra 2.0 h");
  });

  it("distingue un magazzino gia' pieno da uno che non si riempira' mai", () => {
    // Due stati diversi con lo stesso aspetto se li si confonde: uno chiede di spendere,
    // l'altro dice che quella risorsa qui non arriva.
    expect(stallNote(0)).toBe("pieno");
    expect(stallNote(null)).toBe("fermo");
  });

  it("dice le stesse TRE cose anche nella pastiglia stretta", () => {
    // La barra di gioco aveva la sua copia della regola. Una copia e' un posto in piu' dove
    // "fermo" e "pieno" si possono scambiare senza che nessun test se ne accorga.
    expect(stallShort(7200)).toBe("fra 2.0 h");
    expect(stallShort(0)).toBe("pieno");
    expect(stallShort(undefined)).toBe("fermo");
  });
});

describe("cosa manca per il prossimo livello", () => {
  const cost = { stone: "60000", timber: "60000" };

  it("tace quando si puo' gia' costruire", () => {
    expect(missingFor(cost, { stone: "60000", timber: "99999" })).toBeNull();
  });

  it("nomina SOLO cio' che manca davvero", () => {
    // Un messaggio che elenca anche cio' che c'e' costringe a fare la sottrazione a mente.
    expect(missingFor(cost, { stone: "10000", timber: "60000" })).toEqual({ stone: 50000 });
  });

  it("non si fa ingannare da una risorsa che non c'e' affatto nel magazzino", () => {
    expect(missingFor(cost, {})).toEqual({ stone: 60000, timber: 60000 });
  });
});
