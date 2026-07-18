# CatEx schema contracts

CatEx 的 JSON 输出在顶层声明 schema version。当前版本：

| Record | Schema |
|---|---|
| artifact provenance | `catex.artifact.v1` |
| periodic structure summary | `catex.structure.v1` |
| transformation provenance | `catex.transformation.v1` |
| structure inspection | `catex.inspection.v1` |
| periodic comparison | `catex.comparison.v1` |
| raw INCAR summary | `catex.incar.v1` |
| KPOINTS summary | `catex.kpoints.v1` |
| copyright-safe POTCAR metadata | `catex.potcar-metadata.v1` |
| VASP input validation report | `catex.vasp-input-validation.v1` |
| VASP output parse report | `catex.vasp-output-parse.v1` |
| Materials Studio capability | `catex.materials-studio-capability.v1` |
| Materials Studio round-trip plan | `catex.materials-studio-roundtrip-plan.v1` |
| Materials Studio execution | `catex.materials-studio-execution.v1` |
| Materials Studio round-trip audit | `catex.materials-studio-roundtrip.v1` |
| scientific protocol | `catex.scientific-protocol.v1` |
| protocol review | `catex.protocol-review.v1` |
| resolved protocol | `catex.resolved-protocol.v1` |
| protocol resolution report | `catex.protocol-resolution.v1` |
| Slurm execution profile | `catex.slurm-execution-profile.v1` |
| Slurm cluster policy | `catex.slurm-cluster-policy.v1` |
| Slurm script plan | `catex.slurm-script-plan.v1` |
| calculation plan | `catex.calculation-plan.v1` |
| materialization manifest | `catex.materialization-manifest.v1` |
| materialization result | `catex.materialization.v1` |
| CatEx-supported VASP 5.4.4 INCAR registry | `catex.vasp544-incar-registry.v1` |
| HPC POTCAR metadata extraction | `catex.hpc-potcar-metadata-extraction.v1` |
| Slurm job observation | `catex.slurm-job-observation.v1` |
| Slurm snapshot parse report | `catex.slurm-snapshot-parse.v1` |
| path-sanitized VASP restart evidence | `catex.vasp-restart-evidence.v1` |
| restart assessment | `catex.restart-assessment.v1` |
| submission receipt | `catex.submission-receipt.v1` |
| submission receipt parse report | `catex.submission-receipt-parse.v1` |
| run-evidence binding | `catex.run-binding.v1` |
| sanitized run protocol identity | `catex.run-protocol-identity.v1` |
| explicit scientific result review | `catex.scientific-result-review.v1` |
| reviewed VASP electronic energy | `catex.reviewed-energy.v1` |
| reviewed-energy compatibility report | `catex.energy-compatibility.v1` |
| generic linear energy derivation | `catex.linear-energy-derivation.v1` |
| periodic catalyst identity | `catex.catalyst-system.v1` |
| active-site identity | `catex.site-definition.v1` |
| molecular adsorbate identity | `catex.adsorbate.v1` |
| single-adsorbate configuration identity | `catex.adsorption-configuration.v1` |
| catalysis scientific identity review | `catex.scientific-identity-review.v1` |
| configuration planning readiness | `catex.configuration-readiness.v1` |
| chemical reaction state | `catex.chemical-state.v1` |
| explicit reference-state set | `catex.reference-state-set.v1` |
| balanced reaction definition | `catex.reaction-definition.v1` |
| reaction-definition validation report | `catex.reaction-definition-report.v1` |
| reviewed state-energy binding | `catex.state-energy-binding.v1` |
| reaction-domain scientific review | `catex.scientific-definition-review.v1` |
| reviewed electronic reaction energy | `catex.reaction-electronic-energy.v1` |
| thermochemistry protocol | `catex.thermochemistry-protocol.v1` |
| state thermochemical correction | `catex.thermochemical-correction.v1` |
| component-resolved reaction free energy | `catex.reaction-free-energy.v1` |
| structure transformation provenance | `catex.structure-transformation.v1` |
| runtime transformation product | `catex.transformation-product.v1` |
| transformation scientific review | `catex.transformation-review.v1` |
| transformation readiness gate | `catex.transformation-readiness.v1` |
| rigid adsorption generation provenance | `catex.adsorption-generation.v1` |
| generated adsorption configuration | `catex.generated-adsorption-configuration.v1` |
| configuration deduplication report | `catex.configuration-deduplication.v1` |
| collinear spin protocol variant | `catex.spin-protocol-variant.v1` |
| multi-spin calculation plan | `catex.multi-spin-calculation-plan.v1` |
| caller-parsed density of states | `catex.density-of-states-input.v1` |
| density-of-states numerical analysis | `catex.density-of-states-analysis.v1` |
| caller-parsed magnetic moments | `catex.magnetic-moment-input.v1` |
| magnetism numerical analysis | `catex.magnetism-analysis.v1` |
| caller-parsed charge partition | `catex.charge-partition-input.v1` |
| charge numerical analysis | `catex.charge-analysis.v1` |
| review-gated electronic-structure summary | `catex.electronic-structure-summary.v1` |
| connected balanced reaction network | `catex.reaction-network.v1` |
| reaction-network construction report | `catex.reaction-network-report.v1` |
| reaction-network scientific review | `catex.reaction-network-review.v1` |
| reaction-network planning readiness | `catex.reaction-network-readiness.v1` |
| CHE scientific protocol | `catex.computational-hydrogen-electrode-protocol.v1` |
| CHE-corrected free energy | `catex.computational-hydrogen-electrode-report.v1` |
| scientific-case requirement assessment | `catex.scientific-case-requirement.v1` |
| non-authorizing production readiness | `catex.scientific-case-readiness.v1` |

