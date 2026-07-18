# CatEx（Catalysis Exploration）：完整可执行计划

版本：Implementation Baseline 1.0

日期：2026-07-16

状态：PR-001 至 PR-024 已实现；本地 Web 与受控 HPC 初版闭环完成，Paper 4 真实生产验收仍受证据门禁阻塞

## 1. 产品目标

建设一套可扩展、可配置、可追踪、可测试、支持自动化并保留人工科学审核的周期性催化研究平台。

平台统一服务：

- 文献复现；
- 原创催化研究；
- 实验体系理论解释；
- 新催化剂设计；
- 催化机理研究；
- 批量筛选、MLIP 预筛、DFT 验证和主动学习。

`project_purpose` 只记录科研目的，不选择另一套软件核心。

## 2. 第一阶段边界

第一阶段支持周期性非均相催化、VASP 5.4.4 和 Slurm。暂不把以下内容作为一级目标：

- 泛函或赝势开发；
- 自动寻找“最佳 DFT 方法”；
- 均相量子化学全覆盖；
- 无人审核高通量计算；
- Agent 自动形成最终科研结论；
- 大型 GUI、Dashboard 或数据库。

## 3. 架构

```text
CLI / API / future GUI / Agent
              ↓
Workflow planning and review gates
              ↓
Catalysis domain
  catalyst / site / adsorbate / reaction / thermochemistry
              ↓
Scientific core
  structure / protocol / calculation / result / provenance
              ↓
Adapters
  VASP | Slurm | Materials Studio | MLIP | future engines
```

科学核心不调用远程服务器或商业 GUI。适配器不重新定义科学语义。

## 4. 科学协议与执行配置

严格分开：

### ScientificProtocol

- engine/version；
- functional；
- POTCAR family 和每元素 metadata；
- ENCUT、KPOINTS；
- dispersion、DFT+U、solvent；
- spin policy、charge；
- convergence 和数值设置；
- 2D 边界、偶极修正和对称性策略。

### ExecutionProfile

- scheduler、partition、account；
- nodes、cores、memory、walltime；
- modules 和启动命令；
- scratch、archive 和 retention。

改变 partition 或核数通常不改变科学协议；改变 POTCAR、泛函、溶剂、自旋约束或关键数值参数必须改变兼容性签名。

## 5. 数据与 provenance

每个可序列化对象包含 `schema_version`。结构同时保存：

- 来源文件 SHA256；
- 规范化结构 SHA256；
- 父结构和变换记录；
- 原子/位点映射；
- 单位、时间、软件版本和来源；
- 人工审核状态。

结果至少区分 TOTEN、`energy(sigma→0)`、校正能和自由能，不使用含糊的单一 `energy` 字段。

派生能量只能组合兼容的 `energy_family_id`，并显式记录参考态、温度、压力和热修正协议。

## 6. 人工审核门

以下步骤默认需要人工科学确认：

1. 外部结构 provenance；
2. 改变化学组成或拓扑的结构变换；
3. 活性位点和吸附构型；
4. resolved protocol；
5. POTCAR metadata 与元素顺序；
6. 第一次或大批量 Slurm 提交；
7. 会改变科学参数的错误恢复；
8. 结果是否科学有效；
9. 不同结果是否允许组成派生能量；
10. 最终机理和科研结论。

## 7. 实施阶段

### Phase 0：治理和可重复开发基线

交付物：

- 私有 GitHub 仓库；
- README、ADR、数据安全策略和本计划；
- `.gitignore` 与敏感数据扫描；
- Python 包名占位符和命名审计任务；
- 核心/适配器环境拆分方案；
- Git 分支、PR、测试和发布约定。

验收门：远端不含虚拟环境、密钥、POTCAR、论文 PDF 或大型输出。

### Phase 1：只读科学核心

目标：任何外部自动化前，先可靠地理解结构和 VASP 文件。

交付物：

