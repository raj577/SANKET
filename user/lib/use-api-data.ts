"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

export function useApiData<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const [tick, setTick] = useState(0);
  const mounted = useRef(true);

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

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, reload, setData };
}
