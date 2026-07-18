# Supporting Information 精读与复现含义

本文档对应 `references/cs5c07689_si_001.pdf`，共 23 页。它补齐了自由能、机器学习、补充图和 91 体系数据，但没有提供可直接运行的 VASP 输入或原子坐标。

## 1. 关键页索引

| SI 页码 | 内容 | 对复现的用途 |
|---|---|---|
| 3 | CHE 自由能方法、机器学习流程 | 明确自由能修正与数据划分 |
| 8 | 不同电位下的二维火山图 | 核对描述符和电位趋势 |
| 9 | NiMn/SnNi 中间体构型、SnNi AIMD | 建立吸附初猜并理解动态稳定性 |
| 10 | 四层显式水、grand-canonical DFT 对照 | 评估隐式溶剂近似 |
| 15-18 | Table S1-S2 | 磁态与 91 体系参考结果 |
| 18-22 | Table S3-S4 | 91 体系的元素/电子特征 |

版面核验图保存在 `references/rendered/si-*.png`，300 dpi 的公式页保存在 `references/rendered/si-formula-03.png`。

## 2. 自由能方法到底补充了什么

SI 明确采用计算氢电极（CHE）。按文字说明，自由能变化包含：

```text
DeltaG = DeltaE
       + DeltaZPE
       + DeltaG_U
       + DeltaG_pH
       + Delta[Integral(0 to T) Cp dT]
       - T*DeltaS
```

其中：

- `DeltaE` 是 DFT 给出的反应/吸附能差；
- `DeltaZPE` 是零点振动能差；
- `DeltaG_U = q * U`，必须沿用论文对转移电荷 `q` 的符号约定；
- `DeltaG_pH = 2.303*kB*T*pH`，约为 `0.06*pH eV`；本文取 `pH = 0`，所以此项为零；
- 中间体的热容积分和熵来自振动能；
- 自由气相分子的焓和熵来自 NIST-JANAF 热化学表。

重要的版面问题：当前 SI PDF 的式 (1) 在积分项之后只显示一个减号，`T*DeltaS` 字样没有正常显示；但紧随其后的正文明确提到“integration and entropy terms”。上式是依据这段文字和标准热力学形式作出的明确重建，不能把 PDF 中丢失的字形误当作作者取消了熵项。

SI 仍然没有给出每个中间体的独立 ZPE/熵修正表、振动频率列表、有限差分位移、被固定原子、温度数值或对应 INCAR。因此严格数值复现需要我们自己做频率计算，并把采用的温度（通常先以 298.15 K 为工作假设）明确记录；在确认前不能声称该温度是原文明确参数。

## 3. 机器学习流程与仍缺失的信息

论文使用 Python 3.6.12 和 Scikit-learn，比较八类回归方法：

1. LASSO；
2. Ridge；
3. Elastic Net；
4. Polynomial Regression；
5. SVR；
6. Decision Tree Regression；
7. Random Forest Regression；
8. XGBoost Regression。

数据被随机拆成 4:1 的训练集和测试集。训练集内部使用 5 折交叉验证：先用较宽范围做随机搜索，再用较窄范围做网格搜索。评价指标为 RMSE、MAE 和 R2。

Table S3 给出五类属性 `epsilon_d, mu, r, n, EA` 的两金属“和/差”，共 10 列；Table S4 给出 `ED, qd, nd, EN` 的“和/差”和一个体系 `EF`，共 9 列；再加关键吸附能描述符，构成正文所说的 20 个特征。

SI 没有给出随机种子、实际训练/测试样本编号、Scikit-learn/XGBoost 版本、随机搜索与网格搜索范围、最终超参数。这意味着可以复现方法逻辑并接近论文指标，但仅凭论文和 SI 无法保证逐点得到同一组测试集预测及完全相同的 `R2 = 0.96`。

## 4. Table S2：最重要的数据表及一个列名矛盾

Table S2 含 91 行，覆盖 13 种金属的所有无序可重复组合。项目已用 `scripts/extract_si_table_s2.py` 将它转成 `results/reference_table_s2.csv`，并校验了 91 个组合完整且无重复。

