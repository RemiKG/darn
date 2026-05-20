/**
 * 30-min sparkline — 1.5px ink line; anomalous segments draw amber and
 * slightly frayed (a small deterministic jitter + frayed thread-ends when the
 * anomaly runs to "now"). Time-axis labels mono 10px. Data only ever comes
 * from the API (SparkPoint[]) — no invented shapes.
 */

import type { SparkPoint } from "../lib/api";

export type { SparkPoint };

const INK = "#1B2A44";
const AMBER = "#E8A33D";

export interface SparkProps {
  points: SparkPoint[];
  /** viewBox width/height — the health card uses 396×56. */
  width?: number;
  height?: number;
  /** Time-axis labels, left → right (default "-30m" / "-15m" / "now"). Pass [] to hide. */
  axisLabels?: string[];
  className?: string;
}

interface Pt {
  x: number;
  y: number;
  anomalous: boolean;
}

function scale(points: SparkPoint[], w: number, h: number): Pt[] {
  const padTop = 6;
  const baselineY = h - 7;
  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const tSpan = t1 - t0 || 1;
  let vMax = -Infinity;
  let vMin = Infinity;
  for (const p of points) {
    vMax = Math.max(vMax, p.v);
    vMin = Math.min(vMin, p.v);
  }
  const vSpan = vMax - vMin || 1;
  return points.map((p, i) => {
    const x = ((p.t - t0) / tSpan) * w;
    let y = baselineY - ((p.v - vMin) / vSpan) * (baselineY - padTop);
    if (p.anomalous) {
      // slightly frayed: small deterministic jitter, never a smooth lie
      y += i % 2 === 0 ? -1.1 : 1.1;
      y = Math.min(baselineY, Math.max(padTop - 2, y));
    }
    return { x, y, anomalous: p.anomalous };
  });
}

/** Split into runs of equal `anomalous`, sharing boundary points for continuity. */
function runs(pts: Pt[]): Pt[][] {
  const out: Pt[][] = [];
  let current: Pt[] = [];
  for (const p of pts) {
    if (current.length === 0) {
      current = [p];
      continue;
    }
    if (current[current.length - 1].anomalous === p.anomalous) {
      current.push(p);
    } else {
      current.push(p); // share the boundary point
      out.push(current);
      current = [p];
    }
  }
  if (current.length > 0) {
    out.push(current);
  }
  return out;
}

export default function Spark({
  points,
  width = 396,
  height = 56,
  axisLabels = ["-30m", "-15m", "now"],
  className,
}: SparkProps) {
  const baselineY = height - 7;
  const pts = points.length >= 2 ? scale(points, width, height) : [];
  const segments = runs(pts);
  const last = pts[pts.length - 1];
  const frayed = last !== undefined && last.anomalous;

  return (
    <div className={className}>
      <svg
        className="spark"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ height: `${height}px` }}
        aria-hidden="true"
      >
        <line x1="0" y1={baselineY} x2={width} y2={baselineY} stroke="rgba(27,42,68,.13)" strokeWidth="1" />
        {segments.map((seg, i) => (
          <polyline
            key={i}
            fill="none"
            stroke={seg[seg.length - 1].anomalous ? AMBER : INK}
            strokeWidth="1.5"
            strokeLinejoin="round"
            points={seg.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")}
          />
        ))}
        {frayed && last && (
          <path
            d={`M${(last.x - 1).toFixed(1)} ${last.y.toFixed(1)} l5 -3.4 M${(last.x - 2).toFixed(1)} ${(last.y + 1.6).toFixed(1)} l6 .8`}
            stroke={AMBER}
            strokeWidth="1.3"
            strokeLinecap="round"
            fill="none"
          />
        )}
      </svg>
      {axisLabels.length > 0 && (
        <div className="axis num">
          {axisLabels.map((label, i) => (
            <span key={i}>{label}</span>
          ))}
        </div>
      )}
    </div>
  );
}
