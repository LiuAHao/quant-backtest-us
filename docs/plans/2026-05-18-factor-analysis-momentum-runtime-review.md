# 因子分析性能 Review：20 日动量因子耗时问题

日期：2026-05-18

## 背景

为了确认因子分析链路的实际性能，针对因子库中的“20日动量因子”执行了最近一个月区间的真实任务测试。

本次测试配置：

- 因子：`20日动量因子`
- 因子定义 key：`momentum_20_factor`
- 区间：`2026-04-14` 至 `2026-05-14`
- `rebalance_rule`: `daily`
- `windows`: `[1, 5, 10, 20]`
- `quantiles`: `5`
- `universe`: `all_a`
- `filters`: `[]`

## 实测结果

真实任务启动后，5 分钟内没有完成，状态仍为：

- `status = running`
- `progress = 25`

这说明：

- 任务创建链路正常
- 因子定义加载正常
- 主要耗时发生在 `FactorAnalysisEngine.run()` 主计算阶段，而不是任务提交或结果写盘阶段

## 核心结论

当前这版 20 日动量因子**可以明显优化**，并不是“已经无法再优化”的状态。

当前耗时偏高的主要原因，不是因子分析功能本身天然无法提速，而是因子定义实现使用了当前框架里最慢的一种写法：**逐股票调用 `get_history()`**。

## 主要瓶颈定位

### 1. 20 日动量因子当前实现是逐股历史查询

文件：`backend/storage/factor_analyses/generated/momentum_20_factor.py`

当前实现：

```python
class Momentum20Factor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("20日动量因子")

    def compute(self, context):
        rows = []
        current_date = context["current_date"]
        market_data = context["market_data"]
        for ts_code in market_data["ts_code"].astype(str).tolist():
            hist = context["get_history"](ts_code, current_date, window=21)
            if len(hist) < 21:
                continue
            value = hist["close"].iloc[-1] / hist["close"].iloc[0] - 1
            rows.append({"ts_code": ts_code, "trade_date": current_date.strftime("%Y-%m-%d"), "factor_value": value})
        return pd.DataFrame(rows)
```

问题在于：

- 每个分析日会遍历全市场股票
- 每只股票都会执行一次 `get_history()`
- 这是 Python 层循环 + 单股 SQL 查询的组合

### 2. 因子分析引擎会对每个分析日重复执行 `compute(context)`

文件：`factor_analysis/engine.py`

`FactorAnalysisEngine.run()` 的执行方式是：

1. 取分析区间内交易日
2. 按 `daily/weekly/monthly` 选出因子计算日期
3. **每个日期都执行一次 `compute(context)`**
4. 再计算 IC、RankIC、分组收益、多空收益、覆盖率等统计结果

因此，当前复杂度近似为：

- `分析日数量 × 股票数量 × 单次历史查询成本`

如果是最近一个月、日频、全市场，查询次数会很大。

### 3. `get_history()` 本身是单股票 SQL 访问接口

文件：`backtest/data_loader.py`

`get_history()` 的 SQL 路径本质是：

```sql
SELECT ...
FROM daily_bar
WHERE ts_code = ?
  AND trade_date <= ?
ORDER BY trade_date DESC
LIMIT ?
```

这意味着当前 20 日动量因子会触发：

- 每个分析日一轮全市场逐股查询
- 大量重复的历史窗口读取
- 无法有效利用 DuckDB 一次性批量扫描的优势

## 哪些地方还能优化

## 方案 1：把 20 日动量因子改成批量 SQL 版本

**优先级最高，收益最大。**

不要逐股 `get_history()`，而是针对当前日期一次性算出全市场所有股票的 20 日动量。

项目里其实已经有明确的最佳实践提示：

文件：`backend/services/ai_factor_analysis_prompt.py`

其中已经写明：

- 需要历史窗口时，优先用 DuckDB SQL 一次性扫描
- 不要逐股票循环查询全历史

该文件还给了接近可直接落地的示例：

