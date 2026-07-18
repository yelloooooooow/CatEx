# VASP 输出解析

## 范围

PR-003 为 VASP 5.4.4 提供流式、只读、可审计的 `OUTCAR`/`OSZICAR` 解析。它不运行 VASP、不读取 WAVECAR/CHGCAR/vasprun.xml、不修改计算目录，也不查询或改变调度器状态。

```powershell
catex parse-vasp-output path\to\calculation --format text
catex parse-vasp-output path\to\calculation --format json
```

JSON 顶层 schema 是 `catex.vasp-output-parse.v1`。CLI 只有在 `scientifically_complete=true` 时返回 0；未收敛、截断、失败、未知或无法证明收敛时返回非零值，便于后续审核门阻止结果混用。

## 证据优先级

1. `OUTCAR` 是能量、力、局域磁矩、输入摘要和正常结束 footer 的主要证据。
2. `OSZICAR` 提供最终自由能、sigma→0 能量和晶胞磁矩的独立交叉证据。
3. 两个文件都按流式方式读取；解析过程中同时计算原始字节 SHA256，不把大型输出整体载入内存。
4. 若文件在扫描期间发生变化，报告产生 error，不能把该结果当作稳定快照。

VASP 官方说明 OUTCAR 包含力、局域电荷和磁矩等详细结果，而 OSZICAR 记录电子/离子步、自由能和晶胞磁矩：

- [OUTCAR](https://vasp.at/wiki/OUTCAR)
- [OSZICAR](https://vasp.at/wiki/OSZICAR)
- [Output files](https://vasp.at/wiki/Output_files)

## 结果与收敛状态

`termination.outcome` 的含义：

| outcome | 证据 |
|---|---|
| `normal` | 找到正常 timing/accounting footer，且没有明确未收敛或 fatal 证据 |
| `unconverged` | 正常结束，但最终电子步达到 NELM 或离子步达到 NSW 且没有对应收敛标记 |
| `truncated` | 已有输出内容，但没有正常 footer；也可能是仍在运行，必须结合调度器判断 |
| `failed` | 找到受控列表中的 VASP、MPI 或运行时 fatal marker |
| `unknown` | 文件缺失、为空或证据不足 |

进程正常结束不等于科学收敛。电子收敛与离子收敛分别报告：

- 电子收敛以最终电子循环的 EDIFF marker 为正证据；NELM 是电子 SCF 最大步数。
- 几何优化以 EDIFFG 对应的 structural minimisation marker 为正证据。
- 静态计算、分子动力学和部分非优化任务的离子收敛标为 `not_applicable`。

官方语义参考：[EDIFF](https://vasp.at/wiki/EDIFF)、[EDIFFG](https://vasp.at/wiki/EDIFFG)、[NELM](https://vasp.at/wiki/NELM)。

## 提取量

### 能量

报告最终完整能量记录：

- `free_energy_eV`：OUTCAR 的 TOTEN 或 OSZICAR 的 F；
- `energy_without_entropy_eV`：OUTCAR 的 energy without entropy；
- `sigma_zero_energy_eV`：OUTCAR/OSZICAR 的 sigma→0 能量。

若 OUTCAR 和 OSZICAR 的最终自由能差异超过文本精度容差，置信度降为 low，并产生 `ENERGY_SOURCE_DISAGREEMENT`。

### 力

只接受行数与 NIONS 一致的完整 `TOTAL-FORCE (eV/Angst)` 块。报告逐原子三维力、最大力范数、对应的 1-based 原子序号和离子步。截断块被忽略并产生诊断，绝不以零填充。

### 磁矩

OUTCAR `magnetization (x/y/z)` 表中的逐原子 `tot` 是 PAW 球内投影量；OSZICAR `mag` 是晶胞磁矩。两者保留为不同字段，不进行相等性假设，也不把局域投影之和冒充总磁矩。

## 置信度

- `high`：直接完整标记或完整数据块；能量可由两个输出相互印证。
- `medium`：单一正式输出源，或文件缺少正常 footer 但数据块自身完整。
- `low`：来源间不一致或只有不足以证明完整性的弱证据。

置信度只描述“解析观测是否可靠”，不评价 DFT 方法、结构、泛函或计算协议是否科学合理。

## 测试与数据策略

仓库只包含人工编写的最小合成 OUTCAR/OSZICAR 夹具，覆盖正常、未收敛、截断和失败。真实超算输出、服务器路径、用户名、任务号及其他可能识别研究或基础设施的信息不进入 Git。