## Hash 与结构等价性的边界

`canonical_hash` 是确定性的内容指纹：

- 包含晶格、物种/占据率和 wrap 后的分数坐标；
- 不受 site 顺序影响；
- 对全局平移、不同等价晶胞或超胞不保证不变。

因此不能用 `canonical_hash` 代替科学结构匹配。`compare-structures` 使用显式容差和周期边界条件判断等价性，并分别报告匹配设置、诊断和归一化位移。

## 兼容规则

- 同一 major schema 内只允许增加可选字段；
- 删除字段、改变单位或改变语义必须升级 schema major；
- 所有长度单位在字段名中显式标注；
- 诊断使用稳定 code，显示消息可以改进但不能承担机器判断；
- provenance 的 artifact hash 基于原始字节，结构 hash 基于解析后的规范 payload。

## 只读保证

PR-001 的公共入口只读取输入并返回内存对象或 stdout。它们不会：

- 覆盖或规范化源结构；
- 生成 VASP 输入；
- 调用 Materials Studio；
- 连接、提交或取消 HPC 作业。

## VASP 输入 schema 边界

`catex.vasp-input-validation.v1` 面向 VASP 5.4.4，并区分：

- 原始语法和维度错误：在 strict/exploration 中始终为 error；
- 科学策略未决项：strict 为 error，exploration 可降为 warning；
- 运行时能力：例如 VASPsol 或 `vasp_ncl`，只能声明需要确认，不能由输入文件推断为可用。

`catex.potcar-metadata.v1` 只记录数据集顺序、TITEL、LEXCH、ZVAL、ENMAX 和 SHA256。CatEx 不把 POTCAR 内容、POTCAR 路径或赝势文件打包进报告。

## VASP 输出 schema 边界

`catex.vasp-output-parse.v1` 把三个概念分开：

- `termination.outcome`：`normal`、`unconverged`、`truncated`、`failed` 或 `unknown`；
- `convergence.electronic` 与 `convergence.ionic`：`converged`、`not_converged`、`not_applicable` 或 `unknown`；
- `scientifically_complete`：只有正常结束且适用的收敛状态都有明确正证据时才为 true。

能量、力和磁矩记录包含 `evidence` 和 `confidence`。evidence 指向报告中已哈希的 artifact、行号与稳定 parser rule。OUTCAR 的逐原子磁矩是 PAW 球内投影，OSZICAR 的 `mag` 是晶胞量；schema 不允许把两者合并成同一物理量。

## Materials Studio schema 边界

Materials Studio 四类记录保持规划、执行和科学审核分离：

