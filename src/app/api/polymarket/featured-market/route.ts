import { NextRequest, NextResponse } from "next/server";
import { polymarketConfig } from "@/services/polymarket/config";
import { proxyJson, validateProxyBaseUrls, validateRequestedSlug } from "../_lib/proxy";

export const revalidate = 60;
const MARKET_CACHE_SECONDS = 300;
const MARKET_STALE_IF_ERROR_SECONDS = 3600;

export async function GET(request: NextRequest) {
  const baseUrlError = validateProxyBaseUrls();
  if (baseUrlError) return baseUrlError;

  const slug = request.nextUrl.searchParams.get("slug") ?? polymarketConfig.featuredMarketSlug;
  const slugError = validateRequestedSlug(slug);
  if (slugError) return slugError;

  const bySlugUrl = `${polymarketConfig.gammaBaseUrl}/events/slug/${slug}`;
  const cacheOptions = {
    revalidateSeconds: MARKET_CACHE_SECONDS,
    staleIfErrorSeconds: MARKET_STALE_IF_ERROR_SECONDS
  };

  try {
    const response = await proxyJson(bySlugUrl, cacheOptions);
    if (response.ok) return response;

    throw new Error(`Gamma slug request failed: ${response.status}`);
  } catch {
    const fallbackUrl = `${polymarketConfig.gammaBaseUrl}/events?slug=${encodeURIComponent(slug)}`;
    try {
      return await proxyJson(fallbackUrl, cacheOptions);
    } catch {
      return NextResponse.json({ error: "Featured market proxy request failed" }, { status: 502 });
    }
  }
}
