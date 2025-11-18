# 当前进度诊断（v0.5 基线）

> 依据 `PRD v0.5` 的目标，对代码库的现状进行横向比对，方便后续排期。

## 0. 重构进度表

| 模块 | 状态 | 最新进展 | 下一步 |
| --- | --- | --- | --- |
| 数据模型 & 连接 | ✅ 基础结构已补齐 | `services/db/models/` 覆盖 User/Group/Subscription/Play/PlayAlias/PlaySourceLink/PlaySnapshot/HLQEvent/HLQTicket/Metric/ErrorLog/SendQueue，`base.py` 统一 `utcnow`/枚举/软删，`connection.py` 默认 WAL + `check_same_thread=False`，`init_db` 一次性建表。 | 为 service 层提供统一的数据访问封装，补齐 `updated_at` 自动更新钩子以及必要索引。 |
| JSON → SQLite 迁移 | ⚠️ 初版导入脚本可用 | `scripts/import_v0_json.py` 支持导入用户/群组/订阅/别名/跨源映射，提供 `--dry-run` 便于验收，但暂未覆盖 HLQ 快照、票务与指标。 | 扩展到 HLQ/快照/日志，加入校验/回滚策略与导入报告。 |
| Service / Compat | ⚠️ 仅有观测脚手架 | 新增 `services/compat/utils.py` 与 `logs/metrics/`，可为 Compat 方法输出结构化日志与指标，但插件仍直接依赖 JSON DataManager。 | 拆分 `services/user|subscription|alias|play` 并提供 Compat 代理，让主插件优先切换读取路径。 |
| 呼啦圈链路 | ❌ 未落地 | 仍停留在 DataManager 的同步命令，尚无轮询器/事件/快照管理。 | 构建轮询任务、事件总线与快照管理器，并落地 `PlaySnapshot`/`HLQ*` 的读写流程。 |
| 稳定性与运维 | ⚠️ 零散组件 | `services/system` 仅含网络探测/降级 helper，NapCat 自愈、维护模式、分级日志/告警尚未实现。 | 补齐 NapCat 健康检查、自愈脚本、`logs/*.log` 目录与 `scripts/verify_logs.py`。 |
| 测试与验收 | ❌ 未搭建 | `tests/` 仍只有爬虫 demo，缺少 CRUD/导入/HLQ 流程测试与压测脚本。 | 引入 pytest + 最低限度的数据层/导入单测及轮询压测脚本，纳入 CI。 |

## 1. 数据与模型层

- SQLModel 结构现已覆盖 PRD v0.5 所需的主要实体：`services/db/models/` 下新增 Play、Alias、SourceLink、Snapshot、HLQEvent/HLQTicket 以及 Metrics/ErrorLog/SendQueue，统一使用 `utcnow()` 与 mixin 管理 `created_at/updated_at`、软删标记等字段。
- `services/db/connection.py` 改为以 SQLModel `create_engine` 提供单例 engine/session，默认配置 `journal_mode=WAL`、`synchronous=NORMAL` 与 `check_same_thread=False`，满足 2C2G 服务器的并发与可靠性要求。
- `scripts/import_v0_json.py` 可以把 `UsersManager.json` 与 `alias.json` 中的用户、群组、订阅、别名及 Legacy PlaySourceLink 导入 SQLite，支持 `--dry-run` 供预检查；但旧体系中的 HLQ 数据、统计指标与错误日志仍未迁移，需要在下一阶段补齐。

## 2. 服务层与兼容层

- `services/` 目录依旧只有 `crawler/`、`db/`、`system/`，尚无 `user/`、`subscription/`、`alias/`、`play/` 等 Service 模块，`plugins/Hulaquan/data_managers.py` 仍然直接暴露 JSON DataManager 单例。
- 新增 `services/compat/utils.py` 提供 `@compat_entrypoint` 装饰器，自动采集 request_id/user_id/group_id 与延迟，基于 `.env` 中的 `LEGACY_COMPAT`、`MAINTENANCE_MODE` 以及 `COMPAT_DISABLED_PATHS` 进行灰度开关管控，并通过 `logs/metrics` 记录 compat vs. native 调用计数，为后续切换提供可观测性。
- `plugins/Hulaquan/main.py`、`plugins/AdminPlugin/main.py` 等入口仍手动实例化 `UsersManager`/`HulaquanDataManager`，插件业务尚未解耦 IO 或引入新的服务接口。

## 3. 呼啦圈轮询 / 事件 / 快照链路

- 呼啦圈仍依赖 `StatsDataManager`/`HulaquanDataManager` 在命令执行时同步访问网络，既没有独立轮询器也没有事件机制或快照表写入，无法利用新建的 `HLQEvent`、`HLQTicket`、`PlaySnapshot`。
- `services/crawler/` 的连接池、熔断、健康探测尚未与 HLQ 业务链路整合，仍缺乏“轮询 → 变更写库 → 事件 → 快照”闭环。

## 4. 稳定性与可观测性

- 除 `services/system/network_health.py`、`error_protection.py`、`degradation.py` 外，没有 NapCat 健康检查、自愈脚本、维护模式开关，也没有 PRD 要求的 `logs/{framework,network,db,plugin,health_check}.log` 目录。
- `Metric`/`ErrorLog`/`SendQueue` 虽已存在表结构，但尚无写入管道或监控脚本，`scripts/verify_logs.py` 也未实现。`logs/metrics` 目前仅以结构化日志记录指标，后续仍需接入持久化或推送链路。

## 5. 测试与验收

- `tests/` 依旧只包含 `tests/crawler` demo，未覆盖 CRUD、别名解析、HLQ 轮询链路或导入脚本；缺少 pytest/CI 配置，无法验证 PRD 所需的回归集。

## 6. 汇总结论

| PRD 模块 | 当前状态 | 下一步 |
| --- | --- | --- |
| 数据模型 | ✅ SQLModel 全量建表 + WAL/UTC 统一策略；`import_v0_json.py` 已能迁移用户/别名核心数据。 | 扩展迁移脚本并输出 service 访问封装，保障插件可读写新表。 |
| 服务层 & compat | ❌ 未落地。 | 创建 service/compat 包，将插件从 JSON 管理器迁移至 service API。 |
| 呼啦圈链路 | ❌ 未落地。 | 落地轮询 → 事件 → 快照全链路，并接入新建的 HLQ/PlaySnapshot 表。 |
| 稳定性/运维 | ⚠️ 零散组件。 | 实现 NapCat 健康检查、自愈、维护模式、分级日志与 `scripts/verify_logs.py`。 |
| 测试 | ❌ 未搭建。 | 引入 CRUD/导入/HLQ 流程单元测试与压测脚本，纳入 CI。 |

> 结论：数据库与迁移脚手架已就绪，但 service/compat、HLQ 事件链路、稳定性、测试体系仍待实现。下一阶段应聚焦“把插件流量切到 service 层”与“打通 HLQ 轮询链路”，随后在此基础上补齐可观测性与测试脚本。
