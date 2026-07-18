# 提交回执与运行证据绑定

PR-010 增加一个纯读取、不可执行的运行绑定层。它解决的是“这些 Slurm 与 VASP
证据是否属于同一次已批准提交”，不负责提交、监控、续算或接受科学结果。

## 绑定的五类证据

`validate-run-binding` 同时交叉检查：

1. 独立提交回执中的 job ID、目录名、job name、plan SHA256 和 `slurm.sh` SHA256；
2. 物化阶段 `catex-manifest.json` 中的 plan、job 和脚本身份；
3. 运行目录中实际 `slurm.sh` 的原始字节 SHA256；
4. 调用者提供、且必须包含回执 job ID 的固定列 Slurm 快照；
5. 同一运行目录内 OUTCAR/OSZICAR 的终止与收敛证据。

回执是一次单独获批提交完成后留下的审计记录。CatEx 的这个入口只解析既有回执，
不会生成或补写回执，也不能把一个缺失的真实提交记录“推断”出来。

## 提交回执 schema

回执使用 `catex.submission-receipt.v1`，字段集合固定：

```json
{
  "schema_version": "catex.submission-receipt.v1",
  "submitted_at_utc": "2026-01-01T00:00:00Z",
  "job_id": "12345",
  "job_directory_name": "calculation-001",
  "job_name": "calculation-001",
  "plan_sha256": "<64 lowercase hex characters>",
  "slurm_script_sha256": "<64 lowercase hex characters>",
  "submission_command_template": "sbatch --chdir=<authorized-job-directory> --parsable <authorized-job-directory>/slurm.sh",
  "raw_submission_output_sha256": "<64 lowercase hex characters>",
  "submission_performed": true,
  "approved_scope": "authorized-scope-id",
  "scientific_result_eligible": true,
  "overwrite_performed": false,
  "deletion_performed": false
}
```

解析器拒绝未知/缺失字段、非 UTC 时间、非规范标识符、非小写 SHA256、改变后的提交
命令模板，以及任何声称发生覆盖或删除的回执。回执最大 64 KiB；报告仅保留 basename、
SHA256、字节数和类型化字段，不保留原始 JSON 或完整源路径。

`scientific_result_eligible` 是提交时不可放宽的用途门禁。生产科学候选必须显式为
`true`，但这仍不表示结果已经接受；还必须通过绑定、调度/VASP 完整性和 PR-011 人工
审核。环境烟雾、调试或其他非生产运行必须为 `false`，后续审核只能拒绝，不能把该次
运行升级为科研数据；需要科研结果时应使用获批生产协议创建全新运行和回执。

## CLI

```powershell
catex validate-run-binding calculation-directory `
  --submission-receipt submission-receipt.json `
  --slurm-snapshot sacct-snapshot.txt `
  --source sacct `
  --observed-at-utc 2026-01-01T00:10:00Z `
  --format json
```

job ID 不由 CLI 另行输入，而是从独立回执取得，再用于筛选 Slurm 快照。这避免调用者
不小心把一个成功 job 的状态与另一个输出目录拼接。

## 状态语义

| 状态 | 含义 |
|---|---|
| `error` | 回执、manifest、实际脚本、目录或 scheduler 绑定无效；不得接受结果 |
| `active` | 证据已绑定，但同一 job 仍处于活动状态；不得启动第二个作业 |
| `terminal_review_required` | job 已终止，但调度或 VASP 科学完整性不足；必须人工诊断 |
| `scientific_review_required` | 绑定有效、`sacct COMPLETED 0:0` 且 VASP 科学完整；仍需人工接受或拒绝结果 |

即使处于 `scientific_review_required`，报告仍固定声明：

- `scientific_result_accepted=false`；
- `additional_submission_performed=false`；
- `writes_performed=false`；
- `commands_executed=false`。

本模块没有 SSH、`sbatch`、`squeue`、`sacct`、`scancel`、requeue、checkpoint 复制、
文件写入或删除接口。真实续算和后续生产提交需要新的、范围明确的人工授权。

达到 `scientific_review_required` 后，可把类型化报告交给 PR-011 的
`record_scientific_result_review`。后者需要显式审核人、时间、决定和说明；不会由本模块
自动调用。详见 `SCIENTIFIC_RESULT_REVIEW.md`。
