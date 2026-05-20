/**
 * Card surface — radius 18, --shadow-card. `interactive` adds the hover
 * grammar: shadow-pop + 1px ink border (transitions ≤150ms via global.css).
 */

import type { HTMLAttributes } from "react";
import { cx } from "../lib/cx";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
}

export default function Card({ interactive, className, children, ...rest }: CardProps) {
  return (
    <div className={cx("card", interactive && "card-hot", className)} {...rest}>
      {children}
    </div>
  );
}
