import assert from "node:assert/strict";
import test from "node:test";
import {
  filterRegionMarketTrades,
  getVisibleMarketTrades
} from "@/components/maps/MapLiveTradeTape";
import {
  appendTradePopupQueue,
  matchVenueTradesToRegions
} from "@/components/maps/mapTradePopups";
import { REGION_MARKETS } from "@/components/maps/spotlightStates";
import type { MarketTradePrint } from "@/types/market";

const trades = ["one", "two", "three", "four"].map(
  (marketSlug, index): MarketTradePrint => ({
    id: marketSlug,
    conditionId: `condition-${index}`,
    marketSlug,
    title: marketSlug,
    side: index % 2 ? "sell" : "buy",
    price: 0.5,
    size: 10,
    timestamp: `2026-07-24T10:00:0${index}Z`
  })
);

test("live trade tape rotates and wraps through the filtered feed", () => {
  assert.deepEqual(
    getVisibleMarketTrades(trades, 3).map((trade) => trade.marketSlug),
    ["four", "one", "two"]
  );
  assert.deepEqual(getVisibleMarketTrades([], 0), []);
});

test("live trade tape only includes configured regional market pairs", () => {
  const eventMatch = {
    ...trades[1],
    id: "event-match",
    eventSlug: "configured-event"
  };

  assert.deepEqual(
    filterRegionMarketTrades(
      [trades[0], eventMatch, trades[2]],
      ["one", "configured-event"]
    ).map((trade) => trade.id),
    ["one", "event-match"]
  );
});

test("globe trade popups only map actual venue trades to configured regions", () => {
  const texasTrade = {
    ...trades[0],
    id: "texas-trade",
    marketSlug: "texas-republican-senate-primary-winner"
  };
  const unmatchedTrade = {
    ...trades[1],
    id: "unmatched-trade",
    marketSlug: "not-a-configured-regional-market"
  };

  assert.deepEqual(
    matchVenueTradesToRegions(
      [texasTrade, unmatchedTrade],
      REGION_MARKETS
    ).map(({ region, trade }) => [region.code, trade.id]),
    [["TX", "texas-trade"]]
  );
});

test("globe trade popup queue expires old entries and caps FIFO at three", () => {
  const initial = appendTradePopupQueue(
    [],
    [{ id: "one" }, { id: "two" }],
    1_000,
    7_000
  );
  const capped = appendTradePopupQueue(
    initial,
    [{ id: "three" }, { id: "four" }],
    2_000,
    7_000
  );

  assert.deepEqual(
    capped.map(({ id }) => id),
    ["two", "three", "four"]
  );
  assert.deepEqual(
    appendTradePopupQueue(capped, [{ id: "five" }], 10_000, 7_000).map(
      ({ id }) => id
    ),
    ["five"]
  );
});
