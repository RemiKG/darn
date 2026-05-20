/**
 * Typed-confirm modal ("type the tenant host"), reused by
 * the two Data & privacy delete actions. 20%-ink backdrop,
 * card surface, calm copy, no red. The confirm button
 * stays disabled until the typed text matches exactly.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { BtnGhost, BtnInk } from "../Buttons";

export interface ConfirmModalProps {
  title: string;
  /** One calm sentence about what happens (verbatim from the row caption). */
  lead: ReactNode;
  /** The exact text the user must type (tenant host when connected). */
  confirmWord: string;
  /** Label on the ink confirm button. */
  confirmLabel: string;
  /** Resolves on success; a rejection shows the calm failure line instead. */
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

export default function ConfirmModal({
  title,
  lead,
  confirmWord,
  confirmLabel,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const match = typed.trim() === confirmWord;

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const confirm = () => {
    if (!match || busy) {
      return;
    }
    setBusy(true);
    setErr(null);
    onConfirm()
      .then(onClose)
      .catch(() => {
        setErr("This deployment didn’t accept that. Nothing was deleted.");
        setBusy(false);
      });
  };

  return (
    <div
      className="setmodal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="setmodal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        <p className="body">{lead}</p>
        <p className="body">
          Type <span className="mono">{confirmWord}</span> to confirm.
        </p>
        <span className="confirm">
          <input
            ref={inputRef}
            value={typed}
            placeholder={confirmWord}
            aria-label="Type to confirm"
            spellCheck={false}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                confirm();
              }
            }}
          />
        </span>
        {err ? <span className="err">{err}</span> : null}
        <div className="acts">
          <BtnGhost size="sm" onClick={onClose}>
            Cancel
          </BtnGhost>
          <BtnInk size="sm" disabled={!match || busy} onClick={confirm}>
            {confirmLabel}
          </BtnInk>
        </div>
      </div>
    </div>
  );
}
