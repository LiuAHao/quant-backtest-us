# 后端服务模块

`backend/` 是量化回测控制面板对应的本地 API 服务，面向当前前端的策略导入、AI 自动填充、策略校验、策略保存、异步回测和报告读取流程。

## 技术栈

- FastAPI：本地 HTTP API 服务
- SQLite：保存策略、策略版本、回测任务和系统设置
- DuckDB / Parquet：沿用现有 `backtest.DataLoader` 读取本地行情数据
- 后台线程池：本地异步执行回测任务

## 目录结构

```text
backend/
├── main.py                  # FastAPI 应用入口
├── api/                     # API 路由
├── db/                      # SQLite 初始化和连接管理
├── services/                # 策略、回测、报告、设置等业务服务
├── schemas.py               # Pydantic 请求/响应模型
└── storage/                 # 本地运行数据，默认不提交 Git
    ├── quant_backtest.db
    └── strategies/          # 策略文件（模板、手动编写、AI生成）
```

## 启动方式

在项目根目录安装依赖：

```bash
pip install -r requirements.txt
```

启动本地 API：

```bash
uvicorn backend.main:app --reload \
  --reload-exclude 'backend/storage/strategies/*' \
  --reload-exclude 'backend/storage/event_analyses/generated/*' \
  --host 127.0.0.1 --port 8000
```

健康检查：

```text
http://127.0.0.1:8000/api/health
```

## 核心接口

策略管理：

```text
GET  /api/strategies
POST /api/strategies
POST /api/strategies/validate
POST /api/strategies/ai-fill
PUT  /api/strategies/{strategy_id}
POST /api/strategies/{strategy_id}/enable
POST /api/strategies/{strategy_id}/disable
```

回测任务：

```text
GET  /api/backtest-templates
POST /api/backtest-templates
DELETE /api/backtest-templates/{template_id}
GET  /api/backtests
POST /api/backtests
GET  /api/backtests/{task_id}
```

报告：

```text
GET /api/reports
GET /api/reports/{task_id}
```

系统设置：

```text
GET /api/settings
PUT /api/settings
```

## 策略代码约定

前端提交的 Python 策略代码需要继承 `backtest.strategy.StrategyTemplate`：

```python
from backtest.strategy import StrategyTemplate


class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("我的策略")

    def init(self, context):
        pass

    def next(self, context):
        pass
```

后端保存策略时会做基础校验：

- Python 语法校验
- 必须存在继承 `StrategyTemplate` 的策略类
- 必须实现 `init(context)` 和 `next(context)`
- 禁止明显危险的导入和调用，例如 `os`、`subprocess`、`eval`、`exec`、`open`

## 当前边界

这是本地系统的第一版后端框架，重点是把前端流程和后端持久化、异步回测链路打通。后续可以继续增强：

- SSE 或 WebSocket 推送任务进度
- 真实 AI 模型接口调用
- 更严格的策略沙箱
- 策略编辑历史对比
- 批量回测和参数扫描
