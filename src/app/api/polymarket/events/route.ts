import { NextRequest, NextResponse } from "next/server";
import { polymarketConfig } from "@/services/polymarket/config";
import { normalizeGammaEvent } from "@/services/polymarket/normalizers";
import {
  validateProxyBaseUrls,
  validateRequestedSlug
} from "../_lib/proxy";

export const revalidate = 300;

export async function GET(request: NextRequest) {
  const baseUrlError = validateProxyBaseUrls();
  if (baseUrlError) return baseUrlError;

  const slugs = [
    ...new Set(
      (request.nextUrl.searchParams.get("slugs") ?? "")
        .split(",")
        .map((slug) => slug.trim())
        .filter(Boolean)
    )
  ].slice(0, 50);

  if (!slugs.length || slugs.some((slug) => validateRequestedSlug(slug))) {
    return NextResponse.json(
      { error: "Valid Polymarket event slugs are required" },
      { status: 400 }
    );
  }

  const url = new URL(`${polymarketConfig.gammaBaseUrl}/events/keyset`);
  slugs.forEach((slug) => url.searchParams.append("slug", slug));
  url.searchParams.set("closed", "false");
  url.searchParams.set("limit", String(slugs.length));

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`Gamma event request failed: ${response.status}`);
    }
    const payload = (await response.json()) as unknown;
    const events =
      typeof payload === "object" &&
      payload !== null &&
      "events" in payload &&
      Array.isArray(payload.events)
        ? payload.events
        : [];
    const markets = events
      .map((event) => normalizeGammaEvent(event))
      .filter((market) => market !== null);

    return NextResponse.json(
      { markets },
      {
        headers: {
          "Cache-Control":
            "public, s-maxage=300, stale-while-revalidate=3600, stale-if-error=3600"
        }
      }
    );
  } catch {
    return NextResponse.json(
      { error: "Polymarket events request failed" },
      { status: 502 }
    );
  }
}
