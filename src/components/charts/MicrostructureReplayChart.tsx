"use client";

import type { EChartsOption } from "echarts";
import { useTheme } from "@/components/theme/ThemeProvider";
import type { LiveMetricSample } from "@/types/market";
import { formatTimestamp } from "@/utils/time";
import { ReactECharts } from "./ChartContainer";

type MicrostructureReplayChartProps = {
  samples: LiveMetricSample[];
};

type ReplayPanelProps = {
  description: string;
  option: EChartsOption;
  title: string;
};

function ReplayPanel({ description, option, title }: ReplayPanelProps) {
  return (
    <article className="border-t border-[var(--demo-card-divider)] pt-4">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="hidden max-w-[240px] text-right text-xs leading-5 text-slate-500 sm:block">{description}</p>
      </div>
      <div className="mt-3">
        <ReactECharts option={option} style={{ height: 190 }} />
      </div>
    </article>
  );
}

export function MicrostructureReplayChart({ samples }: MicrostructureReplayChartProps) {
  const { theme } = useTheme();

  if (!samples.length) {
    return (
      <div className="flex h-[160px] items-center justify-center border-y border-[var(--demo-card-divider)] px-4 text-center text-sm text-slate-500">
        Recent market activity is not available yet. This view will update automatically.
      </div>
    );
  }

  const textColor = theme === "dark" ? "#f2f1ed" : "#0c0c0c";
  const subtleColor = theme === "dark" ? "rgba(242, 241, 237, 0.56)" : "rgba(12, 12, 12, 0.48)";
  const gridColor = theme === "dark" ? "rgba(242, 241, 237, 0.08)" : "rgba(12, 12, 12, 0.08)";
  const timestamps = samples.map((sample) => formatTimestamp(sample.timestamp, "HH:mm"));
  const sharedGrid = { left: 8, right: 12, top: 12, bottom: 22, containLabel: true };
  const sharedXAxis = {
    type: "category" as const,
    boundaryGap: false,
    data: timestamps,
    axisLine: { lineStyle: { color: subtleColor } },
    axisTick: { show: false },
    axisLabel: {
      color: subtleColor,
      fontSize: 10,
      interval: Math.max(0, Math.floor(samples.length / 4))
    },
    splitLine: { show: false }
  };

  const valueAxis = (formatter: (value: number) => string) => ({
    type: "value" as const,
    scale: true,
    axisLabel: { color: subtleColor, fontSize: 10, formatter },
    splitLine: { lineStyle: { color: gridColor } }
  });

  const lineSeries = (name: string, data: number[], color: string, dashed = false) => ({
    name,
    type: "line" as const,
    data,
    showSymbol: samples.length <= 2,
    symbol: "circle",
    symbolSize: 7,
    itemStyle: { color },
    smooth: 0.2,
    lineStyle: { color, width: 2, type: dashed ? ("dashed" as const) : ("solid" as const) }
  });

  const priceOption: EChartsOption = {
    animationDuration: 350,
    grid: sharedGrid,
    tooltip: { trigger: "axis", valueFormatter: (value) => `${(Number(value) * 100).toFixed(2)}%` },
    xAxis: sharedXAxis,
    yAxis: valueAxis((value) => `${(value * 100).toFixed(1)}%`),
    series: [
      lineSeries("Mid price", samples.map((sample) => sample.midPrice), "#5c7ea6"),
      lineSeries("Microprice", samples.map((sample) => sample.microprice), textColor, true)
    ]
  };

  const spreadOption: EChartsOption = {
    animationDuration: 350,
    grid: sharedGrid,
    tooltip: { trigger: "axis", valueFormatter: (value) => `${Number(value).toFixed(1)} bps` },
    xAxis: sharedXAxis,
    yAxis: valueAxis((value) => `${Math.round(value)} bps`),
    series: [
      {
        ...lineSeries("Spread", samples.map((sample) => sample.spreadBps), "#9f5f71"),
        areaStyle: { color: "rgba(159, 95, 113, 0.12)" }
      }
    ]
  };

  const imbalanceOption: EChartsOption = {
    animationDuration: 350,
    grid: sharedGrid,
    tooltip: { trigger: "axis", valueFormatter: (value) => `${(Number(value) * 100).toFixed(1)}%` },
    xAxis: sharedXAxis,
    yAxis: {
      ...valueAxis((value) => `${Math.round(value * 100)}%`),
      min: -1,
      max: 1
    },
    series: [
      lineSeries("Depth skew", samples.map((sample) => sample.depthSkew), "#5c7ea6"),
      lineSeries("Order flow", samples.map((sample) => sample.orderFlowImbalance), "#9f5f71")
    ]
  };

  const volatilityOption: EChartsOption = {
    animationDuration: 350,
    grid: sharedGrid,
    tooltip: { trigger: "axis", valueFormatter: (value) => Number(value).toFixed(4) },
    xAxis: sharedXAxis,
    yAxis: valueAxis((value) => value.toFixed(3)),
    series: [
      {
        ...lineSeries("Realized volatility", samples.map((sample) => sample.realizedVolatility), "#c08a32"),
        areaStyle: { color: "rgba(192, 138, 50, 0.12)" }
      }
    ]
  };

  return (
    <div className="grid gap-x-8 gap-y-6 lg:grid-cols-2">
      <ReplayPanel
        title="Fair Price Pressure"
        description="Microprice moving above mid indicates bid-side pressure near the touch."
        option={priceOption}
      />
      <ReplayPanel
        title="Spread Cost"
        description="Quoted execution cost in basis points; spikes indicate thinner liquidity."
        option={spreadOption}
      />
      <ReplayPanel
        title="Depth vs Order Flow"
        description="Positive values favor bids or buys; negative values favor asks or sells."
        option={imbalanceOption}
      />
      <ReplayPanel
        title="Realized Volatility"
        description="Short-window price dispersion across recent market observations."
        option={volatilityOption}
      />
    </div>
  );
}
