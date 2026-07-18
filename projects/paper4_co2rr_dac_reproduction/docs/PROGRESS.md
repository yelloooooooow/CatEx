# 项目进度与长期记忆

2026-07-15 的第一次受控 Slurm 环境烟雾任务在 VASP 启动前以退出码 127
结束；原因是非登录 Bash 未初始化 `module`。只读复核确认登录 Bash 可加载
Intel MPI 且提供 PMI2。平台随后增加了 policy-gated `shell_mode=login`；
失败目录和调度证据原样保留，没有覆盖或删除。

同日的全新登录-shell重试通过：调度器正常结束，VASP 5.4.4、Intel MPI、
PMI2 和 VASPsol 均产生明确运行时证据，输出包含正常 footer 且没有已知 fatal
marker。烟雾协议关闭的大型 checkpoint 保持为空；该次运行只证明环境链路，
所有能量继续标记为 `scientific_result_eligible=false`。

PR-010 随后把这次独立提交回执、materialization manifest、实际 `slurm.sh`、
Slurm allocation 与同目录 VASP 输出纳入只读 run binding。绑定通过只表示证据链
一致并可进入人工科学审核；烟雾能量仍未被接受，也没有自动续算或新增提交权限。

PR-011 增加显式 scientific result review，但不会把既有环境烟雾自动升级为科学结果。
该烟雾运行的协议本来就声明 `scientific_result_eligible=false`，且只验证环境链路；除非
未来针对生产协议建立新的完整 run binding 并进行独立科学审核，否则不得生成接受记录。

PR-012 增加 reviewed-energy compatibility gate。现有烟雾运行仍因
`scientific_result_eligible=false` 无法生成 `ReviewedEnergyRecord`；未来生产能量只有在
人工接受、artifact 哈希未变化、解析置信度为 high、能量族和能量类型均一致时，才能进入
通用线性组合。该组合本身仍不等于 Paper 4 的吸附能或自由能。

PR-013 建立通用 catalyst/site/adsorbate/configuration 科学身份，回归测试使用 Pt slab 与
CO 的完全合成非 Paper 4 案例，证明核心没有硬编码 C62N6、DAC、NiZn 或 CO2RR。Paper 4
后续结构必须先登记来源与 ordered atom mapping，再分别审核 catalyst、site、adsorbate 和
configuration；当前论文缺失的精确坐标仍不能由身份模型自动补全。

PR-014 建立通用的平衡反应、显式参考态、电子反应能与 component-resolved 自由能门禁。
它可以表达 Paper 4 的中间体反应和 `ΔE + ΔZPE + ΔHthermal - TΔS + ΔGsolv + ΔGother`，
但不会自动应用 CHE、电位或 pH，也不会把论文缺失的逐中间体 ZPE/熵默认为零。Paper 4
必须先补齐每个 state 的可审计频率/表格来源、standard state 与人工审核，才能生成科研
自由能；现有环境烟雾能量依然永久不具备该资格。

PR-015 建立通用 slab/vacuum/vacancy/doping/substitution provenance、刚体吸附构型生成去重
和多自旋协议计划。Paper 4 可以用这些能力生成候选 6×6 拓扑、金属替换、OCHO/COOH 等
多齿构型和 NiMn 多磁态，但任何候选仍不能被称为作者精确结构；slab termination、金属位点、
binding-anchor mapping、MAGMOM/NUPDOWN 与每个协议变体都必须单独人工审核。

PR-016 建立 source-hash-bound DOS/PDOS、磁矩和 charge-partition 数值分析，并以合成 Pt/CO
完成非 Paper 4 端到端验收。Paper 4 后续可把已审核生产输出经独立解析适配器送入这些接口，
但 d-band center、局域磁矩和电子亏损仍需人工结合构型与收敛证据解释；平台不会自动重现论文
“Mn 3d-N 2p 杂化”或“Sn-OCHO 成键”等结论。当前尚无 Paper 4 生产输出进入该分析层。

PR-017 建立通用 reaction-network、SHE/RHE CHE 和 non-authorizing production-readiness 门禁。
Paper 4 已登记 CO 与 HCOOH 概念路径，但所有 catalyst-bound state/reaction identity 仍为 null；
CHE 草案保留论文明确的 SHE、U=0 V、pH=0，并将未报告 temperature 保持 null；逐态 ZPE、H、S、
solvation/other correction 也全部保持 null。机器可检验 readiness 当前为 3 项 satisfied、10 项
blocked，因而不允许生产 planning 或 execution，更没有生成任何真实科研结果。

更新时间：2026-07-16

## 已确认事实

