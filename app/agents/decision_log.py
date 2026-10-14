"""决策日志：每个决策写一行 JSON（JSONL），事后可以还原每个地标为何被讲解或跳过。"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union


class DecisionLog:
    def __init__(self, path: Optional[Union[str, Path]] = None):
        """path 为 None 时只在内存中保留记录（测试用）。"""
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")
        self.records = []
        self.t_sim: Optional[float] = None  # 当前模拟时间（秒），由调用方更新
        self._last_reason: Dict[Tuple[str, str], str] = {}

    def log(
        self,
        node: str,
        decision: str,
        reason: str,
        landmark_id: Optional[str] = None,
        landmark: Optional[str] = None,
        latency_ms: Optional[float] = None,
        **extra: Any,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "t_sim": self.t_sim,
            "node": node,
            "landmark_id": landmark_id,
            "landmark": landmark,
            "decision": decision,
            "reason": reason,
            "latency_ms": None if latency_ms is None else round(latency_ms, 1),
            **extra,
        }
        self.records.append(record)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if landmark_id:
            self._last_reason[(node, landmark_id)] = reason

    def log_on_change(self, node: str, decision: str, reason: str, landmark_id: str, **kwargs: Any) -> None:
        """同一节点对同一地标的 reason 没变时不重复写（避免每个 ping 都刷一遍 behind）。"""
        if self._last_reason.get((node, landmark_id)) == reason:
            return
        self.log(node, decision, reason, landmark_id=landmark_id, **kwargs)
