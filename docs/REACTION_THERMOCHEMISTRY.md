# 反应、参考态与热化学门禁

PR-014 在 PR-012 的已审核同能量族电子能和 PR-013 的催化科学身份之上，建立通用的
chemical state → balanced reaction → electronic reaction energy → reaction free energy 链。
该模块是纯 Python 领域层：不读写计算目录、不连接 HPC、不提交作业，也不从不完整资料中
猜测参考态、振动修正或电化学校正。

## 化学态

`ChemicalState` 将以下信息绑定为不可变身份：

- 明确的 phase；
- 化学式和逐元素精确有理数组成；
- 精确有理数 formal charge；
- catalyst、adsorbate、adsorption configuration 或 external reference provenance；
- subject identity SHA256 和 state identity SHA256。

催化剂只能建立 surface/solid state；分子 adsorbate 可以建立 gas/liquid/solvated state；
adsorption configuration 建立 adsorbed state。外部参考态仅允许 electron、gas、liquid、
solid 或 solvated；电子库必须使用空化学式和 `charge=-1`，不能由空白字段隐式推断。

## 平衡反应与参考态

`define_reaction` 接受 signed stoichiometry：负数是反应物，正数是产物。整数、`Fraction`
和形如 `"1/2"` 的字符串会规范化为精确有理数；float 被拒绝，避免二进制浮点数进入
元素/电荷平衡判断。term 按 state ID 排序，因此仅改变输入顺序不会改变反应身份。

只有同时满足以下条件才会生成 `ReactionDefinition`：

- state identity 完整且 state ID 唯一；
- 系数非零，并同时存在反应物和产物；
- 每一种元素严格平衡；
- formal charge 严格平衡；
- adsorption/formation 显式提供 reference-state set；
- adsorption/formation 的 reference-state set 完整覆盖全部反应物；
- reference entry 与反应中的同一 state ID/SHA256 一致。

失败时只返回带稳定诊断 code 的 `ReactionDefinitionReport`，不会产生一个标称
`balanced=true` 的部分对象。

## 电子反应能

每个 reaction state 必须通过 `StateEnergyBinding` 绑定恰好一个 PR-012
`ReviewedEnergyRecord`。reaction、reference-state set、每个 state 和每个 binding 都必须
分别有且只有一个 hash-bound 人工批准。缺失、拒绝、重复或批准/拒绝冲突均 fail closed。

`derive_reaction_electronic_energy` 使用反应的 signed coefficient 调用通用线性组合门禁，
并再次要求所有能量：

- 来自科学结果已明确接受的运行；
- artifact 与审核时哈希一致；
- `energy_family_id` 完全相同；
- VASP energy kind 完全相同，例如不能混合 TOTEN 与 sigma→0。

成功报告绑定 reaction identity、linear derivation SHA256、state-energy binding SHA256、
review SHA256、energy family 和明确 energy kind。其科学属性名由 reaction purpose 得出，
例如 `adsorption_electronic_energy`，而不是由任意字符串重命名。

## 热化学协议与自由能

`ThermochemistryProtocol` 显式声明：

- 温度；
- gas standard pressure，默认 1 bar；
- solution standard concentration，默认 1 mol/L；
- low-frequency treatment；
- imaginary-mode policy。

每个 state 必须有一个与同一 protocol 绑定的 `ThermochemicalCorrection`，并记录 phase
兼容的 standard state、source kind、source reference、至少一个 source SHA256，以及单位
明确的 ZPE、thermal enthalpy、entropy、solvation 和 other free-energy component。absolute
state entropy 不得为负。protocol 与每个 correction 也分别需要唯一人工批准。

当前自由能定义为：

```text
ΔG = ΔE_electronic
   + ΔZPE
   + ΔH_thermal
   - TΔS
   + ΔG_solvation
   + ΔG_other
```

`ReactionFreeEnergyReport` 逐项保存上述贡献，并绑定上游 electronic derivation SHA256、
energy family、energy kind、protocol identity、correction identity 和 review identity。改变
输入序列顺序不改变结果身份。

## 明确未自动应用的内容

v1 固定声明：

- `computational_hydrogen_electrode_applied=false`；
- `electrochemical_correction_included=false`；
- `electrode_potential_v=null`；
- `pH=null`；
- `uncertainty_model_applied=false`。

因此显式 proton/electron state 当前只用于元素和电荷平衡，不能被解释为已应用 CHE。
correction 可以记录单态 uncertainty，但 v1 不猜测相关性，也不自动传播总不确定度。

## 最小 API 顺序

```python
surface = create_catalyst_state(catalyst, state_id="surface")
gas = create_adsorbate_state(adsorbate, state_id="co-gas", phase=ChemicalPhase.GAS)
adsorbed = create_adsorption_state(
    catalyst, adsorbate, configuration, state_id="co-adsorbed"
)
references = create_reference_state_set(
    (surface, gas), reference_set_id="co-adsorption-references"
)
definition = define_reaction(
    (
        StateStoichiometry(surface, -1),
        StateStoichiometry(gas, -1),
        StateStoichiometry(adsorbed, 1),
    ),
    reaction_id="co-adsorption",
    purpose=ReactionPurpose.ADSORPTION,
    reference_set=references,
)
```

后续必须显式建立 state-energy bindings、definition reviews、thermochemistry protocol、
state corrections 和各自 reviews；API 不会代表用户自动填写人工接受。

## 当前边界

- 不解析频率输出，不自动生成 ZPE/entropy；
- 不应用 CHE、电位、pH、constant-potential 或 grand-canonical correction；
- 不建立 reaction network、过渡态、动力学或微观动力学；
- 不传播不确定度；
- 不放置吸附物、不创建多吸附物结构；
- 不写文件、不连接 SSH/HPC、不运行 VASP/Slurm。

Paper 4 仍缺少逐中间体 ZPE/entropy 和完整振动协议。那些值必须来自可审计来源并经人工
审核后才能进入本模块，不能因为论文报告了自由能公式而自动补零。
