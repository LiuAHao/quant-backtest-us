"""
模型基类：统一接口
"""
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd


class BaseModel(ABC):
    """所有 ML 模型的基类"""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseModel":
        """训练模型"""
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """预测，返回一维数组"""
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """保存模型到文件"""
        ...

    @abstractmethod
    def load(self, path: Path) -> "BaseModel":
        """从文件加载模型"""
        ...

    def feature_importance(self) -> pd.DataFrame:
        """
        返回特征重要性 DataFrame: [feature, importance]
        默认返回空，子类可覆盖
        """
        return pd.DataFrame(columns=["feature", "importance"])