```python
sql = f'''
    WITH recent AS (
        SELECT ts_code, trade_date, close,
               ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
        FROM daily_bar
        WHERE trade_date <= '{current_date}'
    ), pivoted AS (
        SELECT ts_code,
               MAX(CASE WHEN rn = 1 THEN close END) AS close_now,
               MAX(CASE WHEN rn = 21 THEN close END) AS close_then
        FROM recent
        WHERE rn <= 21
        GROUP BY ts_code
    )
    SELECT ts_code, '{current_date}' AS trade_date,
           close_now / NULLIF(close_then, 0) - 1 AS factor_value
    FROM pivoted
    WHERE close_now IS NOT NULL AND close_then IS NOT NULL
'''
```

### 预期收益

这通常会带来最明显的加速，因为它把：

- 大量逐股历史查询

变成：

- 每个分析日一次批量 SQL 扫描

在当前问题里，这很可能是**数量级级别**的优化。

## 方案 2：在因子分析前增加历史数据预热

文件：`backtest/data_loader.py`

当前 `DataLoader` 已经有：

- `warm_up_cache(ts_codes, start_date, end_date)`

如果短期内不改 20 日动量因子实现，至少可以在执行前：

- 先把目标股票池在目标时间范围内的数据批量加载进缓存
- 让后续 `get_history()` 尽量走缓存路径而不是 SQL 路径

### 预期收益

中等偏上，但不如方案 1。

原因：

- 它仍然保留逐股循环
- 只是把一部分 SQL 成本挪到预热阶段
- 对长期架构不是根治方案

## 方案 3：优化因子分析引擎自己的后处理逻辑

文件：`factor_analysis/engine.py`

在因子值生成之后，引擎还会继续做：

- future return 构造
- IC / RankIC
- 分组收益
- 多空收益
- coverage

这些流程仍有优化空间，尤其是：

- `_build_forward_returns()`
- 多轮 pandas groupby / apply

但相对本问题而言，这些是**次级瓶颈**。

即使优化这些部分，如果因子本身仍是逐股 `get_history()`，总体耗时还是会偏长。

## 方案 4：减轻截面查询负担

文件：`backtest/data_loader.py`

当前 `get_cross_section()` 在 `adjust is None` 时会 LEFT JOIN `daily_basic` 等字段。

对于简单动量因子，如果只需要：

- `ts_code`
- `trade_date`
- 或少量行情字段

那么这部分也有进一步收紧查询字段的空间。

### 预期收益

有帮助，但不是最核心的优化点。

## 是否存在“无法避免的慢”

有一部分是当前架构天然带来的，但**不是当前问题的主要原因**。

### 可以认为是架构层面的自然上限

因子定义接口当前是开放的：

- `compute(self, context)`

这意味着任何因子作者都可以写出：

- 逐股循环
- 逐日循环
- 每只股票单独查历史

所以从长期看：

- 当前系统**容易继续产生慢因子**
- 只要接口不强约束批量计算方式，这类问题仍可能反复出现

### 但当前 20 日动量的问题不是“天然不可优化”

这次的瓶颈主要来自：

- 因子实现方式不佳

而不是：

- 因子分析引擎从原理上无法提速

换句话说：

- **当前慢：主要是实现问题**
- **长期风险：部分是接口约束不足的问题**

## 推荐结论

按优先级排序，建议如下：

### 推荐 1

直接重写 `20日动量因子`，改为**单次 SQL 批量计算模式**。

这是最值得做的优化，且预期收益最大。

### 推荐 2

如果仍有性能压力，再考虑在因子分析任务启动前增加：

- 历史数据预热
- 更窄的数据窗口准备

### 推荐 3

最后再评估是否需要优化引擎后处理（future returns / metrics 统计）。

## 最终判断

**当前 20 日动量因子仍然有明确而且较大的优化空间，不应判定为“已经无法优化”。**

如果只允许做一件事，最优先应当是：

- **把逐股 `get_history()` 改成批量 SQL 计算**

这一步完成后，再重新实测最近一个月的运行时间，才有意义判断是否还需要继续做更深层的框架优化。
