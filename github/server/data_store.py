from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import APP_VERSION, data_dir
from .security import hash_password, new_secret_key, verify_password

DEFAULT_ADMIN = "管理员1"
DEFAULT_PASSWORD = "123456"
DEFAULT_COMPANY_ID = "default"
DEFAULT_COMPANY_NAME = "默认公司"
RETENTION_DAYS = 548

INVOICE_FIELDS = [
    "invoice_code",
    "original_invoice_code",
    "invoice_number",
    "issue_date",
    "buyer_name",
    "seller_name",
    "amount",
    "tax_amount",
    "total_amount",
    "remark",
]


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_key_part(value: Optional[str]) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def normalize_record_code(value: Optional[str]) -> str:
    return str(value or "").strip()


def normalize_company_name(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_original_invoice_code(invoice: Dict[str, Any]) -> str:
    original_code = normalize_key_part(invoice.get("original_invoice_code"))
    if original_code:
        return original_code

    # Compatibility for records created before "invoice_code" became an internal
    # editable registration code.
    legacy_code = normalize_record_code(invoice.get("invoice_code"))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{3,}", legacy_code):
        return ""
    legacy_digits = normalize_key_part(legacy_code)
    if 10 <= len(legacy_digits) <= 12:
        return legacy_digits
    return ""


def invoice_key(invoice: Dict[str, Any]) -> str:
    number = normalize_key_part(invoice.get("invoice_number"))
    if not number:
        return ""
    return f"number::{number}"


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [(text[:19], "%Y-%m-%d %H:%M:%S"), (text[:10], "%Y-%m-%d")]
    for candidate, fmt in candidates:
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


class JsonStore:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.admins_path = self.base_dir / "admins.json"
        self.config_path = self.base_dir / "config.json"
        self.companies_path = self.base_dir / "companies.json"
        self.company_root = self.base_dir / "companies"
        self.audit_path = self.base_dir / "audit.log"
        self.legacy_invoices_path = self.base_dir / "invoices.json"
        self.invoices_path = self.company_invoices_path(DEFAULT_COMPANY_ID)
        self._lock = threading.RLock()
        self.ensure_initialized()

    def ensure_initialized(self) -> None:
        with self._lock:
            self.company_root.mkdir(parents=True, exist_ok=True)
            if not self.companies_path.exists():
                self._write_json(
                    self.companies_path,
                    {
                        "companies": [
                            {
                                "id": DEFAULT_COMPANY_ID,
                                "name": DEFAULT_COMPANY_NAME,
                                "created_at": now_iso(),
                                "created_by": DEFAULT_ADMIN,
                            }
                        ]
                    },
                )
            else:
                self._normalize_companies()

            self._ensure_company_storage(DEFAULT_COMPANY_ID)

            if not self.admins_path.exists():
                self._write_json(
                    self.admins_path,
                    {
                        "admins": [
                            {
                                "username": DEFAULT_ADMIN,
                                "password_hash": hash_password(DEFAULT_PASSWORD),
                                "created_at": now_iso(),
                                "companies": [DEFAULT_COMPANY_ID],
                                "current_company_id": DEFAULT_COMPANY_ID,
                            }
                        ]
                    },
                )
            else:
                self._normalize_admins()

            if not self.config_path.exists():
                self._write_json(
                    self.config_path,
                    {"port": 8080, "secret_key": new_secret_key(), "version": APP_VERSION},
                )

    def _read_json(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if not path.exists():
                return default
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                backup = path.with_suffix(path.suffix + f".broken-{datetime.now().strftime('%Y%m%d%H%M%S')}")
                shutil.copy2(path, backup)
                return default

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(path)

    def append_audit(self, actor: str, action: str, detail: str = "") -> None:
        line = f"{now_iso()}\t{actor}\t{action}\t{detail}\n"
        with self._lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def get_config(self) -> Dict[str, Any]:
        cfg = self._read_json(self.config_path, {})
        changed = False
        if "port" not in cfg:
            cfg["port"] = 8080
            changed = True
        if "secret_key" not in cfg:
            cfg["secret_key"] = new_secret_key()
            changed = True
        if cfg.get("version") != APP_VERSION:
            cfg["version"] = APP_VERSION
            changed = True
        if changed:
            self._write_json(self.config_path, cfg)
        return cfg

    def set_port(self, port: int) -> None:
        if port < 1 or port > 65535:
            raise ValueError("端口号必须在 1 到 65535 之间")
        cfg = self.get_config()
        cfg["port"] = port
        self._write_json(self.config_path, cfg)

    def list_admins(self) -> List[str]:
        payload = self._read_json(self.admins_path, {"admins": []})
        return [item["username"] for item in payload.get("admins", []) if item.get("username")]

    def _load_admin_records(self) -> List[Dict[str, Any]]:
        payload = self._read_json(self.admins_path, {"admins": []})
        return list(payload.get("admins", []))

    def _save_admin_records(self, records: List[Dict[str, Any]]) -> None:
        self._write_json(self.admins_path, {"admins": records})

    def _normalize_admins(self) -> None:
        records = self._load_admin_records()
        changed = False
        for item in records:
            companies = item.get("companies")
            if companies is None:
                item["companies"] = [DEFAULT_COMPANY_ID]
                changed = True
            elif not isinstance(companies, list):
                item["companies"] = [str(companies)]
                changed = True

            current = item.get("current_company_id")
            if current and current not in item["companies"]:
                item["current_company_id"] = item["companies"][0] if item["companies"] else ""
                changed = True
            elif "current_company_id" not in item:
                item["current_company_id"] = item["companies"][0] if item["companies"] else ""
                changed = True
        if changed:
            self._save_admin_records(records)

    def _find_admin(self, username: str) -> Optional[Dict[str, Any]]:
        for admin in self._load_admin_records():
            if admin.get("username") == username:
                return admin
        return None

    def validate_admin(self, username: str, password: str) -> bool:
        admin = self._find_admin(username)
        if not admin:
            return False
        return verify_password(password, admin.get("password_hash", ""))

    def add_admin(self, actor: str, actor_password: str, username: str, password: str) -> None:
        username = username.strip()
        if not username:
            raise ValueError("管理员账号不能为空")
        if len(password) < 6:
            raise ValueError("密码至少需要 6 位")
        if not self.validate_admin(actor, actor_password):
            raise PermissionError("当前管理员密码验证失败")
        records = self._load_admin_records()
        if any(item.get("username") == username for item in records):
            raise ValueError("管理员账号已存在")
        records.append(
            {
                "username": username,
                "password_hash": hash_password(password),
                "created_at": now_iso(),
                "companies": [],
                "current_company_id": "",
            }
        )
        self._save_admin_records(records)
        self.append_audit(actor, "add_admin", username)

    def change_admin_password(
        self,
        actor: str,
        actor_password: str,
        target_username: str,
        new_password: str,
    ) -> None:
        if len(new_password) < 6:
            raise ValueError("新密码至少需要 6 位")
        if not self.validate_admin(actor, actor_password):
            raise PermissionError("当前管理员密码验证失败")
        records = self._load_admin_records()
        found = False
        for item in records:
            if item.get("username") == target_username:
                item["password_hash"] = hash_password(new_password)
                item["updated_at"] = now_iso()
                found = True
                break
        if not found:
            raise ValueError("目标管理员不存在")
        self._save_admin_records(records)
        self.append_audit(actor, "change_admin_password", target_username)

    def _normalize_companies(self) -> None:
        payload = self._read_json(self.companies_path, {"companies": []})
        companies = list(payload.get("companies", []))
        changed = False
        if not any(item.get("id") == DEFAULT_COMPANY_ID for item in companies):
            companies.insert(
                0,
                {
                    "id": DEFAULT_COMPANY_ID,
                    "name": DEFAULT_COMPANY_NAME,
                    "created_at": now_iso(),
                    "created_by": DEFAULT_ADMIN,
                },
            )
            changed = True
        for item in companies:
            if not item.get("id"):
                item["id"] = self._new_company_id()
                changed = True
            if not item.get("name"):
                item["name"] = DEFAULT_COMPANY_NAME if item["id"] == DEFAULT_COMPANY_ID else item["id"]
                changed = True
            if not item.get("created_at"):
                item["created_at"] = now_iso()
                changed = True
        if changed:
            self._write_json(self.companies_path, {"companies": companies})

    def _load_companies(self) -> List[Dict[str, Any]]:
        payload = self._read_json(self.companies_path, {"companies": []})
        return list(payload.get("companies", []))

    def _save_companies(self, companies: List[Dict[str, Any]]) -> None:
        self._write_json(self.companies_path, {"companies": companies})

    def _new_company_id(self) -> str:
        return f"CMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    def _safe_company_id(self, company_id: Optional[str]) -> str:
        candidate = str(company_id or DEFAULT_COMPANY_ID).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
            raise ValueError("公司标识不合法")
        return candidate

    def company_dir(self, company_id: Optional[str]) -> Path:
        return self.company_root / self._safe_company_id(company_id)

    def company_invoices_path(self, company_id: Optional[str]) -> Path:
        return self.company_dir(company_id) / "invoices.json"

    def company_questionable_path(self, company_id: Optional[str]) -> Path:
        return self.company_dir(company_id) / "questionable.json"

    def _ensure_company_storage(self, company_id: Optional[str]) -> None:
        invoices_path = self.company_invoices_path(company_id)
        if not invoices_path.exists():
            self._write_json(invoices_path, {"items": []})
        questionable_path = self.company_questionable_path(company_id)
        if not questionable_path.exists():
            self._write_json(questionable_path, {"items": []})

    def _company_by_id(self, company_id: Optional[str]) -> Optional[Dict[str, Any]]:
        target = self._safe_company_id(company_id)
        for item in self._load_companies():
            if item.get("id") == target:
                return item
        return None

    def company_exists(self, company_id: Optional[str]) -> bool:
        try:
            return self._company_by_id(company_id) is not None
        except ValueError:
            return False

    def admin_can_access_company(self, username: str, company_id: Optional[str]) -> bool:
        admin = self._find_admin(username)
        if not admin:
            return False
        return self._safe_company_id(company_id) in (admin.get("companies") or [])

    def list_companies_for_admin(self, username: str) -> List[Dict[str, Any]]:
        admin = self._find_admin(username)
        if not admin:
            return []
        allowed = set(admin.get("companies") or [])
        admin_counts = self._company_admin_counts()
        companies = [self._company_with_admin_count(item, admin_counts) for item in self._load_companies() if item.get("id") in allowed]
        companies.sort(key=lambda item: item.get("created_at", ""))
        return companies

    def get_current_company(self, username: str) -> Optional[Dict[str, Any]]:
        admin = self._find_admin(username)
        if not admin:
            return None
        allowed = list(admin.get("companies") or [])
        if not allowed:
            return None
        current = admin.get("current_company_id")
        if current in allowed and self.company_exists(current):
            return self._company_with_admin_count(self._company_by_id(current) or {})
        for company_id in allowed:
            if self.company_exists(company_id):
                self.set_current_company(username, company_id)
                return self._company_with_admin_count(self._company_by_id(company_id) or {})
        return None

    def _company_admin_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for admin in self._load_admin_records():
            for company_id in admin.get("companies") or []:
                counts[str(company_id)] = counts.get(str(company_id), 0) + 1
        return counts

    def _company_with_admin_count(
        self,
        company: Dict[str, Any],
        counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        item = dict(company)
        company_id = str(item.get("id", ""))
        item["admin_count"] = (counts or self._company_admin_counts()).get(company_id, 0)
        item.setdefault("remark", "")
        return item

    def company_admin_count(self, company_id: Optional[str]) -> int:
        company_id = self._safe_company_id(company_id)
        return self._company_admin_counts().get(company_id, 0)

    def _grant_company_to_admin(self, username: str, company_id: str, switch: bool = True) -> None:
        records = self._load_admin_records()
        found = False
        for item in records:
            if item.get("username") == username:
                companies = list(item.get("companies") or [])
                if company_id not in companies:
                    companies.append(company_id)
                item["companies"] = companies
                if switch:
                    item["current_company_id"] = company_id
                found = True
                break
        if not found:
            raise ValueError("管理员不存在")
        self._save_admin_records(records)

    def create_or_join_company(self, actor: str, name: str, remark: str = "") -> Dict[str, Any]:
        company_name = normalize_company_name(name)
        if not company_name:
            raise ValueError("公司名称不能为空")
        with self._lock:
            companies = self._load_companies()
            normalized = company_name.casefold()
            company = next((item for item in companies if normalize_company_name(item.get("name")).casefold() == normalized), None)
            if not company:
                company = {
                    "id": self._new_company_id(),
                    "name": company_name,
                    "remark": str(remark or "").strip(),
                    "created_at": now_iso(),
                    "created_by": actor,
                }
                companies.append(company)
                self._save_companies(companies)
            self._ensure_company_storage(company["id"])
            self._grant_company_to_admin(actor, company["id"], switch=True)
            self.append_audit(actor, "create_or_join_company", f"{company['id']}\t{company_name}")
            return self._company_with_admin_count(company)

    def update_company(self, actor: str, company_id: str, name: str, remark: str = "") -> Dict[str, Any]:
        company_id = self._safe_company_id(company_id)
        if not self.admin_can_access_company(actor, company_id):
            raise PermissionError("当前管理员无权修改该公司")
        company_name = normalize_company_name(name)
        if not company_name:
            raise ValueError("公司名称不能为空")
        with self._lock:
            companies = self._load_companies()
            normalized = company_name.casefold()
            for item in companies:
                if item.get("id") != company_id and normalize_company_name(item.get("name")).casefold() == normalized:
                    raise ValueError("同名公司已存在")
            for item in companies:
                if item.get("id") == company_id:
                    item["name"] = company_name
                    item["remark"] = str(remark or "").strip()
                    item["updated_at"] = now_iso()
                    self._save_companies(companies)
                    self.append_audit(actor, "update_company", company_id)
                    return self._company_with_admin_count(item)
        raise ValueError("公司不存在")

    def remove_company_for_admin(
        self,
        actor: str,
        company_id: str,
        delete_database: bool = False,
        password: str = "",
    ) -> Dict[str, Any]:
        company_id = self._safe_company_id(company_id)
        company = self._company_by_id(company_id)
        if not company:
            raise ValueError("公司不存在")
        if not self.admin_can_access_company(actor, company_id):
            raise PermissionError("当前管理员无权删除该公司")

        admin_count = self.company_admin_count(company_id)
        is_last_admin = admin_count <= 1
        if delete_database:
            if not is_last_admin:
                raise ValueError("仍有其他管理员可访问该公司，不能删除公司数据库")
            if not self.validate_admin(actor, password):
                raise PermissionError("当前管理员密码验证失败")

        records = self._load_admin_records()
        for item in records:
            companies = [cid for cid in (item.get("companies") or []) if cid != company_id]
            if item.get("username") == actor or delete_database:
                item["companies"] = companies
                if item.get("current_company_id") == company_id:
                    item["current_company_id"] = companies[0] if companies else ""
        self._save_admin_records(records)

        database_deleted = False
        if delete_database and is_last_admin:
            companies = [item for item in self._load_companies() if item.get("id") != company_id]
            self._save_companies(companies)
            shutil.rmtree(self.company_dir(company_id), ignore_errors=True)
            database_deleted = True

        current_company = self.get_current_company(actor)
        self.append_audit(
            actor,
            "delete_company_database" if database_deleted else "remove_company_from_admin",
            company_id,
        )
        return {
            "removed": True,
            "last_admin": is_last_admin,
            "database_deleted": database_deleted,
            "current_company": current_company,
            "items": self.list_companies_for_admin(actor),
        }

    def set_current_company(self, username: str, company_id: str) -> Dict[str, Any]:
        company_id = self._safe_company_id(company_id)
        company = self._company_by_id(company_id)
        if not company:
            raise ValueError("公司不存在")
        if not self.admin_can_access_company(username, company_id):
            raise PermissionError("当前管理员无权访问该公司")
        records = self._load_admin_records()
        for item in records:
            if item.get("username") == username:
                item["current_company_id"] = company_id
                break
        self._save_admin_records(records)
        self._ensure_company_storage(company_id)
        self.append_audit(username, "switch_company", company_id)
        return self._company_with_admin_count(company)

    def _require_company(self, company_id: Optional[str]) -> str:
        company_id = self._safe_company_id(company_id)
        if not self.company_exists(company_id):
            raise ValueError("公司不存在")
        self._ensure_company_storage(company_id)
        return company_id

    def _read_company_items(self, company_id: Optional[str]) -> List[Dict[str, Any]]:
        company_id = self._require_company(company_id)
        payload = self._read_json(self.company_invoices_path(company_id), {"items": []})
        items = list(payload.get("items", []))
        return self._purge_expired_items(company_id, items)

    def _write_company_items(self, company_id: Optional[str], items: List[Dict[str, Any]]) -> None:
        company_id = self._require_company(company_id)
        self._write_json(self.company_invoices_path(company_id), {"items": items})

    def _purge_expired_items(self, company_id: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
        kept: List[Dict[str, Any]] = []
        expired_count = 0
        for item in items:
            created_at = _parse_datetime(item.get("created_at"))
            if created_at and created_at < cutoff:
                expired_count += 1
                continue
            kept.append(item)
        if expired_count:
            self._write_json(self.company_invoices_path(company_id), {"items": kept})
            self.append_audit("system", "purge_expired_invoices", f"{company_id}\t{expired_count}")
        return kept

    def purge_expired_invoices(self, company_id: Optional[str] = None) -> int:
        company_id = self._require_company(company_id)
        payload = self._read_json(self.company_invoices_path(company_id), {"items": []})
        before = len(payload.get("items", []))
        self._purge_expired_items(company_id, list(payload.get("items", [])))
        after_payload = self._read_json(self.company_invoices_path(company_id), {"items": []})
        return before - len(after_payload.get("items", []))

    def _filter_by_created_range(
        self,
        items: Iterable[Dict[str, Any]],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        start = _parse_datetime(start_date)
        end = _parse_datetime(end_date)
        if end and len(str(end_date or "")) <= 10:
            end = end + timedelta(days=1) - timedelta(seconds=1)
        result: List[Dict[str, Any]] = []
        for item in items:
            created_at = _parse_datetime(item.get("created_at"))
            if start and created_at and created_at < start:
                continue
            if end and created_at and created_at > end:
                continue
            result.append(item)
        return result

    def list_invoices(
        self,
        company_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        items = self._read_company_items(company_id)
        return self._filter_by_created_range(items, start_date, end_date)

    def next_daily_invoice_code(self, company_id: Optional[str] = None, date_text: Optional[str] = None) -> str:
        if company_id and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(company_id)) and date_text is None:
            date_text = str(company_id)
            company_id = None
        day = date_text if date_text and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text) else datetime.now().strftime("%Y-%m-%d")
        legacy_day = day.replace("-", "")
        max_index = 0
        for item in self.list_invoices(company_id):
            code = normalize_record_code(item.get("invoice_code"))
            match = re.fullmatch(rf"{re.escape(day)}-(\d{{3,}})", code)
            if not match:
                match = re.fullmatch(rf"{legacy_day}(\d{{3,}})", code)
            if match:
                max_index = max(max_index, int(match.group(1)))
        return f"{day}-{max_index + 1:03d}"

    def search_invoices(self, company_id: Optional[str] = None, query: str = "", code: str = "", number: str = "") -> List[Dict[str, Any]]:
        if company_id and not self.company_exists(company_id):
            number = code
            code = query
            query = str(company_id)
            company_id = None

        query_norm = query.strip().lower()
        code_norm = normalize_key_part(code)
        number_norm = normalize_key_part(number)
        results: List[Dict[str, Any]] = []
        for item in self.list_invoices(company_id):
            haystack = " ".join(
                str(item.get(field, ""))
                for field in [
                    "invoice_code",
                    "original_invoice_code",
                    "invoice_number",
                    "issue_date",
                    "buyer_name",
                    "seller_name",
                    "amount",
                    "tax_amount",
                    "total_amount",
                    "remark",
                    "created_by",
                ]
            ).lower()
            code_digits = normalize_key_part(item.get("invoice_code"))
            original_code_digits = normalize_key_part(item.get("original_invoice_code"))
            if code_norm and code_norm not in code_digits and code_norm not in original_code_digits:
                continue
            if number_norm and number_norm not in normalize_key_part(item.get("invoice_number")):
                continue
            if query_norm and query_norm not in haystack:
                compact_digits = normalize_key_part(haystack)
                if normalize_key_part(query_norm) not in compact_digits:
                    continue
            results.append(item)
        return results

    def _resolve_company_invoice_args(
        self,
        company_or_invoice: Any,
        invoice: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        if isinstance(company_or_invoice, dict):
            return DEFAULT_COMPANY_ID, company_or_invoice
        if invoice is None:
            raise ValueError("发票数据不能为空")
        return self._safe_company_id(company_or_invoice), invoice

    def find_duplicate(self, company_or_invoice: Any, invoice: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        company_id, invoice_data = self._resolve_company_invoice_args(company_or_invoice, invoice)
        key = invoice_key(invoice_data)
        if not key:
            return None
        for item in self.list_invoices(company_id):
            if invoice_key(item) == key:
                return item
        return None

    def find_duplicates_all_companies(self, invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
        key = invoice_key(invoice)
        if not key:
            return []
        matches: List[Dict[str, Any]] = []
        for company in self._load_companies():
            company_id = company.get("id")
            if not company_id:
                continue
            try:
                items = self.list_invoices(company_id)
            except ValueError:
                continue
            for item in items:
                if invoice_key(item) == key:
                    matches.append(
                        {
                            "company_id": company_id,
                            "company_name": company.get("name", company_id),
                            "invoice": dict(item),
                        }
                    )
        return matches

    def _clean_invoice_for_storage(self, invoice: Dict[str, Any], actor: str, invoice_code: str, invoice_number: str) -> Dict[str, Any]:
        clean = {field: str(invoice.get(field, "") or "").strip() for field in INVOICE_FIELDS}
        clean["invoice_code"] = invoice_code
        clean["original_invoice_code"] = normalize_original_invoice_code(clean)
        clean["invoice_number"] = invoice_number
        clean["created_by"] = actor
        clean["updated_at"] = now_iso()
        return clean

    def add_invoice(
        self,
        company_or_invoice: Any,
        invoice: Optional[Dict[str, Any]] = None,
        actor: str = "",
        allow_update: bool = False,
        allow_duplicate: bool = False,
    ) -> Dict[str, Any]:
        company_id, invoice_data = self._resolve_company_invoice_args(company_or_invoice, invoice)
        company_id = self._require_company(company_id)
        key = invoice_key(invoice_data)
        invoice_code = normalize_record_code(invoice_data.get("invoice_code")) or self.next_daily_invoice_code(company_id)
        invoice_number = normalize_key_part(invoice_data.get("invoice_number"))
        if not invoice_code or not invoice_number:
            raise ValueError("发票编码和发票号码不能为空")

        items = self._read_company_items(company_id)
        duplicate_index = next((idx for idx, item in enumerate(items) if key and invoice_key(item) == key), None)
        if key:
            duplicates = self.find_duplicates_all_companies(invoice_data)
            has_external_duplicate = any(str(item.get("company_id", "")) != company_id for item in duplicates)
            if duplicates and (has_external_duplicate or duplicate_index is None or not allow_update):
                raise FileExistsError("发票号码已存在，重复发票禁止入库")

        code_conflict_index = next(
            (
                idx
                for idx, item in enumerate(items)
                if normalize_record_code(item.get("invoice_code")).lower() == invoice_code.lower()
                and (not key or invoice_key(item) != key)
            ),
            None,
        )
        if duplicate_index is None and code_conflict_index is not None:
            duplicate_index = code_conflict_index

        now = now_iso()
        clean = self._clean_invoice_for_storage(invoice_data, actor, invoice_code, invoice_number)
        clean["company_id"] = company_id

        if duplicate_index is not None:
            if not allow_update:
                raise FileExistsError("该发票已登记或发票编码已存在")
            existing = items[duplicate_index]
            clean["id"] = existing.get("id")
            clean["created_at"] = existing.get("created_at", now)
            items[duplicate_index] = {**existing, **clean}
            action = "update_invoice"
        else:
            clean.setdefault("id", f"INV-{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
            clean["created_at"] = now
            items.append(clean)
            action = "add_invoice"

        self._write_company_items(company_id, items)
        self.append_audit(actor, action, f"{company_id}\t{key}")
        return clean

    def add_invoices(self, company_or_invoices: Any, invoices: Optional[Iterable[Dict[str, Any]]] = None, actor: str = "") -> int:
        if invoices is None:
            company_id = DEFAULT_COMPANY_ID
            invoice_iter = company_or_invoices
        else:
            company_id = self._safe_company_id(company_or_invoices)
            invoice_iter = invoices
        count = 0
        for invoice in invoice_iter:
            self.add_invoice(company_id, invoice, actor=actor)
            count += 1
        return count

    def delete_invoice(self, company_or_invoice_id: str, invoice_id: Optional[str] = None, actor: str = "") -> bool:
        if invoice_id is None:
            company_id = DEFAULT_COMPANY_ID
            target_invoice_id = company_or_invoice_id
        else:
            company_id = self._safe_company_id(company_or_invoice_id)
            target_invoice_id = invoice_id
        items = self._read_company_items(company_id)
        kept = [item for item in items if item.get("id") != target_invoice_id]
        if len(kept) == len(items):
            return False
        self._write_company_items(company_id, kept)
        self.append_audit(actor, "delete_invoice", f"{company_id}\t{target_invoice_id}")
        return True

    def delete_invoices(self, company_id: Optional[str], invoice_ids: Iterable[str], actor: str = "") -> int:
        company_id = self._safe_company_id(company_id)
        target_ids = {str(invoice_id) for invoice_id in invoice_ids if invoice_id}
        if not target_ids:
            return 0
        items = self._read_company_items(company_id)
        kept = [item for item in items if str(item.get("id", "")) not in target_ids]
        deleted = len(items) - len(kept)
        if deleted:
            self._write_company_items(company_id, kept)
            self.append_audit(actor, "delete_invoices", f"{company_id}\t{deleted}")
        return deleted

    def list_invoice_ids(self, company_id: Optional[str], query: str = "", code: str = "", number: str = "") -> List[str]:
        return [str(item.get("id")) for item in self.search_invoices(company_id, query, code, number) if item.get("id")]

    def _read_questionable_items(self, company_id: Optional[str]) -> List[Dict[str, Any]]:
        company_id = self._require_company(company_id)
        payload = self._read_json(self.company_questionable_path(company_id), {"items": []})
        return list(payload.get("items", []))

    def _write_questionable_items(self, company_id: Optional[str], items: List[Dict[str, Any]]) -> None:
        company_id = self._require_company(company_id)
        self._write_json(self.company_questionable_path(company_id), {"items": items})

    def list_questionable(self, company_id: Optional[str]) -> List[Dict[str, Any]]:
        items = self._read_questionable_items(company_id)
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return items

    def add_questionable(self, company_id: Optional[str], record: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
        company_id = self._require_company(company_id)
        file_name = str(record.get("file_name", "") or "").strip()
        if not file_name:
            raise ValueError("文件名不能为空")
        item = {
            "id": f"QST-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            "company_id": company_id,
            "file_name": file_name,
            "reason": str(record.get("reason", "") or "重复发票").strip(),
            "note": str(record.get("note", "") or "").strip(),
            "invoice_number": normalize_key_part(record.get("invoice_number")),
            "original_invoice_code": normalize_key_part(record.get("original_invoice_code")),
            "duplicate_company_id": str(record.get("duplicate_company_id", "") or "").strip(),
            "duplicate_company_name": str(record.get("duplicate_company_name", "") or "").strip(),
            "status": str(record.get("status", "") or "").strip(),
            "created_by": actor,
            "created_at": now_iso(),
        }
        items = self._read_questionable_items(company_id)
        items.append(item)
        self._write_questionable_items(company_id, items)
        self.append_audit(actor, "add_questionable", f"{company_id}\t{file_name}\t{item['reason']}")
        return item

    def delete_questionable(self, company_id: Optional[str], record_id: str, actor: str = "") -> bool:
        company_id = self._require_company(company_id)
        items = self._read_questionable_items(company_id)
        kept = [item for item in items if item.get("id") != record_id]
        if len(kept) == len(items):
            return False
        self._write_questionable_items(company_id, kept)
        self.append_audit(actor, "delete_questionable", f"{company_id}\t{record_id}")
        return True

    def clear_questionable(self, company_id: Optional[str], scope: str, actor: str = "") -> int:
        company_id = self._require_company(company_id)
        items = self._read_questionable_items(company_id)
        if scope == "today":
            today = datetime.now().strftime("%Y-%m-%d")
            kept = [item for item in items if not str(item.get("created_at", "")).startswith(today)]
        elif scope == "all":
            kept = []
        else:
            raise ValueError("清空范围不合法")
        deleted = len(items) - len(kept)
        if deleted:
            self._write_questionable_items(company_id, kept)
            self.append_audit(actor, "clear_questionable", f"{company_id}\t{scope}\t{deleted}")
        return deleted
