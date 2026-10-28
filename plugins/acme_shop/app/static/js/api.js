// Thin fetch wrapper. Every write sends JSON, because the server refuses anything else.
export class ApiError extends Error {
  constructor(message, status = 0, code = "error") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, path, body) {
  const write = method !== "GET";
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: write ? { "Content-Type": "application/json" } : {},
      body: write ? JSON.stringify(body ?? {}) : undefined,
    });
  } catch (err) {
    throw new ApiError("Cannot reach the shop server. Is it still running?", 0, "offline");
  }
  let data = null;
  try {
    data = await res.json();
  } catch (err) {
    data = null;
  }
  if (!res.ok) throw new ApiError((data && data.message) || `Request failed (${res.status})`, res.status, data && data.error);
  return data;
}

export const get = (path) => request("GET", path);
export const post = (path, body) => request("POST", path, body);
export const put = (path, body) => request("PUT", path, body);
