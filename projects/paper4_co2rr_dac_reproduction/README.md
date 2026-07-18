# Metal-N-C 双原子催化剂 CO2RR 复现项目

本项目用于学习并复现论文：

> Y. Qin et al., *Screening Framework of Metal-N-C Diatomic Catalysts for Electrochemical CO2 Reduction*, ACS Catalysis 2026, 16, 2484-2496. DOI: 10.1021/acscatal.5c07689.

项目分成两条相互关联、但不能混为一谈的路线：

1. **学习路线**：使用 GitHub 项目已有的 `NiZn_NC` 结构，掌握 VASP 输入、超算提交、结构优化和结果检查。
2. **严格复现路线**：依据论文重新建立 13 种金属、91 种双原子组合以及 CO/HCOOH/HER 自由能筛选流程。

## 从这里开始

按以下顺序阅读：

1. [工作区与共享 Python 环境](docs/00_environment_and_workspace.md)
2. [论文原理精讲](docs/01_paper_tutorial.md)
3. [VASP 5.4.4 复现路线](docs/02_reproduction_roadmap_vasp544.md)
4. [Supporting Information 精读与复现含义](docs/03_si_notes.md)
5. [项目进度与长期记忆](docs/PROGRESS.md)

生产科学门禁与草案：

- `production-readiness.json`：3 项已满足、10 项阻塞的可执行证据清单；
- `reaction-network-draft.json`：CO/HCOOH 概念路径，科学身份仍为 null；
- `che-protocol-draft.json`：记录 SHE、U=0 V、pH=0，缺失温度保持 null；
- `thermochemistry-requirements.json`：逐态未知 correction 全部保持 null，不自动补零。

## 当前目录

```text
paper4_co2rr_dac_reproduction/
├── docs/           中文课程、环境说明、进度记录
├── references/     原文提取文本和版面核验图
├── structures/     初始结构、结构生成和环境冒烟测试
├── calculations/   后续按阶段保存 VASP 任务
├── hpc/            超算提交脚本
├── scripts/        本项目自己的可复现脚本
├── results/        汇总表、自由能、图片
└── logs/           批量作业和解析日志
```

共享 Python 环境不在本项目内，而在：

```text
.venvs\dft-common-py312
```

因此，`DFT\projects` 下的其他同类计算项目也能使用它。

## 外部参考

- 原始论文 PDF：不进入仓库；仅保存在用户有权访问的本地参考资料目录。
- Supporting Information：不进入仓库；仅保存在用户有权访问的本地参考资料目录。
- 外部示例代码：不复制到仓库；在 provenance 中记录公开 URL、版本或提交哈希。
- 环境生成的 NiZn 冒烟测试：`structures\environment_smoke_test\NiZn_NC`
- SI Table S2 的 91 体系参考数据：`results\reference_table_s2.csv`

## 当前边界

- 超算 VASP 版本：5.4.4。
- 课题组拥有 VASP 许可证。
- 已确认超算使用 Slurm 23.11.3；VASP 5.4.4.pl2 位于受控绝对路径，VASPsol 已编译进入 `vasp_std`，运行时加载 Intel MPI 并使用 PMI2。真实绝对路径不提交 Git。
- SI 已保存并完成关键页版面核验。它没有提供原子坐标、完整 VASP 输入、逐中间体 ZPE/熵表、机器学习随机种子或最终超参数；这些仍需自行重建或向作者索取。
- SI Table S2 的印刷列名与正文代表数值存在明显顺序矛盾，详见 `docs/03_si_notes.md`，后续不能直接把三列标题当作已确认无误。
- 当前生产 readiness 明确为 blocked；该状态既不授权超算提交，也不允许把环境烟雾结果升级为科研能量。
