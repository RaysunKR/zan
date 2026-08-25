const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "same-origin",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError("网络错误，请稍后重试", 0);
  }
  if (!res.ok) {
    let message = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      if (data && typeof data.error === "string") {
        message = data.error;
      }
    } catch {
      // 非 JSON 响应体，使用默认错误信息
    }
    throw new ApiError(message, res.status);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// ---------- API 类型（与 blog/API.md 契约一一对应） ----------

export interface PostCard {
  id: number;
  slug: string;
  title: string;
  summary: string;
  tags: string[];
  created_at: string;
  reading_minutes: number;
  views: number;
  draft: boolean;
}

export interface PostDetail extends PostCard {
  content_html: string;
  content_md: string;
  updated_at: string;
  likes: number;
  reading_minutes: number;
  prev_slug: string | null;
  prev_title: string | null;
  next_slug: string | null;
  next_title: string | null;
}

export interface Comment {
  id: number;
  author: string;
  body: string;
  created_at: string;
}

export interface Tag {
  name: string;
  count: number;
}

export interface Meta {
  blog_title: string;
  posts: number;
  comments: number;
}

export interface PostsResponse {
  items: PostCard[];
  total: number;
  page: number;
  pages: number;
}
