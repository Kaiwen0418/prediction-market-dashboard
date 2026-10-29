"use client";

import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "@/components/theme/ThemeProvider";
import type { TimePoint, TimelineEvent } from "@/types/market";
import { formatTimestamp } from "@/utils/time";
import { ReactECharts } from "./ChartContainer";

type PolymarketHistoryChartProps = {
  events?: TimelineEvent[];
  series: TimePoint[];
  venueName?: string;
};

type AnnotationPlacement = {
  headline: string;
  id: string;
  pointIndex: number;
  source: string;
  summary: string;
  value: number;
  xRatio: number;
};

type OverlayPosition = {
  x: number;
  y: number;
};

function pickIndices(length: number, desiredCount: number) {
  if (length <= 0) return [];
  if (length <= desiredCount) return Array.from({ length }, (_, index) => index);

  const indices = new Set<number>();
  for (let step = 0; step < desiredCount; step += 1) {
    indices.add(Math.round((step / (desiredCount - 1)) * (length - 1)));
  }

  return Array.from(indices).sort((left, right) => left - right);
}

const FALLBACK_ANNOTATIONS: Array<Pick<AnnotationPlacement, "headline" | "source" | "summary">> = [
  {
    source: "Polling Consortium",
    headline: "Swing-state polls tilt Republican",
    summary: "Composite polling broke decisively toward the Republican ticket, repricing the contract well above parity."
  },
  {
    source: "Campaign Desk",
    headline: "Democratic ticket reshuffles",
    summary: "An unexpected Democratic candidate change compressed the Republican lead as bettors priced in fresh momentum."
  },
  {
    source: "Macro Calendar",
    headline: "Soft data tests the rally",
    summary: "Below-consensus prints briefly weighed on the Republican contract before liquidity stabilized."
  },
  {
    source: "Event Monitor",
    headline: "Closing stretch flips bullish",
    summary: "Late-cycle debate and rally signals lifted Republican positioning; best-bid depth doubled overnight."
  }
];

function buildAnnotations(series: TimePoint[], events: TimelineEvent[]): AnnotationPlacement[] {
  const indices = pickIndices(series.length, Math.min(4, series.length));
  const selectedEvents = events.slice(0, indices.length);

  return indices.map((index, annotationIndex) => {
    const point = series[index];
    const event = selectedEvents[annotationIndex];
    const fallback = FALLBACK_ANNOTATIONS[annotationIndex % FALLBACK_ANNOTATIONS.length];
    const xRatio = series.length === 1 ? 0.5 : index / (series.length - 1);

    return {
      id: `${point.timestamp}-${annotationIndex}`,
      headline: event?.headline ?? fallback.headline,
      pointIndex: index,
      source: event?.source ?? fallback.source,
      summary: event?.summary ?? fallback.summary,
      value: point.value,
      xRatio
    };
  });
}

