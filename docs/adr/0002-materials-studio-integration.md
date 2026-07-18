# ADR-0002：Materials Studio 作为可选本地建模适配器

- 状态：Accepted for planning baseline
- 日期：2026-07-15

## 背景

本机安装 BIOVIA Materials Studio 2023，并提供 `RunMatScript.bat` 和 Perl MaterialsScript。公开的 `Materials-Studio-mcp` 仓库证明了 MCP → Python → MaterialsScript → MatServer 路线可行，但该仓库面向 2020/20.1、没有明确开源许可证，并暴露任意 Perl 执行工具。

## 决策

不直接复制、fork 或长期依赖当前公开仓库。依据公开协议、本机官方文档和项目自己的领域模型，独立实现最小适配器。

Materials Studio 负责：

- 可选的结构导入、导出和可视化；
- 人工结构审核；
- 通过类型化工具执行受控结构变换；
- 生成新的 XSD/CIF artifact。

Materials Studio 不负责：

- 平台权威结构表示；
- INCAR、KPOINTS、POTCAR、VASPsol 或自旋协议；
- VASP/Slurm 提交；
- energy-family 判断；
- 自由能或最终科研结论。

## 安全边界

- 不提供 `run_script` 或任何自由代码接口。
- MaterialsScript 仅来自版本控制中的固定模板。
- 所有路径必须位于允许的输入根或 staging 根。
- 输出文件不得覆盖来源文件。
- 实际启动 runner 的工具均按写操作审批。
- 每次变换输出 `TransformationRecord`、父子哈希和原子映射。
- MS 输出必须由 pymatgen/ASE 独立验证，并经过人工可视化审核。

## 首个验证

在开发任何建模工具前，先完成通用结构 round-trip 比较器。随后进行：

```text
原始结构
→ MS 导入并保存新 XSD
→ MS 导出新 CIF
→ 周期结构等价性、真空、局部配位和位点映射检查
→ 人工在 MS 中审核
```

禁止在这一阶段运行 Forcite、CASTEP、VASP 或 Slurm。

## 版本策略

当前后端标识为 `materials_script_perl_2023`。未来升级到 Materials Studio 2026 后，可增加 `materials_script_python_2026`，但不能为了未安装版本提前替换当前可用路径。
