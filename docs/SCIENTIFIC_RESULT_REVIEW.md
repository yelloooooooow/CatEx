# 显式科学结果审核记录

PR-011 在 PR-010 的只读 run binding 之后增加一个纯内存人工审核记录。目标是区分：

- 证据链完整，可以开始科学审核；
- 审核人明确拒绝该结果；
- 审核人明确接受该结果用于同一能量族内的后续派生分析。

调度器成功、VASP 正常结束或 run binding 通过都不会自动生成接受记录。

## 前置门禁

`record_scientific_result_review` 只接受具有完整类型化身份的终态 run binding：

- submission receipt 有效；
- manifest、plan、实际 `slurm.sh` 和目录身份一致；
- scheduler allocation 与回执 job ID 一致；
- manifest 中的科学协议已经人工批准；
- submission receipt 明确声明 `scientific_result_eligible=true`；
- manifest SHA256、resolved protocol SHA256、energy family 和 VASP artifact SHA256 均可绑定。

处于 `active` 或 `error` 的绑定不能建立科学审核记录。处于
`terminal_review_required` 的运行只能被拒绝；只有
`scientific_review_required`、`sacct COMPLETED 0:0` 且 VASP 科学完整的运行才允许被接受。

## 纯 API

```python
from catex import record_scientific_result_review

review = record_scientific_result_review(
    binding_report,
    accepted=True,
    reviewer="reviewer-id",
    reviewed_at_utc="2026-01-01T00:10:00Z",
    note="Protocol, energy, forces, and magnetization reviewed.",
)
```

本阶段故意不提供一键接受 CLI。调用方必须在受控的人工审核界面或明确的 Python
审核步骤中传入决定、审核人、UTC 时间和非空单行说明。时间不得早于绑定的 scheduler
observation。

## 绑定身份与哈希

`binding_identity_sha256` 规范化绑定：

- submission receipt SHA256 与不可放宽的科学用途资格；
- job ID 与输出目录 basename；
- plan、manifest、resolved protocol 和 Slurm script SHA256；
- `energy_family_id`；
- scheduler 状态、退出码、信号与观察时间；
- VASP 终止/收敛状态和 artifact basename/SHA256。

`review_sha256` 进一步绑定决定、审核人、审核时间、说明和
`binding_identity_sha256`。任一已绑定 artifact 字节改变都会产生不同审核身份。

这些 SHA256 是完整性和 provenance 指纹，不是电子签名，也不能证明字符串中的审核人
就是某个真实用户。身份认证、角色授权和不可抵赖签名属于后续治理/服务层；在此之前，
调用方必须控制谁可以调用接受操作，不能让 agent 或批处理自动填写“人工审核”。

## 接受的严格含义

接受记录会声明：

- `scientific_result_accepted=true`；
- `eligible_for_same_energy_family_derivation=true`；
- `human_review_recorded=true`；
- `automatic_acceptance_performed=false`。

这只允许结果进入相同 `energy_family_id` 的后续候选集合。它不表示不同参考态可以相减，
不验证吸附能/自由能公式，不允许跨泛函、POTCAR、溶剂、自旋或数值协议混用，也不等于
论文结论已经成立。

拒绝记录始终声明 scientific acceptance 与派生资格为 false。两类记录都固定声明未写
文件、未执行命令、未新增提交。
