/**
 * Global chrome (CSS in global.css):
 *   TopBar    64px cream bar, wordmark 28px (dot variant) → "/", right nav
 *             with the amber stitch underline on the active link + GitHub
 *             icon-link (repo_url from /api/state, new tab).
 *   LiveStrip 36px amber-wash strip shown ONLY while an incident is live:
 *             "● Mending now — {defect} · stage {n} of 6 · {mm:ss}" with mono
 *             numerals ticking every second + "Watch →".
 *   Footer    cream-2 band: "Found by Davis. Fixed by Darn. Proven in both."
 *             + links + faint needle-&-yarn glyph.
 *   Chrome    default export — wraps a page with all three.
 */

import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { mmss } from "../lib/format";
import { useAppState, useElapsed } from "../lib/store";
import { cx } from "../lib/cx";
import Wordmark from "./Wordmark";

function GitHubIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

export function TopBar() {
  const { state } = useAppState();
  const repoUrl = state?.repo_url || "";
  const navClass = ({ isActive }: { isActive: boolean }) => cx(isActive && "active");
  // Incident pages belong to the shop-floor section (the
  // "Shop floor" link is active there).
  const onIncident = useLocation().pathname.startsWith("/incident");
  return (
    <header className="topbar">
      <Link to="/" aria-label="Darn. — shop floor" style={{ textDecoration: "none" }}>
        <Wordmark size={28} />
      </Link>
      <nav className="nav">
        <NavLink
          to="/"
          end
          className={({ isActive }) => cx((isActive || onIncident) && "active")}
        >
          Shop floor
        </NavLink>
        <NavLink to="/yours" className={navClass}>
          Use it on yours
        </NavLink>
        {repoUrl ? (
          <a className="gh" href={repoUrl} target="_blank" rel="noreferrer" aria-label="Public repo">
            <GitHubIcon />
          </a>
        ) : (
          <span className="gh" aria-hidden="true" style={{ opacity: 0.4 }}>
            <GitHubIcon />
          </span>
        )}
      </nav>
    </header>
  );
}

export function LiveStrip() {
  const { liveIncident } = useAppState();
  const elapsed = useElapsed(liveIncident ? liveIncident.started_at : null);
  if (!liveIncident || liveIncident.status !== "live") {
    return null;
  }
  return (
    <div className="livestrip">
      <span className="dot" />
      <span>
        Mending now — {liveIncident.title} · stage <span className="num">{liveIncident.stage_index + 1}</span> of{" "}
        <span className="num">6</span> · <span className="num">{mmss(elapsed)}</span>
      </span>
      <Link to={`/incident/${liveIncident.id}`}>Watch →</Link>
    </div>
  );
}

export interface FooterProps {
  /** Devpost submission URL — not part of /api/state; wired at ship time. */
  devpostUrl?: string;
}

export function Footer({ devpostUrl }: FooterProps) {
  const { state } = useAppState();
  const repoUrl = state?.repo_url || "";
  const tenantUrl = state?.tenant_url || "";
  return (
    <footer className="footer">
      <div>
        <div className="says">Found by Davis. Fixed by Darn. Proven in both.</div>
        <div className="links">
          {repoUrl ? (
            <a href={repoUrl} target="_blank" rel="noreferrer">
              Public repo
            </a>
          ) : null}
          {tenantUrl ? (
            <a href={tenantUrl} target="_blank" rel="noreferrer">
              The Dynatrace tenant (read-only view)
            </a>
          ) : null}
          <Link to="/#wont-do">What Darn won&rsquo;t do</Link>
          {repoUrl ? (
            <a href={`${repoUrl}/blob/HEAD/LICENSE`} target="_blank" rel="noreferrer">
              MIT license
            </a>
          ) : null}
          {devpostUrl ? (
            <a href={devpostUrl} target="_blank" rel="noreferrer">
              Devpost
            </a>
          ) : null}
        </div>
      </div>
      {/* needle-&-yarn glyph, faint (opacity via .footer svg) */}
      <svg width="110" height="78" viewBox="0 0 340 240" fill="none" aria-hidden="true">
        <circle cx="78" cy="160" r="43" stroke="#1B2A44" strokeWidth="6" />
        <g stroke="#1B2A44" strokeWidth="4.5" strokeLinecap="round" fill="none" opacity="0.85">
          <path d="M38 146 C 60 130, 96 130, 118 146" />
          <path d="M40 174 C 62 158, 96 160, 116 176" />
          <path d="M52 124 C 84 138, 104 164, 110 192" />
        </g>
        <path
          d="M112 134 C 150 102, 162 148, 202 120 C 232 99, 247 72, 255.5 52 C 259 44, 264 39, 269 36"
          stroke="#E8A33D"
          strokeWidth="5.5"
          strokeLinecap="round"
        />
        <g transform="rotate(34 250 60)">
          <path
            d="M 250 132 C 245.5 100 245 80 245 52 Q 245 36 250 30 Q 255 36 255 52 C 255 80 254.5 100 250 132 Z"
            fill="#1B2A44"
          />
          <ellipse cx="250" cy="50" rx="2.6" ry="8" fill="#F5F3EF" />
        </g>
      </svg>
    </footer>
  );
}

/** Page shell: top bar + live strip above, footer below. */
export default function Chrome({ children }: { children: ReactNode }) {
  return (
    <>
      <TopBar />
      <LiveStrip />
      {children}
      <Footer />
    </>
  );
}