1. 包骨架、版本化 schema、`Diagnostic`；
2. `StructureRecord`、`ArtifactRecord`、`TransformationRecord`；
3. `inspect-structure`；
4. `compare-structures` / round-trip validator；
5. VASP 5.4.4 输入验证；
6. VASP 输出降级解析：vasprun.xml → OUTCAR → OSZICAR；
7. JSON/text CLI 和合成测试夹具。

验收门：所有命令只读；截断输出不会崩溃；不把进程结束误判为科学收敛。

### Phase 2：Materials Studio 概念验证

交付物：

- 本机 capability inspector；
- 单独的 Windows/MCP 环境；
- 受限路径和固定脚本模板；
- CIF → XSD → CIF round-trip；
- 结构等价、局部配位、真空和 site mapping 报告；
- 人工 Visualizer 审核记录。

随后才测试确定性元素替换，并与 pymatgen 路线交叉验证。该阶段不运行 Forcite、CASTEP 或 VASP。

验收门：原始文件未覆盖；映射无歧义或歧义被明确上报；输出通过自动检查和人工审核。

### Phase 3：VASP 与 Slurm 安全执行

交付物：

- `ScientificProtocol` / `ResolvedProtocol`；
- VASP 5.4.4 规则注册表；
- HPC 侧 POTCAR metadata 解析；
- `CalculationSpec` 与只生成不提交的 materialization；
- Slurm 脚本生成和静态验证；
- 人工批准后的单个烟雾作业提交；
- 监控、部分结果解析和安全续算记录。

验收门：Paper 4 NiZn 烟雾输入通过；POTCAR 不离开 HPC；每次执行可追溯；无静默参数修改。

### Phase 4：通用催化建模

交付物：

- `CatalystSystem`、`SiteDefinition`；
- Adsorbate 和 adsorption configuration；
- slab、真空、缺陷、掺杂和元素替换；
- 单齿/双齿/桥位与构型去重；
- 多自旋计算计划；
- 参考态、吸附能、形成能和自由能模型；
- 电子结构分析接口。

验收门：至少一个非 Paper 4 的小型合成案例证明核心没有 DAC/CO2RR 硬编码。

当前增量：PR-013 已完成 catalyst/site/adsorbate/single-adsorbate configuration 身份；
PR-014 已完成平衡反应、显式参考态和 review-gated 热化学；PR-015 已完成 slab/vacuum/
vacancy/doping/substitution provenance、刚体吸附构型生成去重和 collinear 多自旋协议计划；
PR-016 已完成 source-bound 电子结构数值分析和完整非 Paper 4 端到端验收。Phase 4 的初版
交付已关闭；PR-017 已完成通用 reaction-network/CHE/production-readiness 集成，并把 Paper 4
真实生产验收无法继续的缺失证据固化为机器可检验 blocker。

### Phase 5：Paper 4 reference implementation

交付物：

- 第三方结构来源和不确定性记录；
- 金属组合设计空间；
- 多磁态和 VASPsol 协议；
- CO2RR 反应网络与吸附构型；
- SI Table S2 数字化数据作为参考而非自动真值；
- 端到端计算、派生能量、电子结构与筛选报告。

验收门：所有论文缺失信息和第三方结构差异被显式报告；不能把候选拓扑称为作者原始结构。

### Phase 6：批量筛选与 MLIP

交付物：

- `DesignSpace`、批次与去重；
- 配额感知的 Slurm 编排；
- CHGNet/Fair-Chem 等可替换 MLIP 适配器；
- DFT 校准、失效域检测和主动学习接口；
- 趋势、火山图和不确定性分析。

验收门：MLIP 结果不能与 VASP 能量族混淆；所有淘汰规则和随机种子可追溯。

### Phase 7：产品化

仅在科学核心稳定后考虑：

