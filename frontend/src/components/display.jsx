import React from "react";
import {
  Activity,
  AlertCircle,
  Briefcase,
  Calendar,
  CheckCircle2,
  Database,
  LineChart,
  ListChecks,
  RefreshCw,
  X,
  XCircle,
} from "lucide-react";

export function StatusBadge({ status }) {
  const config = {
    success: { icon: CheckCircle2, text: "成功", className: "badge badge-success" },
    running: { icon: RefreshCw, text: "运行中", className: "badge badge-info spin-icon" },
    queued: { icon: ListChecks, text: "排队中", className: "badge badge-info" },
    failed: { icon: XCircle, text: "失败", className: "badge badge-danger" },
    cancelled: { icon: XCircle, text: "已终止", className: "badge badge-danger" },
    enabled: { icon: CheckCircle2, text: "启用", className: "badge badge-success" },
    disabled: { icon: XCircle, text: "停用", className: "badge badge-danger" },
  }[status] || { icon: AlertCircle, text: status, className: "badge" };
  const Icon = config.icon;
  return <span className={config.className}><Icon size={14} />{config.text}</span>;
}

export function MetricCard({ label, value, hint, icon: Icon, tone = "neutral" }) {
  return (
    <article className="metric-card">
      <div className="metric-head"><span>{label}</span><Icon size={18} /></div>
      <strong className={`metric-value tone-${tone}`}>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}

export function Toast({ toast, onClose }) {
  if (!toast) return null;
  return (
    <div className="toast">
      <CheckCircle2 size={18} />
      <div><strong>{toast.title}</strong><span>{toast.body}</span></div>
      <button onClick={onClose}><X size={16} /></button>
    </div>
  );
}
