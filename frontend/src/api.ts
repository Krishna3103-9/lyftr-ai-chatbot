import type { ChatResponse, Health } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

function readableDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : String(item))).join("; ");
  }
  if (detail && typeof detail === "object") {
    if ("msg" in detail) return String(detail.msg);
    if ("message" in detail) return String(detail.message);
    return JSON.stringify(detail);
  }
  return "The request failed.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError("Cannot reach the backend. Check the server URL and your connection.", 0);
  }
  const data: unknown = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : data;
    throw new ApiError(readableDetail(detail), response.status);
  }
  return data as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/health");
}

export function postChat(payload: {
  session_id: string;
  message: string;
  system_prompt?: string;
}): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