需要特别警惕：Table S2 的印刷表头依次写成 `DeltaGmax(HER)`、`DeltaGmax(CO)`、`DeltaGmax(HCOOH)`；但正文给出的代表数值与表中数据对不上，而与三列循环左移后的解释完全吻合。例如：

| 体系 | Table S2 三个原始数值 | 正文声称的结果 |
|---|---|---|
| NiMn | 0.22, 0.77, 0.92 | CO 路线 0.22 eV |
| FeFe | 0.23, 0.26, 0.37 | CO 路线 0.23 eV；HCOOH 路线 0.26 eV |
| SnNi | 0.96, 0.23, 0.68 | HCOOH 路线 0.23 eV |

因此，正文一致的推断顺序很可能是：

```text
Table 原始第 1 数值 -> DeltaGmax(CO)
Table 原始第 2 数值 -> DeltaGmax(HCOOH)
Table 原始第 3 数值 -> DeltaGmax(HER)
```

这属于对论文内部证据的推断，不是 SI 明写的勘误。CSV 特意保留印刷表头，不会静默改列名。以后绘图时要同时生成“按印刷表头”和“按正文一致顺序”两版检查，并在报告中说明采用哪一种；若要投稿级复现，最好邮件向作者确认。

## 5. 磁态、AIMD 和溶剂验证

Table S1 说明 NiMn 的基态总磁矩约为 `2.7 muB`。与它相比，固定/初始目标为 0、1、2、3 `muB` 的解分别高 `0.51、0.18、0.08、0.02 eV`。这些数值说明多个近简并磁解可能存在，VASP 计算不能只使用一组 `MAGMOM`。

Figure S6 只报告 SnNi-N-C 的 AIMD：NVT、300 K、20 ps。图中 Sn-N 和 Ni-N 键长在该时间内保持稳定。但 SI 没有给出时间步长、恒温器、质量参数、k 点或 AIMD INCAR，因此暂时只能复现物理条件，不能保证逐轨迹复现。

Figure S8 对 NiMn、ZnMn、IrMn 加入四层显式水。图中隐式/显式模型的 `DeltaGmax(CO)` 分别约为：

| 体系 | 隐式 / eV | 显式 / eV | 差值 / eV |
|---|---:|---:|---:|
| NiMn | 0.25 | 0.22 | 0.03 |
| ZnMn | 0.56 | 0.53 | 0.03 |
| IrMn | 0.95 | 0.89 | 0.06 |

这支持作者用隐式溶剂进行高通量筛选的做法，但不是“所有体系、所有中间体都不受显式水影响”的证明。

## 6. SI 没有解决的结构问题

Figure S5 给出了 NiMn 和 SnNi 上 `CO2/COOH/CO/OCHO/HCOOH` 的优化构型示意，可用于设置吸附方向。它没有提供：

- POSCAR/CIF/CONTCAR；
- 晶格常数和超胞尺寸；
- 每种元素的精确原子数；
- 选择性弛豫约束；
- 中间体的笛卡尔坐标；
- POTCAR 版本、并行参数或完整 INCAR。

所以 GitHub 的 70 原子、6x6 候选模型仍是当前最实用的起点，但它只能被称为“依据公开代码建立的候选模型”。要达到原子坐标级严格复现，还需要作者的结构数据或自行从拓扑和图片重建后做构型搜索。

## 7. 对初学者最合理的复现顺序

1. 先用 GitHub NiZn 模型跑通 VASP 5.4.4、VASPsol 和结果解析；
2. 用同一拓扑替换为 NiMn，完成磁态扫描并检查是否得到约 `2.7 muB` 的低能解；
3. 计算 NiMn 的 `CO2/COOH/CO/H`，先复现 CO 路线和 HER；
4. 再计算 SnNi 的 `CO2/OCHO/HCOOH/H`，复现 HCOOH 路线；
5. 对吸附中间体做振动计算并建立 CHE 自由能表；
6. 用 Table S2 CSV 逐体系核对列顺序和数值；
7. 代表体系成功后再扩展到 91 个组合和机器学习，最后才做 AIMD、显式水和 grand-canonical 对照。

这样每一层都能回答一个明确问题，也能把“软件跑通”“模型相符”“数值相符”和“论文全部复现”四种不同程度分开。
