import { NextRequest, NextResponse } from "next/server";
import { polymarketConfig } from "@/services/polymarket/config";
import { proxyJson, validateProxyBaseUrls } from "../_lib/proxy";

export const revalidate = 2;

export async function GET(request: NextRequest) {
  const baseUrlError = validateProxyBaseUrls();
  if (baseUrlError) return baseUrlError;

  const tokenId = request.nextUrl.searchParams.get("tokenId");
  if (!tokenId) {
    return NextResponse.json({ error: "tokenId is required" }, { status: 400 });
  }

  const url = `${polymarketConfig.clobBaseUrl}/book?token_id=${encodeURIComponent(tokenId)}`;
  try {
    return await proxyJson(url, {
      revalidateSeconds: 2,
      staleIfErrorSeconds: 15
    });
  } catch {
    return NextResponse.json({ error: "Orderbook proxy request failed" }, { status: 502 });
  }
}
