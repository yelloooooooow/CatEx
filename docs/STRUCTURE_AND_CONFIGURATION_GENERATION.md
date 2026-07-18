# 结构变换、吸附构型生成与多自旋规划

PR-015 补齐通用催化建模的候选生成层。所有操作都在内存中完成，返回 live
`pymatgen` 对象和可序列化 provenance；不会覆盖源结构、写 POSCAR、调用 Materials
Studio、连接 HPC、生成 POTCAR 或提交 Slurm 作业。

## 结构变换

`catex.transformations` 当前支持：

- 指定 Miller index、最小 slab 厚度和最小真空的 slab candidates；
- 对正交于面内晶格的 c 轴设置明确真空厚度；
- 按显式 0-based index 建立 vacancy；
- 按显式 0-based index 执行 substitution；
- 使用独立 operation provenance 记录 doping。

每个 `StructureTransformationRecord` 同时绑定输入/输出的：

- order-independent canonical structure SHA256；
- order-sensitive structure SHA256；
- operation 和完整参数；
- parent atom lineage；
- removed parent index 和 created child index；
- mapping strength；
- transformation identity SHA256。

vacancy、substitution、doping 和 set-vacuum 保持明确的 parent→child index lineage，使用
`exact_index`。slab generation 可能复制晶胞并合并对称等价 parent sites，因此只保存
pymatgen 的 `bulk_equivalence` class，固定声明 `exact_atom_mapping_complete=false`；不能把
它冒充作者原始结构的逐原子映射。

### slab candidates

`generate_slab_candidates` 固定：

- `center_slab=true`；
- `symmetrize=false`；
- `repair=false`；
- `filter_out_sym_slabs=true`。

候选按结构哈希排序，调用顺序不改变 candidate ID。函数不会按表面能、化学直觉或论文结论
选择 termination。每个候选带 `SLAB_TERMINATION_REVIEW_REQUIRED`，必须人工检查化学计量、
极性、终止面、对称性、层数、冻结层和真空。

### vacuum

`set_orthogonal_c_vacuum` 从最大周期空隙确定 occupied slab span，再令新 c 长度为
`occupied_span + requested_vacuum` 并居中。v1 只接受 c 同时垂直于 a、b 的晶格；倾斜 c
会 fail closed，而不是用不明确的笛卡尔投影静默改胞。

### transformation review

transformation product 必须满足：

1. live structure 仍匹配记录的 canonical/ordered hash；
2. transformation record identity 完整；
3. 恰有一个 hash-bound 人工批准；
4. 没有 error diagnostic。

通过 `assess_transformation_readiness` 后，`register_transformed_catalyst` 才将其登记为
`StructureOrigin.TRANSFORMED` 的 `CatalystSystem`。拒绝、重复、冲突、结构改动或 record
改动全部阻断。

## 刚体吸附构型生成

`generate_adsorption_configuration` 需要已经登记的 catalyst、site、adsorbate 和与
adsorbate identity 一致的 live `Molecule`。调用者必须明确提供：

- 每个 binding atom 到 site anchor position 的映射；
- 吸附高度；
- rigid alignment tolerance；
- minimum substrate–adsorbate distance。

一个 binding atom 可以映射到多个 anchor，例如 hollow-site centroid；多个 binding atom
可以分别映射到多个 anchor。全部已声明 binding atom 必须被覆盖，不允许工具猜测缺失映射。

对齐算法按唯一 binding point 数选择：

- 1 点：只平移，保留调用者分子朝向；
- 2 点：刚体向量对齐；
- 3 点及以上：保持手性的 Kabsch rotation。

分子内部坐标不会被拉伸。若 target anchor geometry 与 binding geometry 不兼容，alignment
RMSD 超过阈值即拒绝；若任一 substrate–adsorbate 距离低于明确阈值，也拒绝。成功候选仍然
`scientific_identity_approved=false`，必须经过既有四身份审核门。

## 构型去重

`deduplicate_adsorption_configurations` 只在 catalyst、site、adsorbate identity 相同且晶格
一致的候选之间比较；按有序 adsorbate atom mapping 计算 PBC displacement。不同 site 或
不同 adsorbate 不会因为几何相近被合并。

代表构型按 identity SHA256 决定，因此输入列表重排不改变分组或代表。v1 不进行旋转自由度
积分、化学对称群分析或能量排序；超过几何阈值的 orientation 保留为独立候选。

## 多自旋计算计划

`plan_multi_spin_calculations` 只接受已经通过 catalyst/site/adsorbate/configuration 四身份
审核的构型。每个 `SpinInitialization` 必须包含：

- 唯一 label；
- 与 combined structure site 数完全一致的 collinear `MAGMOM`；
- 可选的明确 `NUPDOWN`。

函数为每个状态生成独立 `ScientificProtocol` variant，显式写入 `ISPIN=2`、完整 `MAGMOM`
和可选 `NUPDOWN`。相同 numerical state、重复 label、长度不符、非有限值或
`LNONCOLLINEAR=true` 全部拒绝。

每个 variant 都固定 `manual_protocol_review_required=true`。MAGMOM/NUPDOWN 会参与后续
resolved protocol 和 energy-family 规则；不同初始磁态不能在结果阶段因最终能量接近而静默
混成同一 provenance。plan 固定 `writes_performed=false`、`submitted=false`。

## 当前明确不做

- 自动判断最稳定 slab termination；
- 自动选择 vacancy、dopant 或 substitution site；
- 任意倾斜晶格的真空重构；
- 分子柔性搜索、键长优化或共吸附；
- 构型能量排序；
- noncollinear/SOC 初始磁态；
- 写文件、运行 VASP 或提交作业。
