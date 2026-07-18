# Paper 4 HPC 环境烟雾测试

站点集成探针确认 batch 的非登录 Bash 不提供 `module`，登录 Bash 可以加载
目标 MPI module 和 PMI2。因此真实 smoke execution profile 需要
`shell_mode=login`，且站点 policy 必须显式允许 `login`。该设置只影响执行
环境，不改变科学协议，也不能使烟雾测试能量成为科研结果。

受控重试已验证上述配置：VASP 5.4.4 和 VASPsol 正常初始化，Slurm 以零退出
码完成，OUTCAR 有正常终止 footer，未发现 MPI/VASP fatal marker。真实作业
编号、目录、可执行文件路径和输出哈希只保留在受控 HPC 工作区，不进入 Git。

`environment-smoke-protocol.json` 只用于验证 VASP 5.4.4、Intel MPI、PMI2、PAW-PBE.54 和已编译 VASPsol 能否共同启动。它不是论文生产协议，所得能量不得进入吸附能、形成能、自由能或筛选数据集。

有意降低的设置：

- Gamma-only `1×1×1`；
- `NELM=4`；
- `NSW=0`；
- `LWAVE=F`、`LCHARG=F`；
- `PREC=Normal`；
- 短 walltime 和单节点小规模 MPI。

保留 `ENCUT=500`、PBE、D3(BJ)、自旋、偶极修正和 `LSOL/EB_K`，使烟雾测试能够真正经过目标二进制、赝势和溶剂代码路径。电子不收敛是该短测试的可接受结果，但 MPI/VASP fatal error、POTCAR 顺序错误、VASPsol 初始化失败或没有形成可解析输出均视为环境测试失败。

真实站点的 executable 绝对路径、用户目录、作业 ID 和原始 POTCAR 不提交 Git。运行目录必须位于人工批准的测试根之内，并使用全新子目录；不得覆盖或删除既有文件。
