/**
 * Status pills — palette-disciplined (no red, ever).
 *   PillOk      "All stitched" / "Verified closed" style (soft ink wash)
 *   PillAmber   "Torn" / "Mending — stage 3 of 6" (amber wash, amber-deep text)
 *   PillNeutral "Paused" / "Tied off — not a code problem" (faint ink)
 */

import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "../lib/cx";

export type PillKind = "ok" | "amber" | "neutral";

export interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  kind?: PillKind;
  children: ReactNode;
}

export function Pill({ kind = "neutral", className, children, ...rest }: PillProps) {
  return (
    <span className={cx("pill", `pill-${kind}`, className)} {...rest}>
      {children}
    </span>
  );
}

export function PillOk(props: Omit<PillProps, "kind">) {
  return <Pill kind="ok" {...props} />;
}

export function PillAmber(props: Omit<PillProps, "kind">) {
  return <Pill kind="amber" {...props} />;
}

export function PillNeutral(props: Omit<PillProps, "kind">) {
  return <Pill kind="neutral" {...props} />;
}
