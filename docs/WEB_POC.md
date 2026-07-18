# CatEx Workbench 使用指南

CatEx 是 **Catalysis Exploration** 的正式简称。v0.27.0 工作台把科学核心包装为本机 Web
应用，以自动诊断连接 VASP 5.4.4 与 Slurm，并保留本地写入、远端写入和作业提交确认。

## 启动

Windows 用户在仓库根目录双击：

```text
启动 CatEx 工作台.cmd
```

启动器检查 Python、Node.js 和前端依赖，启动仅监听 `127.0.0.1` 的 API 与网页，并打开
`http://127.0.0.1:5173`。使用期间保留启动窗口；按回车可停止本次创建的前后端子进程。
如果默认端口仍被旧工作台占用，启动器会明确停止并提示关闭旧进程或选择新端口，不会把旧 API
误认为当前版本。

页面右上角的语言按钮会展开“中文 / EN”两项菜单并即时切换界面语言。选择只保存在当前浏览器的
`localStorage`，不会写入科研项目、计算配置或导出包；节点科学标识和数据 schema 不随语言变化。

命令行方式：

```powershell
pnpm web:poc
```

需要避开已占用端口时：

```powershell
node scripts/start_web_poc.mjs --api-port=8001 --web-port=5174
```

首次安装或更新 Python 依赖：

```powershell
.venvs\catex-core-py312\Scripts\python.exe -m pip install -e ".[web,dev]"
pnpm install --frozen-lockfile
```

## 推荐全流程

1. 在“项目”创建项目。
2. 在“结构工作台”选择一个本地工作文件夹。CatEx 会自动寻找结构、INCAR、KPOINTS、
   POTCAR metadata 和 Slurm 脚本；各文件卡片仍可单独“导入/替换”，替换已有来源前会确认。
3. 上传 POSCAR、CONTCAR、`.vasp` 或 CIF。CIF 会自动转换为 POSCAR；已经选择工作文件夹时，
   转换结果直接写为该文件夹中的 `POSCAR`。
4. 如需约束结构，在“选择性弛豫”中选择“仅放开吸附物原子”并填写原子序号，或选择“固定底部
   若干原子层”。CatEx 写入 POSCAR 的 `Selective dynamics` 标记并重新检查结构。
5. 在“运行中心”临时填写 SSH 资料、允许的远端项目根目录和远端 PAW-PBE 库目录，然后先执行
   “只读测试连接”。连接资料只存在于当前页面内存，也可从本机 JSON 临时导入。
6. 在“协议与输入”编辑或导入 INCAR、KPOINTS；在 POTCAR 卡片填写与 POSCAR 顺序一致的 label，
   从超算只读提取 TITEL、ENMAX、ZVAL 和 SHA-256 元数据。
7. 为计算项目命名并配置结构化 Slurm 参数。导入已有 `run.slurm` 时只采纳 `#SBATCH` 资源、
   module 和 VASP 启动参数，不执行其中任意 shell、邮件或清理命令；脚本只进入远端运行目录，
   不复制到本地工作文件夹。
8. 点击“检查输入并进入下一步”。CatEx 检查工作文件夹、POSCAR、INCAR、KPOINTS、POTCAR
   metadata、超算连接和远端项目名；缺少必需项时会直接列出，完整后写回本地三类文本输入并进入
   运行中心。
9. 明确确认后，在允许根目录下新建以项目名命名的唯一子目录，上传输入，上传并运行 CatEx
   内置的独占式 POTCAR 构建器。构建器不覆盖、不删除文件，核对分数据集和合并文件哈希；成功后
   将同一份 POTCAR 复制到用户选择的本地工作文件夹。
10. 再次明确确认后提交一次 `sbatch`。用只读 `squeue` / `sacct` 观察作业，终态后下载白名单
    结果并解析。
11. 在“计算结果”查看结束原因、是否满足 INCAR 收敛标准、电子/离子步数、能量、最大力、
    初始/最终球棍结构和自动诊断。振动计算可展示频率及谐振动校正。
12. 在“反应分析”选择 HER 或 OER 模板，绑定多个结果并生成自由能台阶图。

