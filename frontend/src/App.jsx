import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Briefcase,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Code2,
  Database,
  Download,
  FileText,
  Filter,
  FolderClock,
  LineChart,
  ListChecks,
  LayoutGrid,
  Maximize2,
  Rows3,
  Trash2,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  SquarePen,
  X,
  XCircle,
} from "lucide-react";
import {
  api,
  buildBacktestForm,
  toBacktestTemplateForm,
  toBacktestView,
  toEventAnalysisView,
  toEventDefinitionPayload,
  toEventDefinitionView,
  toFactorAnalysisView,
  toFactorDefinitionPayload,
  toFactorDefinitionView,
  toStrategyPayload,
  toStrategyView,
} from "./api";
import {
  formatReportValue,
  valueTone,
  inDateRange,
  matchesKeyword,
  chartDataFromReport,
  tradesByDateFromReport,
  reportStats,
  sourceClass,
  parseOptionalId,
} from "./lib/formatters";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useConfirmDialog } from "./components/ConfirmDialog";
import { StatusBadge, MetricCard, Toast } from "./components/display";
import { SelectionTableHeader } from "./components/SelectionTableHeader";
import { RuntimeLogPanel } from "./components/RuntimeLogPanel";
import { TradeTable, MetricSummaryTable } from "./components/report-widgets";
import { MonthlyHeatmap } from "./components/MonthlyHeatmap";
import { BacktestTable } from "./components/BacktestTable";
import { MiniLineChart } from "./components/MiniLineChart";
import { Sidebar, TaskDrawer, NotificationPanel, AccountMenu, navItems, bottomNavItems } from "./components/overlays";
import { DataManagementView } from "./components/DataManagementView";
import { SettingsView } from "./components/SettingsView";

const VALID_TABS = ["dashboard", "new_backtest", "result", "strategies", "event_analyses", "event_results", "factor_analyses", "factor_results", "reports", "data", "settings"];
const VALID_DISPLAY_MODES = ["card", "compact"];

function readNavigationState(search = window.location.search) {
  const params = new URLSearchParams(search);
  const tab = params.get("tab");
  const strategyView = params.get("strategyView");
  const eventView = params.get("eventView");
  const factorView = params.get("factorView");
  const activeTab = tab && VALID_TABS.includes(tab) ? tab : "dashboard";
  return {
    activeTab,
    selectedBacktestId: parseOptionalId(params.get("backtestId")),
    selectedEventAnalysisId: parseOptionalId(params.get("eventAnalysisId")),
    selectedFactorAnalysisId: parseOptionalId(params.get("factorAnalysisId")),
    strategyDisplayMode: strategyView && VALID_DISPLAY_MODES.includes(strategyView) ? strategyView : "compact",
    eventAnalysisDisplayMode: eventView && VALID_DISPLAY_MODES.includes(eventView) ? eventView : "compact",
    factorAnalysisDisplayMode: factorView && VALID_DISPLAY_MODES.includes(factorView) ? factorView : "compact",
  };
}


function DashboardView({ strategies, backtests, tasks, navigateTo, latestTradeDate, apiOnline }) {
  const enabledCount = strategies.filter((item) => item.status === "enabled").length;
  const best = strategies[0];
  const dataStatus = !apiOnline
    ? { value: "未连接", hint: "请启动后端 API", tone: "bad" }
    : latestTradeDate
      ? { value: "已加载", hint: `最新交易日: ${latestTradeDate}`, tone: "good" }
      : { value: "日期未知", hint: "暂未读取到数据日期", tone: "neutral" };
  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>总览仪表盘</h2><p>查看数据状态、最近任务和核心策略表现。</p></div>
        <button className="primary-action" onClick={() => navigateTo("new_backtest")}><Play size={18} />新建回测</button>
      </div>
      <section className="metric-grid">
        <MetricCard label="策略总数" value={String(strategies.length)} hint={`其中 ${enabledCount} 个已启用`} icon={Briefcase} />
        <MetricCard label="运行中任务" value={String(tasks.filter((task) => task.status === "running" || task.status === "queued").length)} hint="后台任务不会因页面切换中断" icon={Activity} tone="up" />
        <MetricCard label="数据更新状态" value={dataStatus.value} hint={dataStatus.hint} icon={Database} tone={dataStatus.tone} />
        <MetricCard
          label="最佳策略年化"
          value={best?.return || "待回测"}
          hint={best?.name || "暂无策略"}
          icon={LineChart}
          tone={!best?.return || best.return === "待回测" ? "neutral" : best.return.startsWith("-") ? "loss" : "profit"}
        />
      </section>
      <section className="panel">
        <div className="panel-title"><h3>最近回测任务</h3><button className="text-action" onClick={() => navigateTo("result")}>查看全部</button></div>
        <BacktestTable rows={backtests.slice(0, 5)} onOpen={(item) => navigateTo("result", item.id)} compact />
      </section>
    </div>
  );
}



function NewBacktestView({
  strategies,
  createBacktest,
  navigateTo,
  defaultForm,
  dateBounds,
  templates,
  saveTemplate,
  deleteTemplate,
  preferredStrategyId,
  openEdit,
}) {
  const enabledStrategies = strategies.filter((item) => item.status === "enabled");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("全部");
  const [selectedId, setSelectedId] = useState(enabledStrategies[0]?.id);
  const [templateName, setTemplateName] = useState("");
  const [activeTemplateId, setActiveTemplateId] = useState("");
  const [form, setForm] = useState({
    ...defaultForm,
  });
  const selected = enabledStrategies.find((item) => item.id === selectedId) || enabledStrategies[0];
  const filtered = enabledStrategies.filter((item) => {
    const matchQuery = item.name.includes(query) || item.desc.includes(query) || item.tags.join("").includes(query);
    const matchSource = source === "全部" || item.source === source;
    return matchQuery && matchSource;
  });

  useEffect(() => {
    if (!selectedId && enabledStrategies[0]?.id) setSelectedId(enabledStrategies[0].id);
  }, [enabledStrategies, selectedId]);

  useEffect(() => {
    if (!preferredStrategyId) return;
    if (enabledStrategies.some((item) => item.id === preferredStrategyId)) {
      setSelectedId(preferredStrategyId);
    }
  }, [enabledStrategies, preferredStrategyId]);

  useEffect(() => {
    setForm({ ...defaultForm });
    setActiveTemplateId("");
  }, [defaultForm]);

  const applyTemplate = (template) => {
    setForm(toBacktestTemplateForm(template));
    setTemplateName(template.kind === "saved" ? template.name : "");
    setActiveTemplateId(template.id);
  };

  const handleSaveTemplate = async () => {
    try {
      const normalized = {
        ...form,
        name: templateName.trim() || `${form.startDate} 至 ${form.endDate}`,
      };
      await saveTemplate(normalized);
      setTemplateName("");
    } catch {
      // saveTemplate 内部已经负责通知用户
    }
  };

  const handleRun = async () => {
    if (!selected) return;
    try {
      await createBacktest(selected, form);
      navigateTo("result");
    } catch {
      // createBacktest 内部已经负责通知用户
    }
  };

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>配置回测任务</h2><p>回测只负责运行环境配置，策略逻辑由策略代码自身决定。</p></div>
      </div>
      <section className="panel no-padding">
        <div className="form-body">
          <fieldset>
            <legend>回测模板</legend>
            <div className="template-toolbar">
              <label>
                <span>模板名称</span>
                <input value={templateName} onChange={(e) => setTemplateName(e.target.value)} placeholder="例如：2025 开年至今 / 近一个月快测" />
              </label>
            </div>
            <div className="template-grid">
              {templates.map((template) => (
                <article className={activeTemplateId === template.id ? "template-card selected" : "template-card"} key={template.id}>
                  <button className="template-main" onClick={() => applyTemplate(template)}>
                    <div className="template-head">
                      <strong>{template.name}</strong>
                      <span className={template.kind === "builtin" ? "soft-tag" : "soft-tag tag-ai"}>
                        {template.kind === "builtin" ? "系统默认" : "已保存"}
                      </span>
                    </div>
                    <small>{template.start_date} 至 {template.end_date}</small>
                    <em>资金 {Number(template.initial_capital).toLocaleString("zh-CN")} / 手续费 {Number(template.commission_rate).toFixed(4)} / 滑点 {Number(template.slippage).toFixed(3)}</em>
                  </button>
                  {template.kind === "saved" && (
                    <button className="template-delete" title="删除模板" onClick={() => deleteTemplate(template)}>
                      <Trash2 size={15} />
                    </button>
                  )}
                </article>
              ))}
              {templates.length === 0 && <div className="empty-state">当前还没有可用模板，保存一次之后这里就能复用。</div>}
            </div>
          </fieldset>
          <fieldset>
            <legend>选择策略模型 <span>*</span></legend>
            <div className="filter-row">
              <label className="search-box"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索策略名称、标签或描述" /></label>
              <select value={source} onChange={(e) => setSource(e.target.value)}>
                <option>全部</option><option>内置</option><option>AI生成</option><option>手动导入</option>
              </select>
            </div>
            <div className="strategy-picker strategy-picker-scroll backtest-strategy-picker">
              {filtered.map((strategy) => {
                const visibleTags = (Array.isArray(strategy.tags) ? strategy.tags : []).filter((tag) => tag !== "手动导入" && tag !== "AI生成");
                return (
                  <article key={strategy.id} className={selected?.id === strategy.id ? "strategy-option backtest-strategy-option selected" : "strategy-option backtest-strategy-option"}>
                    <button className="backtest-strategy-option-main" onClick={() => setSelectedId(strategy.id)}>
                      <span>
                        <strong>{strategy.name}</strong>
                        {visibleTags.length > 0 && <small className="backtest-strategy-option-tags">{visibleTags.slice(0, 3).join(" · ")}</small>}
                        <small>{strategy.desc}</small>
                      </span>
                      {selected?.id === strategy.id && <CheckCircle2 size={18} />}
                    </button>
                    <button
                      className="backtest-strategy-option-edit"
                      title="编辑策略"
                      aria-label={`编辑策略 ${strategy.name}`}
                      onClick={() => openEdit(strategy)}
                    >
                      <SquarePen size={15} />
                    </button>
                  </article>
                );
              })}
              {filtered.length === 0 && <div className="empty-state">暂无可用策略，请先在策略管理中导入并保存策略。</div>}
            </div>
          </fieldset>
          {selected && (
            <div className="selected-strategy-note">
              <span className={sourceClass(selected.source)}>{selected.source}</span>
              <strong>{selected.name}</strong>
              <small>策略参数、持仓规则和风控逻辑由策略代码内部处理。</small>
            </div>
          )}
          <div className="form-grid three">
            <label><span>回测起始日期</span><input type="date" min={dateBounds.minDate || undefined} max={dateBounds.maxDate || undefined} value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} /></label>
            <label><span>回测结束日期</span><input type="date" min={dateBounds.minDate || undefined} max={dateBounds.maxDate || undefined} value={form.endDate} onChange={(e) => setForm({ ...form, endDate: e.target.value })} /></label>
            <label><span>初始资金</span><input value={form.initialCapital} onChange={(e) => setForm({ ...form, initialCapital: e.target.value })} /></label>
            <label><span>手续费率</span><input type="number" value={form.commissionRate} step="0.0001" onChange={(e) => setForm({ ...form, commissionRate: e.target.value })} /></label>
            <label><span>滑点</span><input type="number" value={form.slippage} step="0.001" onChange={(e) => setForm({ ...form, slippage: e.target.value })} /></label>
            <label><span>基准指数</span><select value={form.benchmark} onChange={(e) => setForm({ ...form, benchmark: e.target.value })}><option value="hs300">沪深300</option><option value="zz500">中证500</option><option value="zz1000">中证1000</option></select></label>
          </div>
          <div className="selected-strategy-note compact">
            <small>当前可用数据区间：{dateBounds.minDate || "-"} 至 {dateBounds.maxDate || "-"}</small>
          </div>
          <div className="form-footer">
            <button className="secondary-action template-save-button" onClick={handleSaveTemplate}>
              <FolderClock size={16} />保存回测模板
            </button>
            <button className="primary-action" disabled={!selected} onClick={handleRun}><Play size={18} />开始异步回测</button>
          </div>
        </div>
      </section>
    </div>
  );
}

