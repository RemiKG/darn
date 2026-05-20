/**
 * Copy button — flips to "Copied ✓" (ink pill) for 1.5s, per the global
 * interaction defaults. Default look is the `.copybtn` pill; inside
 * `.dqlwrap` the global CSS restyles it for the dark DQL panel.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "../lib/cx";

const COPIED_MS = 1_500;

export interface CopyButtonProps {
  /** The exact text written to the clipboard. */
  text: string;
  /** Button label (defaults to "Copy"). */
  label?: ReactNode;
  /** Hide the little copy glyph (e.g. ultra-compact placements). */
  noIcon?: boolean;
  className?: string;
  "aria-label"?: string;
}

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // quiet fallback for non-secure contexts
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

export default function CopyButton({
  text,
  label = "Copy",
  noIcon,
  className,
  "aria-label": ariaLabel,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    };
  }, []);

  const onClick = () => {
    void writeClipboard(text).then(() => {
      setCopied(true);
      if (timer.current) {
        clearTimeout(timer.current);
      }
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    });
  };

  return (
    <button
      type="button"
      className={cx("copybtn", copied && "copied", className)}
      onClick={onClick}
      aria-label={ariaLabel}
      aria-live="polite"
    >
      {copied ? (
        "Copied ✓"
      ) : (
        <>
          {!noIcon && (
            <svg
              width="13"
              height="13"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              aria-hidden="true"
            >
              <rect x="4.5" y="4.5" width="8" height="8" rx="2" />
              <path d="M9.5 2.5 H4 a2 2 0 0 0 -2 2 V10" />
            </svg>
          )}
          {label}
        </>
      )}
    </button>
  );
}
