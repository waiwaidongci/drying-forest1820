# 槐序干燥时长试算台

RandomForest回归、训练内特征子集交叉验证与留出集MAE。为槐序研究协作组的12位分析与业务人员提供从样本核对、独立worker计算到批准快照交付的完整工作流。

## 真实业务场景

物料初始湿度/厚度/温度→干燥时长估计→工艺试验备忘；解释用留出置换重要性，禁止用留出集选参。团队原先将 `drying-forest-202611-01.csv` 复制到多份人工表格，复核时再逐项对照。三个痛点是口径不可追溯、重复计算易错、业务说明与结果脱节。上游提供合成业务观察，系统承担研究和复核，下游业务人员读取批准快照。全部演示数据是固定随机种子生成的模拟数据。

## 业务模块

1. 业务总览：批次、样本、母料归并组、失效研究与批准交付账册。
2. 干燥研究：创建/修改来源说明、查看样本、用真实业务字段追加记录；列表分页。
3. 母料关系：补认/撤销来源间的同母料关系（间接关联自动同组），发布完整关系版本，呈现连通分量、版本历史与失效处理状态。
4. 分析配置：按关系版本冻结多来源、参数和全部样本（逐行带母料组），进入Redis队列。
5. 完整结果：真实组隔离算法摘要、专属诊断、全部CSV导出和可恢复失败态；失效研究保留数值但标注失效原因。
6. 工艺试验备忘：分析师草案→负责人批准→阅读者下载批准快照；关联研究失效时备忘同步失效。
7. 审计：登录、来源修改、关系补认/撤销、任务worker完成、研究失效、业务说明批准等事件。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可重复执行，不覆盖人工修改
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18248)；[API文档](http://localhost:19248/docs)。数据库仅演示用途映射 `17748`。首次准备依赖和初始化数据库需要等待健康状态：`docker compose ps`，五个服务均需healthy。

| 组件 | 技术与职责 |
|---|---|
| frontend | 原生 HTML / CSS / JS ES Modules，Nginx代理 `/api/` |
| backend | Python3.11 / FastAPI / SQLAlchemy / JWT |
| worker | 独立Python进程，Redis BLPOP队列，持久化结果/CSV/心跳 |
| db | PostgreSQL16，命名卷持久化 |
| redis | Redis7，AOF命名卷 |

恰好五服务，均配置healthcheck；后端/worker依赖数据库与Redis健康，前端依赖后端健康；worker与后端共享 `artifacts` 命名卷。重置演示环境：`docker compose down -v --remove-orphans`，会删除本项目卷。

## 账号与权限

所有演示账号密码：`Research2026!`。

| 邮箱 | 角色 | 权限 |
|---|---|---|
| admin@drying-forest.demo | admin | 全部录入/执行、批准业务说明 |
| analyst@drying-forest.demo | analyst | 录入来源/样本、执行、提交说明，无批准权 |
| viewer@drying-forest.demo | viewer | 只读、导出结果及已批准快照 |

时间在数据库/API中以UTC存储，总览与审计页面明确转换为Asia/Shanghai北京时间。

JWT有效期8小时；PBKDF2盐化哈希保存密码；角色每请求从数据库读取。访客写操作403，匿名访问业务数据401，重复样本409，非法业务字段422，重复批准409。每客户端/路径写请求90次/分钟，超限429。生产使用需修改JWT及演示数据库凭据。

## 实体与字段

DryingStudy / DryingSample / RegressionRun / ProcessMemo 是核心实体；母料关系侧另有 MaterialRelation、RelationVersion、InvalidationJob，以及User和Audit。数据库实际表：`drying_studies` → `drying_samples` → `regression_runs` → `process_memos`；关系侧为 `material_relations`、`relation_versions`、`invalidation_jobs`。样本以固定字段JSON保存，后端按以下字段严格验证，不接受未知字段替代必填值：初始湿度 %（`moisture`）、厚度 mm（`thickness`）、设定温度 ℃（`temperature`）、风量 m³/min（`airflow`）、实测时长 min（`minutes`）。

实体贯穿 `backend/src/models`、`schemas`、`services`、`controllers`、`routes`，以及 `frontend/src/api/research.js`、`stores/research.js` 和 `pages`。`Source.key` 与 `(Record.source_id, reference)` 为自然键；来源改名不会修改已冻结任务输入。业务说明在创建时保存结果快照，批准后从该快照导出。

### 母料关系归并与组隔离

同一母料切出的试件可能散在多个来源，逐行随机会让近亲样本同时进入训练与留出，使误差偏乐观。系统用关系图解决：

- `material_relations` 记录来源两两关系（`active`/`revoked`），只追加、可撤销；撤销保留原行与说明用于追溯，撤销后可对同一对来源重新补认（复用原行）。
- 每次补认或撤销都在同一事务内用并查集重算**全量连通分量**：直接或间接关联的来源归为同一母料组，写入 `relation_versions` 完整版本（含分量、来源→组映射、当时全部关系），旧版本置为非激活，**只发布完整版本，不存在半成品版本**。
- 研究创建时钉住当前 `relation_version`，快照逐行写入 `group`；联合研究可一次选多个来源。PostgreSQL 用 `pg_advisory_xact_lock` 让关系发布与研究创建串行，杜绝“钉旧版本提交却未被失效扫描命中”的交错窗口（SQLite 退化为库级写锁）。
- 算法按母料组隔离：`GroupShuffleSplit` 保证同组试件全在训练或全在留出；训练内特征子集选择改用 `GroupKFold`，留出集仍只作最后一次评估。无任何已认关系时回退原行级随机拆分，保证旧口径可复现。
- 版本发布时在**同一事务**为受影响研究落 `invalidation_jobs`（仅来源组成员发生变化、钉在旧版本的研究；无关研究照常有效）。worker 逐条独立事务幂等消费，并每 15 秒兜底扫描，中断重启不漏不重；研究与备忘置 `is_valid=false` 并写 `invalid_reason`，数值、结果与 CSV 原样保留追溯。排队或计算期间到达的失效在结果落库前重读标志，**迟归计算不会恢复有效性**；失效研究不能再建备忘、批准或导出有效结果。

## 算法与口径

RandomForest回归、训练内特征子集交叉验证与留出集MAE，全部计算位于 `backend/src/services/algorithm.py`，前端不拟合模型、不生成模拟结果。输入是冻结业务观察及参数，输出summary、专属诊断、逐行计算明细、seed与输入SHA256。CSV包含全部结果行；页面仅预览前30行。参数：

- `trees`：森林树数，默认 `60`。
- `depth`：最大深度，默认 `6`。

先固定留出集，特征选择与交叉验证仅在训练行完成；留出集只作最后一次评估。存在母料关系时，留出拆分（`GroupShuffleSplit`）与训练内交叉验证（`GroupKFold`）均按母料连通分量隔离，同母料试件不跨训练/留出。置换重要性是模型依赖度，不是因果贡献。

失败态：业务字段缺失/非有限数值、参数越界、样本不足、退化特征或结构错误均明确拒绝或将任务标failed，错误消息保存在任务中。按组隔离时母料组不足4组、或拆分后训练/留出样本不足，也会明确失败并提示补充无亲缘来源。可回到来源或配置修正后重新执行，历史失败记录保留。

已知边界：只比较三个预定义特征子集，超参数由分析前固定；留出集不用于选择。置换重要性来自最后留出集，不可反复依据它改模再宣称独立验证。不含预测区间，不用于外推工艺。失效研究的数值仅作追溯，不能作为有效依据或再次提交备忘。

## 演示数据与一天剧本

固定seed=42，3个来源 ` HX-202611-01/02/03`，每来源240条，共720条业务记录；三个账号和首轮种子任务。自然键检查后仅插入缺失数据，连跑seed不重复、不覆盖用户修改。`SEED_DEMO=true` 时启动自动执行；失败记录日志但不阻塞服务。首轮任务同样由独立worker真实计算。种子还会补两条母料关系（来源1↔2、2↔3），使三个来源经间接关联同组并发布 v1/v2，首轮钉在 v0 的种子研究随之失效、关联失效任务由 worker 兜底处理，便于直接演示“处理中→已失效（含原因）→按新版本重建”的完整闭环。

1. 09:00 负责人查看三份来源和720条样本。
2. 09:10 分析师选择 `HX-202611-01 秋季常规组`，核对 `drying-forest-202611-01.csv`。
3. 09:15 在“干燥研究”核对初始湿度 %（`moisture`）、厚度 mm（`thickness`）、设定温度 ℃（`temperature`）、风量 m³/min（`airflow`）、实测时长 min（`minutes`），追加编号 `HX-NEW-001` 的样本。
4. 09:20 新建“十一月复核研究”，按默认参数冻结241条输入。
5. 09:21 独立worker消费Redis队列，返回实算结果与输入校验和。
6. 09:25 分析师查看专属诊断及逐行结果，并下载CSV复算。
7. 09:30 提交“十一月业务复核意见”，负责人核对并批准。
8. 09:40 viewer下载批准快照，查看审计中的worker完成与批准事件。

## 目录与本地开发

```text
frontend/src/api, stores, types, components/common, hooks, pages, router, utils, constants
backend/src/routes, controllers, services, models, schemas, middlewares, utils, constants, config
backend/scripts/seed_demo.py
backend/migrations/001_initial.sql
```

母料关系相关代码：后端 `models/{relation,relation_version,invalidation_job}.py`、`services/relations.py`（并查集、版本发布、咨询锁）、`services/invalidation.py`（outbox 幂等消费）、`routes/relations.py`；前端 `pages/relations.js`、`components/common/validity.js`。研究/备忘的有效性字段为 `is_valid`、`invalid_reason`，研究另含 `relation_version`、`source_ids`、`invalidated_version`。

本地后端：Python3.11虚拟环境安装 `backend/requirements.txt`，设置 `DATABASE_URL`、`REDIS_URL`、`ARTIFACT_DIR`，在backend目录运行 `uvicorn src.main:app --reload`；另开终端运行 `python -m src.worker`。原生前端无需编译，推荐以Compose Nginx访问，保证 `/api/` 代理。前端为Google Fonts双字体、oklch色板，离线字体回退serif；1280/768/390响应布局。

| 环境变量 | 默认与说明 |
|---|---|
| COMPOSE_PROJECT_NAME | `drying-forest`，隔离容器/网络/命名卷 |
| FRONTEND_PORT / BACKEND_PORT / DB_PORT | `18248 / 19248 / 17748` |
| SEED_DEMO | `true` |
| JWT_SECRET | `.env.example`演示值，部署前修改 |
| DATABASE_URL / REDIS_URL | Compose内部连接，定义在compose的env锚点 |
| ARTIFACT_DIR | `/artifacts`，后端worker共享 |

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 都定义 admin/analyst/viewer、queued/running/completed/failed、draft/approved。后端service检查对应字符串；README为全量值说明。共享前端组件table/status/chart/business跨总览、结果、配置与复核复用；actions hook和format utils负责交互/格式。后端errors与rate_limit是两个中间件。

测试及截图在批根 `test-artifacts/gb-0044/`，不混入源码。独立算法oracle、HTTP完整流程和真实Playwright浏览器流程见该目录 `TESTING.md`。License：MIT。
