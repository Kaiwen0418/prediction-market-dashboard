export const TRADING_PAIRS_PER_PAGE = 5;

export function paginateTradingPairs<T>(
  pairs: T[],
  requestedPage: number,
  pageSize = TRADING_PAIRS_PER_PAGE
) {
  const safePageSize = Math.max(1, Math.floor(pageSize));
  const pageCount = Math.max(1, Math.ceil(pairs.length / safePageSize));
  const page = Math.max(0, Math.min(Math.floor(requestedPage), pageCount - 1));
  const start = page * safePageSize;

  return {
    items: pairs.slice(start, start + safePageSize),
    page,
    pageCount,
    start,
    end: Math.min(start + safePageSize, pairs.length)
  };
}
