import type { MouseEvent, ReactNode } from "react";

import { navigate } from "./router";

export function Link({
  to,
  className,
  children,
}: {
  to: string;
  className?: string;
  children: ReactNode;
}) {
  // A real href so the link can be opened in a new tab or copied; the click
  // handler keeps in-app navigation from reloading the bundle.
  return (
    <a
      href={to}
      className={className}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}
