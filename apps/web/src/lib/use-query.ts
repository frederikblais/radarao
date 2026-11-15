"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Petit utilitaire de chargement (sans dépendance) : données, erreur, rechargement. */
export function useQuery<T>(fn: () => Promise<T>, deps: unknown[] = [], pollMs?: (data: T | undefined) => number | null) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    try {
      const d = await fnRef.current();
      setData(d);
      setError(undefined);
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let alive = true;
    const tick = async () => {
      const d = await reload();
      const next = pollMs?.(d);
      if (alive && next) timer = setTimeout(tick, next);
    };
    setLoading(true);
    void tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}
