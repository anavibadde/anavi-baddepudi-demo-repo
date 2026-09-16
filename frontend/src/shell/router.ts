import { useCallback, useEffect, useState } from "react";

/** Minimal history-API routing: three static paths do not justify a router
 * dependency, and the tools never nest or take path parameters. */
export function navigate(path: string) {
  if (window.location.pathname === path) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname);
  const sync = useCallback(() => setPath(window.location.pathname), []);
  useEffect(() => {
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [sync]);
  return path;
}
