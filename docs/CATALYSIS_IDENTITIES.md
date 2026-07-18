# 通用催化科学身份

PR-013 为周期性催化研究建立 catalyst → site → adsorbate → adsorption configuration
身份链。它只登记和验证用户提供的科学对象，不自动生成位点、不放置吸附物、不修改结构，
也不运行 Materials Studio、VASP、Slurm 或 SSH。

## 为什么需要两种结构哈希

CatEx 已有 canonical structure hash，故意忽略 site 顺序，适合内容 provenance 与去重。
但活性位点 `anchor_indices_0based` 和构型 atom mapping 必须依赖确定的原子顺序。

因此 `CatalystSystem` 同时保存：

- `canonical_structure_sha256`：忽略 site order；
- `ordered_structure_sha256`：保留 lattice、元素、占据和 wrapped fractional coordinates
  的 site order。

重排等价结构可以保持相同 canonical hash，但 ordered hash 会变化，旧 index mapping 因而
不能被静默复用。

## 身份对象

### CatalystSystem

记录 catalyst ID、周期模型类型、结构来源、化学式、site 数、电荷、两种结构哈希、脱敏的
source artifact SHA256 和 transformation SHA256。`external_import` 必须有 source artifact；
`transformed` 必须有 transformation provenance。

### SiteDefinition

记录 catalyst identity、site kind、唯一 0-based anchor index、anchor species、wrapped
fractional coordinates 和周期边界感知的 fractional centroid。atop/bridge/hollow 分别要求
1/2/至少 3 个 anchor；custom、defect 和 multi-center 保留显式人工定义空间。

### Adsorbate

由非空、有序的 `pymatgen.Molecule` 建立，记录 ordered species、整数 charge、正整数
spin multiplicity、明确 binding atom、stereochemistry label 和 ordered distance-matrix
geometry SHA256。距离矩阵使刚体平移/旋转不改变几何身份；原子重排会改变身份。

`stereochemistry_label="unspecified"` 是显式未知，不代表系统自动证明分子无手性。

### AdsorptionConfiguration

v1 只登记一个吸附物的一个初始周期构型。调用者必须提供：

- catalyst structure 与 combined structure；
- ordered substrate index mapping；
- ordered adsorbate index mapping；
- placement provenance：manual、rule-based 或 external import。

两组 mapping 必须互斥且覆盖 combined structure 全部原子。映射后的 substrate 必须精确重现
catalyst ordered identity，adsorbate species 顺序必须匹配 adsorbate identity。记录会保存
site-anchor 到 binding-atom 的 PBC 距离矩阵，但不会据此自动宣布构型科学合理。

## 人工审核门禁

```python
from catex import assess_configuration_readiness, record_identity_review

reviews = tuple(
    record_identity_review(
        subject,
        accepted=True,
        reviewer="reviewer-id",
        reviewed_at_utc="2026-01-01T00:00:00Z",
        note="Identity and mapping reviewed.",
    )
    for subject in (catalyst, site, adsorbate, configuration)
)

readiness = assess_configuration_readiness(
    catalyst, site, adsorbate, configuration, reviews
)
```

进入 calculation planning 前，四种 identity 各自必须恰有一个完整、绑定正确且批准的审核。
以下情况全部 fail closed：

- 任一审核缺失或拒绝；
- 同一 subject 有重复批准；
- 批准与拒绝同时存在；
- subject kind、ID 或 hash 不匹配；
- identity 字段在创建或审核后被修改；
- agent 自动填充“人工批准”。

审核 SHA256 是完整性/provenance 指纹，不是数字签名或审核人身份认证。服务层仍需实现账号、
角色、撤销和不可篡改审计存储。

## 当前明确不做

- 自动搜索活性位点；
- 自动放置、旋转或去重吸附物；
- 多吸附物、共吸附、显式水或电解质；
- relaxed structure 与 initial configuration 的原子映射；
- 自动生成反应网络、参考态或热化学数值；
- 文件写入、HPC 连接或计算提交。

PR-014 已在独立 reaction-domain schema 中实现人工定义的平衡反应、显式参考态和
review-gated 电子能/自由能派生，但不会由本身份模块自动创建这些科学定义。
