import test from "node:test";
import assert from "node:assert/strict";
import {
  formatMarketProbability,
  getMarketDisplayTitle,
  getMarketOutcomeLabel
} from "@/utils/marketDisplay";

test("binary markets use the full question instead of a generic outcome", () => {
  assert.equal(
    getMarketDisplayTitle({
      title: "Russia x Ukraine ceasefire agreement by December 31, 2026?",
      outcomeLabel: "Yes"
    }),
    "Russia x Ukraine ceasefire agreement by December 31, 2026?"
  );
});

test("multi-outcome markets retain the selected outcome label", () => {
  assert.equal(
    getMarketDisplayTitle({
      title: "California Governor Election Winner",
      outcomeLabel: "Will Xavier Becerra win?"
    }),
    "Will Xavier Becerra win?"
  );
});

test("normalized binary contracts display Yes as the current outcome", () => {
  assert.equal(
    getMarketOutcomeLabel({
      outcomeLabel: "Will a ceasefire be agreed?",
      contractLabel: "Will a ceasefire be agreed?"
    }),
    "Yes"
  );
  assert.equal(
    getMarketOutcomeLabel({
      outcomeLabel: "Vivek Ramaswamy",
      contractLabel: undefined
    }),
    "Vivek Ramaswamy"
  );
});

test("market probabilities use a stable one-decimal display", () => {
  assert.equal(formatMarketProbability(0.595), "59.5%");
  assert.equal(formatMarketProbability(2), "100.0%");
  assert.equal(formatMarketProbability(null), null);
});
