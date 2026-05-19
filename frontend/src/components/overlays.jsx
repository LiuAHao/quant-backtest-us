import React from "react";
import {
  Activity,
  Briefcase,
  Database,
  HardDrive,
  LayoutDashboard,
  LineChart,
  MoreVertical,
  PlaySquare,
  Search,
  Settings,
  User,
  X,
} from "lucide-react";
import { StatusBadge } from "./display";

export const navItems = [
  { id: "dashboard", label: "首页总览", icon: LayoutDashboard },
  { id: "new_backtest", label: "新建回测", icon: PlaySquare },
  { id: "result", label: "回测结果", icon: LineChart },
  { id: "strategies", label: "策略管理", icon: Briefcase },
  { id: "event_analyses", label: "事件分析", icon: Search },
  { id: "event_results", label: "分析结果", icon: LineChart },
  { id: "factor_analyses", label: "因子分析", icon: Activity },
  { id: "factor_results", label: "因子结果", icon: LineChart },
  { id: "reports", label: "报告中心", icon: Database },
];

export const bottomNavItems = [
  { id: "data", label: "数据管理", icon: Database },
  { id: "settings", label: "系统设置", icon: Settings },
];

export function TaskDrawer({ tasks, close, openResult, openEventResult, openFactorResult }) {
  return (
    <div className="side-popover">
      <header><h3>任务中心</h3><button onClick={close}><X size={16} /></button></header>
      <div className="popover-list">
        {tasks.map((task) => (
          <button
            key={task.id}
            onClick={() => {
              if (task.type === "event" && task.eventAnalysisId) openEventResult(task.eventAnalysisId);
              if (task.type === "factor" && task.factorAnalysisId) openFactorResult(task.factorAnalysisId);
              if (!["event", "factor"].includes(task.type) && task.backtestId) openResult(task.backtestId);
            }}
          >
            <span><strong>{task.name}</strong><small>{task.stage}</small></span><StatusBadge status={task.status} />
          </button>
        ))}
      </div>
    </div>
  );
}

export function NotificationPanel({ notifications, close, openResult }) {
  return (
    <div className="side-popover">
      <header><h3>通知</h3><button onClick={close}><X size={16} /></button></header>
      <div className="popover-list">
        {notifications.map((item) => <button key={item.id} onClick={() => item.backtestId && openResult(item.backtestId)}><span><strong>{item.title}</strong><small>{item.body}</small></span></button>)}
      </div>
    </div>
  );
}

export function AccountMenu({ openSettingsSection, close }) {
  return (
    <div className="account-menu">
      <button onClick={() => openSettingsSection("overview")}><HardDrive size={16} />工作区概览</button>
      <button onClick={() => openSettingsSection("ai")}><Settings size={16} />AI 与模型</button>
      <button onClick={() => openSettingsSection("appearance")}><LayoutDashboard size={16} />界面主题</button>
      <button onClick={close}><X size={16} />关闭菜单</button>
    </div>
  );
}

export function Sidebar({ activeTab, setActiveTab, topOverlay, setTopOverlay }) {
  return (
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Activity size={20} /></div><strong>Q-Backtest</strong></div>
      <nav>
        <span className="nav-group">核心功能</span>
        {navItems.map((item) => {
          const Icon = item.icon;
          const className = activeTab === item.id ? "nav-active" : "";
          return (
            <button key={item.id} className={className} onClick={() => setActiveTab(item.id)}>
              <Icon size={20} />
              <span>{item.label}</span>
              {activeTab === item.id && <i />}
            </button>
          );
        })}
        <span className="nav-group">系统维护</span>
        {bottomNavItems.map((item) => { const Icon = item.icon; return <button key={item.id} className={activeTab === item.id ? "nav-active" : ""} onClick={() => setActiveTab(item.id)}><Icon size={20} />{item.label}</button>; })}
      </nav>
      <button className="user-card user-card-button" onClick={() => setTopOverlay(topOverlay === "account" ? null : "account")}><div><User size={16} /></div><span><strong>Quant Admin</strong><small>本地研究环境</small></span><MoreVertical size={16} /></button>
    </aside>
  );
}
