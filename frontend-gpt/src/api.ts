import type { Params } from "./types";

export async function api<T>(
  path: string,
  params: Params = {},
  signal?: AbortSignal,
): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return request<T>(`/api/${path}?${query}`, { signal });
}
export async function mutate<T>(
  path: string,
  method: string,
  body?: unknown,
): Promise<T> {
  return request<T>(`/api/${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}
async function request<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("无法连接本地服务，请确认后端已启动。");
  }
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `请求失败（${response.status}）`,
    );
  return data as T;
}
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "请求失败，请重试";