- capability 只确认 runner/template artifact，不把文件存在等同于许可证可用；
- plan 固定 backend、operation、模板和两个目标输出名，不含任意脚本字段；
- execution 记录返回码、耗时和输出是否实际创建，不自动声明结构正确；
- round-trip audit 保存父子 artifact、周期等价性、source→exported 原子映射、TransformationRecord 和人工审核状态。

只有执行成功、结构等价、映射完整、没有 error 且 `manual_review_state=approved` 时，`ready_for_downstream` 才为 true。

## 协议、能量族和执行计划边界

`catex.resolved-protocol.v1` 保存规范化 INCAR/KPOINTS、POTCAR metadata、输入 artifact hash、`energy_family_id` 和独立的人工审核记录。

- `energy_family_id` 是科学能量兼容性签名，不包含 protocol 名称、Slurm 资源和执行布局；
- `resolved_protocol_sha256` 绑定完整协议文本、所有源 artifact hash 和能量族，因此执行型 INCAR 变化也可被审计；
- 人工审核不改变上述两个科学身份；
- `CalculationPlan` 和 `SlurmScriptPlan` 明确记录 `writes_performed=false`、`submitted=false`；
- materialization manifest 明确记录 `potcar_required_on_hpc=true`、`potcar_materialized=false`、`submitted=false`。

具体包含/排除规则和生成边界见 `PROTOCOL_AND_SLURM_DRY_RUN.md`。

## VASP 5.4.4 注册表与 HPC POTCAR 提取

`catex.vasp544-incar-registry.v1` 是 CatEx 已实现并测试的标签集合，不是 VASP 手册全部功能的镜像。每项声明 value kind、是否进入能量族，以及由 VASP 5.4.4 或 VASPsol 1.0 提供。未注册标签不得在 strict resolved protocol 中静默通过。

`catex.hpc-potcar-metadata-extraction.v1` 只保存源文件 basename、整体 SHA256、字节数、各 dataset 的安全字段/哈希、授权门状态和诊断。它明确声明 `raw_content_included=false`、`writes_performed=false`。成功报告中的 `metadata_document` 符合既有 `catex.potcar-metadata.v1`；任意 dataset 不完整时不输出部分 metadata。

## Slurm 观察与续算评估

`catex.slurm-snapshot-parse.v1` 解析调用者提供的固定列 `squeue`/`sacct` 文本，只保留请求的 allocation；其他行、原始文本和完整路径均不进入报告。`catex.slurm-job-observation.v1` 显式区分 active/terminal 状态，并把 `ExitCode` 的 status 与 signal 分开。

`catex.restart-assessment.v1` 组合 scheduler observation 与脱敏的 `catex.vasp-restart-evidence.v1`，输出 `wait`、`no_restart`、`manual_review_required` 或 `blocked`。该基础评估本身不接收 submission receipt，所以 `no_restart` 仍要求通过独立 run binding 并人工接受科学结果。该 schema 是审核记录，不是执行计划；所有实例都声明 `restart_authorized=false`、`writes_performed=false`、`commands_executed=false` 和 `submitted=false`。

`catex.submission-receipt.v1` 是一次单独获批提交留下的严格审计记录，绑定 job ID、目录 basename、job name、plan SHA256、实际 Slurm 脚本 SHA256、UTC 提交时间和原始提交输出 SHA256。`catex.submission-receipt-parse.v1` 不保留原始 JSON 或完整路径。

`catex.run-binding.v1` 将回执与 `catex.materialization-manifest.v1`、实际 `slurm.sh`、回执 job ID 对应的 scheduler observation，以及同目录 `catex.vasp-restart-evidence.v1` 交叉检查。即使状态为 `scientific_review_required`，仍固定声明 `scientific_result_accepted=false`、`additional_submission_performed=false`、`writes_performed=false` 和 `commands_executed=false`。

`catex.run-protocol-identity.v1` 从通过严格字段检查的 manifest 中保留 job、plan、POSCAR、resolved protocol、energy family、execution profile、cluster policy、Slurm script 和 POTCAR 边界身份，不包含完整路径或原始协议文本。

