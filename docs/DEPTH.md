# 公交到站序列校验规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 定位候选 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 站序匹配 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 漏站复核 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M8 人工确认 | 补传/撤回确认到站并重算 | `GET/POST /api/runs/<id>/confirmations、DELETE /api/runs/<id>/confirmations/<cid>` | `app/review/service.py`、`app/modules/calculate.py`、`app/modules/prepare.py` | `tests/test_confirmations.py`、`tests/test_anchor_calculate.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

候选点需属于班次站序、置信度 1–100，时点不能超过班次截止。路径时间与站序都严格递增，优先覆盖已登记站点，再比较置信度总分，最后按记录键稳定选取。允许缺站，但覆盖低于调度清单要求需复核。

人工确认到站是路径必须命中的锚点。补传确认点后，在所有能按时间与站序覆盖全部锚点的路径里重算最优解（锚点与同站同时的定位点合并，不重复成站；锚点本身计入有效站次），自动定位凑出的长路径若漏掉确认点会被替代。确认点之间出现时间与站序矛盾、同站重复或同时点时，该业务组判 `CONFIRMATION_CONFLICT`，即使自动定位已达标也暂缓。撤回确认点后按剩余锚点重新核算。补传、撤回与签发共用同一乐观版本号，任一写操作生效即推进版本，旧版本号的并发写返回 409；撤回生效后旧复核单不能签发。

`sample_data/incoming.csv` 的 0003 组触发预检异常，0004 组触发业务判定。`tests/test_calculate.py` 还核对逐组结论和证据字段。