- jobflow/quacc/custodian 适配；
- 数据库和检索；
- GUI/Dashboard；
- 教学解释；
- Agent 辅助规划；
- 公开数据包和版本发布。

## 8. 首批 PR 顺序

### PR-001：结构检查与 round-trip 验证

- 包骨架；
- dataclass 领域模型；
- 诊断与哈希；
- 周期结构检查；
- 基于周期匹配的结构比较；
- Paper 4 NiZn 仅作为回归夹具；
- pytest 和 Ruff。

### PR-002：VASP 5.4.4 输入验证

- 原始文本级 INCAR 重复标签检查；
- MAGMOM 展开；
- KPOINTS 中心方式与二维规则；
- POTCAR metadata 契约；
- 严格/探索模式。

### PR-003：VASP 输出解析

- 正常、未收敛、截断和失败夹具；
- 能量、力、磁矩和终止状态；
- 解析来源与置信度。

### PR-004：Materials Studio capability 与 round-trip

- 无任意脚本工具；
- staging 路径限制；
- 固定 import/export 模板；
- 自动报告与人工审核门。

### PR-005：协议解析和 Slurm dry-run

- `ResolvedProtocol`；
- energy-family；
- 输入物化；
- Slurm 脚本验证；
- 不提交。

### PR-006：VASP 5.4.4 注册表与 HPC POTCAR metadata

- 显式、版本化的 CatEx 支持标签集合；
- strict 拒绝未注册标签，exploration 明确降级；
- energy-family 规则由注册表单一维护；
- 仅在授权 HPC 边界读取 POTCAR 的流式 metadata 提取；
- 只输出 TITEL、LEXCH、ZVAL、ENMAX 和 dataset SHA256；
- 不含 SSH、远端写、原始 POTCAR 保存或作业提交。

### PR-007 及以后：Phase 3 剩余执行闭环

- 纯解析 Slurm 状态快照、scheduler/VASP 证据交叉检查、失败分类和不可执行续算评估；
- 确认真实 VASP/VASPsol 可执行入口并建立站点 execution profile；
- 经单独人工批准，在指定非 home 目录物化真实 NiZn 烟雾输入和 POTCAR；
- 经单独人工批准提交一个 Slurm 烟雾作业；
- 只读监控、部分结果解析、失败分类和安全续算记录；
- 完成 Phase 3 验收后进入通用催化建模，而不是直接开始批量筛选。

### PR-008：真实 executable 适配与非生产环境烟雾

- 精确 allowlist 的绝对 POSIX VASP executable；
- 固定 pure-MPI 环境变量；
- 不上传真实站点路径的合成回归测试；
- NiZn 1×1×1、NELM=4、NSW=0 的 non-production VASPsol 环境烟雾协议；
- 禁止把烟雾能量进入科研数据集；
- 只在单一人工批准目录的新子目录测试，不覆盖或删除任何既有文件。

### PR-009：受策略约束的登录 shell

- execution profile 显式选择 `nonlogin` 或 `login`；
- cluster policy 独立 allowlist 可接受的 shell mode；
- 只生成固定 `#!/bin/bash` 或 `#!/bin/bash -l`；
- 不接受任意 `source`、shell 参数或初始化命令；
- 保留失败烟雾目录和证据，不覆盖或删除。

### PR-010：提交回执与运行证据绑定

- 严格、限长、路径脱敏的 submission receipt schema；
- 将 job ID、运行目录 basename、plan SHA256 和实际 `slurm.sh` SHA256 绑定；
- 使用回执 job ID 筛选调用者提供的固定列 Slurm 快照；
- 与 materialization manifest 和同目录 VASP 输出交叉验证；
- 绑定成功后只进入人工科学审核，不自动接受结果、续算或新增提交。

### PR-011：显式科学结果审核记录

