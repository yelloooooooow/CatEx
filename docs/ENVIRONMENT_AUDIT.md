# 环境审计

审计日期：2026-07-15（Asia/Shanghai）

本文件记录只读调查结果和当前规划阶段实际安装的辅助工具。它不是跨平台锁文件。

## 本地科学环境

现有虚拟环境：

```text
.venvs\dft-common-py312
```

已确认：

| 项目 | 状态 |
|---|---|
| Python | 3.12.13 |
| pymatgen | 已安装 |
| ASE | 已安装 |
| CHGNet | 已安装 |
| Paramiko | 已安装 |
| PyTorch | 已安装，CPU 环境 |
| pytest | 未安装 |
| Ruff | 未安装 |
| mypy | 未安装 |
| Pydantic | 未安装 |
| MCP Python SDK | 未安装 |
| Typer/Click | 未安装 |

结论：当前环境足以进行结构读取、VASP 基础 I/O、CHGNet 预筛调查和 SSH 只读连接；尚不具备平台开发测试、MCP 服务或正式 CLI 的完整依赖。

PR-001 新建了隔离的核心开发环境：

```text
.venvs\catex-core-py312
```

该环境由根目录 `pyproject.toml` 安装，已确认：

| 项目 | 版本/状态 |
|---|---|
| CatEx | 0.7.0，可编辑安装 |
| Python | 3.12.13 |
| NumPy | 2.5.1 |
| pymatgen | 2026.5.4 |
| pytest | 9.1.1 |
| Ruff | 0.15.21 |
| build/hatchling | 由 `dev` extra 与构建后端声明管理 |

这个环境不包含 CHGNet、MCP SDK 或 HPC 执行依赖。

Windows/Python 3.12 的已测试解析快照记录在：

```text
requirements\catex-core-py312-windows.lock
```

`pyproject.toml` 是直接依赖的唯一来源；lock 文件用于审计和重建当前 Windows 测试环境，不用于假装不同平台具有完全相同的二进制解析结果。

## Materials Studio

已安装：

```text
BIOVIA Materials Studio 2023
版本 23.1.0.3829
安装目录 E:\ms\file\
```

MaterialsScript runner：

```text
E:\ms\file\Materials Studio 23.1\etc\Scripting\bin\RunMatScript.bat
```

本机版本提供 Perl MaterialsScript、Scripting API、x64 Server 和 Gateway。未发现本机 Materials Studio 2023 原生 Python MaterialsScript；Python MaterialsScript 是 Materials Studio 2026 新增能力。

已用合成 NaCl CIF 完成一次固定模板受控测试：MaterialsScript runner 返回 0，生成 XSD/CIF，pymatgen 独立验证周期等价并建立完整原子映射。这只证明 Visualizer import/export 路线和当前基础许可证可用，不证明 Forcite、CASTEP 或其他计算模块许可证可用。

复杂表面、无序结构、占据率、键级和非正交晶胞的 round-trip 行为仍需分类型验收；所有真实结构仍要求人工可视化审核。

## HPC

此前只读调查确认：

| 项目 | 当前信息 |
|---|---|
| 调度器 | Slurm 23.11.3 |
| VASP | 5.4.4.pl2 |
| 启动方式 | `srun --mpi=pmi2 <vasp_std>` |
| MPI/编译环境 | `intel/oneapi2023.2_impi` |
| VASPsol | 1.0 已编译 |
| POTCAR | PAW-PBE.54，保存在超算受限目录 |
| 节点 | 64 CPU 核，约 512 GB 内存 |
| 主目录配额 | 接近 100 GB 配额上限，必须避免把运行产物写入 home |

HPC 端尚未部署平台 agent、数据库或自动提交服务。

PR-007 新增的 Slurm 观察层只解析调用者提供的合成/脱敏固定列快照；本次没有连接 HPC、查询真实 job、运行调度器命令或写入远端文件。真实 job ID、用户名、路径和连接信息不进入仓库。

后续只读核验确认 VASP 5.4.4.pl2 以可执行的绝对路径安装、VASPsol 已编译进入该二进制；没有 VASP module，默认 PATH 中也没有 `vasp_std`。PR-008 因此增加精确绝对 executable allowlist，但真实路径不写入仓库。人工批准的测试目录为空且非符号链接；其文件系统已使用约 98%，烟雾测试必须禁用 WAVECAR/CHGCAR并使用短时、小规模配置。

PR-005 只把上述已确认信息建模为本地 Slurm allowlist/policy。实现不调用 `sbatch`、`scancel` 或 SSH；兼容性复核仅使用只读版本/帮助/配置查询，未创建、修改、删除或提交任何超算文件和任务。

2026-07-15 的 PR-005 只读复核再次确认 Slurm/srun 23.11.3、PMI2 plugin 和 64 核节点信息；`intel/oneapi2023.2_impi` 可在非交互 shell 加载。但该 shell 中没有可用的 `vasp_std` basename，也没有发现公开的 VASP module。因此合成测试中的 `vasp_std` 只能验证脚本 grammar，不能视为生产命令已批准。真实 execution profile 必须等站点可执行入口或受控 wrapper 被人工确认后再建立；PR-005 不提交烟雾作业。

PR-006 提供可部署到授权 HPC 环境的 stdout-only POTCAR metadata 提取逻辑，但本轮未上传、部署或在真实 POTCAR 上运行，也没有创建任何远端 metadata 文件。真实执行仍需要针对源 POTCAR、目标 metadata 保存位置和数据带出边界策略单独批准。

## Git 与 GitHub

| 项目 | 状态 |
|---|---|
| Git | 2.54.0.windows.1 |
| Git 仓库 | 已初始化；`main` 跟踪 `origin/main` |
| 私有远程仓库 | CatEx 私有仓库（Git 托管 slug 需与产品名统一） |
| GitHub App 连接 | 已连接账号，但当前安装范围尚不能读取新私有仓库 |
| GitHub CLI | 已安装便携版 2.94.0 |
| GitHub CLI 认证 | 已认证为 `yelloooooooow`；可管理该私有仓库 |

GitHub CLI 位置：

```text
.tools\gh_2.94.0\bin\gh.exe
```

安装包已按官方 checksums 校验；SHA256：

```text
c0766af54195dfa0bcd9a0cb63a45c313fbaffdebb9f736f666e9ba4be8c91e8
```

## 分环境策略

不要把所有依赖继续塞入一个环境。建议：

1. `catex-core-py312`：平台核心、pymatgen、pytest、Ruff 和构建工具。
2. `materials-studio-mcp-py312`：Pydantic 2、MCP SDK、本地 MS 适配器，仅 Windows。
3. `mlip`：CHGNet、Fair-Chem 或其他 MLIP，可按 GPU/CPU 单独管理。
4. HPC runtime：尽量只部署平台轻量 runner、解析器和受锁定依赖；VASP 仍由模块系统提供。

每个环境应提供直接依赖清单、解析后的锁文件、平台信息和重建说明。

## 开发工具状态

PR-001 已在 `catex-core-py312` 中隔离安装：

- pytest；
- Ruff；
- build 与 hatchling。

后续按需考虑：

- mypy；
- pre-commit，仅在钩子策略确定后加入。

Pydantic、MCP SDK、Typer、quacc、jobflow、custodian 和 atomate2 不属于第一个核心 PR 的必需依赖。
