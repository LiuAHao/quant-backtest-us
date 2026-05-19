const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";

async function request(path, options = {}) {
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    ...options,
  });

  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        message = data.detail.map((item) => {
          const field = Array.isArray(item.loc) ? item.loc.join(".") : "field";
          return `${field}: ${item.msg}`;
        }).join("；");
      } else if (data.detail) {
        message = JSON.stringify(data.detail);
      }
    } catch {
      // 保持默认错误信息
    }
    throw new Error(message);
  }

  if (response.status === 204) return null;
  return response.json();
}

function sourceLabel(source) {
  const map = {
    manual: "手动导入",
    ai: "AI生成",
    builtin: "内置",
  };
  return map[source] || source || "手动导入";
}

function sourceValue(source) {
  const map = {
    手动导入: "manual",
    AI生成: "ai",
    内置: "builtin",
  };
  return map[source] || source || "manual";
}

function normalizeStrategyTags(tags, source) {
  const sourceTag = sourceLabel(source);
  const values = Array.isArray(tags) ? tags : [];
  const unique = new Set();
  values.forEach((tag) => {
    const text = String(tag || "").trim();
    if (!text || text === sourceTag || unique.has(text)) return;
    unique.add(text);
  });
  return [...unique];
}

export function toStrategyView(item) {
  return {
    id: item.id,
    key: item.key,
    name: item.name,
    source: sourceLabel(item.source),
    status: item.status,
    desc: item.description || "",
    tags: normalizeStrategyTags(item.tags, item.source),
    return: "待回测",
    latestBacktestReturn: "待回测",
    latestBacktestId: null,
    version: item.version,
    validationStatus: item.validation_status,
    validationMessage: item.validation_message,
    code: item.code,
  };
}

export function toStrategyPayload(form) {
  return {
    key: form.key,
    name: form.name,
    source: sourceValue(form.source),
    description: form.desc,
    tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
    code: form.code,
    status: "enabled",
  };
}

export function toEventDefinitionView(item) {
  return {
    id: item.id,
    key: item.key,
    name: item.name,
    source: sourceLabel(item.source),
    status: item.status,
    desc: item.description || "",
    tags: normalizeStrategyTags(item.tags, item.source),
    version: item.version,
    validationStatus: item.validation_status,
    validationMessage: item.validation_message,
    code: item.code,
    recentReturn: "待分析",
    latestAnalysisId: null,
  };
}

export function toEventDefinitionPayload(form) {
  return {
    key: form.key,
    name: form.name,
    source: sourceValue(form.source),
    description: form.desc,
    tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
    code: form.code,
    status: "enabled",
  };
}

export function toFactorDefinitionView(item) {
  return {
    id: item.id,
    key: item.key,
    name: item.name,
    source: sourceLabel(item.source),
    status: item.status,
    desc: item.description || "",
    tags: normalizeStrategyTags(item.tags, item.source),
    version: item.version,
    validationStatus: item.validation_status,
    validationMessage: item.validation_message,
    code: item.code,
    recentIc: "待分析",
    latestAnalysisId: null,
  };
}

export function toFactorDefinitionPayload(form) {
  return {
    key: form.key,
    name: form.name,
    source: sourceValue(form.source),
    description: form.desc,
    tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
    code: form.code,
    status: "enabled",
  };
}

function formatMetric(value, type) {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  if (type === "pct") return `${num >= 0 ? "+" : ""}${(num * 100).toFixed(2)}%`;
  return num.toFixed(2);
}

function formatCreatedAt(value) {
  if (!value) return "-";
  const str = String(value);
  if (str.includes("T")) {
    return str.replace("T", " ").slice(0, 19);
  }
  return str.slice(0, 19);
}

export function toBacktestView(task, strategyMap = new Map()) {
  const strategy = strategyMap.get(task.strategy_id);
  return {
    id: task.id,
    strategyId: task.strategy_id,
    strategy: strategy?.name || `策略 #${task.strategy_id}`,
    source: strategy?.source || "本地策略",
    period: `${task.start_date} 至 ${task.end_date}`,
    status: task.status,
    totalReturn: formatMetric(task.total_return, "pct"),
    drawdown: formatMetric(task.max_drawdown, "pct"),
    sharpe: formatMetric(task.sharpe_ratio, "number"),
    createdAt: formatCreatedAt(task.created_at),
    progress: task.progress,
    reportJsonPath: task.report_json_path,
    reportHtmlPath: task.report_html_path,
    runtimeLogs: task.runtime_logs || [],
    errorMessage: task.error_message,
  };
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  return `${num >= 0 ? "+" : ""}${(num * 100).toFixed(2)}%`;
}