- 从 manifest 暴露脱敏、类型化的 run protocol identity；
- 将接受/拒绝决定绑定到 job、plan、manifest、协议、energy family 和输出 artifact；
- 只有成功且科学完整的终态绑定可以接受；不完整终态只能拒绝；
- 活动作业和无效绑定不能生成科学审核记录；
- SHA256 只承担完整性/provenance，不冒充身份认证或数字签名；
- 接受仅授予同一能量族派生候选资格，不自动计算吸附能或自由能。

### PR-012：已审核能量与兼容性门禁

- 从显式接受记录和字节未变化的 VASP 输出建立 `ReviewedEnergyRecord`；
- 分别保存 TOTEN、energy without entropy 和 sigma→0，不使用含糊的 `energy`；
- 在任何线性组合前强制核对人工接受、高置信度、记录哈希和 `energy_family_id`；
- 拒绝跨能量族、跨能量类型、重复标识或被篡改的输入；
- 线性组合保持通用且无科学解释，不冒充吸附能、形成能或自由能；
- 不写文件、不执行命令、不连接 HPC、不新增提交。

### PR-013：通用催化科学身份

- 建立 `CatalystSystem`、`SiteDefinition`、`Adsorbate` 和
  `AdsorptionConfiguration`，不包含 DAC、CO2RR 或 Paper 4 常量；
- 将结构去重哈希与保留原子顺序的映射哈希分离；
- 位点 anchor 和吸附物 binding atom 均使用显式 0-based index；
- 单吸附物构型要求 substrate/adsorbate mapping 互斥、完整且元素顺序一致；
- catalyst/site/adsorbate/configuration 分别进行 hash-bound 人工审核；
- 缺失、重复、拒绝或冲突审核全部阻止进入 calculation planning。

### PR-014：反应、参考态与热化学门禁

- 建立 phase/composition/formal-charge/provenance 明确的 `ChemicalState`；
- signed stoichiometry 使用精确有理数，只有元素与电荷严格平衡时才生成 reaction identity；
- adsorption/formation 强制提供完整覆盖全部反应物的 reference-state set；
- 将每个 state 绑定到 PR-012 已审核能量，并要求 reaction/reference/state/binding 分别审核；
- 只在相同 `energy_family_id` 和相同 VASP energy kind 下派生电子反应能；
- 以明确 temperature、standard state、source hash、ZPE、enthalpy、entropy、solvation 和
  other component 派生自由能；
- 自由能绑定上游 electronic derivation、energy family、protocol、correction 和 review hash；
- 不自动应用 CHE、电位、pH 或 uncertainty propagation，不读写文件、不连接 HPC。

### PR-015：结构变换、吸附生成与多自旋规划

- slab 生成只返回按 hash 排序的 termination candidates，不自动选择科学模型；
- vacancy、doping、substitution 和正交 c 真空变换保留 exact parent→child atom lineage；
- slab 只声明 pymatgen bulk-equivalence lineage，不伪装 exact atom mapping；
- transformation product 必须通过 live-hash 核对和唯一人工批准才能登记 transformed catalyst；
- 吸附生成要求显式 binding-anchor pairs，以刚体算法对齐并拒绝不兼容几何或原子碰撞；
- 构型去重仅在相同 catalyst/site/adsorbate identity 中比较有序 PBC geometry；
- 多自旋计划要求上游构型四身份已审核，为每个 collinear state 生成独立协议变体；
- 所有候选、transformation、configuration 和 protocol 仍保留人工审核，不写文件、不提交。

### PR-016：电子结构分析与非 Paper 4 端到端验收

- DOS/PDOS、磁矩和 charge partition 均接收调用者解析的数组与 source SHA256；
- 严格校验能量网格、数组长度、有限性、非负 DOS、site mapping 和 d-band window coverage；
- 报告 DOS(Ef)、spin polarization、逐 d-series moment、磁矩合计和显式 charge deficit；
- 不自动指认磁基态、氧化态、成键、活性、选择性或机理；
- electronic summary 重新核对三个报告 content hash，并要求构型四身份审核通过；
- 合成 Pt/CO benchmark 串联 transformation、configuration、spin、reaction、thermo 和
  electronic analysis，证明通用核心没有 DAC/CO2RR/Paper 4 硬编码；
