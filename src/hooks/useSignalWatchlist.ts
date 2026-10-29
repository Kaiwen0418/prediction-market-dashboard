"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSignalAlertCandidates,
  getSignalWatchKey,
  parseSignalWatchlist,
  SIGNAL_ALERTS_STORAGE_KEY,
  SIGNAL_WATCHLIST_STORAGE_KEY,
  toStoredSignalSnapshots
} from "@/components/maps/signalWatchlist";
import type { SignalAlertSnapshot } from "@/components/maps/signalWatchlist";

export type SignalAlertPermission =
  | NotificationPermission
  | "unsupported";

export function useSignalWatchlist(signals: SignalAlertSnapshot[]) {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [watchedOnly, setWatchedOnly] = useState(false);
  const [alertsEnabled, setAlertsEnabled] = useState(false);
  const [alertPermission, setAlertPermission] =
    useState<SignalAlertPermission>("default");
  const [hydrated, setHydrated] = useState(false);
  const previousSignalsRef = useRef(toStoredSignalSnapshots(signals));

  useEffect(() => {
    const supportsNotifications = "Notification" in window;
    const permission = supportsNotifications
      ? window.Notification.permission
      : "unsupported";
    const storedAlertPreference =
      window.localStorage.getItem(SIGNAL_ALERTS_STORAGE_KEY) === "enabled";

    setWatchlist(
      parseSignalWatchlist(
        window.localStorage.getItem(SIGNAL_WATCHLIST_STORAGE_KEY)
      )
    );
    setAlertPermission(permission);
    setAlertsEnabled(permission === "granted" && storedAlertPreference);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) {
      return;
    }

    window.localStorage.setItem(
      SIGNAL_WATCHLIST_STORAGE_KEY,
      JSON.stringify(watchlist)
    );
  }, [hydrated, watchlist]);

  useEffect(() => {
    const previous = previousSignalsRef.current;
    previousSignalsRef.current = toStoredSignalSnapshots(signals);

    if (
      !hydrated ||
      !alertsEnabled ||
      alertPermission !== "granted"
    ) {
      return;
    }

    for (const signal of getSignalAlertCandidates(
      signals,
      previous,
      watchlist
    )) {
      new window.Notification(
        `${signal.regionLabel} activity score ${signal.score}`,
        {
          body: `${signal.pairLabel}: ${signal.headline}`,
          tag: `signal-${signal.countryCode}-${signal.regionCode}`
        }
      );
    }
  }, [
    alertPermission,
    alertsEnabled,
    hydrated,
    signals,
    watchlist
  ]);

  const toggleWatch = useCallback(
    (countryCode: string, regionCode: string) => {
      const key = getSignalWatchKey(countryCode, regionCode);
      setWatchlist((current) =>
        current.includes(key)
          ? current.filter((item) => item !== key)
          : [...current, key].sort()
      );
    },
    []
  );

  const isWatched = useCallback(
    (countryCode: string, regionCode: string) =>
      watchlist.includes(getSignalWatchKey(countryCode, regionCode)),
    [watchlist]
  );

  const setBrowserAlertsEnabled = useCallback(async (enabled: boolean) => {
    if (!enabled) {
      setAlertsEnabled(false);
      window.localStorage.removeItem(SIGNAL_ALERTS_STORAGE_KEY);
      return;
    }

    if (!("Notification" in window)) {
      setAlertPermission("unsupported");
      return;
    }

    const permission =
      window.Notification.permission === "default"
        ? await window.Notification.requestPermission()
        : window.Notification.permission;

    setAlertPermission(permission);
    const granted = permission === "granted";
    setAlertsEnabled(granted);

    if (granted) {
      window.localStorage.setItem(SIGNAL_ALERTS_STORAGE_KEY, "enabled");
    } else {
      window.localStorage.removeItem(SIGNAL_ALERTS_STORAGE_KEY);
    }
  }, []);

  return {
    watchlist,
    watchedOnly,
    setWatchedOnly,
    alertsEnabled,
    alertPermission,
    setBrowserAlertsEnabled,
    toggleWatch,
    isWatched
  };
}
