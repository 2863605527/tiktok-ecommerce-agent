"""Agent 抽象基类。

企业级要点：
- 所有 Agent 统一实现 run(state) -> dict，可直接作为 LangGraph 节点
- 统一 name/description 元信息，便于编排、日志与监控
- 依赖通过构造器注入，测试时替换为 Mock
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Agent 抽象基类。"""

    name: str = "base"
    description: str = ""

    @abstractmethod
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 逻辑，返回对 state 的部分更新。"""

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点调用约定。"""
        return self.run(state)