- 全流程不连接 HPC，不物化生产输入，不提交任务，测试数值不得作为科研数据。

### PR-017：反应网络、CHE 与 Paper 4 生产就绪门禁

- reaction network 只接收 intact balanced reactions，验证 state identity 一致性、connectedness
  和显式 start→terminal directed reachability；
- network 需要唯一人工审核，ready 只允许 pathway planning，固定不授权执行；
- CHE protocol 显式记录 SHE/RHE、U、pH、temperature、source hashes 并单独审核；
- CHE 使用 exact signed proton-electron pair count，分别报告 potential/pH correction 和符号约定；
- 缺失温度、base thermochemistry、协议审核或非有限值全部 fail closed；
- scientific-case requirement 的 satisfied 状态必须有 evidence SHA256，required item 不能 N/A；
- Paper 4 的 CO/HCOOH 网络、CHE、逐态热化学和生产 readiness 均有版本化草案/清单；
- 当前 3 项 requirement 有证据满足，10 项保持 blocked，因此不物化、不提交、不生成假结果。

### PR-018～PR-019：CatEx Web 与持久化项目

- React + FastAPI 本地工作台、节点工作流、周期结构查看和双击启动器；
- 项目、Artifact、工作流和审计日志持久化到本地受控目录；
- 内容寻址结构 Artifact 不覆盖，项目没有删除接口；
- 项目导出排除 POTCAR、WAVECAR、CHGCAR 和任何连接凭据。

### PR-020～PR-021：协议编辑、dry-run 与本地物化

- Web 编辑并严格解析 scientific protocol、POTCAR metadata、execution profile 与 cluster policy；
- 在写文件前展示 resolved protocol、energy family、INCAR、KPOINTS 和 Slurm 脚本；
- 人工审核绑定当前 resolved digest，配置变化后旧审核自然失效；
- 只有显式确认当前 plan digest 后，才在项目 runs 下新建输入目录；
- 本地物化不生成 POTCAR、不连接 HPC、不提交作业。

### PR-022～PR-023：受控 SSH、Slurm 提交与观测

- Paramiko 连接资料只存在于单次请求内存，不写项目、日志或导出包；
- 使用系统 known_hosts 或显式 SHA256 主机密钥指纹，拒绝自动信任未知主机；
- 远端写入限于白名单根目录的一个全新直接子目录，禁止覆盖和删除；
- POTCAR 只能由批准的远端脚本服务器端生成，永不上传到 Web 或下载到本地；
- `sbatch`、`squeue` 和 `sacct` 使用固定命令模板与严格字段；
- 远端准备、提交、观测和结果拉取分别需要独立门禁；没有 cancel、requeue 或清理接口。

### PR-024：结果绑定、能量账本与 Paper 4 验收入口

- 只下载白名单内的受限输出，排除 POTCAR、WAVECAR 和 CHGCAR；
- 下载快照与 submission receipt、manifest、Slurm 证据和实际 `slurm.sh` 重新绑定；
- 科学结果接受/拒绝由人工显式记录，接受后才生成 `ReviewedEnergyRecord`；
- Web 能量账本只允许同 energy family、同能量字段的线性组合；
- 吸附能、形成能、自由能、CHE 和网络解释继续复用 PR-014/017 核心门禁；
- Paper 4 可一键创建验收项目，但 10 个阻断项、缺失温度和空热化学数据保持原样，绝不自动授权执行。

## 9. 测试策略

测试金字塔：

- 纯函数单元测试；
- 合成 POSCAR/INCAR/KPOINTS/OUTCAR 夹具；
- 跨格式 round-trip 测试；
- Materials Studio 本机、显式批准的集成测试；
- HPC 只读探测与单作业烟雾测试；
- Paper 4 端到端验收。

