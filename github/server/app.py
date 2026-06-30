from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Set

from flask import Flask, Response, jsonify, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from .config import APP_DISPLAY_NAME, APP_NAME, APP_VERSION, uploads_dir, web_dist_dir
from .data_store import JsonStore, normalize_key_part
from .excel_service import create_template, export_invoices, export_questionable, read_invoice_rows
from .invoice_parser import parse_invoice_file
from .invoice_qr import parse_invoice_qr_image, parse_invoice_qr_text
from .network import allowed_lan_networks, get_primary_lan_ip, is_allowed_remote

MAX_UPLOAD_MB = 30


def api_ok(data: Any = None, message: str = "success"):
    return jsonify({"ok": True, "message": message, "data": data})


def api_error(message: str, status: int = 400, data: Any = None):
    return jsonify({"ok": False, "message": message, "data": data}), status


def current_user() -> Optional[str]:
    return session.get("admin")


def current_company_id() -> Optional[str]:
    return session.get("company_id")


def require_login():
    if not current_user():
        return api_error("请先登录", 401)
    return None


def require_company(store: JsonStore):
    auth = require_login()
    if auth:
        return None, auth
    username = current_user() or ""
    company_id = current_company_id()
    if company_id and store.admin_can_access_company(username, company_id):
        return company_id, None
    current = store.get_current_company(username)
    if current:
        session["company_id"] = current["id"]
        return current["id"], None
    return None, api_error("请先创建或选择公司", 409)


def save_upload(field_name: str, allowed_suffixes: Set[str]) -> Path:
    file = request.files.get(field_name)
    if not file or not file.filename:
        raise ValueError("请选择上传文件")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed_suffixes:
        raise ValueError("文件类型不支持")
    safe_name = secure_filename(file.filename)
    if not safe_name:
        safe_name = "upload" + suffix
    target = uploads_dir() / safe_name
    counter = 1
    while target.exists():
        target = uploads_dir() / f"{Path(safe_name).stem}_{counter}{suffix}"
        counter += 1
    file.save(target)
    return target


