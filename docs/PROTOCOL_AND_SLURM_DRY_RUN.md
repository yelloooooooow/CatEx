# 科学协议解析与 Slurm dry-run

PR-009 增加 `shell_mode=nonlogin|login`。该字段属于执行环境，不进入
`energy_family_id`。省略字段时保持 `nonlogin`；`login` 必须同时出现在
`SlurmClusterPolicy.allowed_shell_modes` 中，渲染结果才使用
`#!/bin/bash -l`。验证器仍拒绝其他 shebang、任意初始化命令和 shell 片段。

PR-005 把“计算什么”和“在哪里、用多少资源运行”拆成两个独立契约，并实现只生成不提交的安全路径。

## 范围与非目标

当前实现支持：

- 目标版本固定为 VASP 5.4.4；
- 显式 INCAR 字符串值；
- Gamma 或 Monkhorst-Pack 三维规则网格；
- 脱敏 POTCAR metadata 的顺序与哈希契约；
- `ResolvedProtocol`、人工审核记录和 `energy_family_id`；
- allowlist 驱动的 Slurm 资源与脚本静态验证；
- 人工批准后的本地新目录物化。

当前不支持：

- 自动补默认参数或“优化”论文协议；
- line-mode、显式 k-point 或 automatic-length 的协议生成；
- 读取、复制或生成原始 POTCAR；
- `sbatch`、`scancel`、SSH、远程写、监控或续算；
- 任意 shell、任意 module 命令或任意启动命令；
- 未经人工科学审核的物化。

## 两个配置层

`ScientificProtocol` 只描述科学设置：VASP 版本、INCAR 和 KPOINTS。POTCAR 的准确数据集身份来自单独的 `catex.potcar-metadata.v1` 文件，避免把受许可证保护的 POTCAR 内容带入本地仓库。

`SlurmExecutionProfile` 描述 partition、节点、每节点 task、每 task CPU、walltime、module、MPI plugin 和 VASP 可执行文件。executable 可以是安全 basename，也可以是精确 allowlist 的绝对 POSIX 路径；后者用于 VASP 不在默认 PATH 的站点。路径拒绝相对形式、`.`/`..`、空组件、空格和 shell 控制字符，且必须与 `SlurmClusterPolicy.allowed_executables` 逐字一致。`SlurmClusterPolicy` 同时提供其他站点 allowlist 与资源上限；两者都不进入能量族。

合成、可公开测试示例位于 `tests/fixtures/synthetic/workflow/`；其中 POTCAR metadata 的标识和 hash 均为测试占位，不代表真实赝势。

## 能量兼容性规则

`energy_family_id` 是规范 JSON payload 的 SHA256，包含：

- 目标 VASP 版本；
- 除下述明确排除项之外的全部显式 INCAR 值；
- KPOINTS generation mode、subdivisions 和 shift；
- POTCAR family，以及按 POSCAR 元素顺序记录的 label、TITEL、LEXCH、ZVAL、ENMAX 和每个 dataset SHA256。

明确排除的 INCAR 项由版本化 VASP 5.4.4 支持注册表统一声明，目前只有：

```text
KPAR LCHARG LPLANE LWAVE NCORE NPAR NSIM NWRITE SYSTEM
```

这些项仅控制并行布局、输出保留或标签。其他显式 INCAR 值采用保守策略全部进入能量族；例如 ENCUT、ISMEAR、SIGMA、ISPIN、MAGMOM、DFT+U、色散和溶剂相关设置都会改变签名。

Slurm partition、节点数、核数、walltime、module、MPI plugin、可执行文件、job name 和 protocol ID 不进入能量族。改变 NCORE 不改变 `energy_family_id`，但会改变绑定全部输入与源 artifact 的 `resolved_protocol_sha256`，因此仍可追踪。

## 人工审核门

解析成功的协议初始状态总是 `pending`。自动化不能自我批准。调用者必须以 reviewer、UTC 时间和说明生成独立 `ProtocolReview`；审核只改变审核状态，不改变能量族或 resolved protocol digest。

未批准协议可以生成无写入计划，但 `ready_for_materialization=false`。本地物化还要求调用者显式传入 `approved_write=True`。这两个门缺一不可。

## Slurm 固定语法

生成器只产生以下结构：

```bash
#!/bin/bash
#SBATCH --job-name=...
#SBATCH --partition=...
#SBATCH --nodes=...
#SBATCH --ntasks-per-node=...
#SBATCH --cpus-per-task=...
#SBATCH --time=...
#SBATCH --output=slurm-%j.out
set -euo pipefail
module purge
module load <allowlisted-module>
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
srun --mpi=<allowlisted-plugin> <allowlisted-executable>
```

验证器拒绝未知/重复 directive、目录型输出、超限资源、未允许 module/executable/MPI plugin，以及 `sbatch`、`scancel`、删除命令、shell 控制符和重定向。绝对 executable 不是任意命令字段，只接受固定路径 grammar 和 policy 精确匹配。实现中没有运行 shell 或调度器的函数。

Slurm 官方文档说明：`sbatch` 用于请求作业分配，而批处理脚本中的任务通常由 `srun` 启动；`--ntasks-per-node`、`--cpus-per-task` 和 `--output` 分别描述任务布局、每任务 CPU 与输出模式。PMI2 只有在 MPI 实现兼容 Slurm PMI2 plugin 时才能使用。本项目因此把这些值设为站点 policy，而不是通用默认值：

- [Slurm sbatch](https://slurm.schedmd.com/sbatch.html)
- [Slurm srun](https://slurm.schedmd.com/srun.html)
- [Slurm MPI Users Guide](https://slurm.schedmd.com/mpi_guide.html)

## 本地物化结果

批准后的 API 只在预先存在的 destination root 下创建一个全新直接子目录，并以 exclusive create 写入：

```text
POSCAR
INCAR
KPOINTS
catex-potcar-metadata.json
catex-manifest.json
slurm.sh
```

它不会创建 `POTCAR`。manifest 明确声明 `potcar_required_on_hpc=true`、`potcar_materialized=false`、`submitted=false`。写入前会重新哈希 POSCAR 和 plan；目录已存在、源文件变化、审核未通过或 Slurm 验证失败都会阻止写入。写入过程中若发生错误，部分目录保留供审计，不执行清理或删除。

公共 CLI 只有 `resolve-protocol` 和 `plan-vasp-job`，均不写文件。当前没有 materialize CLI，避免把一次命令行确认误当成科学审核记录。

## HPC 兼容性边界

站点能力必须通过只读调查建立 policy：Slurm/VASP 版本、partition、节点核心数、module、MPI plugin 和 executable。当前已确认 Slurm/srun 23.11.3、PMI2 plugin、64 核节点、Intel/MPI module，以及一个具有执行权限的 VASP 5.4.4.pl2 绝对路径；VASPsol 已编译进入该二进制。VASP 不在默认 PATH，也没有 VASP/VASPsol module，因此真实 profile 必须使用绝对 executable。真实路径含站点身份信息，不提交 Git；仓库测试只使用合成 `/opt/...` 路径。

PR-005 可用本地合成输入验证这些约束，但不提交烟雾作业。真实 POTCAR metadata 仍应在授权 HPC 上生成并留在受控边界；原始 POTCAR 不得离开超算或进入 Git。