export function toEventAnalysisView(task, definitionMap = new Map()) {
  const definition = definitionMap.get(task.event_definition_id);
  const windowSummary = Array.isArray(task.summary?.windows) ? task.summary.windows : [];
  const firstWindow = windowSummary[0];
  return {
    id: task.id,
    eventDefinitionId: task.event_definition_id,
    eventName: definition?.name || `事件 #${task.event_definition_id}`,
    source: definition?.source || "事件分析",
    period: `${task.start_date} 至 ${task.end_date}`,
    status: task.status,
    createdAt: formatCreatedAt(task.created_at),
    progress: task.progress,
    windows: task.windows || [],
    sampleCount: task.sample_count ?? task.summary?.sample_count ?? 0,
    avgReturn: firstWindow ? formatPct(firstWindow.avg_return) : "-",
    winRate: firstWindow ? formatPct(firstWindow.win_rate) : "-",
    entryRule: task.entry_rule,
    dedupRule: task.dedup_rule,
    universe: task.universe,
    filters: task.filters || [],
    summary: task.summary || null,
    resultJsonPath: task.result_json_path,
    runtimeLogs: task.runtime_logs || [],
    errorMessage: task.error_message,
  };
}

function firstWindowMetric(summary, group, field = "mean") {
  const block = summary?.[group];
  if (!block || typeof block !== "object") return null;
  const firstKey = Object.keys(block)[0];
  const value = firstKey ? block[firstKey]?.[field] : null;
  return value === undefined ? null : value;
}

export function toFactorAnalysisView(task, definitionMap = new Map()) {
  const definition = definitionMap.get(task.factor_definition_id);
  const firstIc = firstWindowMetric(task.summary, "ic");
  const firstRankIc = firstWindowMetric(task.summary, "rank_ic");
  const firstLongShort = firstWindowMetric(task.summary, "long_short");
  return {
    id: task.id,
    factorDefinitionId: task.factor_definition_id,
    factorName: definition?.name || `因子 #${task.factor_definition_id}`,
    source: definition?.source || "因子分析",
    period: `${task.start_date} 至 ${task.end_date}`,
    status: task.status,
    createdAt: formatCreatedAt(task.created_at),
    progress: task.progress,
    windows: task.windows || [],
    sampleCount: task.sample_count ?? task.summary?.sample_count ?? 0,
    icMean: formatMetric(firstIc, "number"),
    rankIcMean: formatMetric(firstRankIc, "number"),
    longShortMean: formatMetric(firstLongShort, "pct"),
    universe: task.universe,
    filters: task.filters || [],
    rebalanceRule: task.rebalance_rule,
    quantiles: task.quantiles,
    icMethod: task.ic_method,
    factorDirection: task.factor_direction,
    preprocessing: task.preprocessing || {},
    summary: task.summary || null,
    resultJsonPath: task.result_json_path,
    runtimeLogs: task.runtime_logs || [],
    errorMessage: task.error_message,
  };
}

function formatDate(value) {
  return value.toISOString().slice(0, 10);
}

function oneMonthAgo(value) {
  const date = new Date(value);
  date.setMonth(date.getMonth() - 1);
  return date;
}

const today = new Date();

export const defaultBacktestForm = {
  startDate: formatDate(oneMonthAgo(today)),
  endDate: formatDate(today),
  initialCapital: "1000000",
  commissionRate: "0.0003",
  slippage: "0.002",
  benchmark: "hs300",
};

export function buildBacktestForm(settings) {
  const backtest = settings?.backtest || {};
  const data = settings?.data || {};
  const latestTradeDate = data.latest_trade_date || defaultBacktestForm.endDate;
  const latestDate = new Date(latestTradeDate);
  const safeLatestDate = Number.isNaN(latestDate.getTime()) ? today : latestDate;

  return {
    startDate: formatDate(oneMonthAgo(safeLatestDate)),
    endDate: formatDate(safeLatestDate),
    initialCapital: String(backtest.initial_capital ?? defaultBacktestForm.initialCapital),
    commissionRate: String(backtest.commission_rate ?? defaultBacktestForm.commissionRate),
    slippage: String(backtest.slippage ?? defaultBacktestForm.slippage),
    benchmark: String(backtest.benchmark ?? defaultBacktestForm.benchmark),
  };
}

export function toBacktestTemplateForm(template) {
  return {
    name: template.name,
    startDate: template.start_date,
    endDate: template.end_date,
    initialCapital: String(template.initial_capital),
    commissionRate: String(template.commission_rate),
    slippage: String(template.slippage),
    benchmark: template.benchmark || defaultBacktestForm.benchmark,
  };
}

