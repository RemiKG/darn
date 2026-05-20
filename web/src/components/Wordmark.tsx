/**
 * The "Darn." wordmark: "D" + aWrap(patch svg behind the "a" counter) + "rn.".
 *
 * ≥40px: the amber crosshatch darning weave fills the counter patch box
 *        (left 33.4%, top 55.6%, w 28.4%, h 13% — measured, do not retune).
 * <40px: the weave simplifies to a solid amber dot (legible at favicon scale).
 */

import { useId } from "react";
import { cx } from "../lib/cx";

export interface WordmarkProps {
  /** Wordmark font size in px (Baloo 2 800, ink). */
  size: number;
  className?: string;
}

export default function Wordmark({ size, className }: WordmarkProps) {
  // useId emits ":r0:" — strip the colons so the SVG url(#…) reference is safe
  const clipId = `wm-clip-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const weave = size >= 40;
  return (
    <span className={cx("wm", className)} style={{ fontSize: `${size}px` }} translate="no">
      D
      <span className="aWrap">
        <svg className="patch" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {weave ? (
            <>
              <defs>
                <clipPath id={clipId}>
                  <ellipse cx="50" cy="50" rx="49" ry="49" />
                </clipPath>
              </defs>
              <g clipPath={`url(#${clipId})`}>
                <g stroke="#E8A33D" strokeWidth="13" strokeLinecap="round" fill="none">
                  <line x1="28" y1="0" x2="28" y2="100" />
                  <line x1="56" y1="0" x2="56" y2="100" />
                  <line x1="84" y1="0" x2="84" y2="100" />
                  <g stroke="#D88E21">
                    <line x1="0" y1="30" x2="100" y2="30" />
                    <line x1="0" y1="62" x2="100" y2="62" />
                  </g>
                </g>
              </g>
            </>
          ) : (
            <circle cx="50" cy="50" r="49" fill="#E8A33D" />
          )}
        </svg>
        <span className="glyph">a</span>
      </span>
      rn.
    </span>
  );
}
