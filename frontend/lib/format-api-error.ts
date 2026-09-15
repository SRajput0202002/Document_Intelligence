/**
 * FastAPI returns `detail` as a string for HTTPException, but request validation
 * errors use an array of `{ loc, msg, type }`. Passing that array to `Error()`
 * stringifies as "[object Object],..." — normalize to a readable message.
 */
export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") {
    return detail.trim() ? detail : fallback;
  }
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === "object" && "msg" in item) {
        const o = item as { msg: string; loc?: unknown[] };
        const loc = Array.isArray(o.loc) ? o.loc.filter((x) => x !== "body") : [];
        const field =
          loc.length > 0 ? `${String(loc[loc.length - 1])}: ` : "";
        return `${field}${String(o.msg)}`;
      }
      try {
        return JSON.stringify(item);
      } catch {
        return String(item);
      }
    });
    const joined = parts.filter(Boolean).join("; ");
    return joined || fallback;
  }
  if (detail != null && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}