def prepare_invoice_draft(store: JsonStore, company_id: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
    draft = dict(parsed)
    original_code = normalize_key_part(draft.get("original_invoice_code")) or normalize_key_part(draft.get("invoice_code"))
    draft["original_invoice_code"] = original_code
    draft["invoice_code"] = store.next_daily_invoice_code(company_id)
    draft["duplicate"] = store.find_duplicate(company_id, draft)
    draft["duplicates"] = store.find_duplicates_all_companies(draft)
    return draft


def positive_int(value: Any, default: int, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def create_app(store: Optional[JsonStore] = None) -> Flask:
    store = store or JsonStore()
    static_dir = web_dist_dir()
    app = Flask(
        APP_NAME,
        static_folder=str(static_dir / "assets") if (static_dir / "assets").exists() else None,
        static_url_path="/assets",
    )
    cfg = store.get_config()
    app.secret_key = cfg["secret_key"]
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.json.ensure_ascii = False
    app.config["STORE"] = store
    app.config["LAN_NETWORKS"] = allowed_lan_networks()

    @app.before_request
    def restrict_to_lan():
        if not is_allowed_remote(request.remote_addr, app.config["LAN_NETWORKS"]):
            return Response("Forbidden: only same LAN segment is allowed.", status=403)
        return None

    @app.errorhandler(413)
    def too_large(_exc):
        return api_error(f"上传文件不能超过 {MAX_UPLOAD_MB}MB", 413)

    @app.errorhandler(ValueError)
    def bad_request(exc):
        return api_error(str(exc), 400)

    @app.errorhandler(PermissionError)
    def permission_denied(exc):
        return api_error(str(exc), 403)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return api_error(exc.description or exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_exception(exc):
        app.logger.exception("Unhandled error")
        return api_error(str(exc), 500)

    @app.get("/api/auth/admins")
    def admins():
        return api_ok({"admins": store.list_admins()})

    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        if store.validate_admin(username, password):
            session["admin"] = username
            current = store.get_current_company(username)
            if current:
                session["company_id"] = current["id"]
            store.append_audit(username, "web_login")
            return api_ok({"username": username, "current_company": current})
        return api_error("管理员账号或密码错误", 401)

    @app.post("/api/auth/logout")
    def logout():
        actor = current_user() or ""
        session.clear()
        if actor:
            store.append_audit(actor, "web_logout")
        return api_ok()

    @app.get("/api/me")
    def me():
        user = current_user()
        if not user:
            return api_ok({"authenticated": False})
        current = store.get_current_company(user)
        if current:
            session["company_id"] = current["id"]
        return api_ok({"authenticated": True, "username": user, "current_company": current})

    @app.get("/api/companies")
    def companies():
        auth = require_login()
        if auth:
            return auth
        user = current_user() or ""
        current = store.get_current_company(user)
        if current:
            session["company_id"] = current["id"]
        return api_ok({"items": store.list_companies_for_admin(user), "current_company": current})

    @app.post("/api/companies")
    def create_or_join_company():
        auth = require_login()
        if auth:
            return auth
        payload = request.get_json(silent=True) or {}
        company = store.create_or_join_company(
            current_user() or "",
            str(payload.get("name", "")),
            str(payload.get("remark", "")),
        )
        session["company_id"] = company["id"]
        return api_ok({"company": company, "items": store.list_companies_for_admin(current_user() or "")})

    @app.post("/api/companies/update")
    def update_company():
        auth = require_login()
        if auth:
            return auth
        payload = request.get_json(silent=True) or {}
        company = store.update_company(
            current_user() or "",
            str(payload.get("company_id", "")),
            str(payload.get("name", "")),
            str(payload.get("remark", "")),
        )
        return api_ok({"company": company, "items": store.list_companies_for_admin(current_user() or "")})

    @app.post("/api/companies/switch")
    def switch_company():
        auth = require_login()
        if auth:
            return auth
        payload = request.get_json(silent=True) or {}
        company = store.set_current_company(current_user() or "", str(payload.get("company_id", "")))
        session["company_id"] = company["id"]
        return api_ok({"company": company, "items": store.list_companies_for_admin(current_user() or "")})

    @app.post("/api/companies/delete")
    def delete_company():
        auth = require_login()
        if auth:
            return auth
        payload = request.get_json(silent=True) or {}
        result = store.remove_company_for_admin(
            current_user() or "",
            str(payload.get("company_id", "")),
            delete_database=bool(payload.get("delete_database", False)),
            password=str(payload.get("password", "")),
        )
        current = result.get("current_company")
        if current:
            session["company_id"] = current["id"]
        else:
            session.pop("company_id", None)
        return api_ok(result)

    @app.get("/api/service-info")
    def service_info():
        port = store.get_config().get("port", 8080)
        return api_ok(
            {
                "name": APP_DISPLAY_NAME,
                "version": APP_VERSION,
                "lan_ip": get_primary_lan_ip(),
                "port": port,
                "lan_url": f"http://{get_primary_lan_ip()}:{port}",
                "networks": [str(network) for network in app.config["LAN_NETWORKS"]],
            }
        )

    @app.get("/api/invoices")
    def list_invoices():
        company_id, error = require_company(store)
        if error:
            return error
        q = request.args.get("q", "")
        code = request.args.get("code", "")
        number = request.args.get("number", "")
        records = store.search_invoices(company_id, q, code, number)
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        total = len(records)
        page = positive_int(request.args.get("page"), 1, minimum=1, maximum=100000)
        page_size = positive_int(request.args.get("page_size"), 20, minimum=1, maximum=200)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        items = records[start : start + page_size]
        return api_ok({"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages})

    @app.get("/api/invoices/ids")
    def list_invoice_ids():
        company_id, error = require_company(store)
        if error:
            return error
        q = request.args.get("q", "")
        code = request.args.get("code", "")
        number = request.args.get("number", "")
        return api_ok({"ids": store.list_invoice_ids(company_id, q, code, number)})

    @app.post("/api/invoices")
    def add_invoice():
        company_id, error = require_company(store)
        if error:
            return error
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        allow_update = bool(payload.pop("allow_update", False))
        payload.pop("allow_duplicate", None)
        try:
            record = store.add_invoice(
                company_id,
                payload,
                actor=current_user() or "",
                allow_update=allow_update,
            )
            return api_ok(record)
        except FileExistsError as exc:
            duplicates = store.find_duplicates_all_companies(payload)
            duplicate = duplicates[0]["invoice"] if duplicates else store.find_duplicate(company_id, payload)
            return api_error(str(exc), 409, {"duplicate": duplicate, "duplicates": duplicates})

    @app.post("/api/invoices/batch-delete")
    def batch_delete_invoices():
        company_id, error = require_company(store)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        ids = payload.get("ids", [])
        if not isinstance(ids, list):
            return api_error("删除列表不合法", 400)
        deleted = store.delete_invoices(company_id, [str(item) for item in ids], actor=current_user() or "")
        return api_ok({"deleted": deleted})

    @app.delete("/api/invoices/<invoice_id>")
    def delete_invoice(invoice_id: str):
        company_id, error = require_company(store)
        if error:
            return error
        deleted = store.delete_invoice(company_id, invoice_id, actor=current_user() or "")
        return api_ok({"deleted": deleted})

    @app.post("/api/invoices/check")
    def check_invoice():
        company_id, error = require_company(store)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        duplicate = store.find_duplicate(company_id, payload)
        duplicates = store.find_duplicates_all_companies(payload)
        return api_ok({"duplicate": duplicate, "duplicates": duplicates, "exists": bool(duplicates)})

    @app.get("/api/questionable")
    def list_questionable():
        company_id, error = require_company(store)
        if error:
            return error
        return api_ok({"items": store.list_questionable(company_id)})

    @app.post("/api/questionable")
    def add_questionable():
        company_id, error = require_company(store)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        record = store.add_questionable(company_id, payload, actor=current_user() or "")
        return api_ok(record)

    @app.delete("/api/questionable/<record_id>")
    def delete_questionable(record_id: str):
        company_id, error = require_company(store)
        if error:
            return error
        deleted = store.delete_questionable(company_id, record_id, actor=current_user() or "")
        return api_ok({"deleted": deleted})

    @app.post("/api/questionable/clear")
    def clear_questionable():
        company_id, error = require_company(store)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        deleted = store.clear_questionable(company_id, str(payload.get("scope", "")), actor=current_user() or "")
        return api_ok({"deleted": deleted})

    @app.post("/api/files/parse")
    @app.post("/api/files/parse/")
    @app.post("/api/pdf/parse")
    @app.post("/api/pdf/parse/")
    def parse_file_api():
        company_id, error = require_company(store)
        if error:
            return error
        target = save_upload("file", {".pdf", ".jpg", ".jpeg"})
        try:
            parsed = parse_invoice_file(target)
            return api_ok(prepare_invoice_draft(store, company_id, parsed))
        finally:
            try:
                target.unlink()
            except OSError:
                pass

    @app.post("/api/qrcode/parse")
    def parse_qrcode_api():
        company_id, error = require_company(store)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        parsed = parse_invoice_qr_text(str(payload.get("text", "")))
        return api_ok(prepare_invoice_draft(store, company_id, parsed))

    @app.post("/api/qrcode/image")
    def parse_qrcode_image_api():
        company_id, error = require_company(store)
        if error:
            return error
        target = save_upload("file", {".jpg", ".jpeg", ".png", ".bmp", ".webp"})
        try:
            parsed = parse_invoice_qr_image(target)
            return api_ok(prepare_invoice_draft(store, company_id, parsed))
        finally:
            try:
                target.unlink()
            except OSError:
                pass

    @app.get("/api/excel/template")
    def template():
        auth = require_login()
        if auth:
            return auth
        path = create_template()
        return send_file(path, as_attachment=True, download_name="发票导入模板.xlsx")

    @app.get("/api/excel/export")
    def export_all():
        company_id, error = require_company(store)
        if error:
            return error
        start_date = request.args.get("start") or None
        end_date = request.args.get("end") or None
        path = export_invoices(store.list_invoices(company_id, start_date=start_date, end_date=end_date), "发票历史数据.xlsx")
        return send_file(path, as_attachment=True, download_name="发票历史数据.xlsx")

    @app.post("/api/excel/import-preview")
    def import_preview():
        company_id, error = require_company(store)
        if error:
            return error
        target = save_upload("file", {".xlsx"})
        try:
            rows = read_invoice_rows(target, store, company_id)
            return api_ok({"rows": rows})
        finally:
            try:
                target.unlink()
            except OSError:
                pass

    @app.post("/api/excel/import-commit")
    def import_commit():
        company_id, error = require_company(store)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        rows = payload.get("rows", [])
        saved = 0
        skipped = 0
        questionable = []
        for row in rows:
            action = row.get("action") or row.get("suggested_action")
            row["action"] = action
            if action == "save":
                try:
                    store.add_invoice(company_id, row.get("invoice", {}), actor=current_user() or "")
                    saved += 1
                except Exception as exc:
                    row.setdefault("warnings", []).append(str(exc))
                    questionable.append(row)
            elif action == "question":
                questionable.append(row)
            else:
                skipped += 1
        questionable_url = None
        if questionable:
            path = export_questionable(questionable)
            questionable_url = f"/api/download/{path.name}"
        return api_ok({"saved": saved, "skipped": skipped, "questionable": len(questionable), "questionable_url": questionable_url})

    @app.get("/api/download/<path:name>")
    def download_export(name: str):
        auth = require_login()
        if auth:
            return auth
        requested_name = Path(name).name
        target = Path(store.base_dir) / "exports" / requested_name
        try:
            target.resolve().relative_to((Path(store.base_dir) / "exports").resolve())
        except ValueError:
            return api_error("文件路径不合法", 400)
        if not target.exists():
            return api_error("文件不存在", 404)
        return send_file(target, as_attachment=True, download_name=requested_name)

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path: str = ""):
        index = static_dir / "index.html"
        requested = static_dir / path
        if path and requested.exists() and requested.is_file():
            return send_file(requested)
        if index.exists():
            return send_file(index)
        return Response("前端尚未构建，请先运行 npm run build。", mimetype="text/plain; charset=utf-8")

    return app


def main() -> None:
    store = JsonStore()
    app = create_app(store)
    port = int(store.get_config().get("port", 8080))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
