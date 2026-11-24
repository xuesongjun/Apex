import type { DashboardPayload } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export async function fetchDashboard(accountId?: string): Promise<DashboardPayload> {
  const url = new URL("/api/dashboard", API_BASE);
  if (accountId) {
    url.searchParams.set("account_id", accountId);
  }
  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Dashboard API 请求失败: ${response.status}`);
  }
  return response.json();
}
