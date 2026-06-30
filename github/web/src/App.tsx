import {
  AlertTriangle,
  Building2,
  CalendarDays,
  CheckCircle2,
  Download,
  FileWarning,
  FileSearch,
  FileSpreadsheet,
  FileUp,
  FolderOpen,
  Home,
  Info,
  LogOut,
  Pencil,
  PlusCircle,
  RefreshCw,
  Save,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import { ChangeEvent, CSSProperties, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { apiDelete, apiGet, apiPost, uploadFile } from "./api";
import type { Company, DuplicateMatch, ImportRow, Invoice, InvoiceListResponse, QuestionableRecord, ServiceInfo } from "./types";

type Mode = "home" | "register" | "check" | "questionable" | "company" | "info";
type DraftContext = "register" | "check";
type BatchProgress = { total: number; current: number; fileName: string };
type DraftSourceFile = { name: string; url: string };
type PromptSourceFile = DraftSourceFile & { revokeOnClose?: boolean };
type RiskDecision = "ack" | "rollback";
type RiskPrompt = { fileName: string; invoice: Invoice; duplicates: DuplicateMatch[]; rollbackCount: number };
type LowRiskDecision = "ack" | "edit";
type LowRiskPrompt = { fileName: string; invoice: Invoice; sourceFile: PromptSourceFile | null };

const PAGE_SIZE = 20;
const APP_DISPLAY_NAME = "票核通";
const APP_VERSION_TEXT = "内测版demo_260630v0.2";
const APP_INFO_ITEMS = [
  ["软件版本", APP_VERSION_TEXT],
  ["作者", "孙启跃"],
  ["技术交流", "13122056260"],
  ["项目 GitHub", "测试版待上线"]
] as const;

const NAV_ITEMS: Array<{ mode: Mode; label: string; danger?: boolean }> = [
  { mode: "register", label: "登记模式" },
  { mode: "check", label: "核对模式" },
  { mode: "questionable", label: "疑问票据", danger: true },
  { mode: "company", label: "公司管理" },
  { mode: "info", label: "软件信息" }
];

const emptyInvoice: Invoice = {
  invoice_code: "",
  original_invoice_code: "",
  invoice_number: "",
  issue_date: "",
  buyer_name: "",
  seller_name: "",
  amount: "",
  tax_amount: "",
  total_amount: "",
  remark: ""
};

const fields: Array<{ key: keyof Invoice; label: string; required?: boolean }> = [
  { key: "invoice_code", label: "发票编码", required: true },
  { key: "original_invoice_code", label: "原始发票代码" },
  { key: "invoice_number", label: "发票号码", required: true },
  { key: "issue_date", label: "开票日期", required: true },
  { key: "buyer_name", label: "购买方名称" },
  { key: "seller_name", label: "销售方名称" },
  { key: "amount", label: "金额" },
  { key: "tax_amount", label: "税额" },
  { key: "total_amount", label: "价税合计", required: true },
  { key: "remark", label: "备注" }
];

function digits(value?: string) {
  return String(value ?? "").replace(/\D/g, "");
}

function invoiceBatchKey(invoice: Invoice) {
  const number = digits(invoice.invoice_number);
  if (!number) return "";
  return `number::${number}`;
}

function missingAutoRequiredFields(invoice: Invoice) {
  const missing: string[] = [];
  if (!digits(invoice.invoice_number)) missing.push("发票号码");
  if (!String(invoice.issue_date ?? "").trim()) missing.push("开票日期");
  if (!String(invoice.total_amount ?? "").trim()) missing.push("价税合计");
  return missing;
}

function hasTotalAmountDecimalIssue(invoice: Invoice) {
  const amount = String(invoice.total_amount ?? "").trim();
  return Boolean(amount) && !amount.includes(".");
}

function duplicateCompanyNames(duplicates: DuplicateMatch[]) {
  return Array.from(new Set(duplicates.map((item) => item.company_name).filter(Boolean))).join("、");
}

function BrandLogo({ size = "default", onClick }: { size?: "default" | "large"; onClick?: () => void }) {
  const className = `brand-mark ${size === "large" ? "large" : ""}`;
  const image = <img src="/app-icon.png" alt={APP_DISPLAY_NAME} />;
  if (!onClick) {
    return <div className={className}>{image}</div>;
  }
  return (
    <button type="button" className={className} onClick={onClick} aria-label="进入主页">
      {image}
    </button>
  );
}

function CompanyNavIcon() {
  return <img className="nav-image-icon" src="/company-nav-icon.png" alt="" aria-hidden="true" />;
}

function ModeIcon({ mode }: { mode: Mode }) {
  if (mode === "register") return <FileUp size={22} />;
  if (mode === "check") return <FileSearch size={22} />;
  if (mode === "questionable") return <FileWarning size={22} />;
  if (mode === "company") return <CompanyNavIcon />;
  if (mode === "info") return <Info size={22} />;
  return <Home size={22} />;
}

function App() {
  const [admins, setAdmins] = useState<string[]>([]);
  const [user, setUser] = useState<string | null>(null);
  const [service, setService] = useState<ServiceInfo | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [currentCompany, setCurrentCompany] = useState<Company | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [companyRemark, setCompanyRemark] = useState("");
  const [mode, setMode] = useState<Mode>("register");
  const [query, setQuery] = useState("");
  const [exportStart, setExportStart] = useState("");
  const [exportEnd, setExportEnd] = useState("");
  const [records, setRecords] = useState<Invoice[]>([]);
  const [recordTotal, setRecordTotal] = useState(0);
  const [recordPage, setRecordPage] = useState(1);
  const [recordTotalPages, setRecordTotalPages] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [allFilteredSelected, setAllFilteredSelected] = useState(false);
  const [questionableRecords, setQuestionableRecords] = useState<QuestionableRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [draft, setDraft] = useState<Invoice | null>(null);
  const [draftContext, setDraftContext] = useState<DraftContext>("register");
  const [draftSourceFile, setDraftSourceFile] = useState<DraftSourceFile | null>(null);
  const [importRows, setImportRows] = useState<ImportRow[] | null>(null);
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null);
  const [riskPrompt, setRiskPrompt] = useState<RiskPrompt | null>(null);
  const [lowRiskPrompt, setLowRiskPrompt] = useState<LowRiskPrompt | null>(null);
  const draftResolverRef = useRef<((result: "saved" | "cancelled") => void) | null>(null);
  const riskResolverRef = useRef<((result: RiskDecision) => void) | null>(null);
  const lowRiskResolverRef = useRef<((result: LowRiskDecision) => void) | null>(null);
  const currentBatchSavedIdsRef = useRef<string[]>([]);

  useEffect(() => {
    apiGet<{ admins: string[] }>("/api/auth/admins").then((data) => setAdmins(data.admins)).catch(showError);
    apiGet<{ authenticated: boolean; username?: string; current_company?: Company | null }>("/api/me")
      .then((data) => {
        setUser(data.authenticated ? data.username ?? null : null);
        setCurrentCompany(data.current_company ?? null);
      })
      .catch(() => setUser(null));
    loadServiceInfo().catch(showError);
  }, []);

  useEffect(() => {
    if (user) {
      loadCompanies().then((data) => {
        if (data.current_company) {
          loadRecordsPage("", 1);
          loadQuestionableRecords();
        }
      });
    }
  }, [user]);

  async function loadCompanies() {
    const data = await apiGet<{ items: Company[]; current_company: Company | null }>("/api/companies");
    setCompanies(data.items);
    setCurrentCompany(data.current_company);
    return data;
  }

  async function loadServiceInfo() {
    const data = await apiGet<ServiceInfo>("/api/service-info");
    setService(data);
    return data;
  }

  async function loadRecords(nextQuery = query) {
    const targetPage = recordPage;
    return loadRecordsPage(nextQuery, targetPage);
  }

  async function loadRecordsPage(nextQuery = query, nextPage = 1) {
    const params = new URLSearchParams();
    if (nextQuery.trim()) params.set("q", nextQuery.trim());
    params.set("page", String(nextPage));
    params.set("page_size", String(PAGE_SIZE));
    const data = await apiGet<InvoiceListResponse>(`/api/invoices?${params.toString()}`);
    setRecords(data.items);
    setRecordTotal(data.total);
    setRecordPage(data.page);
    setRecordTotalPages(data.total_pages);
    setPageInput(String(data.page));
    setSelectedIds(new Set());
    setAllFilteredSelected(false);
  }

  async function loadQuestionableRecords() {
    const data = await apiGet<{ items: QuestionableRecord[] }>("/api/questionable");
    setQuestionableRecords(data.items);
  }

  function showError(error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    setToast(message);
  }

  async function handleLogout() {
    await apiPost("/api/auth/logout");
    setUser(null);
    setRecords([]);
    setCompanies([]);
    setCurrentCompany(null);
    setQuestionableRecords([]);
    setSelectedIds(new Set());
    setAllFilteredSelected(false);
  }

  async function handleCreateCompany(event: FormEvent) {
    event.preventDefault();
    if (!companyName.trim()) {
      setToast("请输入公司名称");
      return;
    }
    setBusy(true);
    try {
      const data = await apiPost<{ company: Company; items: Company[] }>("/api/companies", {
        name: companyName.trim(),
        remark: companyRemark.trim()
      });
      setCompanies(data.items);
      setCurrentCompany(data.company);
      setCompanyName("");
      setCompanyRemark("");
      await loadRecordsPage("", 1);
      await loadQuestionableRecords();
      setToast(`已切换到公司：${data.company.name}`);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleSwitchCompany(companyId: string) {
    if (!companyId || companyId === currentCompany?.id) return;
    setBusy(true);
    try {
      const data = await apiPost<{ company: Company; items: Company[] }>("/api/companies/switch", { company_id: companyId });
      setCompanies(data.items);
      setCurrentCompany(data.company);
      setQuery("");
      await loadRecordsPage("", 1);
      await loadQuestionableRecords();
      setToast(`已切换到公司：${data.company.name}`);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateCompany(company: Company) {
    const nextName = window.prompt("请输入公司名称", company.name)?.trim();
    if (!nextName) return;
    const nextRemark = window.prompt("请输入公司备注", company.remark ?? "") ?? "";
    setBusy(true);
    try {
      const data = await apiPost<{ company: Company; items: Company[] }>("/api/companies/update", {
        company_id: company.id,
        name: nextName,
        remark: nextRemark.trim()
      });
      setCompanies(data.items);
      if (currentCompany?.id === data.company.id) setCurrentCompany(data.company);
      setToast("公司信息已更新");
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCompany(company: Company) {
    if (!company.id) return;
    const isLastAdmin = (company.admin_count ?? 0) <= 1;
    let deleteDatabase = false;
    let password = "";
    if (isLastAdmin) {
      deleteDatabase = window.confirm(
        `公司“${company.name}”已是最后一个管理员关联。\n\n点击“确定”将删除公司数据库；点击“取消”仅移除你的公司关联，数据保留为可重新加入状态。`
      );
      if (deleteDatabase) {
        password = window.prompt("删除公司数据库属于高风险操作，请输入当前管理员密码") ?? "";
        if (!password) return;
        if (!window.confirm("二次确认：删除公司数据库后，该公司的票据数据将被移除。确认继续？")) return;
      }
    } else if (!window.confirm(`确认从你的公司列表中移除“${company.name}”？其他管理员仍可继续使用。`)) {
      return;
    }
    setBusy(true);
    try {
      const data = await apiPost<{ items: Company[]; current_company: Company | null; database_deleted: boolean }>(
        "/api/companies/delete",
        { company_id: company.id, delete_database: deleteDatabase, password }
      );
      setCompanies(data.items);
      setCurrentCompany(data.current_company);
      setQuery("");
      setRecords([]);
      setQuestionableRecords([]);
      if (data.current_company) {
        await loadRecordsPage("", 1);
        await loadQuestionableRecords();
      }
      setToast(data.database_deleted ? "公司和数据库已删除" : "已移除公司关联");
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  function clearDraftState() {
    if (draftSourceFile?.url) {
      URL.revokeObjectURL(draftSourceFile.url);
    }
    setDraft(null);
    setDraftSourceFile(null);
  }

  function openDraftForBatch(invoice: Invoice, context: DraftContext, sourceFile?: File) {
    if (draftSourceFile?.url) {
      URL.revokeObjectURL(draftSourceFile.url);
    }
    setDraftSourceFile(sourceFile ? { name: sourceFile.name, url: URL.createObjectURL(sourceFile) } : null);
    setDraft({ ...emptyInvoice, ...invoice });
    setDraftContext(context);
    return new Promise<"saved" | "cancelled">((resolve) => {
      draftResolverRef.current = resolve;
    });
  }

  function closeDraft() {
    clearDraftState();
    if (draftResolverRef.current) {
      draftResolverRef.current("cancelled");
      draftResolverRef.current = null;
    }
  }

  function askDuplicateRisk(fileName: string, invoice: Invoice, duplicates: DuplicateMatch[]) {
    setRiskPrompt({ fileName, invoice, duplicates, rollbackCount: currentBatchSavedIdsRef.current.length });
    return new Promise<RiskDecision>((resolve) => {
      riskResolverRef.current = resolve;
    });
  }

  function resolveRiskPrompt(result: RiskDecision) {
    setRiskPrompt(null);
    if (riskResolverRef.current) {
      riskResolverRef.current(result);
      riskResolverRef.current = null;
    }
  }

  function askLowRiskAmount(fileName: string, invoice: Invoice, sourceFile?: File | DraftSourceFile) {
    let promptSourceFile: PromptSourceFile | null = null;
    if (sourceFile instanceof File) {
      promptSourceFile = { name: sourceFile.name, url: URL.createObjectURL(sourceFile), revokeOnClose: true };
    } else if (sourceFile) {
      promptSourceFile = { ...sourceFile, revokeOnClose: false };
    }
    setLowRiskPrompt({ fileName, invoice, sourceFile: promptSourceFile });
    return new Promise<LowRiskDecision>((resolve) => {
      lowRiskResolverRef.current = resolve;
    });
  }

  function resolveLowRiskPrompt(result: LowRiskDecision) {
    setLowRiskPrompt((current) => {
      if (current?.sourceFile?.revokeOnClose && current.sourceFile.url) {
        URL.revokeObjectURL(current.sourceFile.url);
      }
      return null;
    });
    if (lowRiskResolverRef.current) {
      lowRiskResolverRef.current(result);
      lowRiskResolverRef.current = null;
    }
  }

  function rememberCurrentBatchRecord(record: Invoice) {
    if (!record.id) return;
    if (!currentBatchSavedIdsRef.current.includes(record.id)) {
      currentBatchSavedIdsRef.current.push(record.id);
    }
  }

  async function rollbackCurrentBatch() {
    const ids = Array.from(new Set(currentBatchSavedIdsRef.current));
    if (!ids.length) {
      setToast("当前批次暂无可撤回的入库数据");
      return 0;
    }
    setBusy(true);
    try {
      const result = await apiPost<{ deleted: number }>("/api/invoices/batch-delete", { ids });
      currentBatchSavedIdsRef.current = [];
      await loadRecordsPage(query, 1);
      await loadQuestionableRecords();
      setToast(`已撤回本次导入 ${result.deleted} 条数据`);
      return result.deleted;
    } finally {
      setBusy(false);
    }
  }

  async function addQuestionableFromDuplicate(
    fileName: string,
    invoice: Invoice,
    duplicates: DuplicateMatch[],
    note: string,
    status = ""
  ) {
    const firstDuplicate = duplicates[0];
    await apiPost<QuestionableRecord>("/api/questionable", {
      file_name: fileName,
      reason: "重复发票",
      note,
      invoice_number: invoice.invoice_number,
      original_invoice_code: invoice.original_invoice_code,
      duplicate_company_id: firstDuplicate?.company_id ?? "",
      duplicate_company_name: duplicateCompanyNames(duplicates),
      status
    });
    if (mode === "questionable") {
      await loadQuestionableRecords();
    }
  }

  async function handleInvoiceFiles(files: File[], context: DraftContext, autoApprove = false) {
    const uploadFiles = files.filter(Boolean);
    if (!uploadFiles.length) return;
    currentBatchSavedIdsRef.current = [];
    const seenInBatch = new Set<string>();
    let savedCount = 0;
    let skippedCount = 0;
    setBatchProgress({ total: uploadFiles.length, current: 0, fileName: "" });
    for (let index = 0; index < uploadFiles.length; index += 1) {
      const file = uploadFiles[index];
      setBatchProgress({ total: uploadFiles.length, current: index + 1, fileName: file.name });
      setBusy(true);
      try {
        const parsed = await uploadFile<Invoice>("/api/pdf/parse", file);
        setBusy(false);
        const duplicates = parsed.duplicates ?? [];
        if (duplicates.length) {
          const decision = await askDuplicateRisk(file.name, parsed, duplicates);
          await addQuestionableFromDuplicate(file.name, parsed, duplicates, `与 ${duplicateCompanyNames(duplicates)} 重复，重复发票禁止入库`, "skipped_duplicate");
          skippedCount += 1;
          if (decision === "rollback") {
            await rollbackCurrentBatch();
            break;
          }
          continue;
        }

        const batchKey = invoiceBatchKey(parsed);
        if (batchKey && seenInBatch.has(batchKey)) {
          await addQuestionableFromDuplicate(file.name, parsed, [], "文件夹内重复", "folder_duplicate");
          skippedCount += 1;
          continue;
        }
        if (batchKey) seenInBatch.add(batchKey);

        if (hasTotalAmountDecimalIssue(parsed)) {
          const decision = await askLowRiskAmount(file.name, parsed, file);
          if (decision === "edit") {
            const draftResult = await openDraftForBatch(parsed, context, file);
            if (autoApprove && draftResult !== "saved") skippedCount += 1;
          } else if (autoApprove) {
            skippedCount += 1;
          }
          continue;
        }

        if (!autoApprove) {
          await openDraftForBatch(parsed, context, file);
          continue;
        }

        const missingFields = missingAutoRequiredFields(parsed);
        if (missingFields.length) {
          setToast(`文件 ${file.name} 缺少 ${missingFields.join("、")}，请人工补充`);
          await openDraftForBatch(parsed, context, file);
          continue;
        }

        const saved = await apiPost<Invoice>("/api/invoices", parsed);
        rememberCurrentBatchRecord(saved);
        savedCount += 1;
      } catch (error) {
        setBusy(false);
        const message = error instanceof Error ? error.message : String(error);
        const keepGoing = window.confirm(`文件 ${file.name} 识别失败：${message}\n\n点击“确定”撤销本次上传并继续下一张，点击“取消”停止批量处理。`);
        if (!keepGoing) break;
      }
    }
    setBatchProgress(null);
    await loadRecordsPage(query, 1);
    await loadQuestionableRecords();
    if (autoApprove) {
      setToast(`自动审核完成：保存 ${savedCount} 条，跳过 ${skippedCount} 条`);
    }
  }

  async function saveDraft(invoice: Invoice) {
    const missingFields = missingAutoRequiredFields(invoice);
    if (!invoice.invoice_code.trim() || missingFields.length) {
      const labels = [...(!invoice.invoice_code.trim() ? ["发票编码"] : []), ...missingFields];
      setToast(`请补充必填字段：${labels.join("、")}`);
      return;
    }
    setBusy(true);
    try {
      const checked = await apiPost<{ exists: boolean; duplicate: Invoice | null; duplicates: DuplicateMatch[] }>(
        "/api/invoices/check",
        invoice
      );
      if (checked.exists) {
        setBusy(false);
        const decision = await askDuplicateRisk(invoice.source_file || draftSourceFile?.name || "当前票据", invoice, checked.duplicates);
        await addQuestionableFromDuplicate(
          invoice.source_file || draftSourceFile?.name || "当前票据",
          invoice,
          checked.duplicates,
          `与 ${duplicateCompanyNames(checked.duplicates)} 重复，重复发票禁止入库`,
          "skipped_duplicate"
        );
        if (decision === "rollback") {
          await rollbackCurrentBatch();
        } else {
          setToast("已知晓，重复发票未入库");
        }
        clearDraftState();
        if (draftResolverRef.current) {
          draftResolverRef.current("cancelled");
          draftResolverRef.current = null;
        }
        return;
      }

      if (hasTotalAmountDecimalIssue(invoice)) {
        setBusy(false);
        const decision = await askLowRiskAmount(
          invoice.source_file || draftSourceFile?.name || "当前票据",
          invoice,
          draftSourceFile ?? undefined
        );
        setToast(
          decision === "edit"
            ? "请编辑价税合计为带小数点的金额，例如 6000.00"
            : "价税合计缺少小数点，已阻止入库"
        );
        return;
      }

      setBusy(true);
      if (draftContext === "check" && !checked.exists) {
        if (!window.confirm("未查询到重复发票，是否保存到历史数据里？")) {
          closeDraft();
          return;
        }
      }
      const saved = await apiPost<Invoice>("/api/invoices", invoice);
      rememberCurrentBatchRecord(saved);
      clearDraftState();
      setToast("已保存到历史数据");
      await loadRecordsPage(query, 1);
      if (draftResolverRef.current) {
        draftResolverRef.current("saved");
        draftResolverRef.current = null;
      }
    } catch (error) {
      const typed = error as Error & { status?: number; data?: { duplicate?: Invoice; duplicates?: DuplicateMatch[] } };
      if (typed.status === 409) {
        setDraft({ ...invoice, duplicate: typed.data?.duplicate ?? null, duplicates: typed.data?.duplicates ?? [] });
        setToast("已阻止重复发票入库：发票号码已存在。");
      } else {
        showError(error);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleExcel(file: File) {
    setBusy(true);
    try {
      const preview = await uploadFile<{ rows: ImportRow[] }>("/api/excel/import-preview", file);
      setImportRows(preview.rows.map((row) => ({ ...row, action: row.suggested_action })));
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function commitImport() {
    if (!importRows) return;
    setBusy(true);
    try {
      const result = await apiPost<{ saved: number; skipped: number; questionable: number; questionable_url?: string }>(
        "/api/excel/import-commit",
        { rows: importRows }
      );
      setImportRows(null);
      await loadRecords();
      setToast(`导入完成：保存 ${result.saved} 条，跳过 ${result.skipped} 条，疑惑 ${result.questionable} 条`);
      if (result.questionable_url) {
        window.open(result.questionable_url, "_blank");
      }
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function deleteRecord(id?: string) {
    if (!id || !window.confirm("确认删除这条历史记录？")) return;
    try {
      await apiDelete(`/api/invoices/${id}`);
      await loadRecordsPage(query, recordPage);
      setToast("记录已删除");
    } catch (error) {
      showError(error);
    }
  }

  function toggleRecordSelection(id?: string) {
    if (!id) return;
    setAllFilteredSelected(false);
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleCurrentPageSelection() {
    setAllFilteredSelected(false);
    const pageIds = records.map((record) => record.id).filter(Boolean) as string[];
    const allSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
    setSelectedIds((previous) => {
      const next = new Set(previous);
      for (const id of pageIds) {
        if (allSelected) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  async function selectAllFilteredRecords() {
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      const data = await apiGet<{ ids: string[] }>(`/api/invoices/ids?${params.toString()}`);
      setSelectedIds(new Set(data.ids));
      setAllFilteredSelected(true);
      setToast(`已选择全部筛选结果：${data.ids.length} 条`);
    } catch (error) {
      showError(error);
    }
  }

  async function deleteSelectedRecords() {
    const ids = Array.from(selectedIds);
    if (!ids.length) {
      setToast("请先勾选要删除的记录");
      return;
    }
    const scopeText = allFilteredSelected ? "全部筛选结果" : "已勾选记录";
    if (!window.confirm(`确认删除${scopeText}中的 ${ids.length} 条票据？此操作不可撤销。`)) return;
    try {
      const result = await apiPost<{ deleted: number }>("/api/invoices/batch-delete", { ids });
      await loadRecordsPage(query, recordPage);
      setToast(`已删除 ${result.deleted} 条记录`);
    } catch (error) {
      showError(error);
    }
  }

  async function deleteQuestionableRecord(id: string) {
    if (!window.confirm("确认删除这条疑问票据记录？")) return;
    try {
      await apiDelete(`/api/questionable/${id}`);
      await loadQuestionableRecords();
      setToast("疑问记录已删除");
    } catch (error) {
      showError(error);
    }
  }

  async function clearQuestionable(scope: "today" | "all") {
    const text = scope === "today" ? "当日疑问记录" : "全部历史疑问记录";
    if (!window.confirm(`确认清空${text}？`)) return;
    if (!window.confirm(`二次确认：${text}清空后不可恢复，继续？`)) return;
    try {
      const result = await apiPost<{ deleted: number }>("/api/questionable/clear", { scope });
      await loadQuestionableRecords();
      setToast(`已清空 ${result.deleted} 条疑问记录`);
    } catch (error) {
      showError(error);
    }
  }

  function goToPage(page: number) {
    const target = Math.min(Math.max(1, page), recordTotalPages);
    loadRecordsPage(query, target);
  }

  function switchMode(nextMode: Mode) {
    setMode(nextMode);
    if (nextMode === "questionable") {
      loadQuestionableRecords();
    }
    if (nextMode === "company") {
      loadCompanies().catch(showError);
    }
  }

  function refreshCurrentMode() {
    if (mode === "questionable") {
      loadQuestionableRecords();
      return;
    }
    if (mode === "company") {
      loadCompanies().catch(showError);
      return;
    }
    if (mode === "register" || mode === "check") {
      loadRecordsPage(query, recordPage);
      return;
    }
    loadCompanies().catch(showError);
  }

  async function handleReconnect() {
    setBusy(true);
    try {
      const [serviceInfo, sessionInfo] = await Promise.all([
        loadServiceInfo(),
        apiGet<{ authenticated: boolean; username?: string; current_company?: Company | null }>("/api/me")
      ]);
      if (!sessionInfo.authenticated) {
        setUser(null);
        setCurrentCompany(null);
        setToast("已连接本机服务，请重新登录");
        return;
      }
      setUser(sessionInfo.username ?? user);
      setCurrentCompany(sessionInfo.current_company ?? null);
      const companyData = await loadCompanies();
      if (companyData.current_company) {
        if (mode === "questionable") {
          await loadQuestionableRecords();
        } else if (mode === "register" || mode === "check") {
          await loadRecordsPage(query, recordPage);
        }
      }
      setToast(`已重新连接本机服务：${serviceInfo.lan_url}`);
    } catch {
      setToast("重连失败：请确认启动器服务正在运行，然后再点手动重连");
    } finally {
      setBusy(false);
    }
  }

  function handleSettingsClick() {
    setToast("设置功能预留中");
  }

  if (!user) {
    return <Login admins={admins} onLoggedIn={setUser} />;
  }

  const pageIds = records.map((record) => record.id).filter(Boolean) as string[];
  const allCurrentPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
  const activeNavIndex = NAV_ITEMS.findIndex((item) => item.mode === mode);
  const navStyle = (activeNavIndex >= 0 ? { "--nav-index": activeNavIndex } : undefined) as CSSProperties | undefined;

  return (
    <div className={`app-shell theme-${mode}`}>
      <aside className="sidebar">
        <div className="brand-home">
          <BrandLogo onClick={() => switchMode("home")} />
        </div>
        <nav className={`mode-nav ${activeNavIndex >= 0 ? "has-active" : ""}`} style={navStyle} aria-label="功能导航">
          {activeNavIndex >= 0 && <span className="nav-indicator" aria-hidden="true" />}
          {NAV_ITEMS.map((item) => (
            <button
              key={item.mode}
              className={`nav-button ${item.danger ? "danger-nav" : ""} ${mode === item.mode ? "active" : ""}`}
              onClick={() => switchMode(item.mode)}
              data-tooltip={item.label}
              aria-label={item.label}
            >
              <ModeIcon mode={item.mode} />
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button className="nav-button settings-button" onClick={handleSettingsClick} data-tooltip="设置（预留）" aria-label="设置（预留）">
            <Settings size={22} />
          </button>
        </div>
      </aside>

      <main className="workspace">
        {mode !== "home" && mode !== "info" && (
          <section className="company-bar">
            <div className="company-current">
              <Building2 size={18} />
              <span>当前公司</span>
              <strong>{currentCompany?.name ?? "未选择公司"}</strong>
            </div>
            <select value={currentCompany?.id ?? ""} onChange={(event) => handleSwitchCompany(event.target.value)} disabled={busy || companies.length === 0}>
              {companies.length === 0 && <option value="">暂无公司</option>}
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
            <div className="company-meta">
              <span className="company-service">
                <Server size={14} />
                {service?.lan_url ?? "服务信息读取中"}
              </span>
            </div>
            <div className="company-actions">
              <button className="ghost-button compact-button reconnect-button" onClick={handleReconnect} disabled={busy} title="重新连接本机服务">
                <Server size={16} />
                手动重连
              </button>
              <button className="ghost-button compact-button" onClick={refreshCurrentMode} disabled={busy}>
                <RefreshCw size={16} />
                刷新
              </button>
              <div className="admin-chip">
                <ShieldCheck size={16} />
                {user}
              </div>
              <button className="icon-button" onClick={handleLogout} title="退出登录">
                <LogOut size={18} />
              </button>
            </div>
          </section>
        )}

        <div key={mode} className="mode-panel-stage">
          {mode === "home" && <HomePage />}
          {mode === "info" && <InfoPage />}

        {mode === "register" && (
          <section className="command-band">
            <InvoiceFilePanel busy={busy || !currentCompany} onFiles={handleInvoiceFiles} onError={setToast} />
            <ExcelPanel busy={busy || !currentCompany} onFile={handleExcel} exportStart={exportStart} exportEnd={exportEnd} setExportStart={setExportStart} setExportEnd={setExportEnd} />
          </section>
        )}
        {mode === "register" && batchProgress && (
          <div className="batch-progress">
            正在处理 {batchProgress.current}/{batchProgress.total}：{batchProgress.fileName}
          </div>
        )}

        {mode === "company" && (
          <CompanyManagement
            companies={companies}
            currentCompany={currentCompany}
            companyName={companyName}
            companyRemark={companyRemark}
            busy={busy}
            setCompanyName={setCompanyName}
            setCompanyRemark={setCompanyRemark}
            onCreate={handleCreateCompany}
            onUpdate={handleUpdateCompany}
            onDelete={handleDeleteCompany}
          />
        )}

        {mode === "questionable" && (
          <QuestionablePanel
            records={questionableRecords}
            onDelete={deleteQuestionableRecord}
            onClearToday={() => clearQuestionable("today")}
            onClearAll={() => clearQuestionable("all")}
          />
        )}

        {(mode === "register" || mode === "check") && (
          <section className="history-section">
            <div className="section-head">
              <div>
                <h3>历史数据库</h3>
                <p>
                  共 {recordTotal} 条匹配记录，当前第 {recordPage}/{recordTotalPages} 页
                </p>
              </div>
              <form
                className="search-box"
                onSubmit={(event) => {
                  event.preventDefault();
                  loadRecordsPage(query, 1);
                }}
              >
                <Search size={18} />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入几位数字、名称或日期" />
                <button type="submit">查找</button>
              </form>
            </div>
            <HistoryTable
              records={records}
              selectedIds={selectedIds}
              allCurrentPageSelected={allCurrentPageSelected}
              allFilteredSelected={allFilteredSelected}
              selectedCount={selectedIds.size}
              recordPage={recordPage}
              recordTotalPages={recordTotalPages}
              pageInput={pageInput}
              onPageInput={setPageInput}
              onGoToPage={goToPage}
              onToggleRecord={toggleRecordSelection}
              onTogglePage={toggleCurrentPageSelection}
              onSelectAllFiltered={selectAllFilteredRecords}
              onDeleteSelected={deleteSelectedRecords}
              onDelete={deleteRecord}
            />
          </section>
        )}
        </div>
      </main>

      {draft && <InvoiceModal context={draftContext} invoice={draft} busy={busy} sourceFile={draftSourceFile} onClose={closeDraft} onSave={saveDraft} />}
      {importRows && (
        <ImportModal rows={importRows} setRows={setImportRows} busy={busy} onClose={() => setImportRows(null)} onCommit={commitImport} />
      )}
      {riskPrompt && <RiskDuplicateModal prompt={riskPrompt} onResolve={resolveRiskPrompt} />}
      {lowRiskPrompt && <LowRiskAmountModal prompt={lowRiskPrompt} onResolve={resolveLowRiskPrompt} />}
      {toast && <Toast message={toast} onClose={() => setToast("")} />}
    </div>
  );
}

function Login({ admins, onLoggedIn }: { admins: string[]; onLoggedIn: (username: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!admins.length) {
      if (username) setUsername("");
      return;
    }
    if (!username || !admins.includes(username)) setUsername(admins[0]);
  }, [admins, username]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await apiPost<{ username: string }>("/api/auth/login", { username, password });
      onLoggedIn(data.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <div className="login-brand">
          <BrandLogo size="large" />
          <div>
            <h1>{APP_DISPLAY_NAME}</h1>
            <p>管理员登录</p>
          </div>
        </div>
        <label>
          管理员账号
          <select value={username} onChange={(event) => setUsername(event.target.value)} disabled={!admins.length || busy} title={username}>
            {!admins.length && <option value="">暂无管理员</option>}
            {admins.map((admin) => (
              <option key={admin} value={admin} title={admin}>
                {admin}
              </option>
            ))}
          </select>
        </label>
        <label>
          密码
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
        </label>
        {error && <div className="form-error">{error}</div>}
        <button className="primary-button" type="submit" disabled={busy || !username}>
          <ShieldCheck size={18} />
          {busy ? "登录中" : "登录"}
        </button>
      </form>
    </div>
  );
}

function InvoiceFilePanel({
  busy,
  onFiles,
  onError
}: {
  busy: boolean;
  onFiles: (files: File[], context: DraftContext, autoApprove?: boolean) => void;
  onError: (message: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const autoFolderInputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const directoryProps = { webkitdirectory: "" } as Record<string, string>;

  function isSupportedInvoiceFile(file: File) {
    const lowerName = file.name.toLowerCase();
    return lowerName.endsWith(".pdf") || lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg");
  }

  function acceptFiles(fileList?: FileList | File[], autoApprove = false) {
    if (busy) return;
    const selectedFiles = Array.from(fileList ?? []);
    if (!selectedFiles.length) return;
    const files = selectedFiles.filter(isSupportedInvoiceFile);
    const skippedCount = selectedFiles.length - files.length;
    if (!files.length) {
      onError("未找到可识别的 PDF、JPG、JPEG 文件");
      return;
    }
    if (skippedCount > 0) {
      onError(`已跳过 ${skippedCount} 个非 PDF/JPG/JPEG 文件`);
    }
    onFiles(files, "register", autoApprove);
  }

  return (
    <div
      className={`work-panel upload-panel ${dragging ? "drag-over" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setDragging(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        acceptFiles(event.dataTransfer.files);
      }}
    >
      <div className="upload-copy">
        <div className="panel-icon">
          <UploadCloud size={24} />
        </div>
        <div>
          <h3>发票文件识别</h3>
          <p>支持 PDF、JPG、JPEG；批量 100 张建议直接选择文件夹</p>
        </div>
      </div>

      <div className="upload-drop-zone" onClick={() => inputRef.current?.click()}>
        <UploadCloud size={30} />
        <strong>{dragging ? "松开鼠标开始上传" : "拖拽发票文件到这里"}</strong>
        <span>识别后会逐张弹窗确认，错误文件可撤销本次上传</span>
      </div>

      <div className="upload-actions">
        <button className="primary-button" onClick={() => inputRef.current?.click()} disabled={busy}>
          <FileUp size={18} />
          选择文件
        </button>
        <button className="ghost-button" onClick={() => folderInputRef.current?.click()} disabled={busy}>
          <FolderOpen size={18} />
          选择文件夹
        </button>
        <button className="primary-button danger" onClick={() => autoFolderInputRef.current?.click()} disabled={busy}>
          <CheckCircle2 size={18} />
          自动审核
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,application/pdf,image/jpeg"
        multiple
        hidden
        onChange={(event) => {
          acceptFiles(event.target.files ?? undefined);
          event.target.value = "";
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,application/pdf,image/jpeg"
        multiple
        hidden
        {...directoryProps}
        onChange={(event) => {
          acceptFiles(event.target.files ?? undefined);
          event.target.value = "";
        }}
      />
      <input
        ref={autoFolderInputRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,application/pdf,image/jpeg"
        multiple
        hidden
        {...directoryProps}
        onChange={(event) => {
          acceptFiles(event.target.files ?? undefined, true);
          event.target.value = "";
        }}
      />
    </div>
  );
}

function ExcelPanel({
  busy,
  onFile,
  exportStart,
  exportEnd,
  setExportStart,
  setExportEnd
}: {
  busy: boolean;
  onFile: (file: File) => void;
  exportStart: string;
  exportEnd: string;
  setExportStart: (value: string) => void;
  setExportEnd: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  function openExport() {
    const params = new URLSearchParams();
    if (exportStart) params.set("start", exportStart);
    if (exportEnd) params.set("end", exportEnd);
    const query = params.toString();
    window.open(`/api/excel/export${query ? `?${query}` : ""}`, "_blank");
  }
  return (
    <div className="work-panel excel-panel">
      <div className="panel-icon amber">
        <FileSpreadsheet size={24} />
      </div>
      <div>
        <h3>Excel批量导入</h3>
        <p>模板、逐条确认、疑惑归档</p>
      </div>
      <div className="export-filters">
        <label>
          <CalendarDays size={15} />
          开始录入日期
          <input type="date" value={exportStart} onChange={(event) => setExportStart(event.target.value)} />
        </label>
        <label>
          <CalendarDays size={15} />
          结束录入日期
          <input type="date" value={exportEnd} onChange={(event) => setExportEnd(event.target.value)} />
        </label>
      </div>
      <div className="split-actions">
        <button className="ghost-button" onClick={() => window.open("/api/excel/template", "_blank")}>
          <Download size={16} />
          Excel模板
        </button>
        <button className="primary-button muted" onClick={() => inputRef.current?.click()} disabled={busy}>
          <FileSpreadsheet size={18} />
          批量导入
        </button>
        <button className="ghost-button" onClick={openExport} disabled={busy}>
          <Download size={16} />
          导出表格
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx"
        hidden
        onChange={(event: ChangeEvent<HTMLInputElement>) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = "";
        }}
      />
    </div>
  );
}

function InvoiceModal({
  context,
  invoice,
  busy,
  sourceFile,
  onClose,
  onSave
}: {
  context: DraftContext;
  invoice: Invoice;
  busy: boolean;
  sourceFile: DraftSourceFile | null;
  onClose: () => void;
  onSave: (invoice: Invoice) => void;
}) {
  const [form, setForm] = useState<Invoice>(invoice);

  const warnings = useMemo(() => form.warnings?.filter(Boolean) ?? [], [form.warnings]);

  return (
    <div className="modal-layer">
      <div className="modal invoice-modal">
        <div className="modal-head">
          <div>
            <h3>{context === "register" ? "登记确认" : "核对确认"}</h3>
            <p>请核对识别字段</p>
          </div>
          <button className="icon-button" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        {form.duplicate && (
          <div className="duplicate-alert">
            <AlertTriangle size={20} />
            <div>
              <strong>已登记警告</strong>
              <span>
                编码 {form.duplicate.invoice_code} / 原始代码 {form.duplicate.original_invoice_code || "-"} / 号码{" "}
                {form.duplicate.invoice_number}，登记人 {form.duplicate.created_by || "-"}
              </span>
            </div>
          </div>
        )}
        {warnings.length > 0 && (
          <div className="warning-list">
            {warnings.map((warning) => (
              <span key={warning}>{warning}</span>
            ))}
          </div>
        )}
        <div className="form-grid">
          {fields.map((field) => (
            <label key={field.key} className={field.key === "remark" ? "wide" : ""}>
              {field.label}
              {field.required && <b>*</b>}
              <input
                value={String(form[field.key] ?? "")}
                onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
              />
            </label>
          ))}
        </div>
        <details className="raw-text">
          <summary>识别原文</summary>
          <pre>{form.raw_text || "无原文"}</pre>
        </details>
        <div className="modal-actions">
          {sourceFile && (
            <button className="ghost-button" onClick={() => window.open(sourceFile.url, "_blank")}>
              <FileSearch size={18} />
              打开原文件
            </button>
          )}
          <button className="ghost-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" onClick={() => onSave(form)} disabled={busy}>
            <Save size={18} />
            {context === "register" ? "保存到历史数据" : "确认核对"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ImportModal({
  rows,
  setRows,
  busy,
  onClose,
  onCommit
}: {
  rows: ImportRow[];
  setRows: (rows: ImportRow[]) => void;
  busy: boolean;
  onClose: () => void;
  onCommit: () => void;
}) {
  const summary = rows.reduce(
    (acc, row) => {
      const action = row.action ?? row.suggested_action;
      acc[action] += 1;
      return acc;
    },
    { save: 0, question: 0, skip: 0 }
  );

  function updateAction(index: number, action: ImportRow["action"]) {
    setRows(rows.map((row, idx) => (idx === index ? { ...row, action } : row)));
  }

  return (
    <div className="modal-layer">
      <div className="modal import-modal">
        <div className="modal-head">
          <div>
            <h3>批量导入确认</h3>
            <p>
              保存 {summary.save} · 疑惑 {summary.question} · 跳过 {summary.skip}
            </p>
          </div>
          <button className="icon-button" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        <div className="import-table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>行号</th>
                <th>发票编码</th>
                <th>原始发票代码</th>
                <th>发票号码</th>
                <th>价税合计</th>
                <th>疑惑原因</th>
                <th>处理</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.row_number}-${row.invoice.invoice_number}`} className={row.warnings.length ? "row-warning" : ""}>
                  <td>{row.row_number}</td>
                  <td>{row.invoice.invoice_code}</td>
                  <td>{row.invoice.original_invoice_code || "-"}</td>
                  <td>{row.invoice.invoice_number}</td>
                  <td>{row.invoice.total_amount}</td>
                  <td>{row.warnings.join("；") || "正常"}</td>
                  <td>
                    <select value={row.action ?? row.suggested_action} onChange={(event) => updateAction(index, event.target.value as ImportRow["action"])}>
                      <option value="save">保存</option>
                      <option value="question">疑惑归档</option>
                      <option value="skip">跳过</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="modal-actions">
          <button className="ghost-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" onClick={onCommit} disabled={busy}>
            <CheckCircle2 size={18} />
            提交处理
          </button>
        </div>
      </div>
    </div>
  );
}

function CompanyManagement({
  companies,
  currentCompany,
  companyName,
  companyRemark,
  busy,
  setCompanyName,
  setCompanyRemark,
  onCreate,
  onUpdate,
  onDelete
}: {
  companies: Company[];
  currentCompany: Company | null;
  companyName: string;
  companyRemark: string;
  busy: boolean;
  setCompanyName: (value: string) => void;
  setCompanyRemark: (value: string) => void;
  onCreate: (event: FormEvent) => void;
  onUpdate: (company: Company) => void;
  onDelete: (company: Company) => void;
}) {
  return (
    <section className="history-section company-management">
      <div className="section-head">
        <div>
          <h3>公司管理</h3>
          <p>新增、加入、备注维护和删除公司关联</p>
        </div>
      </div>
      <form className="company-create management-create" onSubmit={onCreate}>
        <input value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="输入公司名，创建或加入" />
        <input value={companyRemark} onChange={(event) => setCompanyRemark(event.target.value)} placeholder="公司备注，可为空" />
        <button className="primary-button" type="submit" disabled={busy}>
          <PlusCircle size={17} />
          创建/加入
        </button>
      </form>
      <div className="table-wrap">
        <table className="data-table company-table">
          <thead>
            <tr>
              <th>公司名称</th>
              <th>备注</th>
              <th>管理员数</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {companies.map((company) => (
              <tr key={company.id} className={currentCompany?.id === company.id ? "row-current" : ""}>
                <td>{company.name}</td>
                <td>{company.remark || "-"}</td>
                <td>{company.admin_count ?? "-"}</td>
                <td>{company.created_at || "-"}</td>
                <td>
                  <div className="table-actions">
                    <button className="text-button" onClick={() => onUpdate(company)} disabled={busy}>
                      <Pencil size={14} />
                      修改
                    </button>
                    <button className="text-button danger" onClick={() => onDelete(company)} disabled={busy}>
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function HomePage() {
  return (
    <section className="home-panel">
      <p>内测版内容正在优化中，敬请期待</p>
    </section>
  );
}

function InfoPage() {
  return (
    <section className="history-section info-page">
      <div className="info-title">
        <BrandLogo />
        <div>
          <h3>{APP_DISPLAY_NAME}</h3>
          <p>系统软件版本</p>
        </div>
      </div>
      <dl className="info-list">
        {APP_INFO_ITEMS.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function QuestionablePanel({
  records,
  onDelete,
  onClearToday,
  onClearAll
}: {
  records: QuestionableRecord[];
  onDelete: (id: string) => void;
  onClearToday: () => void;
  onClearAll: () => void;
}) {
  return (
    <section className="history-section questionable-section">
      <div className="section-head">
        <div>
          <h3>疑问票据</h3>
          <p>记录批量导入中发现的重复发票和高风险导入</p>
        </div>
        <div className="split-actions">
          <button className="ghost-button" onClick={onClearToday} disabled={!records.length}>
            清空当日
          </button>
          <button className="primary-button danger" onClick={onClearAll} disabled={!records.length}>
            清空历史
          </button>
        </div>
      </div>
      {!records.length ? (
        <div className="empty-state danger-empty">
          <FileWarning size={36} />
          <strong>暂无疑问票据</strong>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table questionable-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>原因</th>
                <th>备注</th>
                <th>重复公司</th>
                <th>异常时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id} className={record.status === "folder_duplicate" ? "row-muted" : ""}>
                  <td>{record.file_name}</td>
                  <td>{record.reason}</td>
                  <td>{record.note || "-"}</td>
                  <td>{record.duplicate_company_name || "-"}</td>
                  <td>{record.created_at}</td>
                  <td>
                    <button className="text-button danger" onClick={() => onDelete(record.id)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LowRiskAmountModal({ prompt, onResolve }: { prompt: LowRiskPrompt; onResolve: (result: LowRiskDecision) => void }) {
  const invoice = prompt.invoice;
  const sourceFile = prompt.sourceFile;
  return (
    <div className="modal-layer">
      <div className="modal low-risk-modal">
        <div className="modal-head">
          <div>
            <h3>低风险数据异常发票</h3>
            <p>{prompt.fileName}</p>
          </div>
          <button className="icon-button" onClick={() => onResolve("ack")}>
            <X size={20} />
          </button>
        </div>
        <div className="low-risk-warning">
          <AlertTriangle size={22} />
          <div>
            <strong>发现价税合计数据缺少小数点</strong>
            <span>当前价税合计：{invoice.total_amount || "-"}</span>
            <small>价税合计应包含小数点，请核对原文件后编辑为正确金额。</small>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>发票编码</th>
                <th>原始发票代码</th>
                <th>发票号码</th>
                <th>开票日期</th>
                <th>销售方名称</th>
                <th>价税合计</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{invoice.invoice_code}</td>
                <td>{invoice.original_invoice_code || "-"}</td>
                <td>{invoice.invoice_number}</td>
                <td>{invoice.issue_date || "-"}</td>
                <td>{invoice.seller_name || "-"}</td>
                <td>{invoice.total_amount || "-"}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="modal-actions">
          <button className="ghost-button success-outline" onClick={() => onResolve("edit")}>
            <Pencil size={18} />
            编辑
          </button>
          {sourceFile && (
            <button className="ghost-button" onClick={() => window.open(sourceFile.url, "_blank")}>
              <FileSearch size={18} />
              打开原文件
            </button>
          )}
          <button className="ghost-button" onClick={() => onResolve("ack")}>
            已知晓
          </button>
        </div>
      </div>
    </div>
  );
}

function RiskDuplicateModal({ prompt, onResolve }: { prompt: RiskPrompt; onResolve: (result: RiskDecision) => void }) {
  const companyNames = duplicateCompanyNames(prompt.duplicates);
  return (
    <div className="modal-layer">
      <div className="modal risk-modal">
        <div className="modal-head">
          <div>
            <h3>高风险重复发票</h3>
            <p>{prompt.fileName}</p>
          </div>
          <button className="icon-button" onClick={() => onResolve("ack")}>
            <X size={20} />
          </button>
        </div>
        <div className="risk-warning">
          <AlertTriangle size={22} />
          <div>
                <strong>发现全部数据库中已有重复发票</strong>
                <span>重复公司：{companyNames || "未知公司"}</span>
                <small>发票号码相同即判定重复，重复发票禁止入库。</small>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>公司</th>
                <th>发票编码</th>
                <th>原始发票代码</th>
                <th>发票号码</th>
                <th>价税合计</th>
                <th>登记时间</th>
              </tr>
            </thead>
            <tbody>
              {prompt.duplicates.map((item, index) => (
                <tr key={`${item.company_id}-${item.invoice.id ?? index}`}>
                  <td>{item.company_name}</td>
                  <td>{item.invoice.invoice_code}</td>
                  <td>{item.invoice.original_invoice_code || "-"}</td>
                  <td>{item.invoice.invoice_number}</td>
                  <td>{item.invoice.total_amount}</td>
                  <td>{item.invoice.created_at || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="modal-actions">
          <button
            className="ghost-button danger-outline"
            onClick={() => {
              if (prompt.rollbackCount <= 0 || window.confirm(`确认撤回本次导入已入库的 ${prompt.rollbackCount} 条数据？`)) {
                onResolve("rollback");
              }
            }}
            title={
              prompt.rollbackCount > 0
                ? "撤回当前这一批上传中已经入库的数据"
                : "当前批次暂无已入库数据，点击后会提示无需撤回"
            }
          >
            <Trash2 size={18} />
            撤回本次导入
          </button>
          <button className="ghost-button" onClick={() => onResolve("ack")}>
            已知晓
          </button>
        </div>
      </div>
    </div>
  );
}

function HistoryTable({
  records,
  selectedIds,
  allCurrentPageSelected,
  allFilteredSelected,
  selectedCount,
  recordPage,
  recordTotalPages,
  pageInput,
  onPageInput,
  onGoToPage,
  onToggleRecord,
  onTogglePage,
  onSelectAllFiltered,
  onDeleteSelected,
  onDelete
}: {
  records: Invoice[];
  selectedIds: Set<string>;
  allCurrentPageSelected: boolean;
  allFilteredSelected: boolean;
  selectedCount: number;
  recordPage: number;
  recordTotalPages: number;
  pageInput: string;
  onPageInput: (value: string) => void;
  onGoToPage: (page: number) => void;
  onToggleRecord: (id?: string) => void;
  onTogglePage: () => void;
  onSelectAllFiltered: () => void;
  onDeleteSelected: () => void;
  onDelete: (id?: string) => void;
}) {
  if (!records.length) {
    return (
      <div className="empty-state">
        <FileSearch size={36} />
        <strong>暂无匹配记录</strong>
      </div>
    );
  }
  return (
    <>
      <div className="bulk-toolbar">
        <label className="check-line">
          <input type="checkbox" checked={allCurrentPageSelected} onChange={onTogglePage} />
          全选当前页
        </label>
        <button className="ghost-button" onClick={onSelectAllFiltered}>
          选择全部筛选结果
        </button>
        <button className="primary-button danger" onClick={onDeleteSelected} disabled={!selectedCount}>
          <Trash2 size={16} />
          删除勾选
        </button>
        <span>{allFilteredSelected ? "已选择全部筛选结果" : `已选择 ${selectedCount} 条`}</span>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>选择</th>
              <th>发票编码</th>
              <th>原始发票代码</th>
              <th>发票号码</th>
              <th>开票日期</th>
              <th>购买方名称</th>
              <th>销售方名称</th>
              <th>价税合计</th>
              <th>登记人</th>
              <th>登记时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id ?? `${record.invoice_code}-${record.invoice_number}`}>
                <td>
                  <input type="checkbox" checked={!!record.id && selectedIds.has(record.id)} onChange={() => onToggleRecord(record.id)} />
                </td>
                <td>{record.invoice_code}</td>
                <td>{record.original_invoice_code || "-"}</td>
                <td>{record.invoice_number}</td>
                <td>{record.issue_date}</td>
                <td>{record.buyer_name}</td>
                <td>{record.seller_name}</td>
                <td>{record.total_amount}</td>
                <td>{record.created_by}</td>
                <td>{record.created_at}</td>
                <td>
                  <button className="text-button danger" onClick={() => onDelete(record.id)}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pagination-bar">
        <button className="ghost-button" onClick={() => onGoToPage(recordPage - 1)} disabled={recordPage <= 1}>
          上一页
        </button>
        <span>
          第 {recordPage} / {recordTotalPages} 页
        </span>
        <button className="ghost-button" onClick={() => onGoToPage(recordPage + 1)} disabled={recordPage >= recordTotalPages}>
          下一页
        </button>
        <label>
          跳转到
          <input
            type="number"
            min="1"
            max={recordTotalPages}
            value={pageInput}
            onChange={(event) => onPageInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onGoToPage(Number(pageInput) || 1);
            }}
          />
        </label>
        <button className="primary-button muted" onClick={() => onGoToPage(Number(pageInput) || 1)}>
          跳转
        </button>
      </div>
    </>
  );
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 4200);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return (
    <div className="toast">
      <AlertTriangle size={18} />
      <span>{message}</span>
      <button onClick={onClose}>
        <X size={16} />
      </button>
    </div>
  );
}

export default App;
