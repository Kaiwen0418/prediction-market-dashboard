"use client";

import { useEffect, useMemo, useState } from "react";
import type { MarketTradePrint } from "@/types/market";
import { formatTimestamp } from "@/utils/time";

type MapLiveTradeTapeProps = {
  marketSlugs: string[];
  trades: MarketTradePrint[];
};

const VISIBLE_TRADE_COUNT = 3;

function formatNotional(trade: MarketTradePrint) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1
  }).format(trade.price * trade.size);
}

export function formatTradePopupText(trade: MarketTradePrint) {
  const outcome = trade.outcome?.trim().toUpperCase();
  const label =
    outcome === "YES" || outcome === "NO"
      ? outcome
      : trade.side === "buy"
        ? "YES"
        : "NO";
  const sign = trade.side === "buy" ? "+" : "-";

  return `${label} ${sign}${formatNotional(trade)}`;
}

export function getVisibleMarketTrades(
  trades: MarketTradePrint[],
  offset: number,
  count = VISIBLE_TRADE_COUNT
) {
  if (!trades.length) return [];

  return Array.from(
    { length: Math.min(count, trades.length) },
    (_, index) => trades[(offset + index) % trades.length]
  );
}

export function filterRegionMarketTrades(
  trades: MarketTradePrint[],
  marketSlugs: string[]
) {
  const configuredSlugs = new Set(marketSlugs);

  return trades.filter(
    (trade) =>
      configuredSlugs.has(trade.marketSlug) ||
      (trade.eventSlug ? configuredSlugs.has(trade.eventSlug) : false)
  );
}

export function MapLiveTradeTape({
  marketSlugs,
  trades
}: MapLiveTradeTapeProps) {
  const [offset, setOffset] = useState(0);
  const regionTrades = useMemo(
    () => filterRegionMarketTrades(trades, marketSlugs),
    [marketSlugs, trades]
  );

  useEffect(() => {
    setOffset((current) =>
      regionTrades.length ? current % regionTrades.length : 0
    );
  }, [regionTrades.length]);

  useEffect(() => {
    if (regionTrades.length <= VISIBLE_TRADE_COUNT) return;

    const interval = window.setInterval(() => {
      setOffset((current) => (current + 1) % regionTrades.length);
    }, 2_800);

    return () => window.clearInterval(interval);
  }, [regionTrades.length]);

  const visibleTrades = useMemo(
    () => getVisibleMarketTrades(regionTrades, offset),
    [offset, regionTrades]
  );

  if (!visibleTrades.length) return null;

  return (
    <section
      aria-label="Live trades for regional market pairs"
      aria-live="polite"
      className="pointer-events-none absolute bottom-4 left-4 z-10 flex w-[calc(100%_-_2rem)] max-w-[calc(100vw_-_3.5rem)] flex-col items-start gap-1.5 overflow-hidden font-sans sm:max-w-[300px]"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase text-slate-900">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Live trades
      </div>
      <div key={offset} className="map-trade-tape-enter flex flex-col items-start gap-1.5">
        {visibleTrades.map((trade, index) => (
          <a
            key={trade.id}
            href={`https://polymarket.com/event/${
              trade.eventSlug || trade.marketSlug
            }`}
            target="_blank"
            rel="noreferrer"
            className={`pointer-events-auto grid max-w-full grid-cols-[auto_auto] items-baseline gap-x-2 gap-y-0.5 text-shadow-sm ${
              index === 2 ? "hidden sm:grid" : "grid"
            }`}
          >
            <span
              className={`text-[12px] font-bold tabular-nums ${
                trade.side === "buy"
                  ? "text-emerald-700"
                  : "text-rose-700"
              }`}
            >
              {formatTradePopupText(trade)}
            </span>
            <span className="truncate text-[9px] font-medium text-slate-600">
              {formatTimestamp(trade.timestamp, "HH:mm:ss")}
            </span>
          </a>
        ))}
      </div>
    </section>
  );
}
