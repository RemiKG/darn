/**
 * A live numeral: JetBrains Mono, tabular figures (.num). On change the
 * content TICKS — an instant swap (keyed remount kills any inherited
 * transition), never a fade. Unknown values render the honest dash.
 */

import { cx } from "../lib/cx";

export interface MonoNumProps {
  value: string | number | null | undefined;
  className?: string;
  title?: string;
}

export default function MonoNum({ value, className, title }: MonoNumProps) {
  const text = value === null || value === undefined ? "—" : String(value);
  return (
    <span key={text} className={cx("num", className)} title={title}>
      {text}
    </span>
  );
}
