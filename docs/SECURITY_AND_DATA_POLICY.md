# 数据、许可证与执行安全策略

## 仓库可见性

CatEx 的公开仓库只能包含通过发布审计的源码、文档、合成测试夹具和脱敏元数据。公开发布前必须复核许可证状态、数据来源、商标命名、第三方内容、当前文件树、完整 Git 历史和 CI 日志；任何真实凭据、个人连接信息或受限内容都会阻断发布。

仓库公开可见不自动授予开源许可。正式许可证尚未确定时，README 必须明确说明保留所有权利。

## 禁止提交

以下内容不得进入 Git 历史：

- SSH 私钥、VPN 配置、访问令牌、密码和 `.env`；
- POTCAR 原文及其拼接文件；
- WAVECAR、CHGCAR、AECCAR、OUTCAR、vasprun.xml 等大型运行产物；
- 未获再分发许可的论文、SI PDF、网页快照和第三方资料副本；
- 本地虚拟环境、工具缓存和 Materials Studio 安装文件；
- Materials Studio 自带脚本、DLL 或其他专有文件；
- 未脱敏的服务器凭证或许可证信息。

允许保存 POTCAR 的非内容元数据：元素顺序、`TITEL`、`ZVAL`、`ENMAX`、来源家族、版本和在受控主机上计算的 SHA256。

## 原始数据保护

- 外部结构登记为不可变 `ArtifactRecord`，保存文件哈希和来源。
- 所有结构变换创建新 artifact，不覆盖父文件。
- 目录命名不是不可变保证；必须使用哈希、权限和程序级拒绝覆盖共同保护。
- Git 中仅保存可以再分发或由本项目生成的小型输入、元数据和派生结果。

## MCP 安全

- MCP 只是传输和工具发现层，不承载科学真值。
- 不暴露任意 shell、PowerShell、Python、Perl 或 MaterialsScript 执行工具。
- 每个工具使用严格 JSON schema、允许路径根目录和输出新文件策略。
- 实际启动 Materials Studio 的工具初期全部要求人工确认。
- `readOnlyHint` 不能替代文件系统副作用审计；创建任务目录也属于写操作。
- 任务目录不是操作系统沙箱。
- 工具必须记录输入/输出哈希、脚本模板版本、runner/MS 版本、参数、返回码和日志。

## VASP 与 Slurm 安全

- 登录 shell 会读取站点和用户初始化文件，因此不是无条件默认值；execution
  profile 与 cluster policy 必须同时显式选择 `login`。
- 脚本生成器只允许固定的 `#!/bin/bash` 或 `#!/bin/bash -l`，不接受任意
  `source`、shell 参数或初始化命令。

- 本地生成 POTCAR 被禁止；只能在授权 HPC 环境中按 metadata 解析 POTCAR。
- 提交前必须经过结构、协议、POTCAR 顺序、资源请求和输出路径审核。
- 严格复现模式不允许自动修复科学参数。
- custodian 若后续接入，严格模式只允许监控、诊断和事先批准的安全续算。
- 取消作业、清理目录和删除大型文件必须由明确策略与人工授权触发。
- PR-005 的公共 CLI 只解析和规划；没有 `sbatch`、`scancel`、SSH 或远程写接口。
- 本地物化必须同时满足人工协议审核和显式写入批准，只能创建一个全新直接子目录。
- Slurm 脚本只允许固定 directive/body grammar，并拒绝 shell 控制符、重定向、提交和删除命令。
- 物化失败时保留部分目录供审计，不自动清理或递归删除。
- POTCAR metadata 提取默认拒绝读取，必须显式声明授权 HPC 边界；该确认是审计门而不是许可证替代品。
- 提取器只向 stdout 返回脱敏字段和哈希，不接受输出路径，不保留 POTCAR 表格，也不报告完整源路径。
- 真实 POTCAR 提取尚未获本项目远端执行授权；PR-006 只使用完全合成、非赝势夹具测试。
- PR-007 不调用 `squeue`、`sacct`、`sbatch`、`scancel`、`scontrol` 或 SSH；只解析调用者提供的最大 1 MiB 固定列快照。
- Slurm 快照报告不保留原始文本、完整路径或无关 job 行；续算评估永远不构成续算授权。
- 失败分类不得自动修改 INCAR、复制 checkpoint、创建目录、requeue 或提交；真实续算需要新的人工批准。
- 绝对 VASP executable 只允许规范的 POSIX 路径并与 cluster policy 精确匹配；真实站点路径可能包含身份信息，不提交 Git。
- 环境烟雾协议必须明确标记 non-production，关闭大型 checkpoint，并禁止其能量进入科研派生数据。
- PR-010 只读取既有提交回执、materialization manifest、实际 Slurm 脚本、调用者提供的 scheduler 快照和 VASP 输出；不连接 HPC，不运行调度命令，不写文件。
- 回执与绑定报告不保留完整本地/远端路径、原始 scheduler 文本或原始提交输出；SSH/VPN 凭证、真实站点路径和 POTCAR 内容不得进入回执、报告或 Git。
- 绑定成功只允许进入人工科学审核；永远不构成结果接受、续算、requeue、取消或新增提交授权。
- PR-011 的接受操作必须由受控调用方显式提供审核人、UTC 时间、决定和非空说明；当前库不认证审核人身份，也不把 SHA256 冒充数字签名。
- agent、批处理或无人值守工作流不得自动填写人工接受记录；未来服务层必须独立实现身份认证、角色授权与审计存储。
- 科学接受只允许结果成为同一 energy family 派生分析的候选，不得绕过参考态、热修正和能量兼容性检查。
- receipt 中 `scientific_result_eligible=false` 是不可由后续审核放宽的运行级门禁；环境烟雾和调试任务必须保持永久不可接受。
- PR-012 只允许人工接受、解析置信度为 high、且输出 artifact 仍与审核哈希一致的明确
  VASP 能量类型进入候选集合；跨 `energy_family_id`、TOTEN/energy without entropy/
  sigma→0 混合、重复 ID、记录篡改或非有限系数全部 fail closed。
