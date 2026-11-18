import { useCallback, useEffect, useRef, useState } from "react";

export interface Poll<T> {
  data: T | undefined; // last good response: kept when a later request fails
  error: Error | undefined; // from the latest request only
  refresh: () => Promise<void>;
  set: (data: T) => void; // e.g. the kill switch POST returns a fresh Status
}

/**
 * Calls `fetcher` now and every `intervalMs`. Never runs two requests at once,
 * pauses while the tab is hidden, and refreshes as soon as it's visible again.
 */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number): Poll<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const inFlight = useRef(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setData(await fetcherRef.current());
      setError(undefined);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => {
      if (!document.hidden) refresh();
    }, intervalMs);
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, intervalMs]);

  const set = useCallback((d: T) => {
    setData(d);
    setError(undefined);
  }, []);

  return { data, error, refresh, set };
}
