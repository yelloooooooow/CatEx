# 工作区与共享 Python 环境

## 1. 推荐的工作区结构

当前采用以下结构：

```text
<repository-root>\
├── .venvs\
│   └── dft-common-py312\        共享科学计算环境
├── projects\
│   └── paper4_co2rr_dac_reproduction\
├── Reading-notes-code\          下载的参考仓库
└── 未来的其他目录或项目
```

环境与项目分开是合理的。删除或移动某个项目时，不会同时破坏 Python 环境；多个相关项目也可以复用相同依赖。

## 2. 共享环境能否给其他项目使用

可以，但要区分两种情况。

适合共享：

- VASP 前后处理；
- pymatgen、ASE、NumPy、SciPy；
- 相似版本的 CHGNet 结构预优化；
- PDF、CSV 和绘图分析。

建议另建环境：

- 某项目必须锁定旧版 pymatgen；
- 某项目需要特定 CUDA/PyTorch 组合；
- 两个项目的依赖版本互相冲突；
- 需要把计算环境原封不动交付给其他单位。

因此，当前共享环境适合我们的 VASP 入门和这一组 CO2RR 项目，但不应把所有未来软件无条件塞进同一个环境。

## 3. 当前环境

环境路径：

```text
.venvs\dft-common-py312
```

已验证的主要版本：

```text
Python     3.12.13
NumPy      2.5.1
pymatgen   2026.5.4
ASE        3.29.0
CHGNet     0.4.2（内部模型显示 v0.3.0）
PyTorch    2.13.0+cpu
```

完整依赖快照见 [environment-lock.txt](environment-lock.txt)。

## 4. 如何使用环境

### 方法 A：直接调用环境里的 Python

这是最不容易受到 PATH 和 Conda 初始化影响的方法：

```powershell
& ".\.venvs\dft-common-py312\python.exe" --version
```

运行脚本：

```powershell
& ".\.venvs\dft-common-py312\python.exe" .\scripts\example.py
```

### 方法 B：通过 Conda 激活

先打开 Anaconda Prompt，再执行：

```powershell
conda activate ".\.venvs\dft-common-py312"
python --version
```

退出：

```powershell
conda deactivate
```

环境路径包含空格。Python、pymatgen、ASE 和当前脚本已实际验证可以正常工作；如果某个老旧第三方程序错误处理空格，优先使用带引号的绝对路径调用。

## 5. 已完成的可用性测试

### 包导入和结构读取

环境已经成功：

- 导入 NumPy、pymatgen、ASE、CHGNet、PyTorch；
- 读取 `NiZn-N-C.cif`；
- 识别组成为 `Zn1 Ni1 C62 N6`，共 70 个原子；
- 读取晶胞体积约 2846.182 A^3。

### GitHub 结构生成脚本

已经在不修改参考仓库的前提下运行：

```text
build_slab.py --tm1 Ni --tm2 Zn --write-inputs
```

成功生成：

- `POSCAR`
- `INCAR`
- `KPOINTS`
- `structure.json`

输出位于：

```text
structures\environment_smoke_test\NiZn_NC
```

### CHGNet 推理

CHGNet 已在 CPU 上成功对 70 原子结构输出能量和 70x3 的力数组。该测试只说明软件链可运行，不说明 CHGNet 对这个缺陷催化体系达到 DFT 精度。

当前原始 CIF 上 CHGNet 给出的最大力约为 6.06 eV/A，说明原始模板在该模型看来离局部平衡较远；不能把这个数值当成 VASP 的真实力，也不能把 CHGNet 结果当作论文数据。

## 6. 环境的科学定位

本机环境负责：

- 建模；
- 生成 VASP 输入；
- 检查元素顺序和坐标；
- 批量准备任务；
- 下载后的 OUTCAR/vasprun.xml 解析；
- 自由能和机器学习分析。

超算 VASP 5.4.4 负责：

- 电子自洽；
- 原子力和结构优化；
- 吸附能；
- 电荷、磁矩、态密度；
- AIMD 等高成本计算。

Python 环境里安装 CHGNet 并不等于安装了 VASP，也不会替代 VASP 许可证。
