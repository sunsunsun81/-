from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import local_tesseract_path

MONEY_PATTERN = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+\.[0-9]{1,2})"


def clean_money(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"(\d)\s*\.\s*(\d{1,2})", r"\1.\2", text)
    text = text.replace(",", "").replace("￥", "").replace("¥", "")
    text = text.replace("锟?", "").replace("楼", "").replace("元", "")
    return text.strip()


def clean_text_value(value: Optional[str]) -> str:
    if not value:
        return ""
    text = re.sub(r"[ \t]+", " ", str(value))
    text = text.strip(" :：　\t\r\n")
    text = re.split(r"(纳税人识别号|统一社会信用代码|地址|电话|开户行|账号|站\s|$)", text)[0]
    return text.strip(" :：　\t\r\n")


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _first_match(patterns: List[str], text: str, flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return ""


def normalize_invoice_date(value: Optional[str]) -> str:
    text = (value or "").replace(" ", "").strip()
    if not text:
        return ""
    match = re.match(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日?", text)
    if not match:
        match = re.match(r"([0-9]{4})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})", text)
    if not match:
        match = re.match(r"([0-9]{4})([0-9]{2})([0-9]{2})", text)
    if not match:
        return text.replace("/", "-").replace(".", "-")
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        datetime(year, month, day)
    except ValueError:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _money_text(text: str) -> str:
    text = re.sub(r"(\d)\s*\.\s*(\d{1,2})", r"\1.\2", text)
    text = text.replace("，", ",")
    return text


def _money_candidates(text: str) -> List[str]:
    prepared = _money_text(text)
    candidates = [clean_money(value) for value in re.findall(MONEY_PATTERN, prepared)]
    result: List[str] = []
    for value in candidates:
        if not value or value in result:
            continue
        if re.fullmatch(r"\d{4}", value):
            continue
        result.append(value)
    return result


def _drop_field_warnings(warnings: List[str], labels: List[str]) -> List[str]:
    if not labels:
        return warnings
    result: List[str] = []
    for warning in warnings:
        if any(label in warning for label in labels) and (
            warning.startswith("未识别到")
            or "候选填入" in warning
            or warning.startswith("二维码未识别到")
        ):
            continue
        result.append(warning)
    return result


def parse_invoice_text(text: str) -> Dict[str, Any]:
    normalized = normalize_text(text)
    compact = re.sub(r"\s+", "", normalized)
    money_source = _money_text(normalized)
    compact_money_source = _money_text(compact)
    warnings: List[str] = []

    invoice_code = _first_match(
        [
            r"发\s*票\s*代\s*码[:：]?\s*([0-9]{10,12})",
            r"(?<!社会信用)代码[:：]?\s*([0-9]{10,12})",
        ],
        normalized,
    )
    if not invoice_code:
        invoice_code = _first_match([r"发票代码[:：]?([0-9]{10,12})"], compact)

    invoice_number = _first_match(
        [
            r"发\s*票\s*号\s*码[:：]?\s*([0-9]{6,20})",
            r"票\s*据\s*号\s*码[:：]?\s*([0-9]{6,20})",
            r"No\.?\s*([0-9]{6,20})",
        ],
        normalized,
    )
    if not invoice_number:
        invoice_number = _first_match([r"发票号码[:：]?([0-9]{6,20})"], compact)
    if not invoice_number:
        number_candidates = re.findall(r"(?<![0-9])([0-9]{16,20})(?![0-9])", normalized)
        if number_candidates:
            invoice_number = number_candidates[0]
            warnings.append("发票号码按数字候选填入，请核对")

    issue_date = _first_match(
        [
            r"开\s*票\s*日\s*期[:：]?\s*([0-9]{4}\s*年\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日?)",
            r"开\s*票\s*日\s*期[:：]?\s*([0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2})",
            r"开\s*票\s*日\s*期[:：]?\s*([0-9]{8})",
        ],
        normalized,
    )
    if not issue_date:
        issue_date = _first_match(
            [
                r"开票日期[:：]?([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日?)",
                r"开票日期[:：]?([0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2})",
                r"开票日期[:：]?([0-9]{8})",
            ],
            compact,
        )
    issue_date = normalize_invoice_date(issue_date)
    if not issue_date:
        date_candidates = re.findall(
            r"([0-9]{4}\s*年\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日?|[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}|[0-9]{8})",
            normalized,
        )
        for candidate in date_candidates:
            issue_date = normalize_invoice_date(candidate)
            if issue_date:
                warnings.append("开票日期按日期候选填入，请核对")
                break

    buyer_name = clean_text_value(
        _first_match(
            [
                r"购买方名称[:：]?\s*([^\n\r]+)",
                r"购买方[\s\S]{0,120}?名称[:：]?\s*([^\n\r|]+)",
            ],
            normalized,
        )
    )
    seller_name = clean_text_value(
        _first_match(
            [
                r"销售方名称[:：]?\s*([^\n\r]+)",
                r"销售方[\s\S]{0,120}?名称[:：]?\s*([^\n\r|]+)",
            ],
            normalized,
        )
    )

    total_amount = clean_money(
        _first_match(
            [
                rf"价\s*税\s*合\s*计[\s\S]{{0,80}}?[¥￥]?\s*{MONEY_PATTERN}",
                rf"[（(]小\s*写[）)]\s*[¥￥]?\s*{MONEY_PATTERN}",
                rf"票\s*价[:：]?\s*[¥￥]?\s*{MONEY_PATTERN}",
            ],
            money_source,
        )
    )
    if not total_amount:
        total_amount = clean_money(
            _first_match(
                [
                    rf"价税合计[\s\S]{{0,80}}?[¥￥]?{MONEY_PATTERN}",
                    rf"[（(]小写[）)]?[¥￥]?{MONEY_PATTERN}",
                    rf"票价[:：]?[¥￥]?{MONEY_PATTERN}",
                ],
                compact_money_source,
            )
        )
    if not total_amount:
        money_candidates = _money_candidates(money_source)
        if money_candidates:
            total_amount = money_candidates[-1]
            warnings.append("价税合计按金额候选填入，请核对")

    amount = clean_money(
        _first_match(
            [
                rf"金\s*额[:：]?\s*[¥￥]?\s*{MONEY_PATTERN}",
                rf"合\s*计[\s\S]{{0,30}}?[¥￥]\s*{MONEY_PATTERN}\s*[¥￥]\s*{MONEY_PATTERN}",
            ],
            money_source,
        )
    )
    tax_amount = clean_money(
        _first_match(
            [
                rf"税\s*额[:：]?\s*[¥￥]?\s*{MONEY_PATTERN}",
                rf"税额[^\n\r0-9]{{0,20}}{MONEY_PATTERN}",
            ],
            money_source,
        )
    )

    for label, value in [
        ("发票号码", invoice_number),
        ("开票日期", issue_date),
        ("价税合计", total_amount),
    ]:
        if not value:
            warnings.append(f"未识别到{label}，请人工补充")

    return {
        "invoice_code": "".join(ch for ch in invoice_code if ch.isdigit()),
        "original_invoice_code": "".join(ch for ch in invoice_code if ch.isdigit()),
        "invoice_number": "".join(ch for ch in invoice_number if ch.isdigit()),
        "issue_date": issue_date,
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "amount": amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "remark": "",
        "warnings": warnings,
        "raw_text": normalized[:5000],
    }


def extract_text_with_pypdf(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    chunks: List[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    return "\n".join(chunks).strip()


def extract_text_with_fitz(pdf_path: Path) -> str:
    import fitz

    chunks: List[str] = []
    doc = fitz.open(str(pdf_path))
    for page in doc:
        chunks.append(page.get_text("text") or "")
    return "\n".join(chunks).strip()


def configure_tesseract() -> Optional[str]:
    explicit = os.environ.get("TESSERACT_CMD")
    candidates = [
        Path(explicit) if explicit else None,
        local_tesseract_path(),
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    return shutil.which("tesseract")


def tesseract_config(tess_cmd: str) -> str:
    tessdata_dir = Path(tess_cmd).resolve().parent / "tessdata"
    if tessdata_dir.exists():
        return f'--tessdata-dir "{tessdata_dir}" --psm 6'
    return "--psm 6"


def _pdf_page_images(pdf_path: Path, scale: float = 2.5):
    import fitz
    from PIL import Image

    doc = fitz.open(str(pdf_path))
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        yield Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def decode_qr_texts_from_pdf(pdf_path: Path) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    texts: List[str] = []
    try:
        import zxingcpp
    except Exception as exc:
        return [], [f"二维码识别组件不可用：{exc}"]
    try:
        for image in _pdf_page_images(pdf_path, scale=2.5):
            for candidate in [image.convert("RGB"), image.convert("L")]:
                results = zxingcpp.read_barcodes(
                    candidate,
                    formats=zxingcpp.BarcodeFormat.QRCode,
                    try_rotate=True,
                    try_downscale=True,
                )
                for result in results:
                    text = str(getattr(result, "text", "") or "").strip()
                    if text and text not in texts:
                        texts.append(text)
    except Exception as exc:
        warnings.append(f"PDF 二维码识别失败：{exc}")
    return texts, warnings


def decode_qr_texts_from_image(image_path: Path) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    texts: List[str] = []
    try:
        import zxingcpp
        from PIL import Image
    except Exception as exc:
        return [], [f"二维码识别组件不可用：{exc}"]
    try:
        with Image.open(image_path) as image:
            for candidate in [image.convert("RGB"), image.convert("L")]:
                results = zxingcpp.read_barcodes(
                    candidate,
                    formats=zxingcpp.BarcodeFormat.QRCode,
                    try_rotate=True,
                    try_downscale=True,
                )
                for result in results:
                    text = str(getattr(result, "text", "") or "").strip()
                    if text and text not in texts:
                        texts.append(text)
    except Exception as exc:
        warnings.append(f"图片二维码识别失败：{exc}")
    return texts, warnings


def extract_text_with_ocr(pdf_path: Path) -> Tuple[str, List[str]]:
    warnings: List[str] = []
    tess_cmd = configure_tesseract()
    if not tess_cmd:
        return "", ["未找到 Tesseract OCR，扫描件无法自动识别；请确认内置 tools/tesseract/tesseract.exe 存在，或安装到系统 PATH"]

    try:
        import pytesseract
    except Exception as exc:
        return "", [f"OCR 组件不可用：{exc}"]

    pytesseract.pytesseract.tesseract_cmd = tess_cmd
    config = tesseract_config(tess_cmd)
    text_chunks: List[str] = []
    try:
        for image in _pdf_page_images(pdf_path, scale=3):
            text_chunks.append(pytesseract.image_to_string(image, lang="chi_sim+eng", config=config))
    except Exception as exc:
        warnings.append(f"OCR 识别失败：{exc}")
    return "\n".join(text_chunks).strip(), warnings


def extract_text_from_image(image_path: Path) -> Tuple[str, List[str]]:
    warnings: List[str] = []
    tess_cmd = configure_tesseract()
    if not tess_cmd:
        return "", ["未找到 Tesseract OCR，JPG 图片无法自动识别；请确认内置 tools/tesseract/tesseract.exe 存在，或安装到系统 PATH"]

    try:
        import pytesseract
        from PIL import Image
    except Exception as exc:
        return "", [f"OCR 组件不可用：{exc}"]

    pytesseract.pytesseract.tesseract_cmd = tess_cmd
    config = tesseract_config(tess_cmd)
    try:
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng", config=config)
        return text.strip(), warnings
    except Exception as exc:
        return "", [f"JPG 图片 OCR 识别失败：{exc}"]


def _merge_qr_result(parsed: Dict[str, Any], qr_texts: List[str], warnings: List[str]) -> Tuple[Dict[str, Any], List[str], List[str]]:
    raw_parts: List[str] = []
    if not qr_texts:
        return parsed, warnings, raw_parts

    from .invoice_qr import parse_invoice_qr_text

    for text in qr_texts:
        raw_parts.append(f"二维码内容：\n{text}")
        try:
            qr_parsed = parse_invoice_qr_text(text)
        except Exception as exc:
            warnings.append(f"二维码内容解析失败：{exc}")
            continue
        confirmed_labels: List[str] = []
        for key in ["original_invoice_code", "invoice_number", "issue_date", "total_amount", "tax_amount", "amount"]:
            value = qr_parsed.get(key)
            if value:
                parsed[key] = value
                if key == "invoice_number":
                    confirmed_labels.append("发票号码")
                elif key == "issue_date":
                    confirmed_labels.append("开票日期")
                elif key == "total_amount":
                    confirmed_labels.append("价税合计")
        if confirmed_labels:
            parsed["warnings"] = _drop_field_warnings(list(parsed.get("warnings", [])), confirmed_labels)
            warnings = _drop_field_warnings(warnings, confirmed_labels)
        parsed["invoice_code"] = parsed.get("invoice_code") or parsed.get("original_invoice_code", "")
        for warning in qr_parsed.get("warnings", []):
            if "原始发票代码" in warning:
                continue
            warnings.append(warning)
    return parsed, warnings, raw_parts


def _finish_parse(parsed: Dict[str, Any], warnings: List[str], raw_parts: List[str], source_name: str) -> Dict[str, Any]:
    current_warnings = list(parsed.get("warnings", []))
    deduped_warnings: List[str] = []
    for warning in warnings + current_warnings:
        if warning and warning not in deduped_warnings:
            deduped_warnings.append(warning)
    parsed["warnings"] = deduped_warnings
    raw_text = "\n\n".join(part for part in raw_parts if part.strip()).strip()
    parsed["raw_text"] = raw_text[:5000]
    parsed["source_file"] = source_name
    return parsed


def parse_pdf(pdf_path: Path) -> Dict[str, Any]:
    warnings: List[str] = []
    raw_parts: List[str] = []
    qr_texts, qr_warnings = decode_qr_texts_from_pdf(pdf_path)
    warnings.extend(qr_warnings)

    text_chunks: List[str] = []
    try:
        text = extract_text_with_pypdf(pdf_path)
        if text:
            text_chunks.append(text)
    except Exception as exc:
        warnings.append(f"PDF 文本提取失败：{exc}")
    try:
        fitz_text = extract_text_with_fitz(pdf_path)
        if fitz_text and fitz_text not in text_chunks:
            text_chunks.append(fitz_text)
    except Exception as exc:
        warnings.append(f"PDF 版面文本提取失败：{exc}")

    text = normalize_text("\n".join(text_chunks))
    if len(re.sub(r"\s+", "", text)) < 80:
        ocr_text, ocr_warnings = extract_text_with_ocr(pdf_path)
        warnings.extend(ocr_warnings)
        if ocr_text:
            text = normalize_text("\n".join([part for part in [text, ocr_text] if part]))

    if text:
        raw_parts.append(f"文本/OCR原文：\n{text}")
    parsed = parse_invoice_text(text)
    parsed, warnings, qr_raw_parts = _merge_qr_result(parsed, qr_texts, warnings)
    raw_parts = qr_raw_parts + raw_parts
    return _finish_parse(parsed, warnings, raw_parts, pdf_path.name)


def parse_image(image_path: Path) -> Dict[str, Any]:
    warnings: List[str] = []
    raw_parts: List[str] = []
    qr_texts, qr_warnings = decode_qr_texts_from_image(image_path)
    warnings.extend(qr_warnings)
    text, ocr_warnings = extract_text_from_image(image_path)
    warnings.extend(ocr_warnings)
    if text:
        raw_parts.append(f"文本/OCR原文：\n{text}")
    parsed = parse_invoice_text(text)
    parsed, warnings, qr_raw_parts = _merge_qr_result(parsed, qr_texts, warnings)
    raw_parts = qr_raw_parts + raw_parts
    return _finish_parse(parsed, warnings, raw_parts, image_path.name)


def parse_invoice_file(file_path: Path) -> Dict[str, Any]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(file_path)
    if suffix in {".jpg", ".jpeg"}:
        return parse_image(file_path)
    raise ValueError("仅支持 PDF、JPG、JPEG 文件")
