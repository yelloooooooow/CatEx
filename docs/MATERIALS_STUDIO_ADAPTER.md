# Materials Studio 安全适配器

## 定位

PR-004 为 BIOVIA Materials Studio 2023 提供可选的本地结构 import/export 适配器。Materials Studio 不是平台的权威数据模型，不管理 VASP 参数、赝势、Slurm、能量族或科研结论。

本机后端标识固定为 `materials_script_perl_2023`。Dassault Systèmes 说明 MaterialsScript 可控制三维结构文档；Python MaterialsScript 是 2026 才新增的能力，因此 2023 后端继续使用 Perl：

- [Materials Studio Visualizer and MaterialsScript](https://www.3ds.com/fileadmin/PRODUCTS-SERVICES/BIOVIA/PDF/materials-studio-visualizer.pdf)
- [Materials Studio 2026 technical note](https://www.3ds.com/support/documentation/resource-library/t61-2025-materials-studio-2026)

## 不提供任意执行

适配器没有 `run_script`、脚本文本、模块名称、shell 参数或自定义输出名入口。当前注册表只有一个操作：

```text
catex.ms.roundtrip-cif-via-xsd.v1
```

固定模板执行：

```text
source.cif → roundtrip.xsd → roundtrip.cif
```

模板只调用 Visualizer 的 Documents import/new/copy/export API，不调用 Forcite、CASTEP、DMol3、Discover 或任何计算模块。官方社区材料也说明 standalone 脚本需要显式 import，并且每个作业应使用独立目录：[Running MaterialsScripts from command line](https://3dswym.3dexperience.3ds.com/question/biovia-materials-studio/running-materialsscripts-from-command-line-with-materials-studio-4-3_T7Oy6ouYR3u1XMZ2Uaypgg)。

## 路径与写入边界

`MaterialsStudioPathPolicy` 要求：

- 输入必须是配置根目录内已经存在的 CIF；
- 输入先 resolve symlink/相对路径，再进行 containment 判断；
- 拒绝命令解释器元字符；
- staging root 必须预先存在；
- job name 只允许 1–64 位安全 ASCII；
- job 只能是 staging root 的直接新子目录；
- 已存在 job 一律拒绝，不覆盖、不续写、不自动清理；
- 输出名固定为 `roundtrip.xsd` 和 `roundtrip.cif`。

实际执行前重新计算 input、runner 和模板 SHA256，防止计划与执行之间的文件替换。执行会把已验证模板复制为固定 basename；Materials Studio 自己产生的 `.out`、MatStudioLog 和 import 中间文档均保留在该 job 目录，平台不自动删除。

## 三层审核门

1. `detect_materials_studio_capability` 只读检查 runner 和模板，不启动程序，也不宣称许可证可用。
2. `execute_materials_studio_roundtrip` 必须显式传入 `approved=True`，并只执行固定模板。
3. `audit_materials_studio_roundtrip` 用 pymatgen 独立比较源 CIF/导出 CIF，生成 atom mapping 和 `TransformationRecord`，最后要求人工在 Materials Studio 中可视化批准。

人工状态为 `pending` 或 `rejected` 时，`ready_for_downstream` 必定为 false，即使自动结构比较已经通过。

## 受控测试结果

使用仓库自建的最小 NaCl CIF 完成了本机 Materials Studio 2023 round-trip：

- runner 返回 0；
- XSD 和 CIF 均生成；
- 导出 CIF 与源 CIF 周期等价；
- source→exported 原子映射完整；
- 自动报告保持 `manual_review_state=pending`。

测试没有运行计算模块，没有覆盖来源，没有把安装文件、日志或生成结构加入 Git。
