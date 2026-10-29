import { NextRequest, NextResponse } from "next/server";
import { polymarketConfig } from "@/services/polymarket/config";
import { proxyJson, validateProxyBaseUrls } from "../_lib/proxy";

export const revalidate = 3;

export async function GET(request: NextRequest) {
  const baseUrlError = validateProxyBaseUrls();
  if (baseUrlError) return baseUrlError;

  const conditionId = request.nextUrl.searchParams.get("conditionId");
  const limitParam = request.nextUrl.searchParams.get("limit");
  const requestedLimit =
    limitParam === null ? Number.NaN : Number(limitParam);
  const limit = Number.isFinite(requestedLimit)
    ? Math.min(100, Math.max(1, Math.floor(requestedLimit)))
    : 100;

  const url = `${polymarketConfig.dataApiBaseUrl}/trades?limit=${limit}&takerOnly=true${
    conditionId ? `&market=${encodeURIComponent(conditionId)}` : ""
  }`;
  try {
    return await proxyJson(url, {
      revalidateSeconds: 3,
      staleIfErrorSeconds: 15
    });
  } catch {
    return NextResponse.json({ error: "Trades proxy request failed" }, { status: 502 });
  }
}
