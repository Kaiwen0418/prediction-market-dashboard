import assert from "node:assert/strict";
import test from "node:test";
import {
  createMarketSeries,
  createOrderbookSnapshot,
  getMockMarketBySlug
} from "@/services/polymarket/mockData";

const ukMarketSlugs = [
  "will-scotland-hold-an-independence-referendum-before-2030",
  "next-london-mayoral-election-winner",
  "welsh-parliament-election-most-seats",
  "northern-ireland-assembly-election-most-seats"
] as const;

const europeMarketSlugs = [
  "next-french-presidential-election",
  "berlin-state-election-winner",
  "next-prime-minister-of-spain-20260625005215443",
  "next-prime-minister-of-italy",
  "icelandic-european-union-membership-negotiations-referendum-passes-20260609135241589"
] as const;

const conflictMarketSlugs = [
  "israel-x-iran-ceasefire-continues-through-august-31-20260716224448970-754-896-823",
  "us-x-iran-effective-ceasfire-by-august-31-20260715194822047",
  "israel-withdraws-from-lebanon-by-august-31-2026",
  "israel-x-hamas-ceasefire-phase-ii-by-december-31-632",
  "ukraine-signs-peace-deal-with-russia-before-2027",
  "will-russia-capture-all-of-huliaipole-by-september-30",
  "will-russia-capture-kostyantynivka-by-december-31-2026-936-942-271-276-578-687-312-238",
  "will-russia-enter-myrne-by-july-31-2026",
  "will-russia-enter-stinky-by-july-31",
  "will-russia-capture-bilytske-by-december-31-2026-252-757-575",
  "russia-x-ukraine-ceasefire-agreement-by-december-31-2026"
] as const;

test("UK market fallbacks preserve each selected market identity", () => {
  for (const slug of ukMarketSlugs) {
    const market = getMockMarketBySlug(slug);

    assert.equal(market.slug, slug);
    assert.equal(market.eventSlug, slug);
    assert.ok(market.outcomeLabel);
    assert.ok(market.tokenId);
  }
});

test("UK market fallback supplies coherent history and order book values", () => {
  const market = getMockMarketBySlug(ukMarketSlugs[0]);
  const history = createMarketSeries(market);
  const orderbook = createOrderbookSnapshot(market);

  assert.equal(history.length, 30);
  assert.equal(orderbook.marketId, market.marketId);
  assert.equal(orderbook.tokenId, market.tokenId);
  assert.ok(Math.abs(orderbook.midPrice - market.probability) <= 0.011);
  assert.ok(Math.abs((history.at(-1)?.value ?? 0) - market.probability) <= 0.03);
});

test("configured fallbacks distinguish the verified open and closed markets", () => {
  const california = getMockMarketBySlug("california-governor-election-2026");
  const texas = getMockMarketBySlug("texas-republican-senate-primary-winner");

  assert.equal(california.status, "open");
  assert.equal(california.endDate, "2026-11-03T00:00:00.000Z");
  assert.equal(texas.status, "closed");
  assert.equal(texas.endDate, "2026-05-26T00:00:00.000Z");
  assert.equal(texas.probability, 1);
});

test("Europe fallbacks preserve verified open lifecycle context", () => {
  for (const slug of europeMarketSlugs) {
    const market = getMockMarketBySlug(slug);

    assert.equal(market.slug, slug);
    assert.equal(market.status, "open");
    assert.ok(market.endDate);
    assert.ok(market.tokenId);
  }
});

test("conflict-market fallbacks preserve verified open lifecycle context", () => {
  for (const slug of conflictMarketSlugs) {
    const market = getMockMarketBySlug(slug);

    assert.equal(market.slug, slug);
    assert.equal(market.status, "open");
    assert.equal(market.category, "Geopolitics");
    assert.ok(market.endDate);
    assert.ok(market.tokenId);
  }
});
