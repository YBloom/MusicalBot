# 核心模型字段速览

本文档梳理了 `services/db/models` 中目前生效的核心 SQLModel 定义，方便比对与 legacy 导入脚本一致性。所有模型字段均与重排 mixin 之前保持一致，本次仅调整了继承顺序以兼容 Python 3.11。

## User
- `user_id`：主键，最多 32 字符。
- `nickname`：可选，最多 128 字符。
- `active`：是否仍在使用。
- `transactions_success`、`trust_score`：整型计数，均建立索引。
- `extra_json`：补充信息，存储在 JSON 列中。

## Group / Membership
- `Group.group_id`、`name`、`group_type`、`active`、`extra_json` 等字段维持不变。
- `Membership` 中的 `user_id`、`group_id` 外键及 `role`、`joined_at`、`receive_broadcast` 与以往一致。

## Subscription
- `Subscription`：`user_id` 外键 + `targets` / `options` 关系。
- `SubscriptionTarget`：`kind`、`target_id`、`name`、`city_filter`、`flags`，并保留联合唯一约束 `uq_subscription_target`。
- `SubscriptionOption`：`mute`、`freq`、`allow_broadcast`、`last_notified_at`、`subscription_id` 唯一约束，均与旧逻辑一致。

## Play / PlayAlias / PlaySourceLink / PlaySnapshot
- `Play`：`name`、`name_norm`、`default_city_norm`、`note` 等字段无变动。
- `PlayAlias`：`alias`、`alias_norm`、`source`、`weight`、`no_response_count`、`last_used_at`，以及唯一约束 `uq_play_alias_norm` 未调整。
- `PlaySourceLink`：`source`、`source_id`、`title_at_source`、`city_hint`、`confidence`、`last_sync_at`、`payload_hash` 同旧版，仍保持唯一约束 `uq_source_link`。
- `PlaySnapshot`：`city_norm`、`payload`、`last_success_at`、`ttl_seconds`、`stale` 保持不变。

## HLQEvent / HLQTicket
- 事件、票务字段（`title`、`title_norm`、`location`、`start_time`、`update_time`、`status`、`price`、`payload` 等）沿用原定义，未引入新列。

## Observability（Metric / ErrorLog / SendQueue）
- 三张表依旧仅包含监控指标、错误上下文、发送队列相关字段，字段名与语义均与旧版本一致。

> 综上：新版模型的字段集合、数据类型、索引/唯一约束与旧版完全一致，只有 mixin 继承顺序的技术性调整，迁移/导入脚本可无缝复用。
