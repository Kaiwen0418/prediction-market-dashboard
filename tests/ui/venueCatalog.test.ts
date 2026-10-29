import assert from "node:assert/strict";
import test from "node:test";
import { normalizeVenueCatalog } from "@/services/catalog/api";

test("venue catalog normalizes and deduplicates discovered political pairs", () => {
  const catalog = normalizeVenueCatalog({
    updatedAt: "2026-07-28T10:00:00Z",
    venues: {
      polymarket: {
        events: [
          {
            id: "event-1",
            slug: "france-election",
            title: "France presidential election",
            active: true,
            closed: false,
            markets: [
              {
                id: "market-1",
                conditionId: "condition-1",
                clobTokenIds: "[\"token-1\", \"token-2\"]",
                outcomes: "[\"Yes\", \"No\"]",
                outcomePrices: "[\"0.62\", \"0.38\"]",
                volume24hr: 2500,
                active: true,
                closed: false
              }
            ]
          }
        ]
      },
      kalshi: {
        events: [
          {
            event_ticker: "PRES-28",
            series_ticker: "PRES",
            title: "Presidential election winner",
            markets: [
              {
                ticker: "PRES-28-A",
                status: "active",
                last_price_dollars: "0.55",
                volume_24h_fp: "1000"
              }
            ]
          }
        ]
      }
    }
  });

  assert.ok(catalog);
  assert.equal(catalog.polymarketMarkets.length, 1);
  assert.equal(catalog.polymarketMarkets[0]?.eventSlug, "france-election");
  assert.equal(catalog.kalshiMarkets.length, 1);
  assert.equal(catalog.kalshiMarkets[0]?.eventTicker, "PRES-28");
});

test("venue catalog rejects malformed payloads", () => {
  assert.equal(normalizeVenueCatalog(null), null);
  assert.equal(normalizeVenueCatalog({ venues: null }), null);
});
