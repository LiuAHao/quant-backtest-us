# 量化回测控制面板前端

这是项目的独立 React 前端模块，用于承载量化回测系统的可视化控制面板。

## 技术选型

- Vite：轻量开发服务器和构建工具
- React：组件化页面组织
- lucide-react：统一图标系统
- 纯 CSS 设计系统：便于长期维护和接入现有 Python 后端

## 本地运行

```bash
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

默认访问地址：

```text
http://127.0.0.1:5173/
```

## 构建

```bash
npm run build
```

构建产物会输出到 `frontend/dist/`。

## 后续接入建议

当前前端已经接入本地后端 API，默认请求地址为：

```text
http://127.0.0.1:8000/api
```

可通过 `frontend/.env.local` 覆盖：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

已接入的核心流程：

- 策略列表
- AI 策略草稿填充
- 策略代码校验
- 策略保存
- 回测任务创建
- 回测任务轮询
