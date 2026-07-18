# HPC POTCAR metadata 与 VASP 5.4.4 注册表

PR-006 补齐 Phase 3 的两个基础契约：CatEx 实际支持的 VASP 5.4.4 INCAR 标签边界，以及不让原始 POTCAR 离开授权 HPC 的 metadata 提取路径。

## VASP 5.4.4 支持注册表

VASP 官方说明 INCAR 是决定计算行为的核心输入，设置也是错误结果的主要来源；每个 statement 采用 `TAG = VALUE`，VASP 会把其解释写入 OUTCAR，使用者应核对实际解释。因此 CatEx 不把“语法能解析”视为“平台已支持”。

`catex.vasp544-incar-registry.v1` 为每个已支持标签记录：

- value kind：logical、integer、real、real array、keyword 或 text；
- 是否进入 `energy_family_id`；
- provider：VASP 5.4.4 或 VASPsol 1.0；
- 少数固定长度数组约束，例如 DIPOL/SAXIS 必须有 3 个值。

strict 模式中，未注册标签是 error；exploration 模式中是 warning。注册表明确标注 `catex-supported-tags-not-exhaustive-vasp-manual`，避免把现代 VASP Wiki 的全部标签误称为 VASP 5.4.4 都可用。Paper 4 当前烟雾 INCAR 的全部标签都在注册表内。

查询命令只读：

```powershell
catex show-vasp544-registry --format json
```

能量族排除规则也由同一注册表维护，避免验证层和 compatibility hash 出现两套清单。

官方依据：

- [VASP Wiki: INCAR](https://vasp.at/wiki/INCAR)
- [VASP Wiki: INCAR tags](https://vasp.at/wiki/INCAR_tag)
- [VASP Wiki: ENCUT](https://vasp.at/wiki/ENCUT)
- [VASP Wiki: ISPIN](https://vasp.at/wiki/ISPIN)
- [VASP Wiki: MAGMOM](https://vasp.at/wiki/MAGMOM)

## 为什么 POTCAR 只能在 HPC 边界读取

VASP 官方说明 POTCAR 是只读输入，多元素 dataset 必须与 POSCAR 元素顺序一致；header 中包含 TITEL、LEXCH、ZVAL、ENMAX 等复现信息，且每个 dataset 以 `End of Dataset` 结束。原始 POTCAR 受许可证约束，不进入 Git，也不复制到本地开发环境。

参考：

- [VASP Wiki: POTCAR](https://vasp.at/wiki/POTCAR)
- [VASP Wiki: Preparing a POTCAR](https://vasp.at/wiki/Preparing_a_POTCAR)

## 提取器安全边界

`extract-potcar-metadata` 默认不打开源文件。只有显式传入 `--authorized-hpc-read` 才会读取；这个 flag 记录操作者确认，但不能替代 VASP 许可证、文件权限或机构政策。

```bash
catex extract-potcar-metadata POTCAR \
  --potential-family PAW_PBE_54 \
  --authorized-hpc-read \
  --format metadata-json
```

实现行为：

- 二进制逐行读取，不把整个 POTCAR 载入内存；
- 为整个文件和每个 dataset 计算 exact-byte SHA256；
- 只保留 TITEL、LEXCH、ZVAL、ENMAX、元素和 potential label；
- 输出只包含源 basename，不含完整 HPC 路径；
- 不保留 tabulated pseudopotential data；
- 不接受 output path，只写 stdout；
- 不含 SSH、上传、调度器或文件删除功能；
- 任一 dataset 缺字段、字段冲突或缺终止标记时，拒绝输出部分 metadata。

成功时 `metadata-json` 符合 `catex.potcar-metadata.v1`，可供 `validate-vasp-input` 和 `resolve-protocol` 使用。完整审计格式 `json` 额外包含 source SHA256、字节数和安全声明。

## 当前验收状态

自动测试只使用明确写有 `SYNTHETIC` 的短文本夹具，它不是 VASP potential，也不包含厂商数据。PR-006 不连接、上传或运行超算端代码，不读取真实 POTCAR，不创建 metadata 文件。

真实执行前仍需人工确认：

1. 授权的 POTCAR 文件与 potential family；
2. 在 HPC 上运行的 CatEx 代码版本/commit；
3. metadata 是否允许带出 HPC，或只保存在受控项目目录；
4. POSCAR 元素顺序与 dataset 顺序；
5. 真实 VASP/VASPsol executable 入口。
