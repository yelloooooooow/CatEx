# VASP 5.4.4 input validation

PR-002 提供只读输入验证，不生成、规范化或覆盖 POSCAR、INCAR、KPOINTS、POTCAR，也不启动 VASP。

## 命令

```powershell
catex validate-vasp-input calculation-directory --mode strict --format json
```

可用模式：

- `strict`：格式错误、数据维度错误以及缺失的关键科研元数据均阻止继续；
- `exploration`：格式和维度错误仍阻止继续，但允许缺失 POTCAR metadata 等科研策略项以 warning 形式等待人工补充。

命令返回 0 表示没有 error；warning 不会被静默隐藏。JSON 报告包含本地输入路径，不应未经脱敏直接公开。

## INCAR

验证器直接解析原始文本，而不是只读取 pymatgen 合并后的字典，因此可以发现：

- 大小写不敏感的重复标签；
- 分号分隔的多个 statement；
- `#` 和 `!` 注释；
- 反斜杠续行及其尾部空白风险；
- 空值、未闭合引号和 VASP 5.4.4 不支持的 statement 形式；
- MAGMOM 的 `n*value` 展开；
- 共线 `NIONS` 与非共线 `3×NIONS` 长度；
- ISPIN、LNONCOLLINEAR、LSORBIT、NSW/IBRION、DFT+U 数组和 VASPsol 能力声明。

## KPOINTS 与二维体系

regular mesh 会记录中心方式、三轴 subdivisions 和 shift。验证器使用周期结构检查得到的最小环形占据区间估计真空轴，并检查：

- 六方晶格是否采用 Gamma-centered mesh；
- 真空轴 subdivisions 是否为 1；
- 真空轴 shift 是否为 0；
- Gamma mesh 是否被非零 user shift 移离 Gamma；
- LDIPOL/IDIPOL 是否与唯一检测到的 slab 真空轴一致。

explicit、line-mode、automatic-length 和 generalized regular mesh 会被识别，但 PR-002 不宣称已验证其 k-point density。

## 脱敏 POTCAR metadata

默认文件名为 `catex-potcar-metadata.json`。示例中的值和哈希均为虚构数据：

```json
{
  "schema_version": "catex.potcar-metadata.v1",
  "potential_family": "PAW_PBE",
  "datasets": [
    {
      "element": "Ti",
      "potential_label": "Ti_pv",
      "titel": "PAW_PBE Ti_pv example-date",
      "lexch": "PE",
      "zval": 10.0,
      "enmax_eV": 400.0,
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    }
  ]
}
```

规则：

- dataset element 顺序必须与 POSCAR species 顺序一致；
- PBE family 的 LEXCH 应为 `PE`；
- ENCUT 低于最大 ENMAX 时必须显式报告；
- SHA256 必须为 64 位十六进制；
- 原始 POTCAR 即使出现在目录中也不会被 CatEx 打开或哈希。

metadata 只证明“记录的 header 和 hash 是什么”，不能证明赝势许可证、HPC 文件权限、VASP 编译能力或计算协议已经通过人工科学审核。

## 官方语义来源

- [INCAR format](https://vasp.at/wiki/INCAR)
- [MAGMOM](https://vasp.at/wiki/MAGMOM)
- [KPOINTS](https://vasp.at/wiki/KPOINTS)
- [POTCAR](https://vasp.at/wiki/POTCAR)
- [Preparing a POTCAR](https://vasp.at/wiki/Preparing_a_POTCAR)
- [ENCUT](https://vasp.at/wiki/ENCUT)
