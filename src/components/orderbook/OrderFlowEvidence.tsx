"use client";

import { DepthChart } from "@/components/charts/DepthChart";
import {
  getMarketSignalLabel,
  getMarketSignalSeverity
} from "@/components/maps/marketSignals";
import type {
  LiveMicrostructureMetrics,
  OrderbookState,
  OrderbookSummary
} from "@/types/market";
import type { RegionMarketSignal } from "@/types/signals";
import { relativeTime } from "@/utils/time";

type OrderFlowEvidenceProps = {
  liveMicrostructure?: LiveMicrostructureMetrics | null;
  orderbook: OrderbookState;
  orderbookSummary?: OrderbookSummary | null;
  signal?: RegionMarketSignal | null;
};

function formatWalletAddress(address: string) {
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

export function OrderFlowEvidence({
  liveMicrostructure,
  orderbook,
  orderbookSummary,
  signal
}: OrderFlowEvidenceProps) {
  const totalBidDepth = orderbook.bids.reduce(
    (sum, level) => sum + level.size,
    0
  );
  const totalAskDepth = orderbook.asks.reduce(
    (sum, level) => sum + level.size,
    0
  );
  const summary = orderbookSummary ?? {
    marketId: orderbook.marketId,
    tokenId: orderbook.tokenId ?? "",
    updatedAt: orderbook.updatedAt,
    bestBid: orderbook.bids[0]?.price ?? 0,
    bestAsk: orderbook.asks[0]?.price ?? 0,
    midPrice: orderbook.midPrice,
    spread: orderbook.spread,
    bidLevels: orderbook.bids.length,
    askLevels: orderbook.asks.length,
    tradeCount: orderbook.trades.length,
    liquidity: {
      totalBidDepth,
      totalAskDepth,
      imbalance:
        totalBidDepth + totalAskDepth === 0
          ? 0
          : (totalBidDepth - totalAskDepth) /
            (totalBidDepth + totalAskDepth),
      spreadBps:
        orderbook.midPrice === 0
          ? 0
          : (orderbook.spread / orderbook.midPrice) * 10_000
    },
    tradePressure: {
      buyVolume: 0,
      sellVolume: 0,
      ratio: 0,
      pressure: "balanced" as const
    }
  };
  const whaleActivity = summary.whaleActivity ?? {
    status: "insufficient-data" as const,
    sampleSize: orderbook.trades.length,
    medianTradeSize: 0,
    historicalMultipleThreshold: 3,
    depthShareThreshold: 0.05,
    minimumSampleSize: 5,
    attributionAvailable: false,
    attributedTradeCount: 0,
    uniqueWalletCount: 0,
    walletSampleMinimum: 10,
    walletConcentrationStatus: "unavailable" as const,
    walletConcentrationScore: null,
    topWalletVolumeShare: null,
    walletReputationStatus: "unavailable" as const,
    walletReputationScore: null,
    walletResolvedMarketCount: 0,
    walletResolvedMarketMinimum: 5,
    largeTrades: []
  };
  const totalFlow =
    summary.tradePressure.buyVolume + summary.tradePressure.sellVolume;
  const fallbackMicrostructure: LiveMicrostructureMetrics = {
    microprice: summary.midPrice,
    depthSkew: summary.liquidity.imbalance,
    realizedVolatility: 0,
    tradeIntensity:
      summary.tradeCount > 0 ? totalFlow / summary.tradeCount : 0,
    orderFlowImbalance:
      totalFlow === 0
        ? 0
        : (summary.tradePressure.buyVolume -
            summary.tradePressure.sellVolume) /
          totalFlow
  };
  const microstructure = liveMicrostructure ?? fallbackMicrostructure;

  return (
    <div className="grid gap-x-10 gap-y-8 lg:grid-cols-2">
      <section className="border-t border-[var(--demo-card-divider)] pt-5">
        {signal ? (
          <>
            <div className="flex items-start justify-between gap-5">
              <div>
                <p className="metric-label">
                  {getMarketSignalLabel(signal)}
                </p>
                <h3 className="mt-2 text-lg font-semibold text-slate-900">
                  {signal.headline}
                </h3>
              </div>
              <div className="text-right">
                <p className="text-3xl font-semibold tabular-nums text-slate-900">
                  {signal.score}
                </p>
                <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
                  {getMarketSignalSeverity(signal.score)}
                </p>
              </div>
            </div>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              {signal.detail}
            </p>
            <p className="mt-2 text-xs text-slate-400">
              Updated {relativeTime(signal.observedAt)}
              {signal.confidence !== undefined && signal.confidence > 0
                ? ` · ${Math.round(signal.confidence * 100)}% confidence`
                : ""}
            </p>
          </>
        ) : (
          <>
            <p className="metric-label">Regional Signal</p>
            <h3 className="mt-2 text-lg font-semibold text-slate-900">
              Signal coverage unavailable
            </h3>
          </>
        )}
        <div className="mt-6">
          <DepthChart
            askColor="#9f5f71"
            bidColor="#5c7ea6"
            height={280}
            orderbook={orderbook}
          />
        </div>
      </section>

      <div className="grid content-start gap-8">
        <section className="border-t border-[var(--demo-card-divider)] pt-5">
          <div className="flex items-center justify-between gap-3">
            <p className="metric-label">Market Snapshot</p>
            <span className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
              Updated {relativeTime(orderbook.updatedAt)}
            </span>
          </div>
          <div className="mt-3 divide-y divide-[var(--demo-card-divider)] text-sm">
            <div className="flex items-baseline justify-between gap-4 py-2.5">
              <span className="text-slate-500">Mid / microprice</span>
              <span className="font-semibold tabular-nums text-slate-900">
                {summary.midPrice.toFixed(3)} /{" "}
                {microstructure.microprice.toFixed(3)}
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-2.5">
              <span className="text-slate-500">Spread / depth skew</span>
              <span className="font-semibold tabular-nums text-slate-900">
                {summary.liquidity.spreadBps.toFixed(1)} bps /{" "}
                {(microstructure.depthSkew * 100).toFixed(1)}%
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-2.5">
              <span className="text-slate-500">Flow / volatility</span>
              <span className="font-semibold tabular-nums text-slate-900">
                {(microstructure.orderFlowImbalance * 100).toFixed(1)}% /{" "}
                {microstructure.realizedVolatility.toFixed(4)}
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-2.5">
              <span className="text-slate-500">Depth / activity</span>
              <span className="font-semibold tabular-nums text-slate-900">
                {summary.liquidity.totalBidDepth.toFixed(0)} /{" "}
                {summary.liquidity.totalAskDepth.toFixed(0)} ·{" "}
                {microstructure.tradeIntensity.toFixed(1)}
              </span>
            </div>
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            {liveMicrostructure
              ? "Calculated from recent market activity."
              : "Estimated from the latest available order book."}
          </p>
        </section>

        <section className="border-t border-[var(--demo-card-divider)] pt-5">
          <div className="flex items-baseline justify-between gap-3">
            <p className="metric-label">Large Trade Monitor</p>
            <span className="text-xs tabular-nums text-slate-500">
              {whaleActivity.sampleSize} prints
            </span>
          </div>
          {whaleActivity.status === "detected" ? (
            <div className="mt-3 divide-y divide-[var(--demo-card-divider)]">
              {whaleActivity.largeTrades.slice(0, 3).map((trade) => (
                <div
                  key={trade.tradeId}
                  className="grid grid-cols-[auto_1fr_auto] items-baseline gap-3 py-2.5 text-sm"
                >
                  <span
                    className={`font-semibold uppercase ${
                      trade.side === "buy"
                        ? "text-emerald-700"
                        : "text-rose-700"
                    }`}
                  >
                    {trade.side}
                  </span>
                  <span className="text-slate-600">
                    {trade.historicalSizeMultiple.toFixed(1)}x median ·{" "}
                    {(trade.executableDepthShare * 100).toFixed(1)}% depth
                    {trade.walletAddress
                      ? ` · ${formatWalletAddress(trade.walletAddress)}`
                      : ""}
                  </span>
                  <span className="font-semibold tabular-nums text-slate-900">
                    ${trade.notionalUsd.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm leading-6 text-slate-600">
              {whaleActivity.status === "clear"
                ? "No recent print meets both relative thresholds."
                : whaleActivity.sampleSize >= whaleActivity.minimumSampleSize
                  ? "There is not enough recent trade data to assess large-trade activity."
                  : `At least ${whaleActivity.minimumSampleSize} normalized prints and two-sided depth are required.`}
            </p>
          )}
          <p className="mt-3 text-xs leading-5 text-slate-500">
            {whaleActivity.walletConcentrationStatus === "available" &&
            whaleActivity.walletConcentrationScore !== null &&
            whaleActivity.topWalletVolumeShare !== null
              ? `Wallet concentration ${whaleActivity.walletConcentrationScore.toFixed(1)}/100 · top public wallet ${(
                  whaleActivity.topWalletVolumeShare * 100
                ).toFixed(1)}% · ${whaleActivity.uniqueWalletCount} wallets · ${
                  whaleActivity.attributedTradeCount
                } attributed prints`
              : whaleActivity.walletConcentrationStatus === "insufficient-data"
                ? `${whaleActivity.attributedTradeCount} attributed prints · ${whaleActivity.walletSampleMinimum} required for concentration scoring`
                : "Public wallet attribution is unavailable for this sample."}
          </p>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            {whaleActivity.walletReputationStatus === "available" &&
            whaleActivity.walletReputationScore !== null
              ? `Resolved-history score ${whaleActivity.walletReputationScore.toFixed(1)}/100 · ${whaleActivity.walletResolvedMarketCount} resolved markets`
              : whaleActivity.walletReputationStatus === "insufficient-history"
                ? `Resolved history ${whaleActivity.walletResolvedMarketCount}/${whaleActivity.walletResolvedMarketMinimum} markets · score withheld`
                : `Wallet reputation unavailable · ${whaleActivity.walletResolvedMarketCount} resolved markets`}
          </p>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            Flagged at {whaleActivity.historicalMultipleThreshold}x median size
            and {(whaleActivity.depthShareThreshold * 100).toFixed(0)}% of
            executable depth. Public trades do not establish wallet identity or
            insider activity.
          </p>
        </section>
      </div>
    </div>
  );
}
