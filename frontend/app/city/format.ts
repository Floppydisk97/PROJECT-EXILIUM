// Mettere in parole i numeri del server. Tenuto separato dalla schermata perche' queste sono
// decisioni, non disegno: quando una colonia si ferma, e quanto le manca per il prossimo
// livello, sono le due domande a cui la schermata esiste per rispondere -- e si possono
// sbagliare in silenzio.

/** Milli-unita' -> unita', come le legge una persona. */
export function units(milli: string | number): string {
  const value = typeof milli === "string" ? Number(milli) : milli;
  return Math.floor(value / 1000).toLocaleString("it-IT");
}

/** Una durata in parole brevi. Sopra il giorno le ore non interessano piu' a nessuno. */
export function howLong(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = seconds / 3600;
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 1 : 0)} h`;
  return `${Math.round(hours / 24)} giorni`;
}

/** Quando questo magazzino smettera' di guadagnare, detto a chi guarda.
 *
 *  E' la meta' che rende accettabile lo stallo in un mondo che cammina mentre dormi:
 *  fermarsi e' la tensione voluta, fermarsi a sorpresa e' una punizione per chi ha un lavoro.
 */
export function stallNote(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "fermo";
  if (seconds <= 0) return "pieno";
  return `pieno fra ${howLong(seconds)}`;
}

/** Cosa manca per iniziare il prossimo livello, o null se si puo' gia'. */
export function missingFor(
  cost: Record<string, string>,
  held: Record<string, string>,
): Record<string, number> | null {
  const short: Record<string, number> = {};
  for (const [resource, amount] of Object.entries(cost)) {
    const gap = Number(amount) - Number(held[resource] ?? 0);
    if (gap > 0) short[resource] = gap;
  }
  return Object.keys(short).length ? short : null;
}