“工作流”页面中的节点可以双击跳到相应页面；左侧步骤也可单击跳转。“VASP 输入诊断”不是一个
需要单独批准的人工步骤，而是在结构和输入发生变化时自动执行的校验节点。

建议第一次实际验收使用一个很小、参数明确、具有独立 scratch 范围的单作业案例。不要直接
从批量筛选开始。

## 工作文件夹和 VASP 输入自动化边界

- 本地文件夹读取和写回使用 Chromium 的 File System Access API；浏览器会显示操作系统目录授权框。
  如果浏览器不支持该 API，仍可逐文件导入，但无法自动写回用户目录。
- POSCAR 来自自动检查并按 SHA-256 绑定的结构 Artifact。错误会阻止计算，警告会显示。
- POSCAR 卡片的“导入/替换”复用结构 Artifact 上传和自动检查流程。
- CIF 通过 pymatgen 解析并转换；原始 CIF 保留，转换结果命名为 `POSCAR`。
- 选择性弛豫不会猜测吸附物身份：用户必须显式给出可移动原子序号，或明确选择固定底层数。
- INCAR 与自动网格 KPOINTS 可从文件导入并替换当前可视化表单；显式 KPOINTS 暂不自动改写。
- INCAR 表格和 KPOINTS 表单修改结构化配置；点击进入下一步时才写回所选本地工作文件夹。
- 保存配置后，后端按 VASP 5.4.4 规则、POTCAR 元数据、元素顺序和 ENCUT/ENMAX 关系校验输入。
- 页面把原有的 `dry-run`、协议批准和本地物化收进“检查输入并进入下一步”：系统内部仍生成
  plan digest 以保证提交内容可追踪，但用户无需理解这些工程术语。
- POTCAR 只在远端新目录中由 CatEx 内置脚本生成，并核对每个数据集及合并文件的 SHA-256；
  随后按用户要求复制一份到已授权的本地工作文件夹。原始 POTCAR 不写入项目数据库、导出包或 Git。
- POTCAR 卡片只接受 `catex.potcar-metadata.v1` 脱敏 JSON；普通原始 POTCAR 文件不会被导入。

用户提到的“PSCAR”在 VASP 标准文件名中对应 `POSCAR`；CatEx 页面统一采用正式名称 `POSCAR`。

## 安全边界

- API 和前端只监听本机回环地址。
- SSH 私钥路径、用户名、主机与远端根目录只在当前请求内存中使用，不写项目或导出包。
- 本机连接配置 JSON 的导入只用于免去重复填写；页面刷新后需要重新导入。
- 未提供主机密钥指纹时，SSH 主机必须已存在于系统 `known_hosts`；不会自动接受未知主机。
- 远端准备只能在允许根目录中创建一个全新直接子目录，不能覆盖或删除任何已有路径。
- POTCAR 只允许由远端受控脚本生成；复制到本地前必须完成远端构建回执与 SHA-256 一致性校验，
  且只能写入用户已授权的工作文件夹。内容不进入项目数据库、导出包或 Git。
- 结果下载白名单不包含 POTCAR、WAVECAR 或 CHGCAR。
- 当前没有 cancel、requeue、自动续算、checkpoint 复制或远端清理接口。
- Paper 4 readiness 的 blocked/null 值不会被默认值静默替代。

## 项目数据

默认数据根为：

```text
staging/catex-workbench/projects/
```

可通过 `CATEX_WORKBENCH_DATA_ROOT` 改到其他本地路径。项目写入采用新建或内容寻址策略；结构
Artifact 不覆盖。导出包包含项目元数据、工作流、配置、小型输入、审计与受限结果证据，排除
敏感或大型 VASP 文件。

## 开发与验收

```powershell
pnpm web:check
pnpm web:test
pnpm web:build
.venvs\catex-core-py312\Scripts\python.exe -m pytest -q --basetemp=.test-tmp/full
```

真实 HPC 验收不属于自动测试：必须由用户明确提供项目范围、连接资料与一次具体作业授权后
单独执行，并核对服务器实际 Slurm/POTCAR 约定。
