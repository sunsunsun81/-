# -
可以被用于财务人员上传发票至服务端的数据库中，用于日常报销流程中核对发票是否被重复使用。支持最多100张的发票同时批量导入，智能读取pdf/jpg/jpeg格式的发票。更多功能正在加入，目前为测试版
# 票核通

本项目是一个本地 Windows Web 服务，用于登记和核对发票是否已经报销登记过。数据保存在程序目录下的 `data` 文件夹内，内部使用 JSON 文件，不依赖专业数据库。

## 功能

- exe 启动器：修改端口、启动/停止服务、打开网页、管理管理员。
- Web 登录：初始管理员 `管理员1`，初始密码 `123456`。
- 登记模式：上传或拖拽发票 PDF/JPG 自动识别，自动生成可编辑发票编码，弹窗二次确认后保存。
- 核对模式：支持模糊搜索，上传或拖拽 PDF/JPG 识别后核对重复，未重复时可选择保存。
- 手机扫码：移动端 Web 可扫描或拍照识别发票二维码，自动填入原始发票代码、发票号码、开票日期和金额等字段。
- Excel：提供模板、批量导入、逐条确认、疑惑 Excel 下载、导出全部历史。
- 局域网访问：服务绑定 `0.0.0.0`，接口层限制为本机和同网段 IP。

## 字段说明

- `发票编码` 是系统内部登记编号，上传或扫码识别后按当天顺序生成，例如 `2026-06-24-001`，操作员可在确认弹窗中编辑。
- `原始发票代码` 是 OCR 或二维码识别到的发票真实代码，后台优先用 `原始发票代码 + 发票号码` 判断重复。

## 开发运行

```powershell
python -m pip install -r requirements.txt
cd web
npm install
npm run build
cd ..
python launcher.py
```

启动器打开后点击“启动服务”，再点击“打开网页”。

## OCR 说明

文本型电子发票 PDF 会优先用 `pypdf` 提取文本。扫描件 PDF 和 JPG/JPEG 图片会使用内置 Tesseract OCR：

1. OCR 引擎目录：`tools\tesseract\tesseract.exe`。
2. 语言包目录：`tools\tesseract\tessdata\`。
3. 当前内置 `chi_sim.traineddata` 和 `eng.traineddata`。

安装包会把 OCR 引擎一起带到程序目录内。若开发时替换 OCR 文件，保持以上目录结构即可。

## 手机扫码说明

实时摄像头扫码依赖浏览器权限。手机通过普通局域网 `http://` 访问时，部分浏览器会禁止直接打开摄像头；此时请使用扫码弹窗里的“拍照识别”。拍照识别会先在浏览器本地解码，失败后自动上传图片到本机服务端使用二维码识别组件解码。

## 构建 exe 和安装包

兼容 Win7 的交付包必须使用 Python 3.8 环境构建，避免 Python 3.11 在 Win7 上缺少 `api-ms-win-core-path-l1-1-0.dll` 等运行时错误。当前构建脚本会强制选择 Python 3.8；如果本机没有 Python 3.8，可使用自动本地安装参数：

```powershell
.\build_exe.ps1 -BootstrapPython38
```

构建结果：

- exe 文件夹：`dist\EcoInvoiceRecon\EcoInvoiceRecon.exe`
- 安装包：`output\EcoInvoiceRecon_Setup.exe`，需要本机安装 Inno Setup 命令行工具 `ISCC.exe`

安装目录默认在当前用户的本地应用数据目录，保证程序目录内 `data` 文件夹可写。

## 数据文件

首次运行后自动生成：

- `data\admins.json`
- `data\invoices.json`
- `data\config.json`
- `data\exports\`
- `data\audit.log`

请定期备份 `data` 文件夹。
