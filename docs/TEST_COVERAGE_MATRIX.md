# Test Coverage Matrix

| 模块 | 已覆盖 | 缺口 | 推荐测试文件 | 优先级 |
| --- | --- | --- | --- | --- |
| Broker | 手续费、T+1、涨跌停、市值 | 极端订单生命周期 | `tests/test_broker.py` | P2 |
| DataLoader | 复权、缓存、截面、SQL 安全 | 更多真实字段组合 | `tests/test_data_loader*.py` | P1 |
| Strategy API | 创建、校验、版本、AI fill | 批量导入/禁用组合 | `tests/test_strategy_api.py` | P2 |
| Backtest API | 创建、分页、删除、取消、模板 | 运行中状态转换 | `tests/test_backtest_api.py` | P1 |
| Reports | JSON/HTML 下载、日志 escape | backtest/event/factor 统一视图边界 | `tests/test_report_api.py`, `tests/test_factor_report_api.py` | P1 |
| Event Analysis | 分页、批删 | 标准脚本离线模式 | `tests/test_event_analysis_api.py` | P2 |
| Factor Analysis | 指标、API、prompt、过滤器、报告 JSON | 更多真实因子场景 | `tests/test_factor_analysis*.py` | P0 |
| ML Research | features/labels/pipeline/splitter | 数据泄漏边界、训练 artifact | `tests/test_ml_*.py` | P2 |
| Frontend | build | 关键交互缺自动化 | 后续 Playwright | P3 |
