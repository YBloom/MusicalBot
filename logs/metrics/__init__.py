"""供 service 与 compat 层使用的轻量指标记录器。"""
from __future__ import annotations

import logging
from typing import Mapping, MutableMapping, Optional

log = logging.getLogger(__name__)

MetricLabels = Optional[Mapping[str, str]]


def emit(metric_name: str, value: float = 1.0, labels: MetricLabels = None) -> None:
    """输出一个数值型指标。

    当前实现只写结构化日志；待持久化链路就绪后，可以替换成数据库写入
    或 push-gateway 客户端，而无需修改调用端。
    """
    payload: MutableMapping[str, object] = {"metric": metric_name, "value": value}
    if labels:
        payload["labels"] = dict(labels)
    log.info("METRIC %s", payload)


__all__ = ["emit", "MetricLabels"]
