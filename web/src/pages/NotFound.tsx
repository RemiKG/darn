/**
 * 404 — "No thread here."
 * Centered needle-&-yarn glyph at 320px, headline, one calm sentence, ink
 * button back to the shop floor, tiny mono 404, one soft blob (cream
 * bottom-left + amber top-right). Styles are inline — this page
 * owns no shared CSS file.
 */

import type { CSSProperties } from "react";
import { BtnInk } from "../components/Buttons";
import { NeedleYarn } from "../components/EmptyState";

const s404: CSSProperties = {
  position: "relative",
  height: 900,
  overflow: "hidden",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

const blobCream: CSSProperties = {
  width: 720,
  height: 720,
  bottom: -150,
  left: -170,
  background: "radial-gradient(closest-side, #EDEAE2, rgba(237,234,226,0) 70%)",
};

const blobAmber: CSSProperties = {
  width: 640,
  height: 640,
  top: -70,
  right: -50,
  background: "radial-gradient(closest-side, rgba(232,163,61,.095), rgba(232,163,61,0) 72%)",
};

export default function NotFound() {
  return (
    <main style={s404}>
      <div className="blob" style={blobCream} aria-hidden="true" />
      <div className="blob" style={blobAmber} aria-hidden="true" />
      <div
        style={{
          position: "relative",
          zIndex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          marginTop: -16,
        }}
      >
        <NeedleYarn size={320} />
        <h1 style={{ font: "700 28px/1.25 var(--font-ui)", color: "var(--ink)", marginTop: 44 }}>
          No thread here.
        </h1>
        <p style={{ font: "400 15.5px var(--font-ui)", color: "var(--ink-soft)", marginTop: 10 }}>
          This page isn't torn — it just never existed.
        </p>
        <div style={{ marginTop: 32 }}>
          <BtnInk to="/">Back to the shop floor</BtnInk>
        </div>
        <div
          className="mono"
          style={{ fontSize: 12, color: "var(--ink-faint)", marginTop: 22, letterSpacing: ".06em" }}
        >
          404
        </div>
      </div>
    </main>
  );
}
