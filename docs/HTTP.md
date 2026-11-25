# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/confirmations` 列出批次已登记的人工确认到站。`POST /api/runs/<id>/confirmations` 接收 `revision`、`case`、`station`、`second` 补传一个确认点，随后整批按全部确认点重新核算并推进版本号。`DELETE /api/runs/<id>/confirmations/<确认点 id>` 携带 `revision` 撤回确认点，按剩余确认点重新核算。确认点站点须属于该业务组班次站序、时点不超过班次截止，否则返回 422；确认点之间时间与站序冲突时确认点仍落库，但该业务组判定为 `CONFIRMATION_CONFLICT`、整批暂缓。撤回与签发共用同一 `revision`：任一写操作生效都会推进版本号，携带旧版本号的并发写返回 409，已签发批次不可再补传或撤回。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据、人工确认点和复核信息的 JSON。
