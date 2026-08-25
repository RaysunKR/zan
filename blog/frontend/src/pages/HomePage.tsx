import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search, Eye, Clock } from "lucide-react";
import { api, ApiError, type PostsResponse, type Tag } from "@/lib/api";
import { useDebounced, formatDate } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1") || 1;
  const tag = searchParams.get("tag") ?? "";
  const qParam = searchParams.get("q") ?? "";

  const [searchText, setSearchText] = useState(qParam);
  const debouncedSearch = useDebounced(searchText, 350);

  // 搜索词防抖后同步到 URL（并重置回第 1 页）
  useEffect(() => {
    if (debouncedSearch === qParam) return;
    const next = new URLSearchParams(searchParams);
    if (debouncedSearch) next.set("q", debouncedSearch);
    else next.delete("q");
    next.delete("page");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  const [data, setData] = useState<PostsResponse | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ page: String(page), per_page: "10" });
    if (qParam) params.set("q", qParam);
    if (tag) params.set("tag", tag);
    api<PostsResponse>(`/posts?${params.toString()}`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, qParam, tag]);

  useEffect(() => {
    api<{ items: Tag[] }>("/tags")
      .then((res) => setTags(res.items))
      .catch(() => {
        // 标签栏加载失败不影响主列表
      });
  }, []);

  const toggleTag = (name: string) => {
    const next = new URLSearchParams(searchParams);
    if (tag === name) next.delete("tag");
    else next.set("tag", name);
    next.delete("page");
    setSearchParams(next);
  };

  const goToPage = (p: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(p));
    setSearchParams(next);
  };

  const pageButtons = useMemo(() => {
    if (!data) return [];
    const total = data.pages;
    const current = data.page;
    const list: (number | "...")[] = [];
    for (let i = 1; i <= total; i++) {
      if (i === 1 || i === total || Math.abs(i - current) <= 1) {
        list.push(i);
      } else if (list[list.length - 1] !== "...") {
        list.push("...");
      }
    }
    return list;
  }, [data]);

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">文章</h1>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索文章…"
            className="pl-9"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
        </div>
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {tags.map((t) => (
              <Badge
                key={t.name}
                variant={tag === t.name ? "default" : "secondary"}
                className="cursor-pointer select-none"
                onClick={() => toggleTag(t.name)}
              >
                {t.name} · {t.count}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {error && <p className="text-sm text-destructive-foreground">{error}</p>}

      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-full" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-4 w-1/3" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : data && data.items.length > 0 ? (
        <div className="space-y-4">
          {data.items.map((post) => (
            <Link to={`/post/${post.slug}`} key={post.id} className="block">
              <Card className="transition-shadow hover:shadow-md">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <span>{post.title}</span>
                    {post.draft && <Badge variant="outline">草稿</Badge>}
                  </CardTitle>
                  <CardDescription>{post.summary}</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                  <span>{formatDate(post.created_at)}</span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    {post.reading_minutes} 分钟
                  </span>
                  <span className="flex items-center gap-1">
                    <Eye className="h-3.5 w-3.5" />
                    {post.views}
                  </span>
                  <span className="flex flex-wrap gap-1.5">
                    {post.tags.map((t) => (
                      <Badge key={t} variant="secondary">
                        {t}
                      </Badge>
                    ))}
                  </span>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        !error && <p className="py-12 text-center text-muted-foreground">暂无文章</p>
      )}

      {data && data.pages > 1 && (
        <div className="flex items-center justify-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={data.page <= 1}
            onClick={() => goToPage(data.page - 1)}
          >
            上一页
          </Button>
          {pageButtons.map((p, i) =>
            p === "..." ? (
              <span key={`e-${i}`} className="px-2 text-muted-foreground">
                …
              </span>
            ) : (
              <Button
                key={p}
                variant={p === data.page ? "default" : "outline"}
                size="sm"
                onClick={() => goToPage(p)}
              >
                {p}
              </Button>
            )
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={data.page >= data.pages}
            onClick={() => goToPage(data.page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}
