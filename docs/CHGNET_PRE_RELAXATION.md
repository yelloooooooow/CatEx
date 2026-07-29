# CHGNet 可选预弛豫

CatEx 把 CHGNet 定位为 VASP 之前的可选几何预处理器，而不是一种新的 DFT 协议，也不是最终能量来源。它的目标是把明显不合理或离局部极小值较远的初始结构先推向较平滑的几何，从而可能减少后续 VASP 离子步数。

## 在工作流中的位置

```text
当前 POSCAR
  → 可选 Selective dynamics（固定基底 / 放开吸附物）
  → 可选 CHGNet 预弛豫（本机）
  → 新的不可变结构 Artifact / 当前 POSCAR
  → INCAR、KPOINTS、POTCAR 与 Slurm 计划
  → VASP 正式优化
```

该功能位于 Web 工作台的“VASP 输入自动化 → POSCAR”卡片中，默认关闭。运行 CHGNet 不需要 SSH，不连接 HPC，也不提交 Slurm 作业。

## 默认配置

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| 模型 | CHGNet 0.3.0 | MPtrj GGA/GGA+U 轨迹预训练模型 |
| 优化器 | FIRE | 与 paper 4 原型一致 |
| 最大力 | 0.05 eV/Å | 宽松的预弛豫阈值；不是最终 VASP 阈值 |
| 最大步数 | 500 | 到达上限时仍会保留结构，但明确标记未达到目标力 |
| 晶胞优化 | 关闭 | 表面和真空模型默认只优化原子位置 |
| 设备 | 自动 | 自动使用可用设备，也可显式选择 CPU 或可用的 CUDA GPU |

CatEx 按最终移动原子的最大受力是否不高于目标 `fmax` 判断 CHGNet 收敛，而不是仅根据优化器是否提前停止判断。

## 原子约束

若 POSCAR 包含 VASP `Selective dynamics`：

- `F F F` 原子转换为 ASE `FixAtoms`，CHGNet 过程中保持不动；
- `T T T` 原子自由移动；
- 为避免悄悄改变含义，当前受控模式拒绝混合方向标记，例如 `T T F`；
- 所有原子均固定时拒绝运行；
- 固定原子与晶胞优化不能同时启用。

因此，吸附体系应先在 CatEx 中应用“固定催化剂 / 放开吸附物”，确认结构图中的原子选择，再运行 CHGNet。

## 输出与溯源

每次成功调用都会：

1. 保留原始结构 Artifact；
2. 创建新的 `POSCAR_CHGNET.vasp` 结构 Artifact；
3. 保存模型、版本、优化器、设备、阈值、步数、能量变化、最终 Fmax、位移、固定原子和输入/输出 SHA-256；
4. 将预弛豫记录写入项目的 `pre-relaxations/` 并纳入项目导出包；
5. 在用户已经选择本地工作文件夹时，显式写入 `POSCAR_CHGNET.vasp`，并把相同内容写成后续流程使用的 `POSCAR`。

只有点击“运行并采用预弛豫结构”才会执行这些写入。若预弛豫失败，当前 POSCAR 不会被替换。

## 科学边界

CHGNet 0.3.0 来自 Materials Project 的 GGA/GGA+U 轨迹训练。表面、吸附物、缺陷、稀有配位、特殊电荷态、强关联体系或训练集中稀少的化学环境可能超出模型适用域。因此：

- CHGNet 能量不得与 VASP 能量混合计算吸附能、形成能或自由能；
- CHGNet 的“收敛”只表示该机器学习势下满足力阈值；
- 必须检查预弛豫后的成键、吸附位点、真空层和异常位移；
- 后续 VASP 必须使用目标科研协议重新优化并独立判断电子和离子收敛；
- 若项目使用 PBE/GGA 协议，默认 0.3.0 模型通常比 r2SCAN 模型具有更接近的训练层级，但二者都不是目标项目 DFT 协议的替代品。

## 安装

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web,mlip]"
```

`mlip` 可选依赖会安装 CHGNet、ASE 和 PyTorch。未安装时，页面仍可正常使用其他 CatEx 功能，但 CHGNet 卡片会显示缺少的本机包且运行按钮不可用。

## 参考

- CHGNet 官方仓库与结构优化接口：<https://github.com/CederGroupHub/chgnet>
- ASE 原子约束：<https://wiki.fysik.dtu.dk/ase/ase/constraints.html>
- paper 4 中的 slab 与 adsorption 预弛豫脚本作为首个研究案例参考；通用实现未硬编码其元素、结构或反应体系。
