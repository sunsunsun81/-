export type Invoice = {
  id?: string;
  invoice_code: string;
  original_invoice_code?: string;
  invoice_number: string;
  issue_date: string;
  buyer_name: string;
  seller_name: string;
  amount: string;
  tax_amount: string;
  total_amount: string;
  remark: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  source_file?: string;
  warnings?: string[];
  duplicate?: Invoice | null;
  duplicates?: DuplicateMatch[];
  raw_text?: string;
};

export type DuplicateMatch = {
  company_id: string;
  company_name: string;
  invoice: Invoice;
};

export type ImportRow = {
  row_number: number;
  invoice: Invoice;
  duplicate?: Invoice | null;
  duplicates?: DuplicateMatch[];
  warnings: string[];
  suggested_action: "save" | "question" | "skip";
  action?: "save" | "question" | "skip";
};

export type ServiceInfo = {
  name: string;
  version: string;
  lan_ip: string;
  port: number;
  lan_url: string;
  networks: string[];
};

export type Company = {
  id: string;
  name: string;
  remark?: string;
  admin_count?: number;
  created_at?: string;
  created_by?: string;
};

export type QuestionableRecord = {
  id: string;
  company_id: string;
  file_name: string;
  reason: string;
  note: string;
  invoice_number?: string;
  original_invoice_code?: string;
  duplicate_company_id?: string;
  duplicate_company_name?: string;
  status?: string;
  created_by?: string;
  created_at: string;
};

export type InvoiceListResponse = {
  items: Invoice[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};
