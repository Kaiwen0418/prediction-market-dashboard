import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizeGammaEvent,
  normalizeGammaMarket,
  normalizeMarketTrades,
  normalizeOrderbook
} from "@/services/polymarket/normalizers";

test("public Data API trades retain only valid proxy-wallet addresses", () => {
  const orderbook = normalizeOrderbook({
    trades: [
      {
        proxyWallet: "0xaebe4cfd8735f44be2768380f1d9b0cfd6882c1d",
        side: "BUY",
        size: 23.98,
        price: 0.0436663887,
        timestamp: 1784892844,
        transactionHash: "0xtrade"
      },
      {
        proxyWallet: "not-an-address",
        side: "SELL",
        size: 5,
        price: 0.6,
        timestamp: 1784892844,
        transactionHash: "0xinvalid-wallet"
      }
    ]
  });

  assert.equal(
    orderbook?.trades[0]?.walletAddress,
    "0xaebe4cfd8735f44be2768380f1d9b0cfd6882c1d"
  );
  assert.equal(orderbook?.trades[1]?.walletAddress, undefined);
});

test("global market trades preserve identity and sort newest first", () => {
  const trades = normalizeMarketTrades([
    {
      transactionHash: "0xolder",
      asset: "asset-1",
      conditionId: "condition-1",
      slug: "market-one",
      eventSlug: "event-one",
      title: "Market one",
      outcome: "Yes",
      side: "BUY",
      size: 20,
      price: 0.4,
      timestamp: 1784892800
    },
    {
      transactionHash: "0xnewer",
      asset: "asset-2",
      conditionId: "condition-2",
      slug: "market-two",
      title: "Market two",
      side: "SELL",
      size: 10,
      price: 0.7,
      timestamp: "1784892900"
    },
    {
      title: "Incomplete trade",
      size: 2,
      price: 0.5
    }
  ]);

  assert.deepEqual(
    trades.map((trade) => trade.marketSlug),
    ["market-two", "market-one"]
  );
  assert.equal(trades[0]?.side, "sell");
  assert.equal(trades[1]?.eventSlug, "event-one");
  assert.match(trades[0]?.timestamp ?? "", /^2026-/);
});

test("market normalization preserves verified contract context", () => {
  const market = normalizeGammaMarket({
    id: "market-1",
    clobTokenIds: "[\"token-1\"]",
    question: "Will the measure pass?",
    description: "Resolves Yes if the certified result approves the measure.",
    endDate: "2026-11-04T00:00:00Z",
    resolutionSource: "https://example.gov/elections/results",
    active: true,
    closed: false
  });

  assert.equal(market?.venue, "Polymarket");
  assert.equal(market?.status, "open");
  assert.equal(market?.endDate, "2026-11-04T00:00:00.000Z");
  assert.equal(market?.resolutionSource, "https://example.gov/elections/results");
  assert.equal(
    market?.description,
    "Resolves Yes if the certified result approves the measure."
  );
});

test("event normalization prefers market rules and rejects unsafe contract metadata", () => {
  const market = normalizeGammaEvent({
    id: "event-1",
    title: "Election event",
    description: "General event description",
    endDate: "not-a-date",
    resolutionSource: "javascript:alert(1)",
    markets: [
      {
        id: "market-1",
        clobTokenIds: "[\"token-1\"]",
        question: "Will the candidate win?",
        description: "Resolves from the certified election result.",
        outcomes: "[\"Yes\", \"No\"]",
        outcomePrices: "[\"0.6\", \"0.4\"]"
      }
    ]
  });

  assert.equal(market?.description, "Resolves from the certified election result.");
  assert.equal(market?.endDate, undefined);
  assert.equal(market?.resolutionSource, undefined);
  assert.equal(market?.status, "unknown");
});

test("closed status takes precedence and non-orderable markets are inactive", () => {
  const closedMarket = normalizeGammaEvent({
    id: "closed-event",
    title: "Closed election",
    active: true,
    closed: true,
    markets: [
      {
        id: "closed-market",
        clobTokenIds: "[\"closed-token\"]",
        question: "Will the candidate win?",
        active: true,
        closed: true,
        acceptingOrders: false
      }
    ]
  });
  const inactiveMarket = normalizeGammaMarket({
    id: "inactive-market",
    clobTokenIds: "[\"inactive-token\"]",
    question: "Will trading resume?",
    active: true,
    closed: false,
    acceptingOrders: false
  });

  assert.equal(closedMarket?.status, "closed");
  assert.equal(inactiveMarket?.status, "inactive");
});
