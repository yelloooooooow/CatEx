# Slurm 只读观察与安全续算评估

PR-007 为 Phase 3 增加一个纯解析、纯决策层：它读取调用者已经取得的固定列 Slurm 快照，与现有 VASP 输出解析结果交叉检查，并生成不可执行的续算评估记录。

它不连接超算，不运行 `squeue`/`sacct`，不调用 `sbatch`、`scancel` 或 `scontrol`，不修改 INCAR，不复制 CONTCAR/WAVECAR，也不创建续算目录。

## 为什么调度器成功不等于科学成功

Slurm 的 `COMPLETED` 和退出码描述作业/脚本层结果；VASP 是否电子收敛、离子收敛以及是否留下完整输出，需要独立检查。官方 Slurm 文档也提醒：批脚本的零退出码不保证其中关键步骤一定成功，作业输出仍需检查。

CatEx 因而只在以下证据全部成立时返回 `no_restart`：

1. 使用 `sacct` allocation record；
2. state 为 `COMPLETED`；
3. `ExitCode` 为 `0:0`；
4. VASP 正常结束；
5. 适用的电子和离子收敛均有正证据；
6. VASP 输出解析没有 error。

`squeue` 的完成状态本身不足以关闭运行记录，因为它没有最终 accounting exit code。

基础 `assess-restart` 不接收 submission receipt，因此 `no_restart` 只表示“所提供证据不提示续算”，仍列出 `verify_scheduler_vasp_run_binding` 和 `accept_scientific_result` 两个人工审核项；它不是最终科研验收。PR-010 的独立 `validate-run-binding` 可进一步绑定 job ID、plan hash、实际脚本与运行目录，但通过后仍只进入人工科学审核。详见 `RUN_BINDING.md`。

官方依据：

- [Slurm squeue](https://slurm.schedmd.com/squeue.html)
- [Slurm sacct](https://slurm.schedmd.com/sacct.html)
- [Slurm Job State Codes](https://slurm.schedmd.com/job_state_codes.html)
- [Slurm Job Exit Codes](https://slurm.schedmd.com/job_exit_code.html)

## 固定输入语法

活动作业快照使用 `squeue` 的扩展状态和 TimeUsed：

```bash
squeue --noheader --jobs=JOB_ID --format="%i|%T|%M"
```

解析格式：

```text
JobID|State|TimeUsed
12345|RUNNING|02:31
```

终态 accounting 快照使用 allocation-only、无表头、无末尾分隔符的 `sacct`：

```bash
sacct --noheader --allocations --parsable2 --jobs=JOB_ID \
  --format=JobIDRaw,State,ExitCode,ElapsedRaw
```

解析格式：

```text
JobIDRaw|State|ExitCode|ElapsedRaw
12345|COMPLETED|0:0|151
```

命令只作为站点操作说明；CatEx CLI 不执行它们。操作者先在获准环境取得快照，再把快照文件交给解析器。

## CLI

```powershell
catex parse-slurm-snapshot snapshot.txt --source sacct --job-id 12345 `
  --observed-at-utc 2026-07-15T12:34:56Z --format json

catex assess-restart calculation-directory --slurm-snapshot snapshot.txt `
  --source sacct --job-id 12345 --observed-at-utc 2026-07-15T12:34:56Z `
  --format json
```

两个命令都只读。快照最多 1 MiB，只接受 UTF-8、pipe-delimited 固定列语法和明确的 numeric/array/heterogeneous job ID。报告仅保留目标 job 行的类型化字段、快照 basename、SHA256 和字节数；原始文本、完整快照路径及其他 job 行不会进入报告。

## 决策状态

| 状态 | 含义 |
|---|---|
| `wait` | 作业仍为 pending/configuring/running/completing/suspended；不得启动第二个作业 |
| `no_restart` | `sacct COMPLETED 0:0` 与科学完整 VASP 输出一致；仍需审核 run binding 和科学结果 |
| `manual_review_required` | 失败、不收敛、输出截断、非零退出或证据冲突；需要人工决定 |
| `blocked` | 快照缺失、歧义、未知状态或格式错误，证据不足 |

`manual_review_required` 不等于允许续算。记录固定声明：

- `restart_authorized=false`；
- `restart_inputs_materialized=false`；
- `scientific_parameters_changed=false`；
- `writes_performed=false`；
- `commands_executed=false`；
- `submitted=false`。

任何真实续算必须在后续独立步骤中核对 checkpoint 完整性、原协议 identity、参数是否改变、输出保留策略，并获得新的人工批准。

## 当前边界

PR-007 只使用合成 Slurm 文本和已有合成 VASP 输出测试。它没有连接或修改超算，没有监控真实 job，也没有创建、提交、取消、requeue 或删除任何任务。
