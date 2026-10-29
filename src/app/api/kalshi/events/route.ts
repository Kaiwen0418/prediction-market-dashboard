import { NextRequest, NextResponse } from "next/server";
import { kalshiConfig } from "@/services/kalshi/config";

export const revalidate = 15;

export async function GET(request: NextRequest) {
  const tickers = [
    ...new Set(
      (request.nextUrl.searchParams.get("tickers") ?? "")
        .split(",")
        .filter(Boolean)
    )
  ].slice(0, 20);

  if (
    !tickers.length ||
    tickers.some((ticker) => !/^[A-Z0-9-]{2,80}$/.test(ticker))
  ) {
    return NextResponse.json(
      { error: "Valid Kalshi event tickers are required" },
      { status: 400 }
    );
  }

  const url = new URL(`${kalshiConfig.apiBaseUrl}/events`);
  url.searchParams.set("tickers", tickers.join(","));
  url.searchParams.set("with_nested_markets", "true");

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      next: { revalidate }
    });
    const body = await response.text();

    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("content-type") ?? "application/json",
        "Cache-Control":
          "public, s-maxage=15, stale-while-revalidate=60, stale-if-error=300"
      }
    });
  } catch {
    return NextResponse.json(
      { error: "Kalshi events request failed" },
      { status: 502 }
    );
  }
}
