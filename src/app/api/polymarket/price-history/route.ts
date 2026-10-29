import { NextRequest, NextResponse } from "next/server";
import { polymarketConfig } from "@/services/polymarket/config";
import { proxyJson, validateProxyBaseUrls } from "../_lib/proxy";

export const revalidate = 300;

export async function GET(request: NextRequest) {
  const baseUrlError = validateProxyBaseUrls();
  if (baseUrlError) return baseUrlError;

  const market = request.nextUrl.searchParams.get("market");
  const debug = request.nextUrl.searchParams.get("debug") === "1";
  if (!market) {
    return NextResponse.json({ error: "market is required" }, { status: 400 });
  }

  const url = `${polymarketConfig.clobBaseUrl}/prices-history?interval=all&market=${encodeURIComponent(market)}&fidelity=720`;
  try {
    if (!debug) {
      return await proxyJson(url, {
        revalidateSeconds: 300,
        staleIfErrorSeconds: 3600
      });
    }

    const response = await fetch(url, {
      headers: {
        Accept: "application/json"
      },
      cache: "no-store"
    });

    const payload = await response.json();
    const historySource =
      Array.isArray(payload) ? payload : typeof payload === "object" && payload !== null && Array.isArray((payload as Record<string, unknown>).history)
        ? ((payload as Record<string, unknown>).history as unknown[])
        : typeof payload === "object" && payload !== null && Array.isArray((payload as Record<string, unknown>).data)
          ? ((payload as Record<string, unknown>).data as unknown[])
          : [];

    const history: unknown[] = historySource;

    return NextResponse.json(
      {
        requestUrl: url,
        market,
        status: response.status,
        historyLength: history.length,
        sample: history.slice(0, 3),
        payload
      },
      {
        status: response.status
      }
    );
  } catch {
    return NextResponse.json({ error: "Price history proxy request failed" }, { status: 502 });
  }
}
