import { NextResponse } from "next/server";
import { polymarketConfig } from "@/services/polymarket/config";
import { validateBaseUrl, validateSlug } from "@/services/polymarket/preflight";

type ProxyJsonOptions = {
  revalidateSeconds?: number;
  staleIfErrorSeconds?: number;
};

export async function proxyJson(url: string, options: ProxyJsonOptions = {}) {
  const revalidateSeconds = options.revalidateSeconds ?? 0;
  const staleIfErrorSeconds = options.staleIfErrorSeconds ?? 0;
  const response = await fetch(url, {
    headers: {
      Accept: "application/json"
    },
    ...(revalidateSeconds > 0
      ? { next: { revalidate: revalidateSeconds } }
      : { cache: "no-store" as const })
  });

  const text = await response.text();

  return new NextResponse(text, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
      "Cache-Control":
        revalidateSeconds > 0
          ? `public, s-maxage=${revalidateSeconds}, stale-while-revalidate=${staleIfErrorSeconds}, stale-if-error=${staleIfErrorSeconds}`
          : "no-store"
    }
  });
}

export function validateProxyBaseUrls() {
  const gammaUrlIssue = validateBaseUrl(polymarketConfig.gammaBaseUrl, "Gamma base URL");
  if (gammaUrlIssue) {
    return NextResponse.json({ error: gammaUrlIssue.message }, { status: 500 });
  }

  const clobUrlIssue = validateBaseUrl(polymarketConfig.clobBaseUrl, "CLOB base URL");
  if (clobUrlIssue) {
    return NextResponse.json({ error: clobUrlIssue.message }, { status: 500 });
  }

  const dataUrlIssue = validateBaseUrl(polymarketConfig.dataApiBaseUrl, "Data API base URL");
  if (dataUrlIssue) {
    return NextResponse.json({ error: dataUrlIssue.message }, { status: 500 });
  }

  return null;
}

export function validateRequestedSlug(slug: string) {
  const slugIssue = validateSlug(slug);
  if (slugIssue) {
    return NextResponse.json({ error: slugIssue.message }, { status: 400 });
  }
  return null;
}
