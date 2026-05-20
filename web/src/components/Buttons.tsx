/**
 * Buttons — radius 14, 2px-amber focus ring from global.css.
 *   BtnAmber    primary action ("Tear a hole in it", "Ship the bad commit")
 *   BtnInk      strong action ("Approve fix", "Connect your tenant")
 *   BtnGhost    quiet action (hairline border)
 *   BtnGhostInk quiet-but-firm (ink border — "Disconnect and delete…")
 *
 * Pass `to` for an internal route (react-router Link), `href` for an external
 * link (renders <a>), otherwise it renders a <button>.
 */

import type { MouseEventHandler, ReactNode } from "react";
import { Link } from "react-router-dom";
import { cx } from "../lib/cx";

export type BtnSize = "sm" | "md" | "big";

export interface BtnProps {
  children: ReactNode;
  /** Internal route — renders a react-router <Link>. */
  to?: string;
  /** External URL — renders an <a>. */
  href?: string;
  target?: string;
  rel?: string;
  size?: BtnSize;
  type?: "button" | "submit";
  disabled?: boolean;
  onClick?: MouseEventHandler<HTMLElement>;
  className?: string;
  title?: string;
  "aria-label"?: string;
}

function makeBtn(variantClass: string) {
  return function Btn({
    children,
    to,
    href,
    target,
    rel,
    size = "md",
    type = "button",
    disabled,
    onClick,
    className,
    title,
    "aria-label": ariaLabel,
  }: BtnProps) {
    const cls = cx(
      "btn",
      variantClass,
      size === "sm" && "btn-sm",
      size === "big" && "btn-big",
      className
    );
    if (to && !disabled) {
      return (
        <Link to={to} className={cls} onClick={onClick} title={title} aria-label={ariaLabel}>
          {children}
        </Link>
      );
    }
    if (href && !disabled) {
      return (
        <a
          href={href}
          target={target}
          rel={rel ?? (target === "_blank" ? "noreferrer" : undefined)}
          className={cls}
          onClick={onClick}
          title={title}
          aria-label={ariaLabel}
        >
          {children}
        </a>
      );
    }
    return (
      <button
        type={type}
        className={cls}
        disabled={disabled}
        onClick={onClick}
        title={title}
        aria-label={ariaLabel}
      >
        {children}
      </button>
    );
  };
}

export const BtnAmber = makeBtn("btn-amber");
export const BtnInk = makeBtn("btn-ink");
export const BtnGhost = makeBtn("btn-ghost");
export const BtnGhostInk = makeBtn("btn-ghost-ink");
/** Ghost variant for ink-background surfaces (the medic teaser card). */
export const BtnOnInk = makeBtn("btn-onink");
