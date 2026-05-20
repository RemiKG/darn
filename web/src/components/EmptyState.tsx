/**
 * Empty state — the needle-&-yarn glyph (empty states and the 404 ONLY; never
 * in headers, never near data) + one calm sentence.
 */

import type { ReactNode } from "react";
import { cx } from "../lib/cx";

/** The yarn ball + threaded darning needle glyph (art/needle-yarn.svg). */
export function NeedleYarn({ size = 200, className }: { size?: number; className?: string }) {
  const h = Math.round((size * 240) / 340);
  return (
    <img
      src="/art/needle-yarn.svg"
      width={size}
      height={h}
      alt=""
      aria-hidden="true"
      className={className}
    />
  );
}

export interface EmptyStateProps {
  /** Glyph width in px (404 uses 320; everywhere else defaults to 200). */
  size?: number;
  /** The one calm sentence. */
  children: ReactNode;
  className?: string;
}

export default function EmptyState({ size = 200, children, className }: EmptyStateProps) {
  return (
    <div className={cx("empty", className)}>
      <NeedleYarn size={size} />
      <p>{children}</p>
    </div>
  );
}
