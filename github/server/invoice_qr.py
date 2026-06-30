from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qs, urlparse

from .data_store import normalize_key_part
from .invoice_parser import clean_money, parse_invoice_text


def _first_query_value(query: Dict[str, List[str]], keys: Iterable[str]) -> str:
    lowered = {key.lower(): values for key, values in query.items()}
    for key in keys:
        values = lowered.get(key.lower())
        if values:
            return str(values[0]).strip()
    return ""


def _format_qr_date(value: str) -> str:
    digits = normalize_key_part(value)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value.strip()):
        parts = re.split(r"[-/.]", value.strip())
        return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return value.strip()


def parse_invoice_qr_text(raw_text: str) -> Dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("二维码内容为空")

    result: Dict[str, Any] = {
        "invoice_code": "",
        "original_invoice_code": "",
        "invoice_number": "",
        "issue_date": "",
        "buyer_name": "",
        "seller_name": "",
        "amount": "",
        "tax_amount": "",
        "total_amount": "",
        "remark": "",
    }

    parts = [part.strip() for part in text.split(",")]
    if len(parts) >= 6:
        result["original_invoice_code"] = normalize_key_part(parts[2])
        result["invoice_number"] = normalize_key_part(parts[3])
        result["total_amount"] = clean_money(parts[4])
        result["issue_date"] = _format_qr_date(parts[5])

    parsed_url = urlparse(text)
    if parsed_url.query:
        query = parse_qs(parsed_url.query)
        result["original_invoice_code"] = result["original_invoice_code"] or normalize_key_part(
            _first_query_value(query, ["fpdm", "invoiceCode", "invoice_code", "code"])
        )
        result["invoice_number"] = result["invoice_number"] or normalize_key_part(
            _first_query_value(query, ["fphm", "invoiceNo", "invoice_number", "number"])
        )
        result["issue_date"] = result["issue_date"] or _format_qr_date(
            _first_query_value(query, ["kprq", "invoiceDate", "issue_date", "date"])
        )
        result["total_amount"] = result["total_amount"] or clean_money(
            _first_query_value(query, ["jshj", "hjje", "totalAmount", "total_amount", "amount", "je"])
        )
        result["tax_amount"] = result["tax_amount"] or clean_money(
            _first_query_value(query, ["se", "taxAmount", "tax_amount"])
        )

    fallback = parse_invoice_text(text)
    for key in ["original_invoice_code", "invoice_number", "issue_date", "total_amount", "tax_amount", "amount"]:
        result[key] = result.get(key) or fallback.get(key, "")

    warnings = []
    for label, key in [
        ("原始发票代码", "original_invoice_code"),
        ("发票号码", "invoice_number"),
        ("开票日期", "issue_date"),
        ("价税合计", "total_amount"),
    ]:
        if not result.get(key):
            warnings.append(f"二维码未识别到{label}，请人工补充")

    result["warnings"] = warnings
    result["raw_text"] = f"二维码内容：\n{text[:5000]}"
    return result


def decode_qr_text_from_image(image_path: Path) -> str:
    try:
        import zxingcpp
        from PIL import Image
    except Exception as exc:
        raise ValueError(f"二维码图片识别组件不可用：{exc}") from exc

    try:
        with Image.open(image_path) as image:
            candidates = [image.convert("RGB"), image.convert("L")]
            for candidate in candidates:
                results = zxingcpp.read_barcodes(
                    candidate,
                    formats=zxingcpp.BarcodeFormat.QRCode,
                    try_rotate=True,
                    try_downscale=True,
                )
                for result in results:
                    text = str(getattr(result, "text", "") or "").strip()
                    if text:
                        return text
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"二维码图片读取失败：{exc}") from exc

    raise ValueError("未识别到二维码，请重新拍摄清晰、完整的发票二维码。")


def parse_invoice_qr_image(image_path: Path) -> Dict[str, Any]:
    text = decode_qr_text_from_image(image_path)
    parsed = parse_invoice_qr_text(text)
    parsed["source_file"] = image_path.name
    return parsed
