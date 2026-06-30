type ApiResult<T> = {
  ok: boolean;
  message: string;
  data: T;
};

export async function apiGet<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "include" });
  return parseResponse<T>(response);
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body ?? {})
  });
  return parseResponse<T>(response);
}

export async function apiDelete<T>(url: string): Promise<T> {
  const response = await fetch(url, { method: "DELETE", credentials: "include" });
  return parseResponse<T>(response);
}

export async function uploadFile<T>(url: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(url, { method: "POST", body: form, credentials: "include" });
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as ApiResult<T>;
  if (!response.ok || !payload.ok) {
    const error = new Error(payload.message || "请求失败") as Error & { data?: unknown; status?: number };
    error.data = payload.data;
    error.status = response.status;
    throw error;
  }
  return payload.data;
}
