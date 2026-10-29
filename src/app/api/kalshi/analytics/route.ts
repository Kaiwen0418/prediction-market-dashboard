import { NextRequest, NextResponse } from "next/server";
import { kalshiConfig } from "@/services/kalshi/config";

export const revalidate = 5;

const TICKER_PATTERN = /^[A-Z0-9-]{2,100}$/;

async function fetchKalshiJson(url: URL, cacheSeconds: number) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    next: { revalidate: cacheSeconds }
  });
  if (!response.ok) {
    throw new Error(`Kalshi request failed: ${response.status}`);
  }
  return response.json() as Promise<unknown>;
}

export async function GET(request: NextRequest) {
  const ticker = request.nextUrl.searchParams.get("ticker") ?? "";
  const seriesTicker =
    request.nextUrl.searchParams.get("seriesTicker") ?? "";
  if (
    !TICKER_PATTERN.test(ticker) ||
    !TICKER_PATTERN.test(seriesTicker)
  ) {
    return NextResponse.json(
      { error: "Valid Kalshi market and series tickers are required" },
      { status: 400 }
    );
  }

  const endTimestamp =
    Math.floor(Date.now() / (60 * 60 * 1_000)) * 60 * 60;
  const startTimestamp = endTimestamp - 14 * 24 * 60 * 60;
  const orderbookUrl = new URL(
    `${kalshiConfig.apiBaseUrl}/markets/${ticker}/orderbook`
  );
  orderbookUrl.searchParams.set("depth", "100");
  const tradesUrl = new URL(`${kalshiConfig.apiBaseUrl}/markets/trades`);
  tradesUrl.searchParams.set("ticker", ticker);
  tradesUrl.searchParams.set("limit", "200");
  const candlesUrl = new URL(
    `${kalshiConfig.apiBaseUrl}/series/${seriesTicker}/markets/${ticker}/candlesticks`
  );
  candlesUrl.searchParams.set("start_ts", String(startTimestamp));
  candlesUrl.searchParams.set("end_ts", String(endTimestamp));
  candlesUrl.searchParams.set("period_interval", "60");
  candlesUrl.searchParams.set("include_latest_before_start", "true");

  const [orderbook, trades, candlesticks] = await Promise.allSettled([
    fetchKalshiJson(orderbookUrl, 10),
    fetchKalshiJson(tradesUrl, 10),
    fetchKalshiJson(candlesUrl, 300)
  ]);

  if (
    orderbook.status === "rejected" &&
    trades.status === "rejected" &&
    candlesticks.status === "rejected"
  ) {
    return NextResponse.json(
      { error: "Kalshi analytics requests failed" },
      { status: 502 }
    );
  }

  return NextResponse.json(
    {
      ticker,
      seriesTicker,
      orderbook: orderbook.status === "fulfilled" ? orderbook.value : null,
      trades: trades.status === "fulfilled" ? trades.value : null,
      candlesticks:
        candlesticks.status === "fulfilled" ? candlesticks.value : null
    },
    {
      headers: {
        "Cache-Control":
          "public, s-maxage=10, stale-while-revalidate=60, stale-if-error=300"
      }
    }
  );
}