function StrategyManagerView({ strategies, openImport, openEdit, runStrategy, onDelete, onBatchDelete, navigateTo, displayMode, setDisplayMode }) {
  const [query, setQuery] = useState("");
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const visibleTags = (tags = [], source = "") => {
    const list = Array.isArray(tags) ? tags : [];
    return list.filter((tag) => source !== "手动导入" || tag !== source);
  };
  const filtered = strategies.filter((item) => item.name.includes(query) || item.desc.includes(query) || item.tags.join("").includes(query));

  useEffect(() => {
    if (!batchMode) setSelectedIds([]);
  }, [batchMode]);

  const toggleSelect = (strategyId) => {
    setSelectedIds((current) => (
      current.includes(strategyId)
        ? current.filter((item) => item !== strategyId)
        : [...current, strategyId]
    ));
  };

  const runBatchDelete = async () => {
    if (!selectedIds.length) return;
    await onBatchDelete?.(selectedIds);
    setSelectedIds([]);
    setBatchMode(false);
  };

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>策略管理</h2><p>统一维护内置、手动导入和 AI 生成策略。新增策略后可直接用于新建回测。</p></div>
        <div className="toolbar">
          <label className="search-box"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索策略..." /></label>
          <div className="view-mode-toggle" aria-label="展示方式切换">
            <button
              className={displayMode === "card" ? "secondary-action is-active" : "secondary-action"}
              onClick={() => setDisplayMode("card")}
              title="卡片视图"
              aria-label="卡片视图"
            >
              <LayoutGrid size={16} />
            </button>
            <button
              className={displayMode === "compact" ? "secondary-action is-active" : "secondary-action"}
              onClick={() => setDisplayMode("compact")}
              title="列表视图"
              aria-label="列表视图"
            >
              <Rows3 size={16} />
            </button>
          </div>
          {batchMode && (
            <button className="secondary-action icon-only-action" disabled={!selectedIds.length} onClick={runBatchDelete} title={`删除已选 ${selectedIds.length} 项`} aria-label={`删除已选 ${selectedIds.length} 项`}>
              <Trash2 size={16} />
            </button>
          )}
          <button
            className="secondary-action icon-only-action"
            onClick={() => setBatchMode((value) => !value)}
            title={batchMode ? "取消多选" : "开启多选删除"}
            aria-label={batchMode ? "取消多选" : "开启多选删除"}
          >
            {batchMode ? <X size={16} /> : <ListChecks size={16} />}
          </button>
          <button className="dark-action" onClick={openImport}><Code2 size={16} />导入新策略</button>
        </div>
      </div>
      {displayMode === "card" ? (
        <section className="strategy-grid">
          {filtered.map((strategy) => {
            const tags = visibleTags(strategy.tags, strategy.source);
            return (
              <article className={selectedIds.includes(strategy.id) ? "strategy-card is-selected" : "strategy-card"} key={strategy.id}>
                <i className="card-accent active" />
                <div className="strategy-head">
                  <div><h3>{strategy.name}</h3>{tags.length > 0 && <span className="strategy-meta-inline">{tags.slice(0, 2).join(" · ")}</span>}</div>
                  {batchMode && (
                    <label className="card-checkbox">
                      <input type="checkbox" checked={selectedIds.includes(strategy.id)} onChange={() => toggleSelect(strategy.id)} />
                      <span>选择</span>
                    </label>
                  )}
                </div>
                {tags.length > 0 && <div className="tag-row">{tags.map((tag) => <span key={tag}>{tag}</span>)}</div>}
                <p className="strategy-desc">{strategy.desc}</p>
                <div className="strategy-footer">
                  <div>
                    <small>最近回测</small>
                    {strategy.latestBacktestId ? (
                      <button className={`link-button ${valueTone(strategy.latestBacktestReturn)}`} onClick={() => navigateTo?.("result", strategy.latestBacktestId)}>
                        {strategy.latestBacktestReturn}
                      </button>
                    ) : (
                      <strong className={valueTone(strategy.latestBacktestReturn)}>{strategy.latestBacktestReturn}</strong>
                    )}
                  </div>
                  {batchMode ? (
                    <div className="card-actions"><button className="text-action" onClick={() => toggleSelect(strategy.id)}>{selectedIds.includes(strategy.id) ? "取消选择" : "加入已选"}</button></div>
                  ) : (
                    <div className="card-actions">
                      <button className="text-action" onClick={() => openEdit(strategy)}>编辑</button>
                      <button className="text-action" onClick={() => runStrategy(strategy)}>运行回测</button>
                      <button className="text-action danger-action" onClick={() => onDelete?.(strategy)}>删除</button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
          {filtered.length === 0 && (
            <div className="empty-state strategy-empty">
              当前后端策略库为空。请点击"导入新策略"，使用 AI 自动填充或手写代码后保存。
            </div>
          )}
          <button className="strategy-add" onClick={openImport}><Briefcase size={24} /><strong>导入新策略</strong><span>支持手写代码或 AI 自动填充</span></button>
        </section>
      ) : (
        <section className="compact-list">
          {filtered.map((strategy) => {
            const tags = visibleTags(strategy.tags, strategy.source);
            return (
              <article className={selectedIds.includes(strategy.id) ? "compact-row is-selected" : "compact-row"} key={strategy.id}>
                {batchMode && (
                  <label className="card-checkbox compact-row-check">
                    <input type="checkbox" checked={selectedIds.includes(strategy.id)} onChange={() => toggleSelect(strategy.id)} />
                    <span>选择</span>
                  </label>
                )}
                <div className="compact-row-main">
                  <strong className="compact-row-title">{strategy.name}</strong>
                  {tags.length > 0 && <span className="strategy-meta-inline">{tags.slice(0, 3).join(" · ")}</span>}
                </div>
                <p className="compact-row-desc">{strategy.desc}</p>
                <div className="compact-row-result">
                  <small>最近回测</small>
                  {strategy.latestBacktestId ? (
                    <button className={`link-button ${valueTone(strategy.latestBacktestReturn)}`} onClick={() => navigateTo?.("result", strategy.latestBacktestId)}>
                      {strategy.latestBacktestReturn}
                    </button>
                  ) : (
                    <strong className={valueTone(strategy.latestBacktestReturn)}>{strategy.latestBacktestReturn}</strong>
                  )}
                </div>
                {batchMode ? (
                  <div className="row-actions compact-row-actions"><button className="link-button" onClick={() => toggleSelect(strategy.id)}>{selectedIds.includes(strategy.id) ? "取消选择" : "选择"}</button></div>
                ) : (
                  <div className="row-actions compact-row-actions">
                    <button className="text-action" onClick={() => openEdit(strategy)}>编辑</button>
                    <button className="text-action" onClick={() => runStrategy(strategy)}>运行回测</button>
                    <button className="text-action danger-action" onClick={() => onDelete?.(strategy)}>删除</button>
                  </div>
                )}
              </article>
            );
          })}
          {filtered.length === 0 && (
            <div className="empty-state strategy-empty">
              当前后端策略库为空。请点击"导入新策略"，使用 AI 自动填充或手写代码后保存。
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function StrategyImportModal({ initialData, isEditing = false, onClose, onSave, onAiFill, onValidate }) {
  const [mode, setMode] = useState("manual");
  const [aiText, setAiText] = useState("选出近20日放量突破、总市值小于100亿且非ST的股票，等权买入，最多持有5个交易日。");
  const [validation, setValidation] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [aiStatus, setAiStatus] = useState("");
  const [codeEditorOpen, setCodeEditorOpen] = useState(false);
  const [form, setForm] = useState(initialData || {
    name: "放量突破小市值策略",
    key: "ai_volume_breakout_small_cap",
    source: "手动导入",
    desc: "每5个交易日筛选近20日放量突破、总市值不超过100亿且非ST的股票，等权买入并最多持有5个交易日。",
    tags: "放量,突破,小市值,轮动",
    code: "from backtest.strategy import StrategyTemplate\n\n\nclass VolumeBreakoutSmallCapStrategy(StrategyTemplate):\n    def __init__(self, hold_days: int = 5, lookback_days: int = 20, stock_count: int = 5):\n        super().__init__(\"放量突破小市值策略\")\n        self.hold_days = hold_days\n        self.lookback_days = lookback_days\n        self.stock_count = stock_count\n\n    def init(self, context):\n        self.day_count = 0\n\n    def next(self, context):\n        self.day_count += 1\n        market_data = context[\"market_data\"]\n        if market_data.empty:\n            return\n\n        positions = context[\"broker\"].account.positions\n        current_date = context[\"current_date\"]\n\n        for ts_code, position in list(positions.items()):\n            if position.volume <= 0 or not position.buy_dates:\n                continue\n            entry_date = min(position.buy_dates.keys())\n            hold_days = context[\"get_hold_days\"](entry_date, current_date)\n            if hold_days >= self.hold_days:\n                context[\"order_target_percent\"](ts_code, 0)\n\n        if self.day_count % self.hold_days != 1:\n            return\n\n        candidates = market_data.copy()\n        if \"total_mv\" not in candidates.columns:\n            return\n        candidates = candidates[candidates[\"total_mv\"].notna()]\n        candidates = candidates[candidates[\"total_mv\"] <= 100]\n\n        name_col = \"name\" if \"name\" in candidates.columns else \"symbol\" if \"symbol\" in candidates.columns else None\n        if name_col:\n            candidates = candidates[~candidates[name_col].astype(str).str.contains(\"ST\", na=False)]\n\n        selected = []\n        for ts_code in candidates.nsmallest(max(self.stock_count * 3, self.stock_count), \"total_mv\")[\"ts_code\"].tolist():\n            history = context[\"get_history\"](ts_code, current_date, window=self.lookback_days + 5)\n            if len(history) < self.lookback_days + 1:\n                continue\n\n            recent = history.tail(self.lookback_days + 1).reset_index(drop=True)\n            previous_window = recent.iloc[:-1]\n            latest = recent.iloc[-1]\n\n            prev_high = previous_window[\"high\"].max()\n            avg_volume = previous_window[\"volume\"].mean()\n            if avg_volume <= 0:\n                continue\n\n            is_breakout = latest[\"close\"] > prev_high\n            is_volume_expand = latest[\"volume\"] >= avg_volume * 1.5\n            if is_breakout and is_volume_expand:\n                selected.append(ts_code)\n            if len(selected) >= self.stock_count:\n                break\n\n        target_stocks = set(selected)\n        for ts_code, position in list(positions.items()):\n            if position.volume > 0 and ts_code not in target_stocks:\n                context[\"order_target_percent\"](ts_code, 0)\n\n        if not selected:\n            return\n\n        weight = 1.0 / len(selected)\n        for ts_code in selected:\n            context[\"order_target_percent\"](ts_code, weight)\n",
  });
  const busy = aiLoading || validating || saving;

  useEffect(() => {
    if (initialData) {
      setMode(initialData.source === "AI生成" ? "ai" : "manual");
      setForm(initialData);
    }
  }, [initialData]);

  const aiFill = async () => {
    if (!aiText.trim()) {
      setValidation({ ok: false, message: "请先输入自然语言策略描述。" });
      return;
    }
    setAiLoading(true);
    setValidation(null);
    setAiStatus("正在调用 DeepSeek 生成策略，通常需要几十秒。");
    try {
      const draft = await onAiFill(aiText);
      setMode("ai");
      setForm({
        name: draft.name,
        key: draft.key,
        source: draft.source,
        desc: draft.description,
        tags: draft.tags.join(","),
        code: draft.code,
      });
      setAiStatus("AI 已生成策略草稿，请先校验后保存。");
      setValidation({ ok: true, message: "AI 生成完成。建议点击“校验策略”确认代码结构和安全规则。" });
    } catch (error) {
      setAiStatus("");
      setValidation({ ok: false, message: error.message });
    } finally {
      setAiLoading(false);
    }
  };

  const validate = async () => {
    setValidating(true);
    try {
      const result = await onValidate(form.code);
      setValidation(result);
    } catch (error) {
      setValidation({ ok: false, message: error.message });
    } finally {
      setValidating(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(form);
    } catch (error) {
      setValidation({ ok: false, message: error.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <section className="modal-panel large">
        <header className="modal-header"><div><h2>{isEditing ? "编辑策略" : "导入新策略"}</h2><p>{isEditing ? "修改策略名称、描述、标签和代码，保存后会覆盖当前策略文件。" : "手动维护策略信息，也可以通过 AI 描述自动填充策略草稿。"}</p></div><button onClick={onClose}><X size={18} /></button></header>
        <div className="modal-body">
          {!isEditing && (
            <div className="ai-box">
              <label><span>自然语言策略描述</span><textarea value={aiText} disabled={aiLoading} onChange={(e) => setAiText(e.target.value)} /></label>
              <button className="primary-action ai-generate-button" disabled={busy || !aiText.trim()} onClick={aiFill}>
                {aiLoading ? <span className="spin-icon"><RefreshCw size={17} /></span> : <Sparkles size={17} />}
                {aiLoading ? "生成中" : "AI 生成"}
              </button>
              {(aiLoading || aiStatus) && (
                <div className={aiLoading ? "ai-progress active" : "ai-progress"}>
                  {aiLoading && <span className="spin-icon"><RefreshCw size={15} /></span>}
                  <span>{aiStatus}</span>
                </div>
              )}
            </div>
          )}
          <div className="form-grid two">
            <label><span>策略名称</span><input disabled={busy} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label><span>策略标识</span><input disabled value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
            <label><span>策略来源</span><select disabled={busy || isEditing} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}><option>手动导入</option><option>AI生成</option></select></label>
            <label><span>标签</span><input disabled={busy} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label>
          </div>
          <label><span>策略描述</span><textarea disabled={busy} value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} /></label>
          <label>
            <span className="label-with-action">
              <span>策略代码预览</span>
              <button type="button" className="secondary-action inline-action" disabled={busy} onClick={() => setCodeEditorOpen(true)}>
                <Maximize2 size={15} />放大编辑
              </button>
            </span>
            <textarea disabled={busy} className="code-area" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </label>
          <div className={validation?.ok === false ? "validation-strip validation-error" : "validation-strip"}>
            {validation?.ok === false ? <XCircle size={16} /> : <CheckCircle2 size={16} />}
            {validation ? validation.message : "保存前建议先调用后端校验，检查语法结构、策略类接口和基础安全规则。"}
            {mode === "ai" && " 当前内容来自 AI 自动填充。"}
          </div>
        </div>
        <footer className="modal-footer">
          <button className="secondary-action" disabled={busy} onClick={onClose}>取消</button>
          <button className="secondary-action" disabled={busy} onClick={validate}>
            {validating && <span className="spin-icon"><RefreshCw size={16} /></span>}
            {validating ? "校验中" : "校验策略"}
          </button>
          <button className="primary-action" disabled={busy} onClick={save}>
            {saving && <span className="spin-icon"><RefreshCw size={16} /></span>}
            {saving ? "保存中" : isEditing ? "保存修改" : "保存到策略库"}
          </button>
        </footer>
      </section>
      {codeEditorOpen && (
        <div className="modal-backdrop code-editor-backdrop">
          <section className="modal-panel code-editor-panel">
            <header className="modal-header">
              <div>
                <h2>放大编辑策略代码</h2>
                <p>这里的修改会实时同步回当前策略表单。</p>
              </div>
              <button onClick={() => setCodeEditorOpen(false)}><X size={18} /></button>
            </header>
            <div className="modal-body code-editor-body">
              <textarea
                disabled={busy}
                className="code-area code-area-expanded"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
              />
            </div>
            <footer className="modal-footer">
              <button className="secondary-action" onClick={() => setCodeEditorOpen(false)}>返回表单</button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

function EventDefinitionModal({ initialData, isEditing = false, onClose, onSave, onAiFill, onValidate }) {
  const [aiText, setAiText] = useState("判断当天是否出现收盘接近跌停的事件信号。");
  const [validation, setValidation] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [aiStatus, setAiStatus] = useState("");
  const [codeEditorOpen, setCodeEditorOpen] = useState(false);
  const [form, setForm] = useState(initialData || {
    name: "跌停后收益分析",
    key: "limit_down_rebound_event",
    source: "手动导入",
    desc: "扫描当天是否出现跌停事件信号。",
    tags: "跌停,反弹,事件分析",
    code: "from __future__ import annotations\n\nimport pandas as pd\n\nfrom event_analysis.template import EventAnalysisTemplate\n\n\nclass LimitDownEventAnalysis(EventAnalysisTemplate):\n    def __init__(self):\n        super().__init__(\"跌停后收益分析\")\n\n    def scan(self, context):\n        start = context[\"start_date\"].strftime(\"%Y-%m-%d\")\n        end = context[\"end_date\"].strftime(\"%Y-%m-%d\")\n        sql = f'''\n            SELECT d.ts_code, d.trade_date, '跌停样本' AS event_name\n            FROM daily_bar d\n            JOIN stk_limit l\n              ON d.ts_code = l.ts_code AND d.trade_date = l.trade_date\n            WHERE d.trade_date BETWEEN '{start}' AND '{end}'\n              AND d.close <= l.down_limit * 1.002\n        '''\n        return context[\"conn\"].execute(sql).fetchdf()\n",
  });
  const busy = aiLoading || validating || saving;

  useEffect(() => {
    if (initialData) {
      setForm(initialData);
    }
  }, [initialData]);

  const validate = async () => {
    try {
      setValidating(true);
      setValidation(await onValidate(form.code));
    } finally {
      setValidating(false);
    }
  };

  const runAiFill = async () => {
    try {
      setAiLoading(true);
      const draft = await onAiFill(aiText);
      setAiStatus("AI 已生成事件分析草稿，请先校验后保存。");
      setForm({
        name: draft.name || form.name,
        key: draft.key || form.key,
        source: draft.source || "AI生成",
        desc: draft.description || form.desc,
        tags: Array.isArray(draft.tags) ? draft.tags.join(",") : form.tags,
        code: draft.code || form.code,
      });
      setValidation({ ok: true, message: "AI 生成完成。建议点击“校验事件”确认代码结构和安全规则。" });
    } catch (error) {
      setAiStatus("");
      setValidation({ ok: false, message: error.message });
    } finally {
      setAiLoading(false);
    }
  };

  const save = async () => {
    try {
      setSaving(true);
      await onSave(form);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <section className="modal-panel large">
        <header className="modal-header">
          <div>
            <h2>{isEditing ? "编辑事件定义" : "导入事件定义"}</h2>
            <p>{isEditing ? "修改事件名称、说明、标签和代码，保存后会覆盖当前事件文件。" : "手动维护事件分析定义，也可以通过 AI 描述自动填充事件草稿。"}</p>
          </div>
          <button onClick={onClose}><X size={18} /></button>
        </header>
        <div className="modal-body">
          {!isEditing && (
            <div className="ai-box">
              <label><span>自然语言事件描述</span><textarea value={aiText} disabled={aiLoading} onChange={(e) => setAiText(e.target.value)} /></label>
              <button className="primary-action ai-generate-button" disabled={busy || !aiText.trim()} onClick={runAiFill}>
                {aiLoading ? <span className="spin-icon"><RefreshCw size={17} /></span> : <Sparkles size={17} />}
                {aiLoading ? "生成中" : "AI 生成"}
              </button>
              {(aiLoading || aiStatus) && (
                <div className={aiLoading ? "ai-progress active" : "ai-progress"}>
                  {aiLoading && <span className="spin-icon"><RefreshCw size={15} /></span>}
                  <span>{aiStatus || "正在调用模型生成事件分析代码，通常需要几十秒。"}</span>
                </div>
              )}
            </div>
          )}
          <div className="form-grid two">
            <label><span>事件名称</span><input disabled={busy} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label><span>事件标识</span><input disabled value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
            <label><span>事件来源</span><select disabled={busy || isEditing} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}><option>手动导入</option><option>AI生成</option></select></label>
            <label><span>标签</span><input disabled={busy} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="跌停,反弹,事件分析" /></label>
          </div>
          <label><span>事件说明</span><textarea disabled={busy} value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} /></label>
          <label>
            <span className="label-with-action">
              <span>事件代码预览</span>
              <button type="button" className="secondary-action inline-action" disabled={busy} onClick={() => setCodeEditorOpen(true)}>
                <Maximize2 size={15} />放大编辑
              </button>
            </span>
            <textarea disabled={busy} className="code-area" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </label>
          <div className={validation?.ok === false ? "validation-strip validation-error" : "validation-strip"}>
            {validation?.ok === false ? <XCircle size={16} /> : <CheckCircle2 size={16} />}
            {validation ? validation.message : "保存前建议先调用后端校验，检查语法结构、事件类接口和基础安全规则。"}
          </div>
        </div>
        <footer className="modal-footer">
          <button className="secondary-action" disabled={busy} onClick={onClose}>取消</button>
          <button className="secondary-action" disabled={busy} onClick={validate}>
            {validating && <span className="spin-icon"><RefreshCw size={16} /></span>}
            {validating ? "校验中" : "校验事件"}
          </button>
          <button className="primary-action" disabled={busy} onClick={save}>
            {saving && <span className="spin-icon"><RefreshCw size={16} /></span>}
            {saving ? "保存中" : isEditing ? "保存修改" : "保存到事件库"}
          </button>
        </footer>
      </section>
      {codeEditorOpen && (
        <div className="modal-backdrop code-editor-backdrop">
          <section className="modal-panel code-editor-panel">
            <header className="modal-header">
              <div><h2>放大编辑事件代码</h2><p>这里的修改会实时同步回当前事件表单。</p></div>
              <button onClick={() => setCodeEditorOpen(false)}><X size={18} /></button>
            </header>
            <div className="modal-body code-editor-body">
              <textarea disabled={busy} className="code-area code-area-expanded" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
            </div>
            <footer className="modal-footer">
              <button className="secondary-action" onClick={() => setCodeEditorOpen(false)}>返回表单</button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

function EventAnalysisRunModal({ definition, dateBounds, defaultDates, onClose, onRun }) {
  const [form, setForm] = useState({
    startDate: defaultDates.startDate,
    endDate: defaultDates.endDate,
    windows: "5,10,15",
    entryRule: "next_open",
    dedupRule: "none",
    filters: ["exclude_st", "exclude_new_stock", "exclude_kcb_cyb", "exclude_beijing"],
  });
  const [running, setRunning] = useState(false);

  const toggleFilter = (value) => {
    setForm((current) => ({
      ...current,
      filters: current.filters.includes(value)
        ? current.filters.filter((item) => item !== value)
        : [...current.filters, value],
    }));
  };

  const run = async () => {
    try {
      setRunning(true);
      await onRun({
        start_date: form.startDate,
        end_date: form.endDate,
        windows: form.windows.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0),
        entry_rule: form.entryRule,
        dedup_rule: form.dedupRule,
        universe: "all_a",
        filters: form.filters,
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <section className="modal-panel">
        <header className="modal-header">
          <div><h2>运行事件分析</h2><p>{definition.name}</p></div>
          <button onClick={onClose}><X size={18} /></button>
        </header>
        <div className="modal-body">
          <div className="selected-strategy-note">
            <span className={sourceClass(definition.source)}>{definition.source}</span>
            <strong>{definition.name}</strong>
            <small>平台会基于事件样本统一统计未来收益，不进行资金回测。</small>
          </div>
          <div className="form-grid three">
            <label><span>开始日期</span><input type="date" min={dateBounds.minDate || undefined} max={dateBounds.maxDate || undefined} value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} /></label>
            <label><span>结束日期</span><input type="date" min={dateBounds.minDate || undefined} max={dateBounds.maxDate || undefined} value={form.endDate} onChange={(e) => setForm({ ...form, endDate: e.target.value })} /></label>
            <label><span>观察窗口</span><input value={form.windows} onChange={(e) => setForm({ ...form, windows: e.target.value })} placeholder="5,10,15" /></label>
            <label><span>入场口径</span><select value={form.entryRule} onChange={(e) => setForm({ ...form, entryRule: e.target.value })}><option value="next_open">次日开盘</option><option value="next_close">次日收盘</option><option value="event_close">事件当日收盘</option></select></label>
            <label><span>去重规则</span><select value={form.dedupRule} onChange={(e) => setForm({ ...form, dedupRule: e.target.value })}><option value="none">不去重</option><option value="per_stock_per_day">单票单日</option><option value="per_stock_gap_5">单票间隔5日</option><option value="per_stock_gap_10">单票间隔10日</option></select></label>
          </div>
          <fieldset>
            <legend>股票范围过滤</legend>
            <div className="checkbox-grid">
              {[
                ["exclude_st", "排除 ST 股票"],
                ["exclude_new_stock", "排除次新股"],
                ["exclude_kcb_cyb", "排除科创/创业板"],
                ["exclude_main_board", "排除主板"],
                ["exclude_beijing", "排除北交所"],
              ].map(([value, label]) => (
                <label className="checkbox-card" key={value}>
                  <input type="checkbox" checked={form.filters.includes(value)} onChange={() => toggleFilter(value)} />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <footer className="modal-footer">
          <button className="secondary-action" disabled={running} onClick={onClose}>取消</button>
          <button className="primary-action" disabled={running} onClick={run}>
            {running && <span className="spin-icon"><RefreshCw size={16} /></span>}
            <Play size={16} />开始分析
          </button>
        </footer>
      </section>
    </div>
  );
}

function FactorDefinitionModal({ initialData, isEditing = false, onClose, onSave, onAiFill, onValidate }) {
  const [aiText, setAiText] = useState("构造一个 20 日动量因子，因子值为当前收盘价相对 20 日前收盘价的涨跌幅。");
  const [validation, setValidation] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(initialData || {
    name: "20日动量因子",
    key: "momentum_20_factor",
    source: "手动导入",
    desc: "计算股票 20 个交易日动量。",
    tags: "动量,因子分析",
    code: "from __future__ import annotations\n\nfrom factor_analysis.template import FactorAnalysisTemplate\n\n\nclass Momentum20Factor(FactorAnalysisTemplate):\n    def __init__(self):\n        super().__init__(\"20日动量因子\")\n\n    def compute(self, context):\n        current_date = context[\"current_date\"].strftime(\"%Y-%m-%d\")\n        market = context[\"market_data\"][[\"ts_code\"]].drop_duplicates().copy()\n        market[\"ts_code\"] = market[\"ts_code\"].astype(str)\n        if market.empty:\n            return market.assign(trade_date=current_date, factor_value=[])\n\n        sql = f\"\"\"\n            WITH recent AS (\n                SELECT\n                    d.ts_code,\n                    d.close,\n                    ROW_NUMBER() OVER (PARTITION BY d.ts_code ORDER BY d.trade_date DESC) AS rn\n                FROM daily_bar d\n                WHERE d.trade_date <= '{current_date}'\n                  AND d.ts_code IN (\n                      SELECT ts_code FROM market_codes\n                  )\n            ), pivoted AS (\n                SELECT\n                    ts_code,\n                    MAX(CASE WHEN rn = 1 THEN close END) AS close_now,\n                    MAX(CASE WHEN rn = 21 THEN close END) AS close_then\n                FROM recent\n                WHERE rn <= 21\n                GROUP BY ts_code\n            )\n            SELECT\n                ts_code,\n                '{current_date}' AS trade_date,\n                close_now / NULLIF(close_then, 0) - 1 AS factor_value\n            FROM pivoted\n            WHERE close_now IS NOT NULL\n              AND close_then IS NOT NULL\n        \"\"\"\n        context[\"conn\"].register(\"market_codes\", market)\n        try:\n            return context[\"conn\"].execute(sql).fetchdf()\n        finally:\n            context[\"conn\"].unregister(\"market_codes\")\n",
  });
  const busy = aiLoading || validating || saving;
  useEffect(() => { if (initialData) setForm(initialData); }, [initialData]);
  const validate = async () => {
    try { setValidating(true); setValidation(await onValidate(form.code)); } finally { setValidating(false); }
  };
  const runAiFill = async () => {
    try {
      setAiLoading(true);
      const draft = await onAiFill(aiText);
      setForm({
        name: draft.name || form.name,
        key: draft.key || form.key,
        source: draft.source || "AI生成",
        desc: draft.description || form.desc,
        tags: Array.isArray(draft.tags) ? draft.tags.join(",") : form.tags,
        code: draft.code || form.code,
      });
      setValidation({ ok: true, message: "AI 生成完成。建议点击“校验因子”确认代码结构和安全规则。" });
    } catch (error) {
      setValidation({ ok: false, message: error.message });
    } finally {
      setAiLoading(false);
    }
  };
  const save = async () => {
    try { setSaving(true); await onSave(form); } finally { setSaving(false); }
  };
  return (
    <div className="modal-backdrop">
      <section className="modal-panel large">
        <header className="modal-header">
          <div><h2>{isEditing ? "编辑因子定义" : "导入因子定义"}</h2><p>维护单因子计算代码，平台统一计算未来收益、IC、分组收益和覆盖率。</p></div>
          <button onClick={onClose}><X size={18} /></button>
        </header>
        <div className="modal-body">
          {!isEditing && (
            <div className="ai-box">
              <label><span>自然语言因子描述</span><textarea value={aiText} disabled={aiLoading} onChange={(e) => setAiText(e.target.value)} /></label>
              <button className="primary-action ai-generate-button" disabled={busy || !aiText.trim()} onClick={runAiFill}>
                {aiLoading ? <span className="spin-icon"><RefreshCw size={17} /></span> : <Sparkles size={17} />}
                {aiLoading ? "生成中" : "AI 生成"}
              </button>
            </div>
          )}
          <div className="form-grid two">
            <label><span>因子名称</span><input disabled={busy} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label><span>因子标识</span><input disabled value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
            <label><span>因子来源</span><select disabled={busy || isEditing} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}><option>手动导入</option><option>AI生成</option></select></label>
            <label><span>标签</span><input disabled={busy} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label>
          </div>
          <label><span>因子说明</span><textarea disabled={busy} value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} /></label>
          <label><span>因子代码预览</span><textarea disabled={busy} className="code-area" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>
          <div className={validation?.ok === false ? "validation-strip validation-error" : "validation-strip"}>
            {validation?.ok === false ? <XCircle size={16} /> : <CheckCircle2 size={16} />}
            {validation ? validation.message : "保存前建议先调用后端校验，检查因子类接口和基础安全规则。"}
          </div>
        </div>
        <footer className="modal-footer">
          <button className="secondary-action" disabled={busy} onClick={onClose}>取消</button>
          <button className="secondary-action" disabled={busy} onClick={validate}>{validating ? "校验中" : "校验因子"}</button>
          <button className="primary-action" disabled={busy} onClick={save}>{saving ? "保存中" : isEditing ? "保存修改" : "保存到因子库"}</button>
        </footer>
      </section>
    </div>
  );
}

function FactorAnalysisRunModal({ definition, dateBounds, defaultDates, onClose, onRun }) {
  const [form, setForm] = useState({
    startDate: defaultDates.startDate,
    endDate: defaultDates.endDate,
    windows: "1,5,10,20",
    rebalanceRule: "daily",
    quantiles: "5",
    icMethod: "spearman",
    factorDirection: "higher_better",
    filters: ["exclude_st", "exclude_new_stock", "exclude_beijing"],
  });
  const [running, setRunning] = useState(false);
  const toggleFilter = (value) => setForm((current) => ({ ...current, filters: current.filters.includes(value) ? current.filters.filter((item) => item !== value) : [...current.filters, value] }));
  const run = async () => {
    try {
      setRunning(true);
      await onRun({
        start_date: form.startDate,
        end_date: form.endDate,
        windows: form.windows.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0),
        universe: "all_a",
        filters: form.filters,
        rebalance_rule: form.rebalanceRule,
        quantiles: Number(form.quantiles) || 5,
        ic_method: form.icMethod,
        factor_direction: form.factorDirection,
        preprocessing: { winsorize: "mad", standardize: "zscore" },
      });
    } finally {
      setRunning(false);
    }
  };
  return (
    <div className="modal-backdrop">
      <section className="modal-panel">
        <header className="modal-header">
          <div><h2>运行因子分析</h2><p>{definition.name}</p></div>
          <button onClick={onClose}><X size={18} /></button>
        </header>
        <div className="modal-body">
          <div className="selected-strategy-note"><span className={sourceClass(definition.source)}>{definition.source}</span><strong>{definition.name}</strong><small>平台统一计算 IC、RankIC、分组收益、多空收益和覆盖率。</small></div>
          <div className="form-grid three">
            <label><span>开始日期</span><input type="date" min={dateBounds.minDate || undefined} max={dateBounds.maxDate || undefined} value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} /></label>
            <label><span>结束日期</span><input type="date" min={dateBounds.minDate || undefined} max={dateBounds.maxDate || undefined} value={form.endDate} onChange={(e) => setForm({ ...form, endDate: e.target.value })} /></label>
            <label><span>收益窗口</span><input value={form.windows} onChange={(e) => setForm({ ...form, windows: e.target.value })} /></label>
            <label><span>计算频率</span><select value={form.rebalanceRule} onChange={(e) => setForm({ ...form, rebalanceRule: e.target.value })}><option value="daily">每日</option><option value="weekly">每周</option><option value="monthly">每月</option></select></label>
            <label><span>分组数</span><input value={form.quantiles} onChange={(e) => setForm({ ...form, quantiles: e.target.value })} /></label>
            <label><span>IC 方法</span><select value={form.icMethod} onChange={(e) => setForm({ ...form, icMethod: e.target.value })}><option value="spearman">Spearman</option><option value="pearson">Pearson</option></select></label>
            <label><span>因子方向</span><select value={form.factorDirection} onChange={(e) => setForm({ ...form, factorDirection: e.target.value })}><option value="higher_better">高值更优</option><option value="lower_better">低值更优</option></select></label>
          </div>
          <fieldset>
            <legend>股票范围过滤</legend>
            <div className="checkbox-grid">
              {[["exclude_st", "排除 ST 股票"], ["exclude_new_stock", "排除次新股"], ["exclude_kcb_cyb", "排除科创/创业板"], ["exclude_beijing", "排除北交所"]].map(([value, label]) => (
                <label className="checkbox-card" key={value}><input type="checkbox" checked={form.filters.includes(value)} onChange={() => toggleFilter(value)} /><span>{label}</span></label>
              ))}
            </div>
          </fieldset>
        </div>
        <footer className="modal-footer">
          <button className="secondary-action" disabled={running} onClick={onClose}>取消</button>
          <button className="primary-action" disabled={running} onClick={run}>{running && <span className="spin-icon"><RefreshCw size={16} /></span>}<Play size={16} />开始分析</button>
        </footer>
      </section>
    </div>
  );
}

function EventAnalysisManagerView({
  definitions,
  openImport,
  openEdit,
  runDefinition,
  onDeleteDefinition,
  onBatchDeleteDefinitions,
  navigateTo,
  displayMode,
  setDisplayMode,
}) {
  const [query, setQuery] = useState("");
  const [batchMode, setBatchMode] = useState(false);
  const [selectedDefinitionIds, setSelectedDefinitionIds] = useState([]);
  const visibleTags = (tags = [], source = "") => {
    const list = Array.isArray(tags) ? tags : [];
    return list.filter((tag) => source !== "手动导入" || tag !== source);
  };
  const filtered = definitions.filter((item) => item.name.includes(query) || item.desc.includes(query) || item.tags.join("").includes(query));
  useEffect(() => {
    if (!batchMode) setSelectedDefinitionIds([]);
  }, [batchMode]);
  const toggleDefinitionSelection = (definitionId) => {
    setSelectedDefinitionIds((current) => (
      current.includes(definitionId)
        ? current.filter((item) => item !== definitionId)
        : [...current, definitionId]
    ));
  };

  const runBatchDelete = async () => {
    if (!selectedDefinitionIds.length) return;
    await onBatchDeleteDefinitions?.(selectedDefinitionIds);
    setSelectedDefinitionIds([]);
    setBatchMode(false);
  };
  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>事件分析</h2><p>在全市场扫描事件样本，统一统计未来收益分布。事件定义支持手写代码和 AI 生成。</p></div>
        <div className="toolbar">
          <label className="search-box"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索事件定义..." /></label>
          <div className="view-mode-toggle" aria-label="展示方式切换">
            <button
              className={displayMode === "card" ? "secondary-action is-active" : "secondary-action"}
              onClick={() => setDisplayMode("card")}
              title="卡片视图"
              aria-label="卡片视图"
            >
              <LayoutGrid size={16} />
            </button>
            <button
              className={displayMode === "compact" ? "secondary-action is-active" : "secondary-action"}
              onClick={() => setDisplayMode("compact")}
              title="列表视图"
              aria-label="列表视图"
            >
              <Rows3 size={16} />
            </button>
          </div>
          {batchMode && (
            <button className="secondary-action icon-only-action" disabled={!selectedDefinitionIds.length} onClick={runBatchDelete} title={`删除已选 ${selectedDefinitionIds.length} 项`} aria-label={`删除已选 ${selectedDefinitionIds.length} 项`}>
              <Trash2 size={16} />
            </button>
          )}
          <button
            className="secondary-action icon-only-action"
            onClick={() => setBatchMode((value) => !value)}
            title={batchMode ? "取消多选" : "开启多选删除"}
            aria-label={batchMode ? "取消多选" : "开启多选删除"}
          >
            {batchMode ? <X size={16} /> : <ListChecks size={16} />}
          </button>
          <button className="dark-action" onClick={openImport}><Code2 size={16} />导入事件定义</button>
        </div>
      </div>
      {displayMode === "card" ? (
        <section className="strategy-grid">
          {filtered.map((definition) => {
            const tags = visibleTags(definition.tags, definition.source);
            return (
              <article className={selectedDefinitionIds.includes(definition.id) ? "strategy-card is-selected" : "strategy-card"} key={definition.id}>
                <i className="card-accent active" />
                <div className="strategy-head">
                  <div><h3>{definition.name}</h3>{tags.length > 0 && <span className="strategy-meta-inline">{tags.slice(0, 2).join(" · ")}</span>}</div>
                  {batchMode && (
                    <label className="card-checkbox">
                      <input type="checkbox" checked={selectedDefinitionIds.includes(definition.id)} onChange={() => toggleDefinitionSelection(definition.id)} />
                      <span>选择</span>
                    </label>
                  )}
                </div>
                {tags.length > 0 && <div className="tag-row">{tags.map((tag) => <span key={tag}>{tag}</span>)}</div>}
                <p className="strategy-desc">{definition.desc}</p>
                <div className="strategy-footer">
                  <div>
                    <small>最近分析</small>
                    {definition.latestAnalysisId ? (
                      <button className={`link-button ${valueTone(definition.recentReturn)}`} onClick={() => navigateTo?.("event_results", null, { eventAnalysisId: definition.latestAnalysisId })}>
                        {definition.recentReturn}
                      </button>
                    ) : (
                      <strong className={valueTone(definition.recentReturn)}>{definition.recentReturn}</strong>
                    )}
                  </div>
                  {batchMode ? (
                    <div className="card-actions"><button className="text-action" onClick={() => toggleDefinitionSelection(definition.id)}>{selectedDefinitionIds.includes(definition.id) ? "取消选择" : "加入已选"}</button></div>
                  ) : (
                    <div className="card-actions">
                      <button className="text-action" onClick={() => openEdit(definition)}>编辑</button>
                      <button className="text-action" onClick={() => runDefinition(definition)}>运行分析</button>
                      <button className="text-action danger-action" onClick={() => onDeleteDefinition?.(definition)}>删除</button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
          {filtered.length === 0 && <div className="empty-state strategy-empty">当前还没有事件定义。点击"导入事件定义"后即可使用 AI 或手写代码创建。</div>}
          <button className="strategy-add" onClick={openImport}><Filter size={24} /><strong>导入事件定义</strong><span>支持自定义代码与 AI 生成</span></button>
        </section>
      ) : (
        <section className="compact-list">
          {filtered.map((definition) => {
            const tags = visibleTags(definition.tags, definition.source);
            return (
              <article className={selectedDefinitionIds.includes(definition.id) ? "compact-row is-selected" : "compact-row"} key={definition.id}>
                {batchMode && (
                  <label className="card-checkbox compact-row-check">
                    <input type="checkbox" checked={selectedDefinitionIds.includes(definition.id)} onChange={() => toggleDefinitionSelection(definition.id)} />
                    <span>选择</span>
                  </label>
                )}
                <div className="compact-row-main">
                  <strong className="compact-row-title">{definition.name}</strong>
                  {tags.length > 0 && <span className="strategy-meta-inline">{tags.slice(0, 3).join(" · ")}</span>}
                </div>
                <p className="compact-row-desc">{definition.desc}</p>
                <div className="compact-row-result">
                  <small>最近分析</small>
                  {definition.latestAnalysisId ? (
                    <button className={`link-button ${valueTone(definition.recentReturn)}`} onClick={() => navigateTo?.("event_results", null, { eventAnalysisId: definition.latestAnalysisId })}>
                      {definition.recentReturn}
                    </button>
                  ) : (
                    <strong className={valueTone(definition.recentReturn)}>{definition.recentReturn}</strong>
                  )}
                </div>
                {batchMode ? (
                  <div className="row-actions compact-row-actions"><button className="link-button" onClick={() => toggleDefinitionSelection(definition.id)}>{selectedDefinitionIds.includes(definition.id) ? "取消选择" : "选择"}</button></div>
                ) : (
                  <div className="row-actions compact-row-actions">
                    <button className="text-action" onClick={() => openEdit(definition)}>编辑</button>
                    <button className="text-action" onClick={() => runDefinition(definition)}>运行分析</button>
                    <button className="text-action danger-action" onClick={() => onDeleteDefinition?.(definition)}>删除</button>
                  </div>
                )}
              </article>
            );
          })}
          {filtered.length === 0 && <div className="empty-state strategy-empty">当前还没有事件定义。点击"导入事件定义"后即可使用 AI 或手写代码创建。</div>}
        </section>
      )}
    </div>
  );
}

function EventAnalysisResultsView({ analyses, selectedId, openDetail, backToList, navigateTo, onCancel, onDelete }) {
  const selected = analyses.find((item) => item.id === selectedId);
  const [draftFilters, setDraftFilters] = useState({ keyword: "", startDate: "", endDate: "" });
  const [filters, setFilters] = useState({ keyword: "", startDate: "", endDate: "" });
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const filteredAnalyses = useMemo(() => (
    analyses.filter((item) => (
      matchesKeyword([item.eventName, item.source, item.id], filters.keyword)
      && inDateRange(item.createdAt, filters.startDate, filters.endDate)
    ))
  ), [analyses, filters]);

  useEffect(() => {
    if (!batchMode) setSelectedIds([]);
  }, [batchMode]);

  if (selected) return <EventAnalysisResultView analysis={selected} backToList={backToList} />;

  const applyFilters = () => setFilters({ ...draftFilters });
  const resetFilters = () => {
    const empty = { keyword: "", startDate: "", endDate: "" };
    setDraftFilters(empty);
    setFilters(empty);
  };
  const toggleSelection = (analysisId) => {
    setSelectedIds((current) => (
      current.includes(analysisId)
        ? current.filter((item) => item !== analysisId)
        : [...current, analysisId]
    ));
  };
  const selectableAnalyses = filteredAnalyses.filter((item) => !["queued", "running"].includes(item.status));
  const allSelected = selectableAnalyses.length > 0 && selectableAnalyses.every((item) => selectedIds.includes(item.id));
  const toggleAll = () => {
    if (allSelected) {
      setSelectedIds([]);
      return;
    }
    setSelectedIds(selectableAnalyses.map((item) => item.id));
  };
  const runBatchDelete = async () => {
    for (const analysisId of selectedIds) {
      const item = analyses.find((row) => row.id === analysisId);
      if (item) {
        await onDelete(item, { skipConfirm: true, silent: true });
      }
    }
    setSelectedIds([]);
    setBatchMode(false);
  };

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>分析结果</h2><p>这里展示所有历史分析结果。点击具体记录后再进入对应详情。</p></div>
        <button className="primary-action" onClick={() => navigateTo("event_analyses")}><Play size={18} />新建事件分析</button>
      </div>
      <section className="panel no-padding">
        <div className="report-toolbar report-toolbar-filters">
          <span>共 {filteredAnalyses.length} 条分析任务</span>
          <div className="toolbar toolbar-filters">
            {batchMode && (
              <button className="secondary-action icon-only-action" disabled={!selectedIds.length} onClick={runBatchDelete} title={`删除已选 ${selectedIds.length} 项`} aria-label={`删除已选 ${selectedIds.length} 项`}>
                <Trash2 size={16} />
              </button>
            )}
            <button
              className="secondary-action icon-only-action"
              onClick={() => setBatchMode((value) => !value)}
              title={batchMode ? "取消多选" : "开启多选删除"}
              aria-label={batchMode ? "取消多选" : "开启多选删除"}
            >
              {batchMode ? <X size={16} /> : <ListChecks size={16} />}
            </button>
            <label className="search-box compact-search">
              <Search size={16} />
              <input
                value={draftFilters.keyword}
                onChange={(e) => setDraftFilters({ ...draftFilters, keyword: e.target.value })}
                placeholder="搜索事件名称、来源或任务 ID"
              />
            </label>
            <input type="date" value={draftFilters.startDate} onChange={(e) => setDraftFilters({ ...draftFilters, startDate: e.target.value })} />
            <input type="date" value={draftFilters.endDate} onChange={(e) => setDraftFilters({ ...draftFilters, endDate: e.target.value })} />
            <button className="secondary-action" onClick={applyFilters}>
              <Filter size={16} />筛选
            </button>
            <button className="secondary-action" onClick={resetFilters}>重置</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {batchMode && <th><SelectionTableHeader checked={allSelected} disabled={!selectableAnalyses.length} onToggle={toggleAll} /></th>}
                <th>任务 ID</th><th>事件名称</th><th>区间</th><th>状态</th>
                <th className="align-right">样本数</th><th className="align-right">首窗口均值</th><th className="align-right">首窗口胜率</th>
                <th className="align-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredAnalyses.map((item) => (
                <tr key={item.id}>
                  {batchMode && (
                    <td>
                      <label className="table-checkbox">
                        <input
                          type="checkbox"
                          disabled={["queued", "running"].includes(item.status)}
                          checked={selectedIds.includes(item.id)}
                          onChange={() => toggleSelection(item.id)}
                        />
                        <span>选择</span>
                      </label>
                    </td>
                  )}
                  <td className="mono muted">{item.id}</td>
                  <td className="cell-main"><strong>{item.eventName}</strong><small className="block muted">{item.source}</small></td>
                  <td className="muted cell-wrap">{item.period}</td>
                  <td><StatusBadge status={item.status} /></td>
                  <td className="align-right strong">{item.sampleCount || "-"}</td>
                  <td className={`align-right strong ${item.avgReturn !== "-" && item.avgReturn.startsWith("-") ? "text-down" : "text-up"}`}>{item.avgReturn}</td>
                  <td className="align-right strong">{item.winRate}</td>
                  <td className="align-center">
                    {batchMode ? (
                      <div className="row-actions">
                        <button className="link-button" disabled={["queued", "running"].includes(item.status)} onClick={() => toggleSelection(item.id)}>
                          {selectedIds.includes(item.id) ? "取消选择" : "选择"}
                        </button>
                      </div>
                    ) : (
                      <div className="row-actions">
                        <button className="link-button" disabled={["queued", "running"].includes(item.status)} onClick={() => openDetail(item.id)}>查看</button>
                        {["queued", "running"].includes(item.status) && (
                          <button className="text-action danger-action" onClick={() => onCancel?.(item)}>
                            <XCircle size={16} />终止
                          </button>
                        )}
                        {!["queued", "running"].includes(item.status) && (
                          <button className="text-action danger-action" onClick={() => onDelete?.(item)}>
                            <Trash2 size={16} />删除
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {filteredAnalyses.length === 0 && <tr><td colSpan={batchMode ? 9 : 8}><div className="empty-state">当前还没有事件分析任务。</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function EventAnalysisResultView({ analysis, backToList }) {
  const [resultState, setResultState] = useState({ loading: false, payload: null, task: null, error: "" });

  useEffect(() => {
    if (!analysis) {
      setResultState({ loading: false, payload: null, task: null, error: "" });
      return;
    }
    let mounted = true;
    setResultState((prev) => ({ ...prev, loading: true, error: "" }));
    api.getEventAnalysisResult(analysis.id)
      .then((result) => {
        if (mounted) setResultState({ loading: false, payload: result.payload, task: result.task, error: "" });
      })
      .catch((error) => {
        if (mounted) setResultState((prev) => ({ ...prev, loading: false, error: error.message }));
      });
    return () => { mounted = false; };
  }, [analysis?.id, analysis?.status]);

  if (!analysis) {
    return (
      <div className="view-stack page-enter">
        <div className="empty-state">
          <p>任务不存在或已删除。</p>
          <button className="link-button" onClick={backToList}>返回事件分析列表</button>
        </div>
      </div>
    );
  }

  const payload = resultState.payload;
  const isRunning = ["queued", "running"].includes(analysis.status);
  const isFailed = ["failed", "cancelled"].includes(analysis.status);
  const runtimeLogs = isRunning
    ? (analysis.runtimeLogs?.length ? analysis.runtimeLogs : (resultState.task?.runtime_logs || payload?.runtime?.logs || []))
    : (payload?.runtime?.logs || resultState.task?.runtime_logs || analysis.runtimeLogs || []);
  const summaryRows = payload?.summary?.windows || [];
  const detailRows = payload?.details || [];

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div>
          <button className="link-button back-link" onClick={backToList}>返回事件分析列表</button>
          <div className="title-with-badge"><h2>{analysis.eventName}</h2><StatusBadge status={analysis.status} /></div>
          <p>{analysis.period} | 任务 ID: {analysis.id}</p>
        </div>
      </div>
      {resultState.error && <div className="empty-state">结果读取失败：{resultState.error}</div>}
      {isRunning && !resultState.error && (
        <section className="panel">
          <div className="empty-state">
            <RefreshCw size={24} className="spin-icon" />
            <p>任务正在{analysis.status === "queued" ? "排队等待" : "运行中"}，请稍候...</p>
          </div>
        </section>
      )}
      {isFailed && !resultState.error && analysis.errorMessage && (
        <section className="panel">
          <div className="empty-state">
            <XCircle size={24} />
            <p>任务失败：{analysis.errorMessage}</p>
          </div>
        </section>
      )}
      <section className="metric-grid">
        <MetricCard label="事件样本数" value={String(payload?.summary?.sample_count ?? analysis.sampleCount ?? 0)} hint="去重和范围过滤后样本" icon={ListChecks} />
        <MetricCard label="覆盖股票数" value={String(payload?.summary?.stock_count ?? 0)} hint="样本包含的唯一股票数量" icon={Briefcase} />
        <MetricCard label="覆盖交易日" value={String(payload?.summary?.trade_date_count ?? 0)} hint="触发事件的不同交易日数" icon={Calendar} />
        <MetricCard label="首窗口均值" value={analysis.avgReturn || "-"} hint={analysis.windows?.[0] ? `${analysis.windows[0]} 日收益` : "暂无窗口"} icon={LineChart} tone={!analysis.avgReturn || analysis.avgReturn === "-" ? "neutral" : analysis.avgReturn.startsWith("-") ? "loss" : "profit"} />
      </section>
      <section className="panel no-padding">
        <div className="panel-title padded"><h3>窗口统计</h3><span className="muted">均值、中位数、胜率与分位数</span></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>窗口</th><th className="align-right">样本数</th><th className="align-right">平均收益</th><th className="align-right">中位数</th><th className="align-right">胜率</th><th className="align-right">P25</th><th className="align-right">P75</th>
              </tr>
            </thead>
            <tbody>
              {summaryRows.map((item) => (
                <tr key={item.window}>
                  <td>{item.window} 日</td>
                  <td className="align-right">{item.sample_count}</td>
                  <td className={`align-right strong ${valueTone(formatReportValue(item.avg_return, "pct"))}`}>{formatReportValue(item.avg_return, "pct")}</td>
                  <td className={`align-right strong ${valueTone(formatReportValue(item.median_return, "pct"))}`}>{formatReportValue(item.median_return, "pct")}</td>
                  <td className="align-right strong">{formatReportValue(item.win_rate, "pct")}</td>
                  <td className="align-right">{formatReportValue(item.p25, "pct")}</td>
                  <td className="align-right">{formatReportValue(item.p75, "pct")}</td>
                </tr>
              ))}
              {summaryRows.length === 0 && <tr><td colSpan="7"><div className="empty-state">{resultState.loading ? "正在读取结果..." : "当前任务暂无统计数据。"}</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <RuntimeLogPanel
        title="运行日志"
        logs={runtimeLogs}
        loading={resultState.loading}
        errorMessage={analysis.errorMessage}
        emptyText="当前任务还没有可展示的运行日志。"
      />
      <section className="panel no-padding">
        <div className="panel-title padded"><h3>样本明细</h3><span className="muted">展示前 100 条事件样本</span></div>
        <div className="table-wrap adaptive-table-wrap">
          <table className="adaptive-table report-list-table">
            <thead>
              <tr>
                <th>日期</th><th>股票代码</th><th>事件名</th><th className="align-right">入场价</th>
                {(analysis.windows || []).map((window) => <th className="align-right" key={window}>{window}日收益</th>)}
              </tr>
            </thead>
            <tbody>
              {detailRows.slice(0, 100).map((item, index) => (
                <tr key={`${item.ts_code}-${item.trade_date}-${index}`}>
                  <td className="muted">{item.trade_date}</td>
                  <td><strong>{item.ts_code}</strong></td>
                  <td>{item.event_name || "-"}</td>
                  <td className="align-right mono">{item.entry_price ? Number(item.entry_price).toFixed(2) : "-"}</td>
                  {(analysis.windows || []).map((window) => {
                    const value = item[`ret_${window}d`];
                    const text = formatReportValue(value, "pct");
                    return <td className={`align-right ${valueTone(text)}`} key={`${index}-${window}`}>{text}</td>;
                  })}
                </tr>
              ))}
              {detailRows.length === 0 && <tr><td colSpan={4 + (analysis.windows?.length || 0)}><div className="empty-state">{resultState.loading ? "正在读取结果..." : "当前任务暂无样本明细。"}</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function FactorAnalysisManagerView({ definitions, openImport, openEdit, runDefinition, onDeleteDefinition, displayMode, setDisplayMode }) {
  const [query, setQuery] = useState("");
  const filtered = definitions.filter((item) => item.name.includes(query) || item.desc.includes(query) || item.tags.join("").includes(query));
  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>因子分析</h2><p>维护单因子定义，统一评估 IC、RankIC、分组收益、多空收益和覆盖率。</p></div>
        <div className="toolbar">
          <label className="search-box"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索因子定义..." /></label>
          <div className="view-mode-toggle" aria-label="展示方式切换">
            <button className={displayMode === "card" ? "secondary-action is-active" : "secondary-action"} onClick={() => setDisplayMode("card")}><LayoutGrid size={16} /></button>
            <button className={displayMode === "compact" ? "secondary-action is-active" : "secondary-action"} onClick={() => setDisplayMode("compact")}><Rows3 size={16} /></button>
          </div>
          <button className="dark-action" onClick={openImport}><Code2 size={16} />导入因子定义</button>
        </div>
      </div>
      {displayMode === "card" ? (
        <section className="strategy-grid">
          {filtered.map((definition) => {
            const tags = Array.isArray(definition.tags) ? definition.tags : [];
            return (
              <article className="strategy-card" key={definition.id}>
                <i className="card-accent active" />
                <div className="strategy-head">
                  <div>
                    <h3>{definition.name}</h3>
                    {tags.length > 0 && <span className="strategy-meta-inline">{tags.slice(0, 2).join(" · ")}</span>}
                  </div>
                </div>
                {tags.length > 0 && <div className="tag-row">{tags.map((tag) => <span key={tag}>{tag}</span>)}</div>}
                <p className="strategy-desc">{definition.desc}</p>
                <div className="strategy-footer">
                  <div><small>最近 IC</small><strong>{definition.recentIc}</strong></div>
                  <div className="card-actions">
                    <button className="text-action" onClick={() => openEdit(definition)}>编辑</button>
                    <button className="text-action" onClick={() => runDefinition(definition)}>运行分析</button>
                    <button className="text-action danger-action" onClick={() => onDeleteDefinition?.(definition)}>删除</button>
                  </div>
                </div>
              </article>
            );
          })}
          {filtered.length === 0 && <div className="empty-state strategy-empty">当前还没有因子定义。点击"导入因子定义"后即可创建。</div>}
          <button className="strategy-add" onClick={openImport}><LineChart size={24} /><strong>导入因子定义</strong><span>支持自定义代码与 AI 生成</span></button>
        </section>
      ) : (
        <section className="compact-list">
          {filtered.map((definition) => {
            const tags = Array.isArray(definition.tags) ? definition.tags : [];
            return (
              <article className="compact-row" key={definition.id}>
                <div className="compact-row-main">
                  <strong className="compact-row-title">{definition.name}</strong>
                  {tags.length > 0 && <span className="strategy-meta-inline">{tags.slice(0, 3).join(" · ")}</span>}
                </div>
                <p className="compact-row-desc">{definition.desc}</p>
                <div className="compact-row-result"><small>最近 IC</small><strong>{definition.recentIc}</strong></div>
                <div className="row-actions compact-row-actions">
                  <button className="text-action" onClick={() => openEdit(definition)}>编辑</button>
                  <button className="text-action" onClick={() => runDefinition(definition)}>运行分析</button>
                  <button className="text-action danger-action" onClick={() => onDeleteDefinition?.(definition)}>删除</button>
                </div>
              </article>
            );
          })}
          {filtered.length === 0 && <div className="empty-state strategy-empty">当前还没有因子定义。点击"导入因子定义"后即可创建。</div>}
        </section>
      )}
    </div>
  );
}

function FactorAnalysisResultsView({ analyses, selectedId, openDetail, backToList, navigateTo, onCancel, onDelete }) {
  const selected = analyses.find((item) => item.id === selectedId);
  const [keyword, setKeyword] = useState("");
  const filtered = analyses.filter((item) => matchesKeyword([item.factorName, item.source, item.id], keyword));
  if (selected) return <FactorAnalysisResultView analysis={selected} backToList={backToList} />;
  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>因子结果</h2><p>查看历史因子分析任务和核心指标。</p></div>
        <button className="primary-action" onClick={() => navigateTo("factor_analyses")}><Play size={18} />新建因子分析</button>
      </div>
      <section className="panel no-padding">
        <div className="report-toolbar report-toolbar-filters">
          <span>共 {filtered.length} 条因子任务</span>
          <div className="toolbar toolbar-filters">
            <label className="search-box compact-search"><Search size={16} /><input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索因子名称、来源或任务 ID" /></label>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>任务 ID</th><th>因子名称</th><th>区间</th><th>状态</th>
                <th className="align-right">样本数</th><th className="align-right">首窗口 IC</th><th className="align-right">多空均值</th><th className="align-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td className="mono muted">{item.id}</td>
                  <td className="cell-main"><strong>{item.factorName}</strong><small className="block muted">{item.source}</small></td>
                  <td className="muted cell-wrap">{item.period}</td>
                  <td><StatusBadge status={item.status} /></td>
                  <td className="align-right strong">{item.sampleCount || "-"}</td>
                  <td className="align-right strong">{item.icMean}</td>
                  <td className={`align-right strong ${valueTone(item.longShortMean)}`}>{item.longShortMean}</td>
                  <td className="align-center">
                    <div className="row-actions">
                      <button className="link-button" disabled={["queued", "running"].includes(item.status)} onClick={() => openDetail(item.id)}>查看</button>
                      {["queued", "running"].includes(item.status)
                        ? <button className="text-action danger-action" onClick={() => onCancel?.(item)}><XCircle size={16} />终止</button>
                        : <button className="text-action danger-action" onClick={() => onDelete?.(item)}><Trash2 size={16} />删除</button>}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan="8"><div className="empty-state">当前还没有因子分析任务。</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function FactorAnalysisResultView({ analysis, backToList }) {
  const [resultState, setResultState] = useState({ loading: false, payload: null, task: null, error: "" });
  useEffect(() => {
    let mounted = true;
    setResultState((prev) => ({ ...prev, loading: true, error: "" }));
    api.getFactorAnalysisResult(analysis.id)
      .then((result) => { if (mounted) setResultState({ loading: false, payload: result.payload, task: result.task, error: "" }); })
      .catch((error) => { if (mounted) setResultState((prev) => ({ ...prev, loading: false, error: error.message })); });
    return () => { mounted = false; };
  }, [analysis.id, analysis.status]);
  const payload = resultState.payload;
  const summary = payload?.summary || analysis.summary || {};
  const icRows = payload?.tables?.ic_table || [];
  const groupRows = payload?.tables?.group_return_table || [];
  const detailRows = payload?.tables?.latest_factor_samples || payload?.details || [];
  const runtimeLogs = payload?.runtime?.logs || resultState.task?.runtime_logs || analysis.runtimeLogs || [];
  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><button className="link-button back-link" onClick={backToList}>返回因子结果列表</button><div className="title-with-badge"><h2>{analysis.factorName}</h2><StatusBadge status={analysis.status} /></div><p>{analysis.period} | 任务 ID: {analysis.id}</p></div>
      </div>
      {resultState.error && <div className="empty-state">结果读取失败：{resultState.error}</div>}
      <section className="metric-grid">
        <MetricCard label="有效样本数" value={String(summary.sample_count ?? analysis.sampleCount ?? 0)} hint="参与指标计算的因子样本" icon={ListChecks} />
        <MetricCard label="覆盖交易日" value={String(summary.date_count ?? 0)} hint="有有效因子值的交易日" icon={Calendar} />
        <MetricCard label="首窗口 IC" value={analysis.icMean || "-"} hint={analysis.windows?.[0] ? `${analysis.windows[0]} 日 IC 均值` : "暂无窗口"} icon={LineChart} />
        <MetricCard label="多空均值" value={analysis.longShortMean || "-"} hint="最高组减最低组收益" icon={Activity} tone={valueTone(analysis.longShortMean)} />
      </section>
      <section className="panel no-padding">
        <div className="panel-title padded"><h3>IC 汇总</h3><span className="muted">按收益窗口聚合</span></div>
        <div className="table-wrap"><table><thead><tr><th>窗口</th><th className="align-right">IC均值</th><th className="align-right">标准差</th><th className="align-right">正值占比</th><th className="align-right">样本期数</th></tr></thead><tbody>
          {icRows.map((row) => <tr key={row.window}><td>{row.window}</td><td className="align-right strong">{formatReportValue(row.mean, "number")}</td><td className="align-right">{formatReportValue(row.std, "number")}</td><td className="align-right">{formatReportValue(row.positive_rate, "pct")}</td><td className="align-right">{row.count}</td></tr>)}
          {icRows.length === 0 && <tr><td colSpan="5"><div className="empty-state">{resultState.loading ? "正在读取结果..." : "样本不足，无法计算 IC。"}</div></td></tr>}
        </tbody></table></div>
      </section>
      <section className="panel no-padding">
        <div className="panel-title padded"><h3>分组收益</h3><span className="muted">group=1 为最低因子值</span></div>
        <div className="table-wrap"><table><thead><tr><th>窗口</th><th>分组</th><th className="align-right">平均收益</th></tr></thead><tbody>
          {groupRows.map((row) => <tr key={`${row.window}-${row.group}`}><td>{row.window}d</td><td>{row.group}</td><td className={`align-right strong ${valueTone(formatReportValue(row.avg_ret, "pct"))}`}>{formatReportValue(row.avg_ret, "pct")}</td></tr>)}
          {groupRows.length === 0 && <tr><td colSpan="3"><div className="empty-state">暂无分组收益数据。</div></td></tr>}
        </tbody></table></div>
      </section>
      <RuntimeLogPanel title="运行日志" logs={runtimeLogs} loading={resultState.loading} errorMessage={analysis.errorMessage} emptyText="当前任务还没有可展示的运行日志。" />
      <section className="panel no-padding">
        <div className="panel-title padded"><h3>因子样本</h3><span className="muted">展示前 100 条</span></div>
        <div className="table-wrap"><table><thead><tr><th>日期</th><th>股票代码</th><th className="align-right">因子值</th></tr></thead><tbody>
          {detailRows.slice(0, 100).map((item, index) => <tr key={`${item.ts_code}-${item.trade_date}-${index}`}><td>{item.trade_date}</td><td><strong>{item.ts_code}</strong></td><td className="align-right mono">{formatReportValue(item.factor_value, "number")}</td></tr>)}
          {detailRows.length === 0 && <tr><td colSpan="3"><div className="empty-state">当前任务暂无样本明细。</div></td></tr>}
        </tbody></table></div>
      </section>
    </div>
  );
}

function BacktestResultView({ backtests, selectedId, openDetail, backToList, navigateTo, onCancel, onDelete }) {
  const selected = backtests.find((item) => item.id === selectedId);
  const [draftFilters, setDraftFilters] = useState({ keyword: "", startDate: "", endDate: "" });
  const [filters, setFilters] = useState({ keyword: "", startDate: "", endDate: "" });
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const filteredBacktests = useMemo(() => (
    backtests.filter((item) => (
      matchesKeyword([item.strategy, item.source, item.id], filters.keyword)
      && inDateRange(item.createdAt, filters.startDate, filters.endDate)
    ))
  ), [backtests, filters]);

  useEffect(() => {
    if (!batchMode) setSelectedIds([]);
  }, [batchMode]);

  if (selected) return <ResultDetailsView backtest={selected} backToList={backToList} />;

  const applyFilters = () => setFilters({ ...draftFilters });
  const resetFilters = () => {
    const empty = { keyword: "", startDate: "", endDate: "" };
    setDraftFilters(empty);
    setFilters(empty);
  };
  const toggleSelection = (backtestId) => {
    setSelectedIds((current) => (
      current.includes(backtestId)
        ? current.filter((item) => item !== backtestId)
        : [...current, backtestId]
    ));
  };
  const selectableBacktests = filteredBacktests.filter((item) => !["queued", "running"].includes(item.status));
  const allSelected = selectableBacktests.length > 0 && selectableBacktests.every((item) => selectedIds.includes(item.id));
  const toggleAll = () => {
    if (allSelected) {
      setSelectedIds([]);
      return;
    }
    setSelectedIds(selectableBacktests.map((item) => item.id));
  };
  const runBatchDelete = async () => {
    for (const backtestId of selectedIds) {
      const item = backtests.find((row) => row.id === backtestId);
      if (item) {
        // eslint-disable-next-line no-await-in-loop
        await onDelete(item, { skipConfirm: true, silent: true });
      }
    }
    setSelectedIds([]);
    setBatchMode(false);
  };

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>回测结果</h2><p>这里展示所有历史回测。点击具体记录后再进入对应报告详情。</p></div>
        <button className="primary-action" onClick={() => navigateTo("new_backtest")}><Play size={18} />新建回测</button>
      </div>
      <section className="panel no-padding">
        <div className="report-toolbar report-toolbar-filters">
          <span>共 {filteredBacktests.length} 条回测记录</span>
          <div className="toolbar toolbar-filters">
            {batchMode && (
              <button className="secondary-action icon-only-action" disabled={!selectedIds.length} onClick={runBatchDelete} title={`删除已选 ${selectedIds.length} 项`} aria-label={`删除已选 ${selectedIds.length} 项`}>
                <Trash2 size={16} />
              </button>
            )}
            <button
              className="secondary-action icon-only-action"
              onClick={() => setBatchMode((value) => !value)}
              title={batchMode ? "取消多选" : "开启多选删除"}
              aria-label={batchMode ? "取消多选" : "开启多选删除"}
            >
              {batchMode ? <X size={16} /> : <ListChecks size={16} />}
            </button>
            <label className="search-box compact-search">
              <Search size={16} />
              <input
                value={draftFilters.keyword}
                onChange={(e) => setDraftFilters({ ...draftFilters, keyword: e.target.value })}
                placeholder="搜索策略名称、来源或回测 ID"
              />
            </label>
            <input type="date" value={draftFilters.startDate} onChange={(e) => setDraftFilters({ ...draftFilters, startDate: e.target.value })} />
            <input type="date" value={draftFilters.endDate} onChange={(e) => setDraftFilters({ ...draftFilters, endDate: e.target.value })} />
            <button className="secondary-action" onClick={applyFilters}>
              <Filter size={16} />筛选
            </button>
            <button className="secondary-action" onClick={resetFilters}>重置</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {batchMode && <th><SelectionTableHeader checked={allSelected} disabled={!selectableBacktests.length} onToggle={toggleAll} /></th>}
                <th>回测 ID</th><th>策略名称</th><th>区间</th><th>状态</th>
                <th className="align-right">总收益</th><th className="align-right">最大回撤</th><th className="align-right">夏普</th>
                <th className="align-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredBacktests.map((item) => (
                <tr key={item.id}>
                  {batchMode && (
                    <td>
                      <label className="table-checkbox">
                        <input
                          type="checkbox"
                          disabled={["queued", "running"].includes(item.status)}
                          checked={selectedIds.includes(item.id)}
                          onChange={() => toggleSelection(item.id)}
                        />
                        <span>选择</span>
                      </label>
                    </td>
                  )}
                  <td className="mono muted">{item.id}</td>
                  <td><strong>{item.strategy}</strong><small className="block muted">{item.source}</small></td>
                  <td className="muted">{item.period}</td>
                  <td><StatusBadge status={item.status} /></td>
                  <td className={`align-right strong ${item.totalReturn !== "-" && item.totalReturn.startsWith("-") ? "text-down" : "text-up"}`}>{item.totalReturn}</td>
                  <td className="align-right strong text-down">{item.drawdown}</td>
                  <td className="align-right strong">{item.sharpe}</td>
                  <td className="align-center">
                    {batchMode ? (
                      <div className="row-actions">
                        <button className="link-button" disabled={["queued", "running"].includes(item.status)} onClick={() => toggleSelection(item.id)}>
                          {selectedIds.includes(item.id) ? "取消选择" : "选择"}
                        </button>
                      </div>
                    ) : (
                      <div className="row-actions">
                        <button className="link-button" disabled={["queued", "running"].includes(item.status)} onClick={() => openDetail(item.id)}>查看</button>
                        {["queued", "running"].includes(item.status) && (
                          <button className="text-action danger-action" title="终止回测" onClick={() => onCancel?.(item)}>
                            <XCircle size={16} />终止
                          </button>
                        )}
                        {!["queued", "running"].includes(item.status) && (
                          <button className="text-action danger-action" title="删除回测结果" onClick={() => onDelete?.(item)}>
                            <Trash2 size={16} />删除
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {filteredBacktests.length === 0 && <tr><td colSpan={batchMode ? 9 : 8}><div className="empty-state">后端暂无回测记录。</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}



function ResultDetailsView({ backtest, backToList }) {
  const [reportState, setReportState] = useState({ loading: false, payload: null, task: null, error: "" });

  useEffect(() => {
    if (["queued", "running"].includes(backtest.status)) {
      setReportState({ loading: false, payload: null, task: null, error: "" });
      return;
    }
    let mounted = true;
    setReportState({ loading: true, payload: null, task: null, error: "" });
    api.getReport(backtest.id, "backtest")
      .then((report) => {
        if (mounted) setReportState({ loading: false, payload: report.payload, task: report.task, error: report.warning || "" });
      })
      .catch((error) => {
        if (mounted) setReportState({ loading: false, payload: null, task: null, error: error.message });
      });
    return () => { mounted = false; };
  }, [backtest.id, backtest.status]);

  const report = reportState.payload;
  const runtimeLogs = report?.runtime?.logs || reportState.task?.runtime_logs || backtest.runtimeLogs || [];
  const chartData = useMemo(() => chartDataFromReport(report), [report]);
  const tradesByDate = useMemo(() => tradesByDateFromReport(report), [report]);
  const recentTrades = useMemo(() => {
    const rows = [...(report?.tables?.trades || [])];
    rows.sort((a, b) => String(b.trade_date || "").localeCompare(String(a.trade_date || "")));
    return rows.slice(0, 20);
  }, [report]);
  const monthlyReturns = report?.charts?.monthly_returns || [];
  const statRows = useMemo(() => reportStats(report), [report]);
  const exportReport = () => {
    const format = backtest.reportHtmlPath ? "html" : "json";
    window.open(api.reportDownloadUrl(backtest.id, "backtest", format), "_blank", "noopener,noreferrer");
  };
  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><button className="link-button back-link" onClick={backToList}>返回回测列表</button><div className="title-with-badge"><h2>{backtest.strategy}回测报告</h2><StatusBadge status={backtest.status} /></div><p>{backtest.period} | 回测 ID: {backtest.id}</p></div>
        <button className="secondary-action" disabled={backtest.status !== "success" || (!backtest.reportHtmlPath && !backtest.reportJsonPath)} onClick={exportReport}><Download size={16} />导出报告</button>
      </div>
      <MetricSummaryTable groups={statRows} loading={reportState.loading} />
      {reportState.error && <div className="empty-state">报告读取提示：{reportState.error}</div>}
      {backtest.errorMessage && <div className="empty-state">任务状态说明：{backtest.errorMessage}</div>}
      {chartData.length > 0 && <section className="panel"><div className="panel-title"><h3>累计收益率曲线</h3><div className="legend"><span><i className="dot-blue" />策略净值</span></div></div><MiniLineChart data={chartData} tradesByDate={tradesByDate} /></section>}
      {monthlyReturns.length > 0 && <section className="panel no-padding monthly-heatmap-panel"><div className="panel-title padded"><h3>月度收益热力图</h3></div><MonthlyHeatmap rows={monthlyReturns} /></section>}
      {recentTrades.length > 0 && <section className="panel no-padding"><div className="panel-title padded"><h3>最近交易明细</h3><span className="muted">按交易日期倒序展示最近 20 条</span></div><TradeTable trades={recentTrades} /></section>}
      <RuntimeLogPanel
        title="运行日志"
        logs={runtimeLogs}
        loading={reportState.loading}
        errorMessage={backtest.errorMessage}
        emptyText="当前回测还没有可展示的运行日志。"
      />
    </div>
  );
}


function ReportCenterView({ navigateTo, notify, confirm }) {
  const [reports, setReports] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [draftFilters, setDraftFilters] = useState({ keyword: "", startDate: "", endDate: "", type: "" });
  const [filters, setFilters] = useState({ keyword: "", startDate: "", endDate: "", type: "" });
  const [page, setPage] = useState(1);
  const [batchMode, setBatchMode] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState([]);
  const pageSize = 20;

  const fetchReports = async () => {
    setLoading(true);
    try {
      const params = {
        keyword: filters.keyword || undefined,
        start_date: filters.startDate || undefined,
        end_date: filters.endDate || undefined,
        type: filters.type || undefined,
        page,
        page_size: pageSize,
      };
      const result = await api.listReports(params);
      setReports(result.items || []);
      setTotal(result.total || 0);
    } catch (error) {
      notify("加载报告失败", error.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReports();
  }, [filters, page]);

  useEffect(() => {
    if (!batchMode) setSelectedKeys([]);
  }, [batchMode]);

  const downloadReport = (report) => {
    const format = report.artifacts?.html ? "html" : "json";
    window.open(api.reportDownloadUrl(report.id, report.download_kind, format), "_blank", "noopener,noreferrer");
  };

  const openReport = (report) => {
    if (report.open_target?.tab === "event_analyses") {
      navigateTo("event_results", null, { eventAnalysisId: report.open_target.id });
    } else if (report.open_target?.tab === "factor_results") {
      navigateTo("factor_results", null, { factorAnalysisId: report.open_target.id });
    } else {
      navigateTo("result", report.open_target?.id || report.id);
    }
  };

  const removeReport = async (report) => {
    const confirmed = await confirm({ title: "删除报告", message: `确定删除报告"${report.title}"吗？`, tone: "danger" });
    if (!confirmed) return;
    await removeReportDirect(report, false);
  };

  const removeReportDirect = async (report, silent = false) => {
    try {
      await api.deleteReport(report.id, report.download_kind);
      if (report.download_kind === "event_analysis") {
        setEventAnalyses((items) => items.filter((item) => item.id !== report.id));
        setTasks((items) => items.filter((item) => item.eventAnalysisId !== report.id));
        setSelectedEventAnalysisId((id) => id === report.id ? null : id);
        if (activeTab === "event_results" && selectedEventAnalysisId === report.id) {
          navigateTo("event_results", null, { history: "replace" });
        }
        await refreshEventAnalyses();
      }
      if (!silent) notify("报告已删除", `${report.title} 已移除。`);
      fetchReports();
    } catch (error) {
      if (!silent) notify("删除失败", error.message);
      throw error;
    }
  };

  const handleFilter = () => {
    setPage(1);
    setFilters({ ...draftFilters });
  };

  const resetFilters = () => {
    const empty = { keyword: "", startDate: "", endDate: "", type: "" };
    setDraftFilters(empty);
    setFilters(empty);
    setPage(1);
  };

  const totalPages = Math.ceil(total / pageSize);
  const toggleSelection = (reportKey) => {
    setSelectedKeys((current) => (
      current.includes(reportKey)
        ? current.filter((item) => item !== reportKey)
        : [...current, reportKey]
    ));
  };
  const currentKeys = reports.map((report) => `${report.type}-${report.id}`);
  const allSelected = currentKeys.length > 0 && currentKeys.every((key) => selectedKeys.includes(key));
  const toggleAll = () => {
    if (allSelected) {
      setSelectedKeys([]);
      return;
    }
    setSelectedKeys(currentKeys);
  };
  const runBatchDelete = async () => {
    const selectedReports = reports.filter((report) => selectedKeys.includes(`${report.type}-${report.id}`));
    let successCount = 0;
    let failedCount = 0;
    for (const report of selectedReports) {
      try {
        // eslint-disable-next-line no-await-in-loop
        await removeReportDirect(report, true);
        successCount += 1;
      } catch {
        failedCount += 1;
      }
    }
    setSelectedKeys([]);
    setBatchMode(false);
    if (failedCount > 0) {
      notify("批量删除部分完成", `成功 ${successCount} 份，失败 ${failedCount} 份。`);
    } else {
      notify("批量删除完成", `已删除 ${successCount} 份报告。`);
    }
  };

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row"><div><h2>报告中心</h2><p>统一管理所有回测报告和事件分析结果。</p></div></div>
      <section className="panel no-padding">
        <div className="report-toolbar report-toolbar-filters report-center-toolbar">
          <span className="report-toolbar-meta">共 {total} 份报告</span>
          <div className="toolbar toolbar-filters report-center-filters">
            {batchMode && (
              <button className="secondary-action icon-only-action" disabled={!selectedKeys.length} onClick={runBatchDelete} title={`删除已选 ${selectedKeys.length} 项`} aria-label={`删除已选 ${selectedKeys.length} 项`}>
                <Trash2 size={16} />
              </button>
            )}
            <button
              className="secondary-action icon-only-action"
              onClick={() => setBatchMode((value) => !value)}
              title={batchMode ? "取消多选" : "开启多选删除"}
              aria-label={batchMode ? "取消多选" : "开启多选删除"}
            >
              {batchMode ? <X size={16} /> : <ListChecks size={16} />}
            </button>
            <label className="search-box compact-search report-search-box">
              <Search size={16} />
              <input
                value={draftFilters.keyword}
                onChange={(e) => setDraftFilters({ ...draftFilters, keyword: e.target.value })}
                placeholder="搜索报告名称或来源"
              />
            </label>
            <select className="report-type-select" value={draftFilters.type} onChange={(e) => setDraftFilters({ ...draftFilters, type: e.target.value })}>
              <option value="">全部类型</option>
              <option value="backtest">回测报告</option>
              <option value="event_analysis">事件分析</option>
              <option value="factor_analysis">因子分析</option>
            </select>
            <div className="report-date-range">
              <input className="report-date-input" type="date" value={draftFilters.startDate} onChange={(e) => setDraftFilters({ ...draftFilters, startDate: e.target.value })} />
              <input className="report-date-input" type="date" value={draftFilters.endDate} onChange={(e) => setDraftFilters({ ...draftFilters, endDate: e.target.value })} />
            </div>
            <button className="secondary-action" onClick={handleFilter}>
              <Filter size={16} />筛选
            </button>
            <button className="secondary-action" onClick={resetFilters}>重置</button>
          </div>
        </div>
        <div className="table-wrap adaptive-table-wrap">
          <table className="adaptive-table report-list-table">
            <thead>
              <tr>
                {batchMode && <th><SelectionTableHeader checked={allSelected} disabled={!reports.length} onToggle={toggleAll} /></th>}
                <th>报告名称</th>
                <th className="report-col-type">类型</th>
                <th>完成时间</th>
                <th className="report-col-source">来源</th>
                <th className="align-right">核心指标</th>
                <th className="align-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => (
                <tr key={`${report.type}-${report.id}`}>
                  {batchMode && (
                    <td>
                      <label className="table-checkbox">
                        <input
                          type="checkbox"
                          checked={selectedKeys.includes(`${report.type}-${report.id}`)}
                          onChange={() => toggleSelection(`${report.type}-${report.id}`)}
                        />
                        <span>选择</span>
                      </label>
                    </td>
                  )}
                  <td className="cell-main">
                    <button className="report-name" onClick={() => openReport(report)}>
                      <FileText size={16} />{report.title}
                    </button>
                  </td>
                  <td className="report-col-type">
                    <span className="report-type-text">{report.type === "backtest" ? "回测报告" : report.type === "factor_analysis" ? "因子分析" : "事件分析"}</span>
                  </td>
                  <td className="muted">{(report.finished_at || report.created_at || "").slice(0, 19)}</td>
                  <td className="cell-wrap report-col-source"><span className="report-source-text">{report.source_name}</span></td>
                  <td className={`align-right strong ${valueTone(report.summary?.primary_display)}`}>
                    {report.summary?.primary_display || "-"}
                  </td>
                  <td className="align-center">
                    {batchMode ? (
                      <div className="row-actions">
                        <button className="link-button" onClick={() => toggleSelection(`${report.type}-${report.id}`)}>
                          {selectedKeys.includes(`${report.type}-${report.id}`) ? "取消选择" : "选择"}
                        </button>
                      </div>
                    ) : (
                      <div className="row-actions">
                        <button title="查看" onClick={() => openReport(report)}><ArrowUpRight size={17} /></button>
                        <button title="下载" onClick={() => downloadReport(report)}><Download size={17} /></button>
                        <button title="删除" onClick={() => removeReport(report)}><Trash2 size={17} /></button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {reports.length === 0 && (
                <tr><td colSpan={batchMode ? 7 : 6}><div className="empty-state">{loading ? "加载中..." : total === 0 ? "后端还没有生成分析报告。完成一次成功回测、事件分析或因子分析后，这里会显示结果。" : "当前筛选条件下没有匹配的报告。"}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="pagination">
            <button className="secondary-action" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
            <span>第 {page} / {totalPages} 页</span>
            <button className="secondary-action" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</button>
          </div>
        )}
      </section>
    </div>
  );
}



export default function App() {
  const initialNavigation = useMemo(() => readNavigationState(), []);
  const [activeTab, setActiveTab] = useState(initialNavigation.activeTab);
  const [strategies, setStrategies] = useState([]);
  const [eventDefinitions, setEventDefinitions] = useState([]);
  const [factorDefinitions, setFactorDefinitions] = useState([]);
  const [backtests, setBacktests] = useState([]);
  const [eventAnalyses, setEventAnalyses] = useState([]);
  const [factorAnalyses, setFactorAnalyses] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [selectedBacktestId, setSelectedBacktestId] = useState(initialNavigation.selectedBacktestId);
  const [selectedEventAnalysisId, setSelectedEventAnalysisId] = useState(initialNavigation.selectedEventAnalysisId);
  const [selectedFactorAnalysisId, setSelectedFactorAnalysisId] = useState(initialNavigation.selectedFactorAnalysisId);
  const [strategyDisplayMode, setStrategyDisplayMode] = useState(initialNavigation.strategyDisplayMode);
  const [eventAnalysisDisplayMode, setEventAnalysisDisplayMode] = useState(initialNavigation.eventAnalysisDisplayMode);
  const [factorAnalysisDisplayMode, setFactorAnalysisDisplayMode] = useState(initialNavigation.factorAnalysisDisplayMode);
  const [importOpen, setImportOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState(null);
  const [eventImportOpen, setEventImportOpen] = useState(false);
  const [editingEventDefinition, setEditingEventDefinition] = useState(null);
  const [runEventDefinition, setRunEventDefinition] = useState(null);
  const [factorImportOpen, setFactorImportOpen] = useState(false);
  const [editingFactorDefinition, setEditingFactorDefinition] = useState(null);
  const [runFactorDefinition, setRunFactorDefinition] = useState(null);
  const [topOverlay, setTopOverlay] = useState(null);
  const [toast, setToast] = useState(null);
  const [theme, setTheme] = useState("light");
  const [apiOnline, setApiOnline] = useState(false);
  const [runtimeSettings, setRuntimeSettings] = useState(null);
  const [settingsFocus, setSettingsFocus] = useState("overview");
  const [preferredBacktestStrategyId, setPreferredBacktestStrategyId] = useState(null);
  const historyModeRef = useRef("replace");
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const prevBacktestsKeyRef = useRef("");
  const prevEventAnalysesKeyRef = useRef("");
  const prevFactorAnalysesKeyRef = useRef("");

  const strategyMap = useMemo(() => new Map(strategies.map((item) => [item.id, item])), [strategies]);
  const eventDefinitionMap = useMemo(() => new Map(eventDefinitions.map((item) => [item.id, item])), [eventDefinitions]);
  const factorDefinitionMap = useMemo(() => new Map(factorDefinitions.map((item) => [item.id, item])), [factorDefinitions]);
  const backtestDefaults = useMemo(() => buildBacktestForm(runtimeSettings), [runtimeSettings]);
  const dateBounds = useMemo(() => ({
    minDate: runtimeSettings?.data?.earliest_trade_date || "",
    maxDate: runtimeSettings?.data?.latest_trade_date || "",
  }), [runtimeSettings]);
  const eventDefaultDates = useMemo(() => {
    const endDate = dateBounds.maxDate || backtestDefaults.endDate;
    const end = new Date(endDate);
    if (Number.isNaN(end.getTime())) {
      return { startDate: backtestDefaults.startDate, endDate: backtestDefaults.endDate };
    }
    const start = new Date(end);
    start.setFullYear(start.getFullYear() - 1);
    return {
      startDate: start.toISOString().slice(0, 10),
      endDate,
    };
  }, [backtestDefaults.endDate, backtestDefaults.startDate, dateBounds.maxDate]);

  const notify = (title, body, backtestId) => {
    const item = { id: `n-${Date.now()}`, title, body, backtestId };
    setNotifications((list) => [item, ...list]);
    setToast(item);
  };

  const refreshStrategies = async () => {
    const rows = await api.listStrategies();
    const mapped = rows.map(toStrategyView);
    setStrategies((previous) => mapped.map((item) => {
      const old = previous.find((entry) => entry.id === item.id);
      return old ? {
        ...item,
        return: old.return ?? item.return,
        latestBacktestReturn: old.latestBacktestReturn ?? item.latestBacktestReturn,
        latestBacktestId: old.latestBacktestId ?? item.latestBacktestId,
      } : item;
    }));
    return rows;
  };

  const refreshEventDefinitions = async () => {
    const rows = await api.listEventDefinitions();
    const mapped = rows.map(toEventDefinitionView);
    setEventDefinitions((previous) => mapped.map((item) => {
      const old = previous.find((entry) => entry.id === item.id);
      return old ? {
        ...item,
        recentReturn: old.recentReturn ?? item.recentReturn,
        latestAnalysisId: old.latestAnalysisId ?? item.latestAnalysisId,
      } : item;
    }));
    return rows;
  };

  const refreshFactorDefinitions = async () => {
    const rows = await api.listFactorDefinitions();
    const mapped = rows.map(toFactorDefinitionView);
    setFactorDefinitions((previous) => mapped.map((item) => {
      const old = previous.find((entry) => entry.id === item.id);
      return old ? {
        ...item,
        recentIc: old.recentIc ?? item.recentIc,
        latestAnalysisId: old.latestAnalysisId ?? item.latestAnalysisId,
      } : item;
    }));
    return rows;
  };

  const refreshTemplates = async () => {
    const rows = await api.listBacktestTemplates();
    setTemplates(rows);
    return rows;
  };

  const refreshBacktests = async (currentStrategies = strategies) => {
    const rows = await api.listBacktests();
    const currentMap = new Map(currentStrategies.map((item) => [item.id, item]));
    const mapped = rows.map((item) => toBacktestView(item, currentMap));
    const dataKey = JSON.stringify(mapped.map((item) => ({
      id: item.id,
      strategy: item.strategy,
      source: item.source,
      status: item.status,
      progress: item.progress,
      totalReturn: item.totalReturn,
      drawdown: item.drawdown,
      sharpe: item.sharpe,
    })));
    if (dataKey === prevBacktestsKeyRef.current) return mapped;
    prevBacktestsKeyRef.current = dataKey;

    const latestSuccessByStrategy = new Map();
    rows.forEach((item) => {
      if (item.status !== "success" || latestSuccessByStrategy.has(item.strategy_id)) return;
      latestSuccessByStrategy.set(item.strategy_id, { id: item.id, totalReturn: item.total_return });
    });
    setStrategies((items) => items.map((item) => {
      const latest = latestSuccessByStrategy.get(item.id);
      const latestBacktestReturn = !latest || latest.totalReturn === undefined || latest.totalReturn === null
        ? "待回测"
        : `${Number(latest.totalReturn) >= 0 ? "+" : ""}${(Number(latest.totalReturn) * 100).toFixed(2)}%`;
      return {
        ...item,
        return: latestBacktestReturn,
        latestBacktestReturn,
        latestBacktestId: latest?.id ?? null,
      };
    }));
    setBacktests((previous) => {
      const previousMap = new Map(previous.map((item) => [item.id, item]));
      mapped.forEach((item) => {
        const old = previousMap.get(item.id);
        const wasActive = old && ["queued", "running"].includes(old.status);
        const isFinished = ["success", "failed"].includes(item.status);
        if (wasActive && isFinished) {
          notify(
            item.status === "success" ? "回测任务完成" : "回测任务失败",
            item.status === "success" ? `${item.strategy} 已生成报告。` : `${item.strategy} 执行失败：${item.errorMessage || "请查看任务详情"}`,
            item.id,
          );
        }
      });
      return mapped;
    });
    const backtestTasks = mapped.filter((item) => ["queued", "running"].includes(item.status)).map((item) => ({
      id: `task-${item.id}`,
      backtestId: item.id,
      name: `${item.strategy}回测`,
      status: item.status,
      stage: item.status === "queued" ? "等待后端调度" : `后端运行中 ${item.progress || 0}%`,
      progress: item.progress || 0,
    }));
    setTasks((previous) => {
      const nonBacktestTasks = previous.filter((item) => item.type === "event" || item.type === "factor");
      return [...backtestTasks, ...nonBacktestTasks];
    });
    return mapped;
  };

  const refreshEventAnalyses = async (currentDefinitions = eventDefinitions) => {
    const rows = await api.listEventAnalyses();
    const currentMap = new Map(currentDefinitions.map((item) => [item.id, item]));
    const mapped = rows.map((item) => toEventAnalysisView(item, currentMap));
    const dataKey = JSON.stringify(mapped.map((item) => ({ id: item.id, status: item.status, progress: item.progress })));
    if (dataKey === prevEventAnalysesKeyRef.current) return mapped;
    prevEventAnalysesKeyRef.current = dataKey;

    const latestSuccessByDefinition = new Map();
    rows.forEach((item) => {
      if (item.status !== "success" || latestSuccessByDefinition.has(item.event_definition_id)) return;
      const firstWindow = Array.isArray(item.summary?.windows) ? item.summary.windows[0] : null;
      latestSuccessByDefinition.set(item.event_definition_id, {
        id: item.id,
        recentReturn: firstWindow?.avg_return === null || firstWindow?.avg_return === undefined
          ? "待分析"
          : `${Number(firstWindow.avg_return) >= 0 ? "+" : ""}${(Number(firstWindow.avg_return) * 100).toFixed(2)}%`,
      });
    });
    setEventDefinitions((items) => items.map((item) => {
      const latest = latestSuccessByDefinition.get(item.id);
      return {
        ...item,
        recentReturn: latest?.recentReturn ?? "待分析",
        latestAnalysisId: latest?.id ?? null,
      };
    }));
    setEventAnalyses((previous) => {
      const previousMap = new Map(previous.map((item) => [item.id, item]));
      mapped.forEach((item) => {
        const old = previousMap.get(item.id);
        const wasActive = old && ["queued", "running"].includes(old.status);
        const isFinished = ["success", "failed"].includes(item.status);
        if (wasActive && isFinished) {
          notify(
            item.status === "success" ? "事件分析完成" : "事件分析失败",
            item.status === "success" ? `${item.eventName} 已生成统计结果。` : `${item.eventName} 执行失败：${item.errorMessage || "请查看任务详情"}`,
            null,
          );
        }
      });
      return mapped;
    });
    setTasks((previous) => {
      const backtestTasks = previous.filter((item) => item.type !== "event");
      const eventTasks = mapped.filter((item) => ["queued", "running"].includes(item.status)).map((item) => ({
        id: `event-task-${item.id}`,
        type: "event",
        eventAnalysisId: item.id,
        name: `${item.eventName}事件分析`,
        status: item.status,
        stage: item.status === "queued" ? "等待后端调度" : `事件分析运行中 ${item.progress || 0}%`,
        progress: item.progress || 0,
      }));
      return [...backtestTasks, ...eventTasks];
    });
    return mapped;
  };

  const refreshFactorAnalyses = async (currentDefinitions = factorDefinitions) => {
    const rows = await api.listFactorAnalyses();
    const currentMap = new Map(currentDefinitions.map((item) => [item.id, item]));
    const mapped = rows.map((item) => toFactorAnalysisView(item, currentMap));
    const dataKey = JSON.stringify(mapped.map((item) => ({ id: item.id, status: item.status, progress: item.progress, icMean: item.icMean })));
    if (dataKey === prevFactorAnalysesKeyRef.current) return mapped;
    prevFactorAnalysesKeyRef.current = dataKey;

    const latestSuccessByDefinition = new Map();
    rows.forEach((item) => {
      if (item.status !== "success" || latestSuccessByDefinition.has(item.factor_definition_id)) return;
      const icBlock = item.summary?.ic || {};
      const firstKey = Object.keys(icBlock)[0];
      const value = firstKey ? icBlock[firstKey]?.mean : null;
      latestSuccessByDefinition.set(item.factor_definition_id, {
        id: item.id,
        recentIc: value === null || value === undefined ? "待分析" : Number(value).toFixed(3),
      });
    });
    setFactorDefinitions((items) => items.map((item) => {
      const latest = latestSuccessByDefinition.get(item.id);
      return { ...item, recentIc: latest?.recentIc ?? "待分析", latestAnalysisId: latest?.id ?? null };
    }));
    setFactorAnalyses((previous) => {
      const previousMap = new Map(previous.map((item) => [item.id, item]));
      mapped.forEach((item) => {
        const old = previousMap.get(item.id);
        const wasActive = old && ["queued", "running"].includes(old.status);
        const isFinished = ["success", "failed"].includes(item.status);
        if (wasActive && isFinished) {
          notify(
            item.status === "success" ? "因子分析完成" : "因子分析失败",
            item.status === "success" ? `${item.factorName} 已生成统计结果。` : `${item.factorName} 执行失败：${item.errorMessage || "请查看任务详情"}`,
            null,
          );
        }
      });
      return mapped;
    });
    setTasks((previous) => {
      const nonFactorTasks = previous.filter((item) => item.type !== "factor");
      const factorTasks = mapped.filter((item) => ["queued", "running"].includes(item.status)).map((item) => ({
        id: `factor-task-${item.id}`,
        type: "factor",
        factorAnalysisId: item.id,
        name: `${item.factorName}因子分析`,
        status: item.status,
        stage: item.status === "queued" ? "等待后端调度" : `因子分析运行中 ${item.progress || 0}%`,
        progress: item.progress || 0,
      }));
      return [...nonFactorTasks, ...factorTasks];
    });
    return mapped;
  };

  const refreshAll = async () => {
    try {
      await api.health();
      setApiOnline(true);
      const settings = await api.getSettings();
      setRuntimeSettings(settings);
      setTheme(settings?.ui?.theme || "light");
      await refreshTemplates();
      const strategyRows = await refreshStrategies();
      const eventDefinitionRows = await refreshEventDefinitions();
      const factorDefinitionRows = await refreshFactorDefinitions();
      const loadedStrategies = strategyRows.map(toStrategyView);
      const loadedDefinitions = eventDefinitionRows.map(toEventDefinitionView);
      const loadedFactorDefinitions = factorDefinitionRows.map(toFactorDefinitionView);
      await refreshBacktests(loadedStrategies);
      await refreshEventAnalyses(loadedDefinitions);
      await refreshFactorAnalyses(loadedFactorDefinitions);
    } catch (error) {
      setApiOnline(false);
      setRuntimeSettings(null);
      setStrategies([]);
      setEventDefinitions([]);
      setFactorDefinitions([]);
      setTemplates([]);
      setBacktests([]);
      setEventAnalyses([]);
      setFactorAnalyses([]);
      setTasks([]);
      notify("后端未连接", "请先启动 uvicorn backend.main:app，前端不会再使用示例数据回退。");
    }
  };

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 3600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (activeTab !== "dashboard") params.set("tab", activeTab);
    if (activeTab === "result" && selectedBacktestId) params.set("backtestId", String(selectedBacktestId));
    if (activeTab === "event_results" && selectedEventAnalysisId) params.set("eventAnalysisId", String(selectedEventAnalysisId));
    if (activeTab === "factor_results" && selectedFactorAnalysisId) params.set("factorAnalysisId", String(selectedFactorAnalysisId));
    if (strategyDisplayMode === "card") params.set("strategyView", strategyDisplayMode);
    if (eventAnalysisDisplayMode === "card") params.set("eventView", eventAnalysisDisplayMode);
    if (factorAnalysisDisplayMode === "card") params.set("factorView", factorAnalysisDisplayMode);
    const query = params.toString();
    const url = query ? `/?${query}` : "/";
    const method = historyModeRef.current === "push" ? "pushState" : "replaceState";
    window.history[method](null, "", url);
    historyModeRef.current = "replace";
  }, [activeTab, selectedBacktestId, selectedEventAnalysisId, selectedFactorAnalysisId, strategyDisplayMode, eventAnalysisDisplayMode, factorAnalysisDisplayMode]);

  useEffect(() => {
    const handlePopState = () => {
      const state = readNavigationState();
      historyModeRef.current = "replace";
      setActiveTab(state.activeTab);
      setSelectedBacktestId(state.selectedBacktestId);
      setSelectedEventAnalysisId(state.selectedEventAnalysisId);
      setSelectedFactorAnalysisId(state.selectedFactorAnalysisId);
      setStrategyDisplayMode(state.strategyDisplayMode);
      setEventAnalysisDisplayMode(state.eventAnalysisDisplayMode);
      setFactorAnalysisDisplayMode(state.factorAnalysisDisplayMode);
      setTopOverlay(null);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!apiOnline) return undefined;
    let timer = null;
    const isHidden = () => document.visibilityState === "hidden";
    const poll = () => {
      if (isHidden()) return;
      Promise.all([refreshBacktests(), refreshEventAnalyses(), refreshFactorAnalyses()]).catch(() => setApiOnline(false));
    };
    const startInterval = () => {
      if (timer) return;
      const interval = isHidden() ? 10000 : 2500;
      timer = window.setInterval(poll, interval);
    };
    const stopInterval = () => {
      if (timer) { window.clearInterval(timer); timer = null; }
    };
    const handleVisibility = () => {
      stopInterval();
      if (!isHidden()) poll();
      startInterval();
    };
    startInterval();
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      stopInterval();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [apiOnline, strategyMap, eventDefinitionMap, factorDefinitionMap]);

  const navigateTo = (tab, backtestId = null, options = {}) => {
    const { eventAnalysisId = null, factorAnalysisId = null, history = "push" } = options;
    historyModeRef.current = history;
    setActiveTab(tab);
    setSelectedBacktestId(tab === "result" ? backtestId : null);
    setSelectedEventAnalysisId(tab === "event_results" ? eventAnalysisId : null);
    setSelectedFactorAnalysisId(tab === "factor_results" ? factorAnalysisId : null);
    if (tab !== "new_backtest") setPreferredBacktestStrategyId(null);
    setTopOverlay(null);
  };

  const openSettingsSection = (section) => {
    setSettingsFocus(section);
    navigateTo("settings");
  };

  const createBacktest = async (strategy, form = backtestDefaults) => {
    const normalizedForm = { ...backtestDefaults, ...form };
    if (!apiOnline) {
      notify("后端未连接", "无法创建回测任务，请先启动后端服务。");
      throw new Error("后端未连接");
    }

    const strategyId = Number(strategy.id);
    if (!Number.isInteger(strategyId) || strategyId <= 0) {
      notify("无法创建后端回测", "当前策略不存在后端策略 ID，请先在策略管理中导入并保存策略。");
      throw new Error("当前策略未保存到后端");
    }

    if (!normalizedForm.startDate || !normalizedForm.endDate) {
      const message = "请先选择完整的回测起止日期。";
      notify("回测参数不完整", message);
      throw new Error(message);
    }
    if (normalizedForm.startDate > normalizedForm.endDate) {
      const message = "回测开始日期不能晚于结束日期。";
      notify("回测日期无效", message);
      throw new Error(message);
    }
    if (dateBounds.minDate && normalizedForm.startDate < dateBounds.minDate) {
      const message = `开始日期超出数据范围，可用区间为 ${dateBounds.minDate} 至 ${dateBounds.maxDate}。`;
      notify("回测日期超界", message);
      throw new Error(message);
    }
    if (dateBounds.maxDate && normalizedForm.endDate > dateBounds.maxDate) {
      const message = `结束日期超出数据范围，可用区间为 ${dateBounds.minDate} 至 ${dateBounds.maxDate}。`;
      notify("回测日期超界", message);
      throw new Error(message);
    }

    try {
      const initialCapital = Number(String(normalizedForm.initialCapital).replaceAll(",", ""));
      const commissionRate = Number(normalizedForm.commissionRate);
      const slippage = Number(normalizedForm.slippage);
      if (!Number.isFinite(initialCapital) || initialCapital <= 0) {
        throw new Error("初始资金必须大于 0。");
      }
      if (!Number.isFinite(commissionRate) || commissionRate < 0) {
        throw new Error("手续费率不能小于 0。");
      }
      if (!Number.isFinite(slippage) || slippage < 0) {
        throw new Error("滑点不能小于 0。");
      }
      const task = await api.createBacktest({
        strategy_id: strategyId,
        start_date: normalizedForm.startDate,
        end_date: normalizedForm.endDate,
        initial_capital: initialCapital,
        commission_rate: commissionRate,
        slippage,
      });
      const row = toBacktestView(task, strategyMap);
      setBacktests((items) => [row, ...items.filter((item) => item.id !== row.id)]);
      setTasks((items) => [{ id: `task-${row.id}`, backtestId: row.id, name: `${strategy.name}回测`, status: row.status, stage: "等待后端调度", progress: row.progress }, ...items]);
      notify("回测任务已创建", `${strategy.name} 已进入后端任务队列。`, row.id);
      return row;
    } catch (error) {
      notify("回测任务创建失败", error.message);
      throw error;
    }
  };

  const saveBacktestTemplate = async (form) => {
    if (!apiOnline) {
      notify("后端未连接", "无法保存回测模板，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    try {
      if (!form.startDate || !form.endDate) {
        throw new Error("模板起止日期不能为空。");
      }
      const payload = {
        name: form.name,
        start_date: form.startDate,
        end_date: form.endDate,
        initial_capital: Number(String(form.initialCapital).replaceAll(",", "")),
        commission_rate: Number(form.commissionRate),
        slippage: Number(form.slippage),
        benchmark: form.benchmark || "hs300",
      };
      const saved = await api.createBacktestTemplate(payload);
      setTemplates((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
      notify("回测模板已保存", `${saved.name} 之后可以直接复用。`);
      return saved;
    } catch (error) {
      notify("保存模板失败", error.message);
      throw error;
    }
  };

  const deleteBacktestTemplate = async (template) => {
    if (template.kind !== "saved" || !template.db_id) return;
    const confirmed = await confirm({ title: "删除模板", message: `确定删除模板"${template.name}"吗？`, tone: "danger" });
    if (!confirmed) return;
    try {
      await api.deleteBacktestTemplate(template.db_id);
      setTemplates((items) => items.filter((item) => item.id !== template.id));
      notify("回测模板已删除", `${template.name} 已从模板列表移除。`);
    } catch (error) {
      notify("删除模板失败", error.message);
    }
  };

  const cancelBacktest = async (backtest) => {
    try {
      const saved = await api.cancelBacktest(backtest.id);
      const row = toBacktestView(saved, strategyMap);
      setBacktests((items) => items.map((item) => item.id === row.id ? row : item));
      setTasks((items) => items.filter((item) => item.backtestId !== row.id));
      notify("回测已终止", `${backtest.strategy} 的回测任务已标记为终止。`);
      await refreshBacktests();
    } catch (error) {
      notify("终止回测失败", error.message);
    }
  };

  const deleteBacktest = async (backtest, options = {}) => {
    const { skipConfirm = false, silent = false } = options;
    const confirmed = skipConfirm || await confirm({ title: "删除回测", message: `确定删除回测 #${backtest.id} 吗？关联报告文件也会一并删除。`, tone: "danger" });
    if (!confirmed) return false;
    try {
      await api.deleteBacktest(backtest.id);
      setBacktests((items) => items.filter((item) => item.id !== backtest.id));
      setTasks((items) => items.filter((item) => item.backtestId !== backtest.id));
      setSelectedBacktestId((id) => id === backtest.id ? null : id);
      if (!silent) notify("回测结果已删除", `${backtest.strategy} 的回测记录已移除。`);
      return true;
    } catch (error) {
      if (!silent) notify("删除回测失败", error.message);
      throw error;
    }
  };

  const deleteStrategy = async (strategy) => {
    const confirmed = await confirm({ title: "删除策略", message: `确定删除策略"${strategy.name}"吗？\n\n注意：删除后策略定义将被移除，但历史回测报告会保留。`, tone: "danger" });
    if (!confirmed) return;
    try {
      await api.deleteStrategy(strategy.id);
      setStrategies((items) => items.filter((item) => item.id !== strategy.id));
      notify("策略已删除", `${strategy.name} 的定义已移除，历史回测报告保留。`);
    } catch (error) {
      notify("删除策略失败", error.message);
    }
  };

  const saveStrategy = async (form) => {
    if (!apiOnline) {
      notify("后端未连接", "无法保存策略，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    if (editingStrategy?.id) {
      const payload = {
        name: form.name,
        description: form.desc,
        source: form.source,
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        code: form.code,
      };
      const saved = toStrategyView(await api.updateStrategy(editingStrategy.id, payload));
      setStrategies((items) => items.map((item) => item.id === saved.id ? saved : item));
      setImportOpen(false);
      setEditingStrategy(null);
      notify("策略已更新", `${saved.name} 的代码和参数已保存。`);
      return;
    }
    const payload = toStrategyPayload(form);
    const saved = toStrategyView(await api.createStrategy(payload));
    setStrategies((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
    setImportOpen(false);
    notify("策略已保存", `${saved.name} 已加入策略管理，可用于新建回测。`);
  };

  const validateStrategy = async (code) => {
    if (!apiOnline) throw new Error("后端未连接，无法执行策略校验。");
    return api.validateStrategy(code);
  };

  const aiFillStrategy = async (prompt) => {
    if (!apiOnline) throw new Error("后端未连接，无法调用 AI 填充接口。");
    return api.aiFillStrategy(prompt);
  };

  const saveEventDefinition = async (form) => {
    if (!apiOnline) {
      notify("后端未连接", "无法保存事件定义，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    if (editingEventDefinition?.id) {
      const payload = {
        name: form.name,
        description: form.desc,
        source: form.source,
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        code: form.code,
      };
      const saved = toEventDefinitionView(await api.updateEventDefinition(editingEventDefinition.id, payload));
      setEventDefinitions((items) => items.map((item) => item.id === saved.id ? saved : item));
      setEventImportOpen(false);
      setEditingEventDefinition(null);
      notify("事件定义已更新", `${saved.name} 的事件代码已保存。`);
      return;
    }
    const saved = toEventDefinitionView(await api.createEventDefinition(toEventDefinitionPayload(form)));
    setEventDefinitions((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
    setEventImportOpen(false);
    notify("事件定义已保存", `${saved.name} 已加入事件分析模块。`);
  };

  const validateEventDefinition = async (code) => {
    if (!apiOnline) throw new Error("后端未连接，无法执行事件代码校验。");
    return api.validateEventDefinition(code);
  };

  const aiFillEventDefinition = async (prompt) => {
    if (!apiOnline) throw new Error("后端未连接，无法调用 AI 填充接口。");
    return api.aiFillEventDefinition(prompt);
  };

  const deleteEventDefinition = async (definition) => {
    const confirmed = await confirm({ title: "删除事件定义", message: `确定删除事件定义"${definition.name}"吗？\n\n注意：删除后事件定义将被移除，但历史分析报告会保留。`, tone: "danger" });
    if (!confirmed) return;
    try {
      await api.deleteEventDefinition(definition.id);
      setEventDefinitions((items) => items.filter((item) => item.id !== definition.id));
      await refreshEventAnalyses();
      notify("事件定义已删除", `${definition.name} 的定义已移除，历史分析报告保留。`);
    } catch (error) {
      notify("删除事件定义失败", error.message);
    }
  };

  const openEditEventDefinition = (definition) => {
    setEditingEventDefinition({
      id: definition.id,
      name: definition.name,
      key: definition.key,
      source: definition.source,
      desc: definition.desc,
      tags: definition.tags.join(","),
      code: definition.code || "",
    });
    setEventImportOpen(true);
  };

  const createEventAnalysisTask = async (definition, form) => {
    if (!apiOnline) {
      notify("后端未连接", "无法创建事件分析任务，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    try {
      const task = await api.createEventAnalysis({
        event_definition_id: definition.id,
        start_date: form.start_date,
        end_date: form.end_date,
        windows: form.windows,
        entry_rule: form.entry_rule,
        dedup_rule: form.dedup_rule,
        universe: form.universe,
        filters: form.filters,
      });
      const row = toEventAnalysisView(task, eventDefinitionMap);
      setEventAnalyses((items) => [row, ...items.filter((item) => item.id !== row.id)]);
      setTasks((items) => [{ id: `event-task-${row.id}`, type: "event", eventAnalysisId: row.id, name: `${definition.name}事件分析`, status: row.status, stage: "等待后端调度", progress: row.progress }, ...items]);
      setRunEventDefinition(null);
      notify("事件分析任务已创建", `${definition.name} 已进入后端任务队列。`);
      return row;
    } catch (error) {
      notify("事件分析创建失败", error.message);
      throw error;
    }
  };

  const cancelEventAnalysis = async (analysis) => {
    try {
      const saved = await api.cancelEventAnalysis(analysis.id);
      const row = toEventAnalysisView(saved, eventDefinitionMap);
      setEventAnalyses((items) => items.map((item) => item.id === row.id ? row : item));
      setTasks((items) => items.filter((item) => item.eventAnalysisId !== row.id));
      notify("事件分析已终止", `${analysis.eventName} 的任务已标记为终止。`);
      await refreshEventAnalyses();
    } catch (error) {
      notify("终止事件分析失败", error.message);
    }
  };

  const deleteEventAnalysis = async (analysis, options = {}) => {
    const { skipConfirm = false, silent = false } = options;
    const confirmed = skipConfirm || await confirm({ title: "删除事件分析", message: `确定删除事件分析 #${analysis.id} 吗？关联结果文件也会一并删除。`, tone: "danger" });
    if (!confirmed) return false;
    try {
      await api.deleteEventAnalysis(analysis.id);
      setEventAnalyses((items) => items.filter((item) => item.id !== analysis.id));
      setTasks((items) => items.filter((item) => item.eventAnalysisId !== analysis.id));
      setSelectedEventAnalysisId((id) => id === analysis.id ? null : id);
      await refreshEventAnalyses();
      if (!silent) notify("事件分析结果已删除", `${analysis.eventName} 的分析记录已移除。`);
      return true;
    } catch (error) {
      if (!silent) notify("删除事件分析失败", error.message);
      throw error;
    }
  };

  const saveFactorDefinition = async (form) => {
    if (!apiOnline) {
      notify("后端未连接", "无法保存因子定义，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    if (editingFactorDefinition?.id) {
      const payload = {
        name: form.name,
        description: form.desc,
        source: form.source,
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        code: form.code,
      };
      const saved = toFactorDefinitionView(await api.updateFactorDefinition(editingFactorDefinition.id, payload));
      setFactorDefinitions((items) => items.map((item) => item.id === saved.id ? saved : item));
      setFactorImportOpen(false);
      setEditingFactorDefinition(null);
      notify("因子定义已更新", `${saved.name} 的因子代码已保存。`);
      return;
    }
    const saved = toFactorDefinitionView(await api.createFactorDefinition(toFactorDefinitionPayload(form)));
    setFactorDefinitions((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
    setFactorImportOpen(false);
    notify("因子定义已保存", `${saved.name} 已加入因子分析模块。`);
  };

  const validateFactorDefinition = async (code) => {
    if (!apiOnline) throw new Error("后端未连接，无法执行因子代码校验。");
    return api.validateFactorDefinition(code);
  };

  const aiFillFactorDefinition = async (prompt) => {
    if (!apiOnline) throw new Error("后端未连接，无法调用 AI 填充接口。");
    return api.aiFillFactorDefinition(prompt);
  };

  const deleteFactorDefinition = async (definition) => {
    const confirmed = await confirm({ title: "删除因子定义", message: `确定删除因子定义"${definition.name}"吗？\n\n注意：删除后因子定义将被移除，但历史分析报告会保留。`, tone: "danger" });
    if (!confirmed) return;
    try {
      await api.deleteFactorDefinition(definition.id);
      setFactorDefinitions((items) => items.filter((item) => item.id !== definition.id));
      await refreshFactorAnalyses();
      notify("因子定义已删除", `${definition.name} 的定义已移除，历史分析报告保留。`);
    } catch (error) {
      notify("删除因子定义失败", error.message);
    }
  };

  const openEditFactorDefinition = (definition) => {
    setEditingFactorDefinition({
      id: definition.id,
      name: definition.name,
      key: definition.key,
      source: definition.source,
      desc: definition.desc,
      tags: definition.tags.join(","),
      code: definition.code || "",
    });
    setFactorImportOpen(true);
  };

  const createFactorAnalysisTask = async (definition, form) => {
    if (!apiOnline) {
      notify("后端未连接", "无法创建因子分析任务，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    try {
      const task = await api.createFactorAnalysis({
        factor_definition_id: definition.id,
        ...form,
      });
      const row = toFactorAnalysisView(task, factorDefinitionMap);
      setFactorAnalyses((items) => [row, ...items.filter((item) => item.id !== row.id)]);
      setTasks((items) => [{ id: `factor-task-${row.id}`, type: "factor", factorAnalysisId: row.id, name: `${definition.name}因子分析`, status: row.status, stage: "等待后端调度", progress: row.progress }, ...items]);
      setRunFactorDefinition(null);
      notify("因子分析任务已创建", `${definition.name} 已进入后端任务队列。`);
      return row;
    } catch (error) {
      notify("因子分析创建失败", error.message);
      throw error;
    }
  };

  const cancelFactorAnalysis = async (analysis) => {
    try {
      const saved = await api.cancelFactorAnalysis(analysis.id);
      const row = toFactorAnalysisView(saved, factorDefinitionMap);
      setFactorAnalyses((items) => items.map((item) => item.id === row.id ? row : item));
      setTasks((items) => items.filter((item) => item.factorAnalysisId !== row.id));
      notify("因子分析已终止", `${analysis.factorName} 的任务已标记为终止。`);
      await refreshFactorAnalyses();
    } catch (error) {
      notify("终止因子分析失败", error.message);
    }
  };

  const deleteFactorAnalysis = async (analysis, options = {}) => {
    const { skipConfirm = false, silent = false } = options;
    const confirmed = skipConfirm || await confirm({ title: "删除因子分析", message: `确定删除因子分析 #${analysis.id} 吗？关联结果文件也会一并删除。`, tone: "danger" });
    if (!confirmed) return false;
    try {
      await api.deleteFactorAnalysis(analysis.id);
      setFactorAnalyses((items) => items.filter((item) => item.id !== analysis.id));
      setTasks((items) => items.filter((item) => item.factorAnalysisId !== analysis.id));
      setSelectedFactorAnalysisId((id) => id === analysis.id ? null : id);
      await refreshFactorAnalyses();
      if (!silent) notify("因子分析结果已删除", `${analysis.factorName} 的分析记录已移除。`);
      return true;
    } catch (error) {
      if (!silent) notify("删除因子分析失败", error.message);
      throw error;
    }
  };

  const runStrategy = async (strategy) => {
    setPreferredBacktestStrategyId(strategy.id);
    navigateTo("new_backtest");
    notify("已带入策略", `${strategy.name} 已带入新建回测，你可以继续调整日期和资金参数。`);
  };

  const openEditStrategy = (strategy) => {
    setEditingStrategy({
      id: strategy.id,
      name: strategy.name,
      key: strategy.key,
      source: strategy.source,
      desc: strategy.desc,
      tags: strategy.tags.join(","),
      code: strategy.code || "",
    });
    setImportOpen(true);
  };

  const saveSettings = async (payload) => {
    if (!apiOnline) {
      notify("后端未连接", "无法保存系统设置，请先启动后端服务。");
      throw new Error("后端未连接");
    }
    try {
      const saved = await api.updateSettings(payload);
      setRuntimeSettings(saved);
      setTheme(saved?.ui?.theme || "light");
      await refreshTemplates();
      notify("设置已保存", "默认回测参数和界面主题已更新。");
    } catch (error) {
      notify("保存设置失败", error.message);
      throw error;
    }
  };

  const batchDeleteStrategies = async (ids) => {
    const confirmed = await confirm({ title: "批量删除策略", message: `确定批量删除这 ${ids.length} 个策略吗？\n\n注意：策略定义会被移除，但历史回测报告会保留。`, tone: "danger" });
    if (!confirmed) return;
    try {
      const result = await api.batchDeleteStrategies(ids);
      if (result.deleted_ids?.length) {
        setStrategies((items) => items.filter((item) => !result.deleted_ids.includes(item.id)));
      }
      if (result.failed?.length) {
        notify("批量删除部分完成", `成功 ${result.deleted_ids.length} 个，失败 ${result.failed.length} 个。`);
      } else {
        notify("批量删除完成", `已删除 ${result.deleted_ids.length} 个策略。`);
      }
    } catch (error) {
      notify("批量删除失败", error.message);
    }
  };

  const batchDeleteEventDefinitions = async (ids) => {
    const confirmed = await confirm({ title: "批量删除事件定义", message: `确定批量删除这 ${ids.length} 个事件定义吗？\n\n注意：事件定义会被移除，但历史分析结果会保留。`, tone: "danger" });
    if (!confirmed) return;
    try {
      const result = await api.batchDeleteEventDefinitions(ids);
      if (result.deleted_ids?.length) {
        setEventDefinitions((items) => items.filter((item) => !result.deleted_ids.includes(item.id)));
      }
      if (result.failed?.length) {
        notify("批量删除部分完成", `成功 ${result.deleted_ids.length} 个，失败 ${result.failed.length} 个。`);
      } else {
        notify("批量删除完成", `已删除 ${result.deleted_ids.length} 个事件定义。`);
      }
    } catch (error) {
      notify("批量删除失败", error.message);
    }
  };

  const batchDeleteEventAnalyses = async (ids) => {
    const confirmed = await confirm({ title: "批量删除事件分析", message: `确定批量删除这 ${ids.length} 个事件分析结果吗？关联结果文件也会一并删除。`, tone: "danger" });
    if (!confirmed) return;
    let successCount = 0;
    let failedCount = 0;
    for (const analysisId of ids) {
      const item = eventAnalyses.find((row) => row.id === analysisId);
      if (!item) continue;
      try {
        // eslint-disable-next-line no-await-in-loop
        await deleteEventAnalysis(item, { skipConfirm: true, silent: true });
        successCount += 1;
      } catch {
        failedCount += 1;
      }
    }
    if (failedCount > 0) {
      notify("批量删除部分完成", `成功 ${successCount} 个，失败 ${failedCount} 个。`);
    } else {
      notify("批量删除完成", `已删除 ${successCount} 个事件分析结果。`);
    }
  };

  const allNavItems = [...navItems, ...bottomNavItems];
  const current = allNavItems.find((item) => item.id === activeTab);

  return (
    <div className={`app-shell ${theme === "dark" ? "theme-dark" : ""}`}>
      <Sidebar activeTab={activeTab} setActiveTab={navigateTo} topOverlay={topOverlay} setTopOverlay={setTopOverlay} />
      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb"><span>量化平台</span><ChevronRight size={14} /><strong>{current?.label}</strong></div>
          <div className="top-actions">
            <button title="任务中心" onClick={() => setTopOverlay(topOverlay === "task" ? null : "task")}><ListChecks size={19} />{tasks.some((task) => task.status === "running" || task.status === "queued") && <i className="count-dot" />}</button>
            <button title="通知" className="bell-button" onClick={() => setTopOverlay(topOverlay === "notice" ? null : "notice")}><Bell size={19} />{notifications.length > 0 && <i />}</button>
          </div>
        </header>
        <div className="content-scroll">
          <ErrorBoundary fallbackLabel={current?.label || "页面"}>
          {activeTab === "dashboard" && <DashboardView strategies={strategies} backtests={backtests} tasks={tasks} navigateTo={navigateTo} latestTradeDate={runtimeSettings?.data?.latest_trade_date} apiOnline={apiOnline} />}
          {activeTab === "new_backtest" && (
            <NewBacktestView
              strategies={strategies}
              createBacktest={createBacktest}
              navigateTo={navigateTo}
              defaultForm={backtestDefaults}
              dateBounds={dateBounds}
              templates={templates}
              saveTemplate={saveBacktestTemplate}
              deleteTemplate={deleteBacktestTemplate}
              preferredStrategyId={preferredBacktestStrategyId}
              openEdit={openEditStrategy}
            />
          )}
          {activeTab === "result" && <BacktestResultView backtests={backtests} selectedId={selectedBacktestId} openDetail={(id) => navigateTo("result", id)} backToList={() => navigateTo("result", null)} navigateTo={navigateTo} onCancel={cancelBacktest} onDelete={deleteBacktest} />}
          {activeTab === "strategies" && <StrategyManagerView strategies={strategies} openImport={() => { setEditingStrategy(null); setImportOpen(true); }} openEdit={openEditStrategy} runStrategy={runStrategy} onDelete={deleteStrategy} onBatchDelete={batchDeleteStrategies} navigateTo={navigateTo} displayMode={strategyDisplayMode} setDisplayMode={setStrategyDisplayMode} />}
          {activeTab === "event_analyses" && (
            <EventAnalysisManagerView
              definitions={eventDefinitions}
              openImport={() => { setEditingEventDefinition(null); setEventImportOpen(true); }}
              openEdit={openEditEventDefinition}
              runDefinition={(definition) => setRunEventDefinition(definition)}
              onDeleteDefinition={deleteEventDefinition}
              onBatchDeleteDefinitions={batchDeleteEventDefinitions}
              navigateTo={navigateTo}
              displayMode={eventAnalysisDisplayMode}
              setDisplayMode={setEventAnalysisDisplayMode}
            />
          )}
          {activeTab === "event_results" && (
            <EventAnalysisResultsView
              analyses={eventAnalyses}
              selectedId={selectedEventAnalysisId}
              openDetail={(id) => navigateTo("event_results", null, { eventAnalysisId: id })}
              backToList={() => navigateTo("event_results", null)}
              navigateTo={navigateTo}
              onCancel={cancelEventAnalysis}
              onDelete={deleteEventAnalysis}
            />
          )}
          {activeTab === "factor_analyses" && (
            <FactorAnalysisManagerView
              definitions={factorDefinitions}
              openImport={() => { setEditingFactorDefinition(null); setFactorImportOpen(true); }}
              openEdit={openEditFactorDefinition}
              runDefinition={(definition) => setRunFactorDefinition(definition)}
              onDeleteDefinition={deleteFactorDefinition}
              displayMode={factorAnalysisDisplayMode}
              setDisplayMode={setFactorAnalysisDisplayMode}
            />
          )}
          {activeTab === "factor_results" && (
            <FactorAnalysisResultsView
              analyses={factorAnalyses}
              selectedId={selectedFactorAnalysisId}
              openDetail={(id) => navigateTo("factor_results", null, { factorAnalysisId: id })}
              backToList={() => navigateTo("factor_results", null)}
              navigateTo={navigateTo}
              onCancel={cancelFactorAnalysis}
              onDelete={deleteFactorAnalysis}
            />
          )}
          {activeTab === "reports" && <ReportCenterView navigateTo={navigateTo} notify={notify} confirm={confirm} />}
          {activeTab === "data" && <DataManagementView notify={notify} runtimeSettings={runtimeSettings} apiOnline={apiOnline} />}
          {activeTab === "settings" && <SettingsView runtimeSettings={runtimeSettings} theme={theme} setTheme={setTheme} saveSettings={saveSettings} focusSection={settingsFocus} />}
          </ErrorBoundary>
        </div>
      </main>
      {importOpen && <StrategyImportModal initialData={editingStrategy} isEditing={Boolean(editingStrategy)} onClose={() => { setImportOpen(false); setEditingStrategy(null); }} onSave={saveStrategy} onAiFill={aiFillStrategy} onValidate={validateStrategy} />}
      {eventImportOpen && <EventDefinitionModal initialData={editingEventDefinition} isEditing={Boolean(editingEventDefinition)} onClose={() => { setEventImportOpen(false); setEditingEventDefinition(null); }} onSave={saveEventDefinition} onAiFill={aiFillEventDefinition} onValidate={validateEventDefinition} />}
      {runEventDefinition && <EventAnalysisRunModal definition={runEventDefinition} dateBounds={dateBounds} defaultDates={eventDefaultDates} onClose={() => setRunEventDefinition(null)} onRun={(form) => createEventAnalysisTask(runEventDefinition, form)} />}
      {factorImportOpen && <FactorDefinitionModal initialData={editingFactorDefinition} isEditing={Boolean(editingFactorDefinition)} onClose={() => { setFactorImportOpen(false); setEditingFactorDefinition(null); }} onSave={saveFactorDefinition} onAiFill={aiFillFactorDefinition} onValidate={validateFactorDefinition} />}
      {runFactorDefinition && <FactorAnalysisRunModal definition={runFactorDefinition} dateBounds={dateBounds} defaultDates={eventDefaultDates} onClose={() => setRunFactorDefinition(null)} onRun={(form) => createFactorAnalysisTask(runFactorDefinition, form)} />}
      {topOverlay === "task" && <TaskDrawer tasks={tasks} close={() => setTopOverlay(null)} openResult={(id) => { setTopOverlay(null); navigateTo("result", id); }} openEventResult={(id) => { setTopOverlay(null); navigateTo("event_results", null, { eventAnalysisId: id }); }} openFactorResult={(id) => { setTopOverlay(null); navigateTo("factor_results", null, { factorAnalysisId: id }); }} />}
      {topOverlay === "notice" && <NotificationPanel notifications={notifications} close={() => setTopOverlay(null)} openResult={(id) => { setTopOverlay(null); navigateTo("result", id); }} />}
      {topOverlay === "account" && <AccountMenu openSettingsSection={openSettingsSection} close={() => setTopOverlay(null)} />}
      <Toast toast={toast} onClose={() => setToast(null)} />
      {confirmDialog}
    </div>
  );
}
