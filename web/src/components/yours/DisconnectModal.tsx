/**
 * "Disconnect and delete…" typed-confirm modal (footer danger
 * card). Never red: card surface, ink border, 20%-ink backdrop.
 * The confirm button stays disabled until the visitor types the tenant host.
 */

import { useEffect, useRef, useState } from "react";
import { BtnGhost, BtnGhostInk } from "../Buttons";

export interface DisconnectModalProps {
  tenantHost: string;
  busy: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: (confirmHost: string) => void;
}

export default function DisconnectModal({
  tenantHost,
  busy,
  error,
  onCancel,
  onConfirm,
}: DisconnectModalProps) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const match = typed.trim() === tenantHost;

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="yours-modalback"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onCancel();
        }
      }}
    >
      <div className="yours-modal" role="dialog" aria-modal="true" aria-labelledby="disconnect-title">
        <h3 id="disconnect-title">Disconnect and delete</h3>
        <p>
          Removes your tokens from Secret Manager and deletes every stored incident and mapping.
          The PRs on your repo stay yours.
        </p>
        <label htmlFor="disconnect-host">Type the tenant host to confirm</label>
        <input
          id="disconnect-host"
          ref={inputRef}
          className="input"
          type="text"
          placeholder={tenantHost}
          value={typed}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => setTyped(e.target.value)}
        />
        {error ? (
          <div className="errrow">
            <span className="msg">{error}</span>
          </div>
        ) : null}
        <div className="mrow">
          <BtnGhost size="sm" onClick={onCancel}>
            Keep watching
          </BtnGhost>
          <BtnGhostInk size="sm" disabled={!match || busy} onClick={() => onConfirm(typed.trim())}>
            {busy ? "Disconnecting…" : "Disconnect and delete"}
          </BtnGhostInk>
        </div>
      </div>
    </div>
  );
}
