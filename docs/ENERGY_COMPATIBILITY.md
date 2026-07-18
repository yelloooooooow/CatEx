# 已审核能量、兼容性与线性派生门禁

PR-012 连接“人工接受一个运行”和“允许能量参与派生计算”两个阶段。它解决的是电子能
证据与兼容性，不定义催化反应、参考态或热化学。

## 三层门禁

1. `bind_reviewed_vasp_energy` 只接受 PR-011 的显式人工接受记录。
2. 它重新核对当前 VASP 解析报告的目录 basename、运行 outcome 和全部 artifact SHA256。
3. `assess_energy_compatibility` 在计算前核对每个能量记录自身的 hash、人工接受状态、
   `energy_family_id` 和明确的 VASP 能量类型。

任何一层失败都不会得到派生数值。

## 明确区分 VASP 能量

`VaspEnergyKind` 当前包含：

- `free_energy_toten`：OUTCAR 的 `free energy TOTEN`；
- `energy_without_entropy`：OUTCAR 的 `energy without entropy`；
- `sigma_zero`：OUTCAR 的 `energy(sigma->0)`。

三者不能在同一个线性组合中混用。记录必须来自科学完整且解析置信度为 `high` 的 VASP
输出，并保留脱敏后的 artifact basename、行号、解析规则和 evidence 置信度。

## 纯 Python API

```python
from catex import (
    EnergyTerm,
    VaspEnergyKind,
    bind_reviewed_vasp_energy,
    derive_linear_energy,
)

surface = bind_reviewed_vasp_energy(
    accepted_surface_review,
    surface_vasp_report,
    energy_id="surface",
    kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
)
combined = derive_linear_energy(
    (EnergyTerm(1.0, surface), EnergyTerm(-1.0, another_reviewed_energy)),
    derivation_id="generic-difference",
)
```

这些 API 是纯内存操作：不写文件、不执行命令、不连接 HPC，也不提交或续算作业。

## 科学含义边界

`LinearEnergyDerivationReport` 只是同一能量族、同一能量类型的通用线性组合。即使成功，
它仍固定声明：

- `scientific_interpretation_approved=false`；
- `reference_state_reviewed=false`；
- `thermochemical_corrections_included=false`。

因此该结果不能直接称为吸附能、形成能、反应能或自由能。后续 PR 必须另行定义并审核：

- 催化剂、吸附物、活性位点和构型身份；
- 气相、溶液相和元素参考态；
- 化学计量与反应网络；
- ZPE、熵、温度、压力、溶剂与 CHE 修正；
- 不确定性、异常值和最终科学解释。

## 完整性边界

Reviewed-energy 与 derivation SHA256 是确定性 provenance 指纹，不是数字签名、用户身份认证
或访问控制。生产服务仍需独立实现审核人认证、角色授权、不可篡改审计存储与记录撤销策略。
