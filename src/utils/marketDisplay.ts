import type { MarketSnapshot } from "@/types/market";

export function getMarketDisplayTitle(
  market: Pick<MarketSnapshot, "title" | "outcomeLabel"> | null | undefined
) {
  if (!market) return undefined;

  const outcomeLabel = market.outcomeLabel?.trim();
  if (
    outcomeLabel &&
    !["yes", "no"].includes(outcomeLabel.toLowerCase())
  ) {
    return outcomeLabel;
  }

  return market.title;
}

export function getMarketOutcomeLabel(
  market:
    | Pick<MarketSnapshot, "outcomeLabel" | "contractLabel">
    | null
    | undefined
) {
  const outcomeLabel = market?.outcomeLabel?.trim();
  if (!outcomeLabel) return null;

  if (
    market?.contractLabel &&
    outcomeLabel === market.contractLabel.trim()
  ) {
    return "Yes";
  }

  return outcomeLabel;
}

export function formatMarketProbability(probability: number | null | undefined) {
  if (
    probability === null ||
    probability === undefined ||
    !Number.isFinite(probability)
  ) {
    return null;
  }

  const percentage = Math.max(0, Math.min(1, probability)) * 100;
  return `${percentage.toFixed(1)}%`;
}
