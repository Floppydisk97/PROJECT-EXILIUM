// Il client verso il server autoritativo. Le decisioni che contano non sono "chiama fetch":
// sono COSA fa quando la risposta non arriva, e cosa NON fa quando la risposta e' un rifiuto.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiUnavailable, NotAuthorised, apiBase, call, saveToken, savedToken } from "./api";

// Un magazzino locale finto: i test girano in node, dove non esiste. Averlo in mano serve
// anche a poterlo rompere di proposito, che e' un caso vero -- finestra anonima, dati di
// sito bloccati -- in cui l'accesso NON torna null, lancia.
function fakeStorage(broken = false) {
  const kept = new Map<string, string>();
  return {
    getItem: (k: string) => { if (broken) throw new Error("bloccato"); return kept.get(k) ?? null; },
    setItem: (k: string, v: string) => { if (broken) throw new Error("bloccato"); kept.set(k, v); },
    removeItem: (k: string) => { if (broken) throw new Error("bloccato"); kept.delete(k); },
    clear: () => kept.clear(),
  };
}

beforeEach(() => vi.stubGlobal("localStorage", fakeStorage()));
afterEach(() => vi.unstubAllGlobals());

function replies(...responses: (Response | null)[]) {
  const seen: RequestInit[] = [];
  let at = 0;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    seen.push(init);
    const response = responses[Math.min(at, responses.length - 1)];
    at += 1;
    if (response === null) throw new Error("rete assente");
    return response;
  }));
  return seen;
}

const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

describe("dove sta il server", () => {
  it("si fa spostare a mano senza ricostruire il sito", () => {
    // Un export statico non ha un server a cui chiedere a runtime, quindi l'indirizzo e'
    // cotto nel bundle. Questo e' cio' che permette di puntarlo al backend sul proprio
    // computer in dieci secondi invece che in tre minuti di build.
    localStorage.setItem("exilium.api", "http://127.0.0.1:8000/");
    expect(apiBase()).toBe("http://127.0.0.1:8000");
  });

  it("non lascia una barra finale a raddoppiarsi nei percorsi", () => {
    localStorage.setItem("exilium.api", "https://esempio.test///");
    expect(apiBase()).toBe("https://esempio.test");
  });
});

describe("il token", () => {
  it("si ricorda e si dimentica", () => {
    expect(savedToken()).toBeNull();
    saveToken("abc");
    expect(savedToken()).toBe("abc");
    saveToken(null);
    expect(savedToken()).toBeNull();
  });
});

describe("quando il server dorme", () => {
  it("insiste su un 503 e riesce quando si sveglia", async () => {
    localStorage.setItem("exilium.api", "https://esempio.test");
    replies(new Response("", { status: 503 }), ok({ level: 3 }));
    const city = await call<{ level: number }>("/cities/x", { token: "t", budgetMs: 5000 });
    expect(city.level).toBe(3);
  });

  it("insiste anche su un 429 e su una rete che non c'e'", async () => {
    // Sono le due facce dello stesso momento: l'istanza che si sveglia rifiuta in fretta, e
    // il router a volte non risponde affatto. In entrambi i casi insistere e' la risposta.
    localStorage.setItem("exilium.api", "https://esempio.test");
    replies(new Response("", { status: 429 }), null, ok({ level: 1 }));
    await expect(call("/cities/x", { token: "t", budgetMs: 5000 })).resolves.toBeTruthy();
  });

  it("si arrende dicendo quanto ha aspettato, invece di girare per sempre", async () => {
    localStorage.setItem("exilium.api", "https://esempio.test");
    replies(new Response("", { status: 503 }));
    await expect(call("/cities/x", { token: "t", budgetMs: 120 }))
      .rejects.toBeInstanceOf(ApiUnavailable);
  });
});

describe("quando il server rifiuta", () => {
  it("NON insiste su un token sbagliato", async () => {
    // Un token sbagliato resta sbagliato per quanto a lungo si bussi, e novanta secondi di
    // attesa non direbbero al giocatore nient'altro che "e' rotto".
    localStorage.setItem("exilium.api", "https://esempio.test");
    const seen = replies(new Response("", { status: 401 }));
    await expect(call("/cities/x", { token: "t", budgetMs: 60_000 }))
      .rejects.toBeInstanceOf(NotAuthorised);
    expect(seen).toHaveLength(1);
  });

  it("riporta la ragione del server invece di inventarne una", async () => {
    localStorage.setItem("exilium.api", "https://esempio.test");
    replies(new Response(JSON.stringify({ detail: "not_enough_food" }), { status: 409 }));
    await expect(call("/cities/x/upgrade", { method: "POST", token: "t" }))
      .rejects.toThrow("not_enough_food");
  });

  it("dice chiaro quando non c'e' nessun server configurato", async () => {
    await expect(call("/cities/x", { token: "t" })).rejects.toBeInstanceOf(ApiUnavailable);
  });

  it("non chiama affatto senza un token", async () => {
    localStorage.setItem("exilium.api", "https://esempio.test");
    const seen = replies(ok({}));
    await expect(call("/cities/x")).rejects.toBeInstanceOf(NotAuthorised);
    expect(seen).toHaveLength(0);
  });
});

describe("un browser che non lascia ricordare niente", () => {
  it("non fa cadere la pagina, dice solo che manca il server", async () => {
    // Finestra anonima o dati di sito bloccati: l'accesso al magazzino locale LANCIA invece
    // di tornare vuoto. Una pagina che non se lo aspetta muore prima di disegnare.
    vi.stubGlobal("localStorage", fakeStorage(true));
    expect(() => apiBase()).not.toThrow();
    expect(savedToken()).toBeNull();
    expect(() => saveToken("x")).not.toThrow();
  });
});

describe("cio' che manda", () => {
  it("porta il token e una chiave di idempotenza su ogni POST", async () => {
    // Una richiesta ritentata non deve spendere due volte: e' la stessa garanzia che il
    // server pretende, e il client deve fornirgliela.
    localStorage.setItem("exilium.api", "https://esempio.test");
    const seen = replies(ok({}));
    await call("/cities/x/upgrade", { method: "POST", token: "segreto" });
    const headers = seen[0].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer segreto");
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });
});