export const api = {
  health: () => request("/health"),
  getSettings: () => request("/settings"),
  updateSettings: (payload) => request("/settings", { method: "PUT", body: JSON.stringify(payload) }),
  listBacktestTemplates: () => request("/backtest-templates"),
  createBacktestTemplate: (payload) => request("/backtest-templates", { method: "POST", body: JSON.stringify(payload) }),
  deleteBacktestTemplate: (id) => request(`/backtest-templates/${id}`, { method: "DELETE" }),
  listStrategies: () => request("/strategies"),
  createStrategy: (payload) => request("/strategies", { method: "POST", body: JSON.stringify(payload) }),
  updateStrategy: (id, payload) => request(`/strategies/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteStrategy: (id) => request(`/strategies/${id}`, { method: "DELETE" }),
  batchDeleteStrategies: (ids) => request("/strategies/batch-delete", { method: "POST", body: JSON.stringify({ ids }) }),
  validateStrategy: (code) => request("/strategies/validate", { method: "POST", body: JSON.stringify({ code }) }),
  aiFillStrategy: (prompt) => request("/strategies/ai-fill", { method: "POST", body: JSON.stringify({ prompt }) }),
  listEventDefinitions: () => request("/event-definitions"),
  createEventDefinition: (payload) => request("/event-definitions", { method: "POST", body: JSON.stringify(payload) }),
  updateEventDefinition: (id, payload) => request(`/event-definitions/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteEventDefinition: (id) => request(`/event-definitions/${id}`, { method: "DELETE" }),
  batchDeleteEventDefinitions: (ids) => request("/event-definitions/batch-delete", { method: "POST", body: JSON.stringify({ ids }) }),
  validateEventDefinition: (code) => request("/event-definitions/validate", { method: "POST", body: JSON.stringify({ code }) }),
  aiFillEventDefinition: (prompt) => request("/event-definitions/ai-fill", { method: "POST", body: JSON.stringify({ prompt }) }),
  listEventAnalyses: () => request("/event-analyses"),
  createEventAnalysis: (payload) => request("/event-analyses", { method: "POST", body: JSON.stringify(payload) }),
  getEventAnalysisResult: (id) => request(`/event-analyses/${id}/result`),
  cancelEventAnalysis: (id) => request(`/event-analyses/${id}/cancel`, { method: "POST" }),
  deleteEventAnalysis: (id) => request(`/event-analyses/${id}`, { method: "DELETE" }),
  listFactorDefinitions: () => request("/factor-definitions"),
  createFactorDefinition: (payload) => request("/factor-definitions", { method: "POST", body: JSON.stringify(payload) }),
  updateFactorDefinition: (id, payload) => request(`/factor-definitions/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteFactorDefinition: (id) => request(`/factor-definitions/${id}`, { method: "DELETE" }),
  batchDeleteFactorDefinitions: (ids) => request("/factor-definitions/batch-delete", { method: "POST", body: JSON.stringify({ ids }) }),
  validateFactorDefinition: (code) => request("/factor-definitions/validate", { method: "POST", body: JSON.stringify({ code }) }),
  aiFillFactorDefinition: (prompt) => request("/factor-definitions/ai-fill", { method: "POST", body: JSON.stringify({ prompt }) }),
  listFactorAnalyses: () => request("/factor-analyses"),
  createFactorAnalysis: (payload) => request("/factor-analyses", { method: "POST", body: JSON.stringify(payload) }),
  getFactorAnalysisResult: (id) => request(`/factor-analyses/${id}/result`),
  cancelFactorAnalysis: (id) => request(`/factor-analyses/${id}/cancel`, { method: "POST" }),
  deleteFactorAnalysis: (id) => request(`/factor-analyses/${id}`, { method: "DELETE" }),
  listBacktests: () => request("/backtests"),
  createBacktest: (payload) => request("/backtests", { method: "POST", body: JSON.stringify(payload) }),
  cancelBacktest: (id) => request(`/backtests/${id}/cancel`, { method: "POST" }),
  deleteBacktest: (id) => request(`/backtests/${id}`, { method: "DELETE" }),
  listReports: (params = {}) => {
    const query = new URLSearchParams();
    if (params.type) query.set("type", params.type);
    if (params.keyword) query.set("keyword", params.keyword);
    if (params.start_date) query.set("start_date", params.start_date);
    if (params.end_date) query.set("end_date", params.end_date);
    if (params.status) query.set("status", params.status);
    if (params.page) query.set("page", String(params.page));
    if (params.page_size) query.set("page_size", String(params.page_size));
    const qs = query.toString();
    return request(`/reports${qs ? `?${qs}` : ""}`);
  },
  getReport: (taskId, kind = "backtest") => request(`/reports/${taskId}?kind=${encodeURIComponent(kind)}`),
  deleteReport: (taskId, kind = "backtest") => request(`/reports/${taskId}?kind=${encodeURIComponent(kind)}`, { method: "DELETE" }),
  reportDownloadUrl: (taskId, kind = "backtest", format = "html") => `${API_BASE}/reports/${taskId}/download?kind=${encodeURIComponent(kind)}&format=${encodeURIComponent(format)}`,
};
