"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

export interface UseApiDataOptions {
  /**
   * Refetch when the browser tab regains focus or becomes visible again.
   * Useful when a flow (e.g. FYERS OAuth) completes in another tab and the
   * user comes back to this one.
   */
  refetchOnFocus?: boolean;
}

const FOCUS_REFETCH_MIN_INTERVAL_MS = 1000;

export function useApiData<T>(path: string | null, options: UseApiDataOptions = {}) {
  const { refetchOnFocus = false } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const [tick, setTick] = useState(0);
  const mounted = useRef(true);
  const lastFocusRefresh = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!path) {
      setData(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    api
      .get<T>(path)
      .then((result) => {
        if (active && mounted.current) setData(result);
      })
      .catch((err: Error) => {
        if (active && mounted.current) setError(err.message);
      })
      .finally(() => {
        if (active && mounted.current) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!refetchOnFocus || !path) return;
    // `focus` and `visibilitychange` often fire together; keep it to one refetch.
    const refresh = () => {
      if (document.visibilityState === "hidden") return;
      const now = Date.now();
      if (now - lastFocusRefresh.current < FOCUS_REFETCH_MIN_INTERVAL_MS) return;
      lastFocusRefresh.current = now;
      setTick((value) => value + 1);
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [refetchOnFocus, path]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, reload, setData };
}
