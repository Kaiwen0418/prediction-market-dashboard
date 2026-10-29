import test from "node:test";
import assert from "node:assert/strict";
import { fetchKalshiEvents } from "@/services/kalshi/rest";

test("Kalshi event requests are split into API-safe batches", async () => {
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async (input) => {
    requests.push(String(input));
    return new Response(JSON.stringify({ events: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  };

  try {
    await fetchKalshiEvents(
      Array.from({ length: 28 }, (_, index) => `KXEVENT-${index + 1}`)
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requests.length, 2);
  assert.deepEqual(
    requests.map((request) => {
      const url = new URL(request, "http://localhost");
      return url.searchParams.get("tickers")?.split(",").length;
    }),
    [20, 8]
  );
});