测试不得依赖真实 POTCAR 内容或把大型 VASP 输出提交到 Git。真实输出应脱敏、裁剪为合成夹具或在外部 artifact 存储中引用哈希。

## 10. 存储与配额

HPC home 接近配额上限。建议：

- home 保存代码、配置、小型输入、元数据和必要日志；
- scratch/project storage 保存运行目录和大型输出；
- WAVECAR 只在续算窗口内保留；
- CHGCAR 仅在电荷/PDOS/Bader 等任务明确需要时保留；
- 删除前先确认下游消费、归档哈希和人工策略。

## 11. 关键风险

| 优先级 | 风险 |
|---|---|
| P0 | 原始论文结构、参考态或热修正定义缺失 |
| P0 | 不同 POTCAR/泛函/溶剂/自旋结果被错误混用 |
| P0 | 自动化静默修改科学协议 |
| P1 | VASP 5.4.4 与现代默认 recipe 不兼容 |
| P1 | MS 往返改变晶胞、原子顺序、位点或真空 |
| P1 | 多磁态未充分搜索 |
| P1 | HPC 配额被 WAVECAR/CHGCAR 耗尽 |
| P2 | Python 3.12/NumPy 与旧催化包不兼容 |
| P2 | 第三方代码许可证、CatEx 命名冲突 |
| P2 | MLIP 分布外预测被误当作 DFT 结论 |

## 12. 完成定义

平台第一阶段完成至少要求：

- 从来源结构建立可追踪 `StructureRecord`；
- 建立和审核活性位点/吸附构型；
- 解析版本化 VASP 协议；
- 在 HPC 安全物化输入并经批准提交；
- 解析失败、未收敛和成功结果；
- 阻止不兼容能量混用；
- 生成带证据和不确定性的派生性质；
- Paper 4 作为端到端验收，同时通过非 Paper 4 通用性测试；
- 所有科学关键节点保留人工审核记录。

## 13. 当前门禁

当前 GitHub 仓库地址仍可能保留历史 slug；产品、包、界面与文档统一使用：

```text
CatEx / Catalysis Exploration
```

PR-001 前的包名、dataclass-first、环境拆分和只读核心决策已经落实；Materials Studio 固定模板往返也已完成一次合成结构受控测试，但真实结构仍需逐个 Visualizer 审核。

非生产环境烟雾已经在单一授权目录的新子目录完成，且保留了失败与成功证据。进入生产科学计算前仍必须逐项完成：

1. 指定有足够配额、且适合生产输出的 project/scratch 工作根与保留策略；
2. 审核 Paper 4 NiZn 的生产 resolved protocol、POTCAR 顺序、资源和 energy family；
3. 对多磁态、3×3×1 网格、结构弛豫与 VASPsol 生产设置完成独立科学审核；
4. 使用独立提交回执和 PR-010 绑定报告关闭每个真实 run 的证据链；
5. 每次生产提交、续算、requeue、checkpoint 复用或清理仍需新的范围明确授权；
6. 不得把一次环境烟雾成功扩大为生产或批量提交权限。

PR-008/PR-009 已验证站点 executable、MPI、VASPsol 和登录 shell 链路；PR-010 关闭只读 run binding 缺口；PR-011 补充显式科学接受/拒绝记录；PR-012 阻止未接受、被改动或不兼容的电子能进入线性派生；PR-013/PR-014 将催化身份、平衡反应、参考态与热化学校正纳入独立人工审核链。PR-022/PR-023 现提供默认断开、凭据不落盘、分步审批的受控 SSH 和单作业 Slurm 提交/观测链；仍不提供取消、requeue、checkpoint 复制或远端清理接口。生产执行继续受本节门禁约束；Paper 4 缺失的逐中间体热化学数据也不会被自动补零。
