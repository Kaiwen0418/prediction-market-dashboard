export const kalshiConfig = {
  apiBaseUrl:
    process.env.KALSHI_API_BASE_URL ??
    "https://external-api.kalshi.com/trade-api/v2",
  requestTimeoutMs: 8_000
} as const;
