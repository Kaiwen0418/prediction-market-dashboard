import test from "node:test";
import assert from "node:assert/strict";
import {
  paginateTradingPairs,
  TRADING_PAIRS_PER_PAGE
} from "@/components/maps/tradingPairPagination";

test("trading pairs are limited to five rows per page", () => {
  const pairs = Array.from({ length: 13 }, (_, index) => index + 1);

  const first = paginateTradingPairs(pairs, 0);
  const second = paginateTradingPairs(pairs, 1);
  const final = paginateTradingPairs(pairs, 2);

  assert.equal(TRADING_PAIRS_PER_PAGE, 5);
  assert.deepEqual(first.items, [1, 2, 3, 4, 5]);
  assert.deepEqual(second.items, [6, 7, 8, 9, 10]);
  assert.deepEqual(final.items, [11, 12, 13]);
  assert.equal(final.pageCount, 3);
});

test("trading pair pagination clamps invalid pages", () => {
  assert.equal(paginateTradingPairs(["a"], 99).page, 0);
  assert.equal(paginateTradingPairs([], -4).page, 0);
});
