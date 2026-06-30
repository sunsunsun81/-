本目录随安装包内置 Tesseract OCR。请确保存在：

tools\tesseract\tesseract.exe
tools\tesseract\tessdata\chi_sim.traineddata
tools\tesseract\tessdata\eng.traineddata

程序启动后会优先查找这里的 tesseract.exe，并自动使用本目录下的 tessdata 语言包。
若开发时替换 OCR 文件，保持以上目录结构即可。
