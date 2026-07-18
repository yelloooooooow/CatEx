# ADR-0001：确定性科学核心与可替换适配器

- 状态：Accepted for planning baseline
- 日期：2026-07-15

## 背景

平台需要覆盖文献复现、原创研究、实验解释、催化剂设计和批量筛选，同时支持周期性催化材料、VASP 和 Slurm。Paper 4 只是第一个真实验收案例。

## 决策

采用“自研确定性科学核心 + 可替换外部适配器”。

核心层负责：

- 结构和位点身份；
- 科学协议与兼容性签名；
- 计算规格、运行尝试和结果；
- provenance、诊断和人工审核；
- 催化反应、派生能量和科学验证规则。

外部适配器负责：

- Materials Studio 建模；
- VASP 文件 I/O；
- Slurm 执行；
- 未来的 quacc、jobflow、custodian、MLIP、数据库或 GUI 集成。

核心不能 import Slurm、SSH、Materials Studio、quacc、jobflow 或 Agent 特有对象。

## 工作流模型

平台提供可组合能力图，不维护两套“论文复现”和“原创研究”工作流：

```text
结构获取/构建
→ 标准化与 provenance
→ 位点定义
→ 吸附构型
→ 协议解析
→ 验证与人工审核
→ 输入物化
→ 执行与监控
→ 解析与科学有效性检查
→ 派生性质
→ 分析、审核和归档
```

批量筛选通过 `DesignSpace` 在共享节点上扇出，不另建软件核心。

## 关键模型

- `ResearchProject`
- `ArtifactRecord`
- `StructureRecord`
- `SiteDefinition` / `SiteIdentityMap`
- `CatalystSystem`
- `Adsorbate` / `AdsorptionConfiguration`
- `ReactionNetwork`
- `ScientificProtocol` / `ResolvedProtocol`
- `ExecutionProfile`
- `CalculationSpec` / `CalculationRun`
- `ResultRecord` / `DerivedProperty`
- `TransformationRecord`
- `ReviewRecord`
- `Diagnostic`

持久化科学真值是版本化的领域记录；pymatgen `Structure` 是主要周期结构运行时表示，ASE `Atoms` 是互操作表示。XSD、CIF 和 POSCAR 都是带角色的 artifact，不是唯一真值。

## 状态模型

执行、解析和科学有效性分别记录：

```text
execution: PLANNED → VALIDATED → APPROVED → SUBMITTED → RUNNING → FINISHED/FAILED
parsing:   UNPARSED → PARSED/PARTIAL/PARSE_FAILED
science:   NOT_EVALUATED → COMPLETED/NOT_CONVERGED/INVALID/NEEDS_REVIEW
```

进程结束不等于科学完成；失败任务也允许解析部分输出。

## 结果

优点：科学语义可控、严格复现透明、外部工具可替换。代价：必须先认真定义模型、schema 和适配器契约，短期开发速度低于直接采用通用工作流框架。