- 通用线性组合没有参考态、温度、压力、ZPE、熵或 CHE 语义；在后续领域模型和人工审核
  完成前，不得将其标记为吸附能、形成能、反应能或自由能。
- PR-013 不接受仅凭 canonical structure hash 的原子 index 映射；site 和 configuration
  必须绑定 order-sensitive hash，防止原子重排后 index 静默指向另一元素或位置。
- catalyst、site、adsorbate 和 configuration 审核相互独立；缺失、拒绝、重复、冲突或
  subject hash 不匹配均阻断 calculation planning。当前 hash 不认证审核人真实身份。
- adsorption configuration v1 仅支持一个明确吸附物，不得用未登记原子夹带共吸附物、
  显式溶剂或电解质；扩展这些体系必须使用后续显式 schema。
- PR-014 的 reaction/thermochemistry 层不读取计算目录、不连接 HPC、不写文件，也不接受
  任意命令或路径字段；它只组合已通过前序证据门禁的脱敏对象。
- adsorption/formation 必须显式、完整登记全部反应物参考态；元素、电荷、能量族、VASP
  energy kind、standard state、protocol 或审核任一不一致均 fail closed。
- agent 不得自动批准 reaction、reference state、state-energy binding、thermochemistry
  protocol 或 correction，也不得从论文缺失数据中默认为零构造 ZPE、熵或 solvation correction。
- CHE、电位、pH 与 uncertainty propagation 当前未实现；报告必须保留 false/null 状态，
  不得把显式 proton/electron 平衡误称为已经完成电化学自由能校正。
- PR-015 的全部 structure/configuration generation 仅返回内存对象；不得覆盖源结构、静默
  选择 slab termination、自动批准 transformation/configuration/protocol 或直接物化计算。
- slab 的 `bulk_equivalence` 不是 exact atom mapping；任何调用方不得把它升级为作者结构
  provenance。vacancy、dopant、substitution index 和 binding-anchor pair 必须由调用方明确提供。
- rigid placement 若几何不兼容或产生原子碰撞必须 fail closed，不能通过拉伸分子或移动基底
  自动“修复”。多自旋计划中的每个 protocol variant 仍需独立科学审核且未获提交权限。
- PR-016 的电子结构层不接受文件路径、不读取 DOSCAR/PROCAR/CHGCAR/ACF.dat、不执行 Bader、
  不连接 HPC；调用方必须提供脱敏数值数组、parser 名称和 source SHA256。原始大文件继续留在
  受控存储，不进入 Git。
- DOS/PDOS、磁矩或 charge partition 的数值摘要不得被 agent 自动升级为磁基态、形式氧化态、
  成键机理、活性或选择性结论；summary 只有完整性门禁，没有替代人工科研解释。
- PR-017 的 reaction-network approval 只允许 pathway planning，不是 VASP/Slurm 执行授权；
  scientific-case readiness 即使 ready 也固定 `execution_authorized=false`。
- CHE 不允许从论文常识静默补温度、pH、potential scale、pair count 或 missing thermochemistry。
  Paper 4 未给出的逐态 correction 必须保存为 null/blocked，不得以数值零伪装已有证据。
- production-readiness evidence 只保存可公开/可提交的小型 artifact SHA256；真实站点路径、job ID、
  原始输出、POTCAR 和凭证仍不得进入项目清单或 Git。

## 删除规则

禁止批量递归删除文件或目录。需要删除时只能针对一个明确文件路径；若需要批量清理，应停止并由用户手动处理。

## 发布前检查

每次 push 前至少执行：

1. `git status --short` 和 staged diff 审查；
2. 凭证模式扫描；
3. POTCAR/VASP 大文件扫描；
4. 单文件大小检查；
5. 第三方许可证和来源检查；
6. 测试与静态检查；
7. 确认仓库仍为预期可见性。
