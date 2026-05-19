import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, X } from "lucide-react";

export function useConfirmDialog() {
  const [state, setState] = useState(null);
  const resolveRef = useRef(null);

  const confirm = useCallback((options) => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setState({
        title: options.title || "确认操作",
        message: options.message || "确定执行此操作吗？",
        confirmLabel: options.confirmLabel || "确定",
        cancelLabel: options.cancelLabel || "取消",
        tone: options.tone || "default",
      });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true);
    resolveRef.current = null;
    setState(null);
  }, []);

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false);
    resolveRef.current = null;
    setState(null);
  }, []);

  const dialog = state ? (
    <ConfirmDialog
      title={state.title}
      message={state.message}
      confirmLabel={state.confirmLabel}
      cancelLabel={state.cancelLabel}
      tone={state.tone}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  ) : null;

  return { confirm, dialog };
}

function ConfirmDialog({ title, message, confirmLabel, cancelLabel, tone, onConfirm, onCancel }) {
  const confirmRef = useRef(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const handleKey = (e) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onCancel]);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <section
        className="modal-panel confirm-dialog"
        style={{ maxWidth: 420 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-header">
          <div>
            <h2>{title}</h2>
          </div>
          <button onClick={onCancel}><X size={18} /></button>
        </header>
        <div className="modal-body">
          <div className="confirm-body">
            {tone === "danger" && <AlertCircle size={20} className="confirm-icon danger" />}
            <p>{message}</p>
          </div>
        </div>
        <footer className="modal-footer">
          <button className="secondary-action" onClick={onCancel}>{cancelLabel}</button>
          <button
            ref={confirmRef}
            className={tone === "danger" ? "primary-action danger-action" : "primary-action"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </footer>
      </section>
    </div>
  );
}

export default ConfirmDialog;
