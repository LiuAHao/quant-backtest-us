# Testing Guide

## 快速测试

```bash
./.venv/bin/python -m unittest tests.test_code_validator tests.test_factor_analysis tests.test_backend_api -v
```

## 数据层测试

```bash
./.venv/bin/python -m unittest \
  tests.test_data_loader \
  tests.test_data_loader_security \
  tests.test_data_validation \
  -v
```

## 引擎层测试

```bash
./.venv/bin/python -m unittest \
  tests.test_broker \
  tests.test_engine_metrics \
  tests.test_indicators \
  -v
```

## API 测试

```bash
./.venv/bin/python -m unittest \
  tests.test_strategy_api \
  tests.test_backtest_api \
  tests.test_report_api \
  tests.test_config_api \
  tests.test_event_analysis_api \
  tests.test_factor_analysis_platform \
  tests.test_factor_report_api \
  -v
```

## 因子测试

```bash
./.venv/bin/python -m unittest \
  tests.test_factor_analysis \
  tests.test_factor_analysis_platform \
  tests.test_factor_analysis_prompt \
  tests.test_factor_report_api \
  -v
```

## ML 测试

```bash
./.venv/bin/python -m unittest \
  tests.test_ml_features \
  tests.test_ml_labels \
  tests.test_ml_pipeline \
  tests.test_ml_splitter \
  -v
```

## 全量测试

```bash
./.venv/bin/python -m unittest discover -s tests -v
```
