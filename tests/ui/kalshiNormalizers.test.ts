import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeKalshiAnalytics,
  normalizeKalshiEvents
} from "@/services/kalshi/normalizers";
import type { VenueMarketSummary } from "@/types/market";

test("Kalshi events normalize the leading contract and aggregate event volume", () => {
  const markets = normalizeKalshiEvents({
    events: [
      {
        event_ticker: "KXGOVCA-26",
        series_ticker: "KXGOVCA",
        title: "California Governor winner? (Person)",
        category: "Elections",
        settlement_sources: [
          {
            name: "California Secretary of State",
            url: "https://www.sos.ca.gov/elections"
          }
        ],
        markets: [
          {
            ticker: "KXGOVCA-26-XBEC",
            status: "active",
            yes_sub_title: "Xavier Becerra",
            last_price_dollars: "0.8500",
            volume_24h_fp: "125.50",
            liquidity_dollars: "500.00",
            expected_expiration_time: "2027-11-03T16:00:00Z",
            updated_time: "2026-07-28T09:00:00Z"
          },
          {
            ticker: "KXGOVCA-26-SHIL",
            status: "active",
            yes_sub_title: "Steve Hilton",
            last_price_dollars: "0.0900",
            volume_24h_fp: "74.50",
            liquidity_dollars: "250.00",
            updated_time: "2026-07-28T09:01:00Z"
          }
        ]
      }
    ]
  });

  assert.equal(markets.length, 1);
  assert.equal(markets[0]?.eventTicker, "KXGOVCA-26");
  assert.equal(markets[0]?.marketTicker, "KXGOVCA-26-XBEC");
  assert.equal(markets[0]?.outcomeLabel, "Xavier Becerra");
  assert.equal(markets[0]?.probability, 0.85);
  assert.equal(markets[0]?.volume24h, 200);
  assert.equal(markets[0]?.liquidity, 750);
  assert.equal(markets[0]?.status, "open");
  assert.equal(
    markets[0]?.url,
    "https://kalshi.com/markets/kxgovca/kxgovca-26"
  );
  assert.equal(
    markets[0]?.resolutionSource,
    "https://www.sos.ca.gov/elections"
  );
});

test("Kalshi normalization rejects malformed events and unsafe source URLs", () => {
  const markets = normalizeKalshiEvents({
    events: [
      { event_ticker: "MISSING-MARKETS" },
      {
        event_ticker: "SENATETX-26",
        series_ticker: "SENATETX",
        title: "Texas Senate winner?",
        settlement_sources: [{ url: "javascript:alert(1)" }],
        markets: [
          {
            ticker: "SENATETX-26-R",
            status: "finalized",
            yes_sub_title: "Republican party",
            last_price_dollars: "0.64"
          }
        ]
      }
    ]
  });

  assert.equal(markets.length, 1);
  assert.equal(markets[0]?.status, "closed");
  assert.equal(markets[0]?.resolutionSource, undefined);
});

test("Kalshi analytics normalize orderbook, trades, history, and large prints", () => {
  const summary: VenueMarketSummary = {
    venue: "Kalshi",
    eventTicker: "KXGOVCA-26",
    marketTicker: "KXGOVCA-26-XBEC",
    seriesTicker: "KXGOVCA",
    title: "Who will win the governorship in California?",
    outcomeLabel: "Xavier Becerra",
    probability: 0.62,
    volume24h: 25_000,
    liquidity: 12_000,
    status: "open",
    url: "https://kalshi.com/markets/kxgovca/kxgovca-26",
    updatedAt: "2026-07-28T10:00:00.000Z"
  };
  const analytics = normalizeKalshiAnalytics(
    {
      orderbook: {
        orderbook_fp: {
          yes_dollars: [
            ["0.60", "100"],
            ["0.61", "50"]
          ],
          no_dollars: [
            ["0.36", "80"],
            ["0.37", "40"]
          ]
        }
      },
      trades: {
        trades: [
          {
            trade_id: "large-buy",
            yes_price_dollars: "0.63",
            count_fp: "60",
            taker_outcome_side: "yes",
            created_time: "2026-07-28T10:00:00Z"
          },
          {
            trade_id: "sell",
            yes_price_dollars: "0.62",
            count_fp: "5",
            taker_outcome_side: "no",
            created_time: "2026-07-28T09:00:00Z"
          },
          {
            trade_id: "small-1",
            yes_price_dollars: "0.61",
            count_fp: "5",
            taker_outcome_side: "yes",
            created_time: "2026-07-28T08:00:00Z"
          },
          {
            trade_id: "small-2",
            yes_price_dollars: "0.60",
            count_fp: "5",
            taker_outcome_side: "yes",
            created_time: "2026-07-28T07:00:00Z"
          },
          {
            trade_id: "small-3",
            yes_price_dollars: "0.59",
            count_fp: "5",
            taker_outcome_side: "no",
            created_time: "2026-07-28T06:00:00Z"
          }
        ]
      },
      candlesticks: {
        candlesticks: [
          {
            end_period_ts: 1785232800,
            price: { close_dollars: "0.60" },
            yes_bid: { close_dollars: "0.59" },
            yes_ask: { close_dollars: "0.61" },
            volume_fp: "100"
          },
          {
            end_period_ts: 1785236400,
            price: { close_dollars: "", previous_dollars: "0.62" },
            yes_bid: { close_dollars: "0.61" },
            yes_ask: { close_dollars: "0.63" },
            volume_fp: "150"
          }
        ]
      }
    },
    summary
  );

  assert.ok(analytics);
  assert.equal(analytics.market.venue, "Kalshi");
  assert.equal(analytics.orderbook.bids[0]?.price, 0.61);
  assert.equal(analytics.orderbook.asks[0]?.price, 0.63);
  assert.equal(analytics.orderbook.trades[0]?.side, "buy");
  assert.equal(analytics.orderbookSummary.tradeCount, 5);
  assert.equal(analytics.orderbookSummary.whaleActivity?.status, "detected");
  assert.equal(
    analytics.orderbookSummary.whaleActivity?.largeTrades[0]?.tradeId,
    "large-buy"
  );
  assert.equal(analytics.marketSeries.length, 2);
  assert.equal(analytics.replay.samples.length, 2);
});
