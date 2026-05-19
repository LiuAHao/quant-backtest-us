import React, { useEffect, useRef, useState } from "react";
import {
  HardDrive,
  LayoutDashboard,
  LineChart,
  Settings,
} from "lucide-react";

export function SettingsView({ runtimeSettings, theme, setTheme, saveSettings, focusSection }) {
  const [form, setForm] = useState({
    initialCapital: "1000000",
    commissionRate: "0.0003",
    slippage: "0.001",
    theme: "light",
  });
  const overviewRef = useRef(null);
  const aiRef = useRef(null);
  const backtestRef = useRef(null);
  const appearanceRef = useRef(null);
  const sectionRefs = {
    overview: overviewRef,
    ai: aiRef,
    backtest: backtestRef,
    appearance: appearanceRef,
  };

  useEffect(() => {
    const backtest = runtimeSettings?.backtest || {};
    const ui = runtimeSettings?.ui || {};
    setForm({
      initialCapital: String(backtest.initial_capital ?? 1000000),
      commissionRate: String(backtest.commission_rate ?? 0.0003),
      slippage: String(backtest.slippage ?? 0.001),
      theme: String(theme || ui.theme || "light"),
    });
  }, [runtimeSettings, theme]);

  const isDark = form.theme === "dark";

  useEffect(() => {
    if (!focusSection) return;
    const target = sectionRefs[focusSection]?.current;
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focusSection]);

  const handleSave = async () => {
    await saveSettings({
      backtest: {
        initial_capital: Number(String(form.initialCapital).replaceAll(",", "")),
        commission_rate: Number(form.commissionRate),
        slippage: Number(form.slippage),
      },
      ui: {
        theme: form.theme,
      },
    });
  };

  const jumpTo = (section) => {
    const target = sectionRefs[section]?.current;
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row">
        <div><h2>系统设置</h2><p>这里只保留当前系统真正会生效的设置项，避免出现"能填但没作用"的假配置。</p></div>
        <button className="primary-action" onClick={handleSave}>保存设置</button>
      </div>
      <section className="settings-nav">
        <button className="secondary-action" onClick={() => jumpTo("overview")}><HardDrive size={16} />工作区</button>
        <button className="secondary-action" onClick={() => jumpTo("ai")}><Settings size={16} />AI 配置</button>
        <button className="secondary-action" onClick={() => jumpTo("backtest")}><LineChart size={16} />默认回测</button>
        <button className="secondary-action" onClick={() => jumpTo("appearance")}><LayoutDashboard size={16} />界面主题</button>
      </section>
      <section className="settings-layout">
        <article className="panel" ref={overviewRef}>
          <div className="panel-title"><h3>工作区概览</h3></div>
          <div className="settings-list">
            <div className="setting-readonly">
              <span>本地工作模式</span>
              <strong>单机研究环境</strong>
              <small>策略、模板、回测结果都保存在当前项目目录。</small>
            </div>
            <div className="setting-readonly">
              <span>数据可用区间</span>
              <strong>{runtimeSettings?.data?.earliest_trade_date || "-"} 至 {runtimeSettings?.data?.latest_trade_date || "-"}</strong>
              <small>新建回测和系统默认模板都会以这个数据窗口为准。</small>
            </div>
          </div>
        </article>

        <article className="panel" ref={aiRef}>
          <div className="panel-title"><h3>AI 与 API 模型配置</h3></div>
          <div className="settings-list">
            <div className="setting-readonly">
              <span>服务提供方</span>
              <strong>{runtimeSettings?.ai?.provider || "openai-compatible"}</strong>
              <small>当前 AI 配置来自项目根目录 `.env` 和后端设置，不在前端直接改密钥。</small>
            </div>
            <div className="setting-readonly">
              <span>模型名称</span>
              <strong>{runtimeSettings?.ai?.model || "-"}</strong>
              <small>策略生成会直接调用这个模型。</small>
            </div>
            <div className="setting-readonly">
              <span>Base URL</span>
              <strong>{runtimeSettings?.ai?.base_url || "-"}</strong>
              <small>如果要切换服务源，应该修改 `.env`，避免前端保存敏感配置。</small>
            </div>
          </div>
        </article>

        <article className="panel" ref={backtestRef}>
          <div className="panel-title"><h3>默认回测参数</h3></div>
          <div className="settings-list">
            <label><span>默认初始资金</span><input value={form.initialCapital} onChange={(e) => setForm({ ...form, initialCapital: e.target.value })} /></label>
            <label><span>默认手续费率</span><input type="number" value={form.commissionRate} step="0.0001" onChange={(e) => setForm({ ...form, commissionRate: e.target.value })} /></label>
            <label><span>默认滑点</span><input type="number" value={form.slippage} step="0.001" onChange={(e) => setForm({ ...form, slippage: e.target.value })} /></label>
          </div>
        </article>

        <article className="panel" ref={appearanceRef}>
          <div className="panel-title"><h3>界面主题</h3></div>
          <div className="settings-list">
            <div className="theme-row">
              <div><strong>界面主题</strong><span>{isDark ? "当前为夜间模式" : "当前为白天模式"}</span></div>
              <button
                className="secondary-action"
                onClick={() => {
                  const nextTheme = isDark ? "light" : "dark";
                  setForm({ ...form, theme: nextTheme });
                  setTheme(nextTheme);
                }}
              >
                {isDark ? "切换白天模式" : "切换夜间模式"}
              </button>
            </div>
            <div className="setting-readonly">
              <span>说明</span>
              <strong>主题切换会同时影响背景、顶部导航和操作面板。</strong>
              <small>保存之后，刷新页面仍会维持当前主题。</small>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
