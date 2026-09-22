// Le due domande a cui la schermata esiste per rispondere -- quando mi fermo, e cosa mi manca
// -- sono aritmetica, e l'aritmetica sbagliata dentro un componente non si vede: si legge
// come un numero plausibile.
import { describe, expect, it } from "vitest";
import { howLong, missingFor, stallNote, stallShort, units } from "./format";
import cases from "./format.cases.json";

// I casi condivisi con il client Godot. Vivono in un file solo perche' `format.ts` e
// `client/exilium/format.gd` sono la stessa regola scritta due volte, e due elenchi che si
// giurano uguali in questo progetto hanno gia' mentito cinque volte. Aggiungere un caso li'
// lo aggiunge a tutti e due; toglierne uno lo toglie a tutti e due, il che e' il punto.
describe("gli stessi casi che prova il client Godot", () => {
  it("dice i numeri come li dice l'altro", () => {
    for (const [milli, want] of cases.units) expect(units(milli as string)).toBe(want);
  });

  it("dice le durate come le dice l'altro", () => {
    for (const [seconds, want] of cases.how_long) expect(howLong(seconds as number)).toBe(want);
  });

  it("dice lo stallo come lo dice l'altro, in tutte e due le forme", () => {
    for (const [seconds, want] of cases.stall_note)
      expect(stallNote(seconds as number | null)).toBe(want);
    for (const [seconds, want] of cases.stall_short)
      expect(stallShort(seconds as number | null)).toBe(want);
  });

  it("conta cio' che manca come lo conta l'altro", () => {
    for (const [cost, held, want] of cases.missing_for) {
      const got = missingFor(cost as Record<string, string>, held as Record<string, string>);
      expect(got ?? {}).toEqual(want);
    }
  });
});

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