`catex.scientific-result-review.v1` 是显式接受/拒绝记录。接受要求 receipt 中 `scientific_result_eligible=true`、完整的终态 run binding、`sacct COMPLETED 0:0` 和科学完整 VASP 证据；`false` 的烟雾/调试运行永久不能被该审核升级，只能拒绝。拒绝也必须绑定到可识别的终态运行。记录包含 binding/review SHA256，但这些 hash 不是身份认证或数字签名。接受只授予同一 `energy_family_id` 内后续派生的候选资格，不代表任意能量已经可以相减。

`catex.reviewed-energy.v1` 从显式接受记录与重新解析的同一 VASP 输出建立。创建时再次
核对目录 basename、VASP outcome、全部解析 artifact 的 basename/SHA256、高置信度
evidence 和选定的明确能量类型。记录自身的 SHA256 覆盖数值、类型、能量族、审核身份、
artifact 与脱敏 evidence；审核后文件改动或记录字段改动都会使其失去兼容资格。

`catex.energy-compatibility.v1` 在任何线性组合前逐项检查人工接受、运行资格、记录完整性、
唯一 energy ID、相同 `energy_family_id` 和相同 VASP 能量类型。
`catex.linear-energy-derivation.v1` 只表示通过上述门禁的通用线性组合；它固定声明
`scientific_interpretation_approved=false`、`reference_state_reviewed=false` 和
`thermochemical_corrections_included=false`，因此不能被称为吸附能、形成能或自由能。

## 通用催化身份与映射边界

`catex.catalyst-system.v1` 同时保存 order-independent canonical structure SHA256 和
order-sensitive structure SHA256。前者用于内容 provenance 和去重，后者绑定所有基于
原子 index 的位点与构型映射；二者不能互相替代。

`catex.site-definition.v1` 保存 catalyst identity、ordered structure identity、位点类型、
0-based anchor index、anchor species、wrapped fractional coordinate 和 PBC-aware centroid。
`catex.adsorbate.v1` 保存有序元素列表、整数 charge、spin multiplicity、binding atom、
stereochemistry label 和基于有序距离矩阵的 geometry SHA256。

`catex.adsorption-configuration.v1` 当前明确只表示一个吸附物。substrate mapping 与
adsorbate mapping 必须互斥并覆盖 combined structure 的全部原子；映射后的 substrate
必须重现 catalyst ordered identity，adsorbate 元素顺序必须重现 adsorbate identity。
多吸附物、显式溶剂和共吸附将在后续 schema 中显式扩展，不在 v1 中静默表达。

`catex.scientific-identity-review.v1` 是绑定 subject kind/id/SHA256 的显式批准或拒绝记录。
`catex.configuration-readiness.v1` 要求 catalyst、site、adsorbate、configuration 各自恰有
一个完整且批准的审核；批准与拒绝并存也视为歧义并阻断。SHA256 仍不是身份认证或数字签名。

## 反应与热化学 schema 边界

`catex.chemical-state.v1` 将 phase、化学式、精确有理数组成、formal charge 与一个上游
科学身份绑定。`catex.reaction-definition.v1` 的 signed coefficient 同样使用精确有理数，
只有元素与电荷严格平衡、两侧非空且 state 唯一时才会生成。term 按 state ID 排序，调用者
输入顺序不属于反应科学身份。

adsorption/formation 必须绑定 `catex.reference-state-set.v1`，且该集合完整覆盖反应物。
`catex.state-energy-binding.v1` 将一个 state identity 绑定到一个完整的 PR-012 reviewed
energy；reaction、reference set、state、binding 分别通过
`catex.scientific-definition-review.v1` 审核后，才可生成
`catex.reaction-electronic-energy.v1`。跨 energy family 或 VASP energy kind 的组合被拒绝。

`catex.thermochemistry-protocol.v1` 显式保存温度、pressure/concentration standard、
low-frequency treatment 和 imaginary-mode policy。`catex.thermochemical-correction.v1`
逐 state 保存 standard state、source hashes、ZPE、thermal enthalpy、entropy、solvation、
other correction 和可选 uncertainty。`catex.reaction-free-energy.v1` 逐项报告
`ΔE + ΔZPE + ΔHthermal - TΔS + ΔGsolv + ΔGother`，并绑定电子能推导、能量族、协议、修正
和审核 identity。

