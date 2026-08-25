import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type PostsResponse, type PostDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";

export default function EditPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const { authenticated } = useAuth();

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [summary, setSummary] = useState("");
  const [contentMd, setContentMd] = useState("");
  const [tags, setTags] = useState("");
  const [draft, setDraft] = useState(false);

  useEffect(() => {
    if (authenticated === false) {
      navigate("/login", { replace: true });
    }
  }, [authenticated, navigate]);

  // 编辑模式：契约只提供按 slug 的详情接口，先从列表反查 slug
  useEffect(() => {
    if (!isEdit || !id) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const list = await api<PostsResponse>("/posts?per_page=100");
        const card = list.items.find((p) => String(p.id) === id);
        if (!card) throw new ApiError("文章不存在", 404);
        const detail = await api<PostDetail>(
          `/posts/${encodeURIComponent(card.slug)}`
        );
        if (cancelled) return;
        setTitle(detail.title);
        setSlug(detail.slug);
        setSummary(detail.summary);
        setContentMd(detail.content_md);
        setTags(detail.tags.join(", "));
        setDraft(detail.draft);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "文章加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isEdit, id]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !contentMd.trim()) return;
    setSaving(true);
    setError(null);
    const tagList = tags
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean);
    const payload: Record<string, unknown> = {
      title: title.trim(),
      summary: summary.trim(),
      content_md: contentMd,
      tags: tagList,
      draft,
    };
    if (slug.trim()) payload.slug = slug.trim();
    try {
      if (isEdit && id) {
        await api(`/posts/${id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      } else {
        await api("/posts", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      navigate("/admin");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (authenticated === null || authenticated === false) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/admin" className="text-sm text-muted-foreground hover:underline">
          返回管理
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">
          {isEdit ? "编辑文章" : "新建文章"}
        </h1>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor="title">标题</Label>
          <Input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="文章标题"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="slug">
            Slug（留空自动生成{isEdit ? "；修改会影响文章地址" : ""}）
          </Label>
          <Input
            id="slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="url-friendly-slug"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="summary">摘要</Label>
          <Textarea
            id="summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={2}
            placeholder="一句话概括这篇文章"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="content">正文（Markdown）</Label>
          <Textarea
            id="content"
            value={contentMd}
            onChange={(e) => setContentMd(e.target.value)}
            required
            rows={18}
            placeholder="# 标题&#10;&#10;正文支持 Markdown 语法…"
            className="font-mono text-sm leading-7"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="tags">标签（逗号分隔）</Label>
          <Input
            id="tags"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="rust, web, 随笔"
          />
        </div>

        <div className="flex items-center gap-3">
          <Switch
            id="draft"
            checked={draft}
            onCheckedChange={setDraft}
          />
          <Label htmlFor="draft">存为草稿（草稿仅登录后可见）</Label>
        </div>

        {error && <p className="text-sm text-destructive-foreground">{error}</p>}

        <div className="flex gap-2">
          <Button type="submit" disabled={saving}>
            {saving ? "保存中…" : "保存"}
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link to="/admin">取消</Link>
          </Button>
        </div>
      </form>
    </div>
  );
}
