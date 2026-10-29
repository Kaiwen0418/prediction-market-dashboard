export const ACTIVITY_FEED_PAGE_SIZE = 8;

export type PaginationItem = number | "ellipsis";

export function getPaginationItems(
  currentPage: number,
  pageCount: number
): PaginationItem[] {
  if (pageCount <= 1) return pageCount === 1 ? [1] : [];
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const pages = Array.from(
    new Set([
      1,
      pageCount,
      Math.max(1, currentPage - 1),
      currentPage,
      Math.min(pageCount, currentPage + 1)
    ])
  ).sort((left, right) => left - right);

  return pages.flatMap((page, index) => {
    const previous = pages[index - 1];
    return previous !== undefined && page - previous > 1
      ? ["ellipsis" as const, page]
      : [page];
  });
}
