/**
 * Settings page controls.
 *   Switch     the .sw toggle; `locked` renders the disabled X-stitch knob
 *              (cursor not-allowed, no change events — server-enforced constants)
 *   Field      mono input pill with optional unit suffix/prefix
 *   SelectBox  the .selectbox with a real <select> riding invisibly on top
 *   ChipsInput PR-labels chips (add on Enter/comma, × removes, backspace pops)
 *   Radios     the .radios/.radio/.rdot group
 */

import { useState, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "../../lib/cx";

/* The X-stitch on a locked switch knob. */
function XStitch() {
  return (
    <svg className="xst" width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <path
        d="M2 2 L8 8 M8 2 L2 8"
        stroke="#A9690F"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeDasharray="2.6 1.7"
      />
    </svg>
  );
}

// ------------------------------------------------------------------ Switch

export interface SwitchProps {
  on: boolean;
  /** Locked switches are server-enforced constants: disabled, no change events. */
  locked?: boolean;
  onChange?: (on: boolean) => void;
  "aria-label"?: string;
}

export function Switch({ on, locked, onChange, "aria-label": ariaLabel }: SwitchProps) {
  if (locked) {
    return (
      <span
        className={cx("sw", on ? "on" : "off", "locked")}
        role="switch"
        aria-checked={on}
        aria-disabled="true"
        aria-label={ariaLabel}
        title={on ? "Locked on" : "Locked off"}
      >
        <span className="knob">
          <XStitch />
        </span>
      </span>
    );
  }
  const toggle = () => onChange?.(!on);
  const onKey = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      toggle();
    }
  };
  return (
    <span
      className={cx("sw", on ? "on" : "off")}
      role="switch"
      aria-checked={on}
      aria-label={ariaLabel}
      tabIndex={0}
      onClick={toggle}
      onKeyDown={onKey}
    >
      <span className="knob" />
    </span>
  );
}

// ------------------------------------------------------------------ Field

export interface FieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Unit suffix, e.g. "s", "queries", "min", "files", "lines", "tokens". */
  unit?: string;
  /** Unit prefix, e.g. "$" on the monthly spend cap. */
  unitBefore?: string;
  /** Fixed width in ch; defaults to content width + slack. */
  widthCh?: number;
  /** Text inputs (branch prefix, webhook) are left-aligned. */
  alignLeft?: boolean;
  placeholder?: string;
  disabled?: boolean;
  "aria-label": string;
}

export function Field({
  value,
  onChange,
  unit,
  unitBefore,
  widthCh,
  alignLeft,
  placeholder,
  disabled,
  "aria-label": ariaLabel,
}: FieldProps) {
  const w = widthCh ?? Math.max((value || placeholder || "").length + 0.4, 1.6);
  return (
    <span className={cx("field", disabled && "dim")}>
      {unitBefore ? <span className="unit">{unitBefore}</span> : null}
      <input
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={ariaLabel}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: `${w}ch`, textAlign: alignLeft ? "left" : undefined }}
      />
      {unit ? <span className="unit">{unit}</span> : null}
    </span>
  );
}

// ------------------------------------------------------------------ SelectBox

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectBoxProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label": string;
}

export function SelectBox({ value, options, onChange, disabled, "aria-label": ariaLabel }: SelectBoxProps) {
  const selected = options.find((o) => o.value === value);
  return (
    <span className={cx("selectbox", disabled && "dim")}>
      {selected ? selected.label : value} <span className="car">▾</span>
      <select
        value={value}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </span>
  );
}

// ------------------------------------------------------------------ ChipsInput

export interface ChipsInputProps {
  chips: string[];
  onChange: (chips: string[]) => void;
  placeholder: string;
  "aria-label": string;
}

export function ChipsInput({ chips, onChange, placeholder, "aria-label": ariaLabel }: ChipsInputProps) {
  const [text, setText] = useState("");

  const commit = () => {
    const v = text.trim();
    if (v && !chips.includes(v)) {
      onChange([...chips, v]);
    }
    setText("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && text === "" && chips.length > 0) {
      onChange(chips.slice(0, -1));
    }
  };

  return (
    <div
      className="chips"
      onClick={(e) => e.currentTarget.querySelector("input")?.focus()}
    >
      {chips.map((c) => (
        <span key={c} className="chip">
          {c}
          <span
            className="x"
            role="button"
            tabIndex={0}
            aria-label={`Remove label ${c}`}
            onClick={() => onChange(chips.filter((x) => x !== c))}
            onKeyDown={(e) => {
              if (e.key === " " || e.key === "Enter") {
                e.preventDefault();
                onChange(chips.filter((x) => x !== c));
              }
            }}
          >
            ×
          </span>
        </span>
      ))}
      <input
        className="chipin"
        value={text}
        placeholder={placeholder}
        aria-label={ariaLabel}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        onBlur={commit}
      />
    </div>
  );
}

// ------------------------------------------------------------------ Radios

export interface RadioOption<T extends string> {
  value: T;
  label: ReactNode;
  ariaLabel: string;
}

export interface RadiosProps<T extends string> {
  value: T;
  options: RadioOption<T>[];
  onChange: (value: T) => void;
}

export function Radios<T extends string>({ value, options, onChange }: RadiosProps<T>) {
  return (
    <div className="radios" role="radiogroup">
      {options.map((o) => (
        <span
          key={o.value}
          className={cx("radio", value === o.value && "sel")}
          role="radio"
          aria-checked={value === o.value}
          aria-label={o.ariaLabel}
          tabIndex={0}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => {
            if (e.key === " " || e.key === "Enter") {
              e.preventDefault();
              onChange(o.value);
            }
          }}
        >
          <span className="rdot" />
          {o.label}
        </span>
      ))}
    </div>
  );
}