export function PolymarketHistoryChart({
  events = [],
  series,
  venueName = "Polymarket"
}: PolymarketHistoryChartProps) {
  const { theme } = useTheme();
  const chartInstanceRef = useRef<any>(null);
  const [annotationPositions, setAnnotationPositions] = useState<Record<string, OverlayPosition>>({});

  const sortedSeries = useMemo(
    () => [...series].sort((left, right) => left.timestamp.localeCompare(right.timestamp)),
    [series]
  );

  const chartModel = useMemo(() => {
    const values = sortedSeries.map((point) => point.value);
    const rawMin = values.length ? Math.min(...values) : 0;
    const rawMax = values.length ? Math.max(...values) : 1;
    const spread = rawMax - rawMin;
    const padding = Math.max(spread * 0.12, 0.03);
    const yAxisMin = Math.max(0, rawMin - padding);
    const yAxisMax = Math.min(1, rawMax + padding);
    const textColor = theme === "dark" ? "#f2f1ed" : "#0c0c0c";
    const subtleColor = theme === "dark" ? "rgba(242, 241, 237, 0.62)" : "rgba(12, 12, 12, 0.48)";
    const leaderColor = theme === "dark" ? "rgba(242, 241, 237, 0.35)" : "rgba(12, 12, 12, 0.28)";
    const gridColor = theme === "dark" ? "rgba(242, 241, 237, 0.08)" : "rgba(12, 12, 12, 0.08)";

    const option: EChartsOption = {
      animationDuration: 600,
      grid: {
        left: 18,
        right: 18,
        top: 48,
        bottom: 30,
        containLabel: true
      },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value) => `${(Number(value) * 100).toFixed(1)}%`
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: sortedSeries.map((point) => formatTimestamp(point.timestamp, "MMM d")),
        axisLine: { lineStyle: { color: subtleColor } },
        axisTick: { show: false },
        axisLabel: {
          color: subtleColor,
          interval: Math.max(0, Math.floor(sortedSeries.length / 6))
        },
        splitLine: { show: false }
      },
      yAxis: {
        type: "value",
        min: yAxisMin,
        max: yAxisMax,
        axisLabel: {
          color: subtleColor,
          formatter: (value: number) => `${Math.round(value * 100)}%`
        },
        splitLine: { lineStyle: { color: gridColor } }
      },
      series: [
        {
          name: `${venueName} Price`,
          type: "line",
          smooth: 0.22,
          symbol: "circle",
          showSymbol: true,
          symbolSize: 5,
          itemStyle: { color: textColor },
          lineStyle: { width: 2.5, color: textColor },
          data: sortedSeries.map((point) => point.value)
        }
      ]
    };

    return {
      annotations:
        events.length || venueName === "Polymarket"
          ? buildAnnotations(sortedSeries, events)
          : [],
      leaderColor,
      option,
      textColor
    };
  }, [events, sortedSeries, theme, venueName]);

  useEffect(() => {
    const updateOverlayPositions = () => {
      const instance = chartInstanceRef.current;
      if (!instance) return;

      const nextAnnotationPositions = Object.fromEntries(
        chartModel.annotations.map((annotation) => {
          const [x, y] = instance.convertToPixel(
            { xAxisIndex: 0, yAxisIndex: 0 },
            [annotation.pointIndex, annotation.value]
          );
          return [annotation.id, { x, y }];
        })
      );

      setAnnotationPositions(nextAnnotationPositions);
    };

    const timeoutId = window.setTimeout(updateOverlayPositions, 0);
    window.addEventListener("resize", updateOverlayPositions);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("resize", updateOverlayPositions);
    };
  }, [chartModel.annotations, chartModel.option]);

  if (!sortedSeries.length) {
    return (
      <div className="flex h-[360px] items-center justify-center text-sm text-slate-500">
        No price history is available for this market.
      </div>
    );
  }

  const annotationCount = chartModel.annotations.length;

  return (
    <div className="relative w-full">
      {/* Desktop: callout band sits above the chart so cards never collide with the price line */}
      <div
        className="relative hidden w-full md:block"
        style={{ height: annotationCount ? 132 : 0 }}
      >
        {chartModel.annotations.map((annotation, index) => {
          const isFirst = index === 0;
          const isLast = index === annotationCount - 1;
          const slotWidth = annotationCount > 0 ? 100 / annotationCount : 100;
          const cardStyle: React.CSSProperties = {
            top: 0,
            width: `calc(${slotWidth}% - 18px)`,
            borderColor: chartModel.textColor,
            color: chartModel.textColor
          };
          if (isFirst) {
            cardStyle.left = `${annotation.xRatio * 100}%`;
          } else if (isLast) {
            cardStyle.right = `${(1 - annotation.xRatio) * 100}%`;
          } else {
            cardStyle.left = `${annotation.xRatio * 100}%`;
            cardStyle.transform = "translateX(-50%)";
          }
          return (
            <div
              key={`${annotation.id}-card`}
              className="pointer-events-none absolute border-l-[3px] pl-3 text-left"
              style={cardStyle}
            >
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] opacity-70">{annotation.source}</p>
              <p className="mt-1 text-sm font-medium leading-5">{annotation.headline}</p>
              <p className="mt-1 text-xs leading-5 opacity-75">{annotation.summary}</p>
            </div>
          );
        })}
      </div>

      <div className="relative h-[320px] w-full sm:h-[360px] md:h-[380px]">
        <ReactECharts
          option={chartModel.option}
          notMerge
          onChartReady={(instance) => {
            chartInstanceRef.current = instance;

            setAnnotationPositions(
              Object.fromEntries(
                chartModel.annotations.map((annotation) => {
                  const [x, y] = instance.convertToPixel(
                    { xAxisIndex: 0, yAxisIndex: 0 },
                    [annotation.pointIndex, annotation.value]
                  );
                  return [annotation.id, { x, y }];
                })
              )
            );
          }}
          style={{ height: "100%", width: "100%" }}
        />

        {chartModel.annotations.map((annotation) => (
          <div key={`${annotation.id}-marker`} className="pointer-events-none hidden md:block">
            {annotationPositions[annotation.id] ? (
              <>
                <div
                  className="absolute"
                  style={{
                    left: annotationPositions[annotation.id].x,
                    top: 0,
                    height: annotationPositions[annotation.id].y,
                    width: 1,
                    backgroundColor: chartModel.leaderColor,
                    transform: "translateX(-0.5px)"
                  }}
                />
                <div
                  className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
                  style={{
                    left: annotationPositions[annotation.id].x,
                    top: annotationPositions[annotation.id].y,
                    backgroundColor: chartModel.textColor,
                    borderColor: chartModel.textColor
                  }}
                />
              </>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
