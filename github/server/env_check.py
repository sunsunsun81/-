from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from .config import data_dir, local_tesseract_path, web_dist_dir

Issue = Dict[str, str]


def _issue(level: str, title: str, detail: str) -> Issue:
    return {"level": level, "title": title, "detail": detail}


def _module_checks() -> List[tuple]:
    return [
        ("flask", "Web 服务组件 Flask"),
        ("werkzeug", "Web 服务组件 Werkzeug"),
        ("openpyxl", "Excel 读写组件 openpyxl"),
        ("pypdf", "PDF 文本读取组件 pypdf"),
        ("fitz", "PDF 渲染组件 PyMuPDF"),
        ("PIL.Image", "图片处理组件 Pillow"),
        ("pytesseract", "OCR 调用组件 pytesseract"),
        ("zxingcpp", "二维码识别组件 zxing-cpp"),
    ]


def check_startup_environment() -> List[Issue]:
    issues: List[Issue] = []

    if sys.version_info < (3, 8):
        issues.append(_issue("error", "Python 版本过低", "当前运行时低于 Python 3.8，无法保证服务正常启动。"))

    index_file = web_dist_dir() / "index.html"
    if not index_file.exists():
        issues.append(_issue("error", "Web 前端资源缺失", f"未找到 {index_file}，请重新构建或重新安装。"))

    try:
        target = data_dir() / ".env_check.tmp"
        target.write_text("ok", encoding="utf-8")
        target.unlink()
    except Exception as exc:
        issues.append(_issue("error", "数据目录不可写", f"{data_dir()} 无法写入：{exc}"))

    return issues


def check_runtime_environment() -> List[Issue]:
    issues: List[Issue] = []

    if sys.version_info < (3, 8):
        issues.append(_issue("error", "Python 版本过低", "当前运行时低于 Python 3.8，无法保证服务正常启动。"))

    for module_name, label in _module_checks():
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            issues.append(_issue("error", label + "缺失", str(exc)))

    index_file = web_dist_dir() / "index.html"
    if not index_file.exists():
        issues.append(_issue("error", "Web 前端资源缺失", f"未找到 {index_file}，请重新构建或重新安装。"))

    tess_cmd = local_tesseract_path()
    if not tess_cmd.exists():
        issues.append(_issue("error", "Tesseract OCR 缺失", f"未找到 {tess_cmd}，扫描件 PDF/JPG 无法识别。"))
    else:
        tessdata_dir = tess_cmd.parent / "tessdata"
        for lang in ["chi_sim.traineddata", "eng.traineddata"]:
            if not (tessdata_dir / lang).exists():
                issues.append(_issue("error", "Tesseract 语言包缺失", f"未找到 {tessdata_dir / lang}。"))
        try:
            subprocess.run(
                [str(tess_cmd), "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=6,
                check=False,
            )
        except Exception as exc:
            issues.append(_issue("error", "Tesseract 无法启动", f"{exc}。请检查 OCR 目录内 DLL 是否完整。"))

    try:
        target = data_dir() / ".env_check.tmp"
        target.write_text("ok", encoding="utf-8")
        target.unlink()
    except Exception as exc:
        issues.append(_issue("error", "数据目录不可写", f"{data_dir()} 无法写入：{exc}"))

    return issues


def has_errors(issues: List[Issue]) -> bool:
    return any(issue.get("level") == "error" for issue in issues)


def format_environment_report(issues: List[Issue]) -> str:
    if not issues:
        return "环境检测通过，服务运行所需组件完整。"
    lines: List[str] = []
    for issue in issues:
        prefix = "错误" if issue.get("level") == "error" else "提示"
        lines.append(f"[{prefix}] {issue.get('title', '')}\n{issue.get('detail', '')}")
    return "\n\n".join(lines)
