import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTIVITY_FEED_PAGE_SIZE,
  getPaginationItems
} from "@/components/maps/activityFeedPagination";

test("activity pagination exposes every page for small result sets", () => {
  assert.equal(ACTIVITY_FEED_PAGE_SIZE, 8);
  assert.deepEqual(getPaginationItems(2, 4), [1, 2, 3, 4]);
});

test("activity pagination keeps nearby and boundary pages for large sets", () => {
  assert.deepEqual(
    getPaginationItems(6, 12),
    [1, "ellipsis", 5, 6, 7, "ellipsis", 12]
  );
  assert.deepEqual(getPaginationItems(1, 0), []);
});
