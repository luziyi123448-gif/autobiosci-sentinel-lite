# ASReview SYNERGY 方法学基准

这是一个与 `autobiosci_sentinel` 主代码隔离的、回顾性方法学基准。它使用 ASReview LAB 3.0.8 对 SYNERGY 1.0 的 `Sep_2021` 全标注数据运行两次同配置 simulation，再从完整排序重建 95% recall 截止点。

## 一条命令复跑

从仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File experiments\synergy_benchmark\run.ps1
```

脚本在本目录创建隔离的 `.venv`，按 `requirements.lock.txt` 安装并核对完整环境，本地拉取并校验数据 SHA-256，然后运行两个相同种子重复。结果先写入临时分代目录，通过全部检查后再整体替换 `artifacts/`；失败时保留上一份有效结果，并把本次状态写入 `last_attempt.json`。原始 CSV、`.asreview` 归档与日志由本目录 `.gitignore` 排除；不会提交、推送或外部发布。

## 预先固定的方法

- 数据：`Sep_2021`，271 条记录，40 条 `label_included=1`，231 条 `0`；所有行必须有二元标签。
- 标签含义：`1` 是原系统综述在全文筛选后纳入，`0` 是排除。它们是源综述决策，不是不容置疑的“人工金标准”，更不是 AI 标签。
- 模型：ASReview `elas_u4`；CLI 输出会回读实际观察到的 classifier、querier、balancer 与 feature extractor。
- 随机性：`seed=535`、`prior_seed=535`；1 条 included prior、1 条 excluded prior；单条查询；不启用 similar-record grouping。
- 排序：`--n-stop -1` 生成完整 271 条排序。95% recall 截止点是累计找到至少 38/40 条 relevant 的最小排序前缀，prior 计入已筛记录。
- Precision：截止点前 relevant 数 / 已筛记录数；这是 screening yield，不是对未见样本的 classifier precision。
- Recall：截止点前 relevant 数 / 40。
- 漏检：截止点之后仍为 `label_included=1` 的记录，并写入 `artifacts/results/failure_cases.csv`。
- Work saved：未筛记录比例；`WSS@95 = work_saved_fraction - 0.05 = 0.95 - screened_fraction`。
- 一致性：比较去除时间戳后的完整有序 labeling sequence；不比较 `.asreview` ZIP 字节，因为项目 ID、时间戳和 ZIP 元数据会变化。

## 输出

- `artifacts/results/metrics.json`：主指标、运行时间、命令、种子、版本和限制。
- `artifacts/results/failure_cases.csv`：95% recall 截止点之后的 relevant 记录表，不含摘要。
- `artifacts/results/repeat_consistency.json`：两次规范化序列与截止点指标是否一致。
- `artifacts/results/source_manifest.json`：数据来源、许可、字段、行数、标签数、缺失文本计数和 SHA-256。
- `artifacts/results/environment.json`：Python、平台、线程设置和完整 `pip freeze --all`。
- `artifacts/results/checks.json`：合成指标自检、数据哈希、全量排序、固定预期序列、重复性和漏检表一致性检查。
- `last_attempt.json`：最近一次执行成功或失败的独立状态，不会与上一份有效结果混淆。
- `gptweb_transport_status.json`：GPTweb 传输合规状态；非 9223 结果不计为审计证据。

## 官方依据

- [SYNERGY 官方仓库](https://github.com/asreview/synergy-dataset)：CC0 1.0；`label_included=1` 表示源综述全文筛选后纳入，`0` 表示排除。
- [SYNERGY 数据记录](https://doi.org/10.34894/HE6NAQ)：数据集持久标识和引用信息。
- [ASReview simulation CLI 3.0.8](https://asreview.readthedocs.io/en/stable/lab/simulation_cli.html)：`simulate`、`--seed`、`--prior-seed`、`--n-stop` 和 `.asreview` 输出。
- [ASReview fully labeled data 3.0.8](https://asreview.readthedocs.io/en/stable/lab/data_labeled.html)：simulation 需要全标注数据，`0`/`1` 标签定义。
- [ASReview simulation overview 3.0.8](https://asreview.readthedocs.io/en/stable/lab/simulation_overview.html)：SYNERGY 是可用的全标注 benchmark 数据源。

## 方法限制

这是单一小数据集上的回顾性、探索性基准，不能证明跨主题、跨规模或前瞻性表现。95% cutoff 借助了完整标签，因此不是实际部署时可直接使用的停止规则。数据中有 1 条记录缺少摘要；结果受源综述决策、文本缺失、重复记录处理、软件版本、硬件和依赖环境影响。环境会核对精确包版本与完整已安装包集合，但未锁定 wheel 哈希。失败案例只表示它们排在预定义截止点之后，不表示模型作出了临床或生物学错误判断。本实验不产生任何临床或生物学结论，也不构成人工复核或发表就绪证明。