v1 不应用 CHE、电位或 pH，也不传播 uncertainty；相应字段必须明确为 false/null，不能用
零值伪装“已计算”。这些 hash 是确定性完整性/provenance 指纹，不是数字签名。

## 结构生成与构型规划边界

`catex.structure-transformation.v1` 绑定输入/输出的 canonical 和 ordered structure hash、
operation、参数、atom lineage、removed/created index 与 mapping strength。vacancy、显式元素
替换和正交 c 真空变换可以声明 exact-index lineage；slab generation 只声明
`bulk_equivalence`，并固定 `exact_atom_mapping_complete=false`。

`catex.transformation-review.v1` 与 `catex.transformation-readiness.v1` 要求 live output hash
未变化且恰有一个人工批准，才可登记 transformed catalyst。`catex.transformation-product.v1`
只在运行时携带 `pymatgen.Structure`，JSON 固定 `live_structure_embedded=false`。

`catex.adsorption-generation.v1` 保存 binding-anchor pairs、height、rigid alignment mode/RMSD
和 clash threshold；它不批准生成的 `catex.adsorption-configuration.v1`。
`catex.configuration-deduplication.v1` 只在相同 catalyst/site/adsorbate identity 内比较有序
adsorbate PBC geometry。

`catex.spin-protocol-variant.v1` 为每个 collinear initial state 保存完整 MAGMOM、可选 NUPDOWN
和独立 scientific protocol。`catex.multi-spin-calculation-plan.v1` 要求上游构型四身份已审核，
但自身不写文件、不提交任务，所有 protocol variant 仍需人工审核。

## 电子结构分析 schema 边界

`catex.density-of-states-input.v1`、`catex.magnetic-moment-input.v1` 和
`catex.charge-partition-input.v1` 只接收调用者已经解析的、绑定 source SHA256 和 configuration
identity 的数值数据，不包含路径或文件读取能力。DOS energy grid 必须严格递增，所有数组
必须有限且同长，DOS 必须非负，spin-up/down 必须成对提供；d-band window 必须被网格完整覆盖。
三类报告的总 site 数必须与被审核 configuration 的完整原子映射一致。

`catex.density-of-states-analysis.v1` 逐显式 d-projected series 报告积分权重、相对 Fermi center
和 width；`catex.magnetism-analysis.v1` 只做有符号/绝对磁矩合计；
`catex.charge-analysis.v1` 使用 `reference population - partitioned population`，正号明确表示
该分区定义下的 electron loss。三者都不自动生成氧化态、磁序、成键或催化活性结论。

`catex.electronic-structure-summary.v1` 重新核对三个报告 content hash、configuration identity
与构型四身份审核。它固定保留 `manual_interpretation_required=true` 和
`automatic_scientific_conclusion_performed=false`。这些记录是完整性/provenance 指纹，不是
解析文件真实性、科研结论正确性、身份认证或数字签名的替代品。

## 反应网络、CHE 与生产门禁 schema 边界

`catex.reaction-network.v1` 只聚合 intact `catex.reaction-definition.v1`，保存按 ID 排序的 state/
reaction identities、reactant→product connectivity、required starts/terminals 和 component count。
它验证 reachability 但不自动挑选机理。`catex.reaction-network-review.v1` 必须唯一批准后，
`catex.reaction-network-readiness.v1` 才允许 pathway planning；`execution_authorized` 固定为 false。

`catex.computational-hydrogen-electrode-protocol.v1` 显式保存 SHE/RHE、potential、pH、temperature、
source reference/hash 并作为 reaction-domain definition 独立审核。
`catex.computational-hydrogen-electrode-report.v1` 绑定 intact pre-electrochemical free energy、
exact proton-electron pair count 和协议审核，分别保存 potential、pH 与总 correction。RHE 的显式
pH correction 为零，因为 pH 已吸收到 RHE potential scale；这不表示 pH 被忽略。

`catex.scientific-case-requirement.v1` 的 satisfied 状态必须有 evidence SHA256；blocked 不会被
默认值升级。`catex.scientific-case-readiness.v1` 只有所有 required requirement satisfied 才 ready，
但无论 ready/blocked 都不提供 execution authorization、写文件、提交、续算或删除权限。
