// The bug these pin cost a live site and a morning of reading logs, so they are written
// against the shape of the mistake rather than the shape of the code: patience that is
// promised in seconds must be spent in seconds, no matter how fast the far end refuses.
import { describe, expect, it } from "vitest";
import { keepKnocking } from "./patience";

/** A clock that only moves when the code under test says time passed. */
function fakeClock() {
  let t = 0;
  return {
    now: () => t,
    sleep: async (ms: number) => { t += ms; },
    spend: (ms: number) => { t += ms; },
  };
}

describe("keepKnocking", () => {
  it("keeps knocking for the whole budget when every refusal is instant", async () => {
    // This is the regression. Render's router rejects a request for a sleeping service in a
    // fraction of a second, so the old attempt-counting loop spent its four tries in eighteen
    // seconds and reported an outage while the instance was still forty seconds from ready.
    const clock = fakeClock();
    const result = await keepKnocking(
      { budgetMs: 90_000, gapMs: 1_500, maxGapMs: 8_000, now: clock.now, sleep: clock.sleep },
      async () => { clock.spend(200); return { done: false }; },   // an immediate 503
    );
    expect(result.value).toBeNull();
    expect(result.elapsedMs).toBeGreaterThanOrEqual(90_000);
    expect(result.attempts).toBeGreaterThan(10);
  });

  it("waits out a cold start that finishes inside the budget", async () => {
    const clock = fakeClock();
    const result = await keepKnocking<string>(
      { budgetMs: 90_000, gapMs: 1_500, maxGapMs: 8_000, now: clock.now, sleep: clock.sleep },
      async () => {
        clock.spend(200);
        return clock.now() >= 50_000 ? { done: true, value: "awake" } : { done: false };
      },
    );
    expect(result.value).toBe("awake");
    expect(result.elapsedMs).toBeLessThan(90_000);
  });

  it("answers on the first knock without spending anything", async () => {
    const clock = fakeClock();
    const result = await keepKnocking<string>(
      { budgetMs: 90_000, gapMs: 1_500, maxGapMs: 8_000, now: clock.now, sleep: clock.sleep },
      async () => ({ done: true, value: "cached" }),
    );
    expect(result).toEqual({ value: "cached", attempts: 1, elapsedMs: 0 });
  });

  it("never sleeps past the deadline it promised", async () => {
    // The budget is a statement about when we stop, so a long final pause must be clipped
    // rather than allowed to overshoot into a wait nobody asked for.
    const clock = fakeClock();
    const result = await keepKnocking(
      { budgetMs: 10_000, gapMs: 8_000, maxGapMs: 8_000, now: clock.now, sleep: clock.sleep },
      async () => ({ done: false }),
    );
    expect(result.elapsedMs).toBe(10_000);
  });

  it("slows its cadence but never stops early", async () => {
    // A two-minute wait must not also be a hammering: the gap grows. It must not grow without
    // limit either, or the last knocks land minutes apart and a ready server goes unnoticed.
    const clock = fakeClock();
    const gaps: number[] = [];
    let last = 0;
    await keepKnocking(
      {
        budgetMs: 60_000, gapMs: 1_000, maxGapMs: 4_000,
        now: clock.now,
        sleep: async (ms) => { gaps.push(ms); await clock.sleep(ms); },
      },
      async () => { last = clock.now(); return { done: false }; },
    );
    expect(gaps.slice(0, 3)).toEqual([1_000, 2_000, 4_000]);
    expect(Math.max(...gaps)).toBeLessThanOrEqual(4_000);
    expect(last).toBeGreaterThan(55_000);   // still knocking near the end of the budget
  });
});
