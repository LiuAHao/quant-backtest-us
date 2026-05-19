"""
LightGBM 模型封装
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml_research.models.base import BaseModel


class LightGBMModel(BaseModel):
    def __init__(self, params: dict = None):
        default_params = {
            "objective": "regression",
            "metric": "mse",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "max_depth": 7,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "n_estimators": 500,
            "verbose": -1,
            "n_jobs": -1,
        }
        self.params = params or default_params
        self.model = lgb.LGBMRegressor(**self.params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LightGBMModel":
        self.model.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.model.booster_.save_model(str(path))

    def load(self, path: Path) -> "LightGBMModel":
        path = Path(path)
        booster = lgb.Booster(model_file=str(path))
        self.model.booster_ = booster
        return self

    def feature_importance(self) -> pd.DataFrame:
        booster = self.model.booster_
        names = booster.feature_name()
        importance = booster.feature_importance(importance_type="gain")
        df = pd.DataFrame({"feature": names, "importance": importance})
        return df.sort_values("importance", ascending=False).reset_index(drop=True)
