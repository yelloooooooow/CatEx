# ADR-0003：模板优先的本地 Web Workbench

- 状态：Accepted for proof of concept
- 日期：2026-07-16

## 背景

CatEx v0.24.0 已提供确定性的科学核心、版本化记录和人工审核门，但操作入口仍以
Python API 与 CLI 为主。项目需要直观的结构查看、模板向导、节点图、运行状态和结果审核，
同时不能因 Web 开发弱化科学 provenance 或扩大 HPC 授权。

## 决策

采用以下分层：

1. `catex` 继续作为无 Web、数据库和 SSH 依赖的科学核心；
2. `catex_app` 提供 UI 无关的工作流合同和有界应用服务；
3. `catex_web` 是可选 FastAPI 适配器；
4. `apps/web` 使用 React、TypeScript 和 React Flow；
5. POC 只绑定本机开发服务，使用合成数据，不连接 HPC；
6. 模板向导和节点画布必须表示同一个版本化 workflow revision；
7. UI 图是计划表达，不替代 CatEx 的结构、协议、运行和结果身份。

## POC 安全边界

- 结构上传最大 5 MiB，只接受 POSCAR/CONTCAR/CIF；
- 上传文件在临时目录中检查，响应返回后不保留；
- 不读取 POTCAR，不接受 SSH 密钥，不运行 VASP 或 Slurm；
- 合成结果永久标记为不可进入科研派生；
- 前后端分别验证节点端口，后端结果具有最终权威；
- 不开放任意路径、shell、脚本或远程命令字段。

## 后续门禁

在本地 POC 通过可用性、安全和核心回归测试之前，不增加数据库、持久 Artifact、SSH、
真实运行提交或自动续算。HPC 适配器必须另立 ADR 和显式授权模型。

POC 结构查看器暂用 WEAS 0.2.10 并单独按需加载。其发布包包含一处 `eval`，因此未来启用
严格 Content Security Policy 或部署到非本机环境前，必须完成上游修复、受控构建或替换
查看器；该依赖当前不能获得生产安全批准。
