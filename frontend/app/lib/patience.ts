// Waiting out a free instance's cold start, counted the way the wait actually happens.
//
// The first version of this counted *attempts* and sized its patience with a per-attempt
// timeout. That reasoning only holds if a failing attempt is a slow one. It is not: Render's
// router answers a request for a sleeping service with an immediate 5xx, so each attempt cost
// about two seconds instead of the twenty-five the timeout allowed, and four attempts were
// spent in eighteen seconds. The comment promised a minute and a half of patience; the code
// delivered eighteen seconds, against a wake-up that needs fifty. Clicking "Riprova" only
// restarted a race that could not be won, which is exactly what it looked like from outside.
//
// So the budget here is wall-clock and nothing else. However fast the far end says no, we
// keep knocking until the time we said we would wait has genuinely passed.
export type Knock<T> = { done: true; value: T } | { done: false };

export type Patience = {
  budgetMs: number;   // total wall-clock time to keep trying before calling it an outage
  gapMs: number;      // pause after the first refusal...
  maxGapMs: number;   // ...doubling up to here, so a long wait is not also a hammering
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
};

export type Knocked<T> = { value: T | null; attempts: number; elapsedMs: number };

/** Call `probe` until it reports done or the budget runs out. Always probes at least once. */
export async function keepKnocking<T>(
  patience: Patience,
  probe: (attempt: number) => Promise<Knock<T>>,
): Promise<Knocked<T>> {
  const now = patience.now ?? (() => Date.now());
  const sleep = patience.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const started = now();
  let gap = patience.gapMs;
  let attempts = 0;

  for (;;) {
    attempts += 1;
    const knock = await probe(attempts);
    if (knock.done) return { value: knock.value, attempts, elapsedMs: now() - started };

    // Never sleep past the deadline: the budget is a promise about when we give up, not a
    // floor that a long final pause is allowed to overshoot.
    const remaining = patience.budgetMs - (now() - started);
    if (remaining <= 0) return { value: null, attempts, elapsedMs: now() - started };
    await sleep(Math.min(gap, remaining));
    gap = Math.min(gap * 2, patience.maxGapMs);
  }
}
