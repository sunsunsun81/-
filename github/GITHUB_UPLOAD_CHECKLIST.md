# GitHub 上传版清单

此目录是从当前项目整理出的 GitHub 上传版源码备份。

## 已包含

- `server/` 后端源码
- `web/src/`、`web/public/`、`web/package.json`、`web/package-lock.json` 前端源码与依赖锁定文件
- `assets/` 图标资源
- `docs/` 使用说明文档与说明书
- `installer/` 安装脚本
- `tests/` 后端测试
- `tools/tesseract/` 内置 OCR 运行时和语言包
- `build_exe.ps1`、`EcoInvoiceRecon.spec`、`launcher.py`、`README.md`、`requirements.txt`、`require.txt`

## 已排除

- `data/` 本机运行数据和用户数据库
- `dist/`、`build/`、`output/`、`.build/` 打包产物和构建缓存
- `web/node_modules/`、`web/dist/` 前端依赖和前端构建产物
- `tmp/`、`.tmp/`、`test-results/` 临时文件和测试产物
- `agent_work_log.md`、`agentworkingrules.md` Agent 内部工作记录和规则
- `__pycache__/`、`*.pyc` 等 Python 缓存

## 上传前建议

1. 进入本目录后初始化仓库：`git init`
2. 检查将要提交的文件：`git status`
3. 前端依赖重新安装：`cd web && npm install`
4. 后端依赖按 README 或 `requirements.txt` 安装
5. 如果不希望 GitHub 仓库包含 OCR 二进制运行时，可删除 `tools/tesseract/` 后再提交，并在 README 中说明需要用户自行安装 Tesseract。