- 课题组拥有 VASP 许可证。
- VASP 在超算运行，版本为 5.4.4。
- 本机可用 Anaconda，基础 Python 为 3.13.5。
- Windows Store 登记的 Python 3.12 启动器路径异常，未采用。
- 已在 DFT 根目录创建共享 Conda 环境 `dft-common-py312`，Python 3.12.13。
- 已安装并验证 NumPy、pymatgen、ASE、CHGNet、PyTorch、pypdf、pdfplumber。
- 当前 PyTorch 为 CPU 版；足够进行前后处理和少量 CHGNet 测试。
- 已成功读取 70 原子的 NiZn-N-C CIF。
- 已成功运行 GitHub 的 `build_slab.py` 并生成 NiZn 输入文件。
- 已成功运行一次 CHGNet 结构能量/力推理。
- 已提取并逐页核验 13 页论文正文。
- 已取得 23 页 Supporting Information，并复制到项目 `references`。
- 已提取 SI 全文并核验自由能公式、机器学习方法、AIMD、显式水和数据表关键页。
- 已从 Table S2 提取并校验全部 91 个体系，生成 `results/reference_table_s2.csv`。
- 已只读确认 Slurm 23.11.3、PMI2、64 核节点、Intel MPI、VASP 5.4.4.pl2 和内编译 VASPsol。
- VASP 不在默认 PATH，也没有 VASP/VASPsol module；执行配置必须使用精确 allowlist 的绝对路径，真实路径不提交 Git。
- 已建立非生产 NiZn 环境烟雾协议：1×1×1、NELM=4、NSW=0、关闭 WAVECAR/CHGCAR。

## 论文核心设置

```text
PAW, spin-polarized PBE
ENCUT = 500 eV
Monkhorst-Pack 3x3x1
vacuum = 15 A
force threshold = 0.03 eV/A
EDIFF = 1E-5 eV
VASPsol, EB_K = 78.4
DFT-D3(BJ)
no DFT+U
multiple initial spin moments
```

## 论文核心结论

- 13 种金属、允许同核组合，共 91 个 M1M2-N-C。
- NiMn-N-C 偏向 CO；Eform 约 2.10 eV。
- SnNi-N-C 偏向 HCOOH；Eform 约 3.90 eV。
- `E*COOH` 是 CO 路径关键描述符，火山顶约 -0.51 eV。
- `E*OCHO` 是 HCOOH 路径关键描述符，火山顶约 -0.43 eV。
- Mn 3d-N 2p 杂化有利于位点稳定。
- Sn 对 OCHO 两个 O 的结合有利于 HCOOH 选择性。
- SI 使用 CHE；取 pH=0，中间体的热容积分和熵来自振动能，气相分子热化学来自 NIST-JANAF。
- 机器学习按 4:1 随机拆分、5 折 CV，先随机搜索再网格搜索。
- SnNi 的 AIMD 条件为 NVT、300 K、20 ps。
- 四层显式水对 NiMn/ZnMn/IrMn 的 `DeltaGmax(CO)` 影响约 0.03-0.06 eV。
- Table S2 的印刷列名与正文代表数值存在明显顺序矛盾，后续必须保留两种解释并向作者确认。

## GitHub 与论文的关键差异

- GitHub 金属列表没有 Sn。
- GitHub 主要选择不同元素对，不包含完整同核集合。
- GitHub 用 NiZn 做基准，不是论文最佳 NiMn/SnNi。
- GitHub HCOOH 路径缺少 OCHO。
- GitHub 使用 CHGNet 预弛豫，论文未报告该步骤。
- GitHub 吸附脚本固定全部 slab，论文正文表述为原子位置弛豫。
- GitHub 没有 VASP 结果和完整自由能参考文件。
- `parse_outcar.py` 仍为 NotImplemented。

## 未解决问题

1. 正文和 SI 均未给出精确超胞坐标、完整原子数/约束或可直接运行的 VASP 输入。
2. N 化学势只写作 `nitrogen`，具体参考态没有被进一步定义。
3. SI 未给出逐中间体 ZPE/熵表、振动设置和温度数值。
4. SI 未给出 ML 随机种子、训练/测试样本、搜索范围、软件版本和最终超参数。
5. AIMD 未给出时间步长、恒温器和完整 INCAR。
6. Table S2 的三列印刷标签与正文数值不一致，需要作者勘误或我们在报告中显式声明解释。

## 下一步

1. 获得或人工接受 production catalyst coordinates、atom order 与 constraints。
2. 确定有足够配额的 project/scratch 生产工作根和输出保留策略。
3. 审核 3×3×1、结构弛豫、VASPsol、输出保留和每个多磁态 production protocol。
4. 明确 nitrogen chemical-potential reference、thermochemistry temperature 和逐态 correction 来源。
5. 关闭 Table S2 printed-header/正文代表值解释冲突，再授权单个 production run。

## 关于跨聊天记忆

不同 GPT/Codex 任务之间不能依赖隐式共享记忆。本文件和项目文档是显式、可检查、可版本控制的长期记忆。新任务只需让助手先阅读本项目 `README.md` 和 `docs/PROGRESS.md`，即可恢复上下文。
