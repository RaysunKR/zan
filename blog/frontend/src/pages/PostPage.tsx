import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { Eye, Clock, Heart, ArrowLeft, ArrowRight } from "lucide-react";
import { api, ApiError, type PostDetail, type Comment } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function PostPage() {
  const { slug } = useParams<{ slug: string }>();
  const [post, setPost] = useState<PostDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [likes, setLikes] = useState<number | null>(null);
  const [liked, setLiked] = useState(false);
  const [likeError, setLikeError] = useState<string | null>(null);

  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [author, setAuthor] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [commentError, setCommentError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPost(null);
    setLikes(null);
    setLiked(false);
    api<PostDetail>(`/posts/${encodeURIComponent(slug ?? "")}`)
      .then((res) => {
        if (cancelled) return;
        setPost(res);
        setLikes(res.likes ?? 0);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "文章加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    api<{ items: Comment[] }>(`/posts/${encodeURIComponent(slug ?? "")}/comments`)
      .then((res) => {
        if (!cancelled) setComments(res.items);
      })
      .catch(() => {
        // 评论加载失败不阻塞正文
      })
      .finally(() => {
        if (!cancelled) setCommentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const handleLike = async () => {
    if (!post || liked || likes === null) return;
    setLikeError(null);
    try {
      const res = await api<{ likes: number }>(
        `/posts/${encodeURIComponent(post.slug)}/like`,
        { method: "POST" }
      );
      setLikes(res.likes);
      setLiked(true);
    } catch (e) {
      setLikeError(e instanceof ApiError ? e.message : "点赞失败");
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!post || !author.trim() || !body.trim()) return;
    setSubmitting(true);
    setCommentError(null);
    try {
      const created = await api<Comment>(
        `/posts/${encodeURIComponent(post.slug)}/comments`,
        {
          method: "POST",
          body: JSON.stringify({ author: author.trim(), body: body.trim() }),
        }
      );
      setComments((prev) => [...prev, created]);
      setAuthor("");
      setBody("");
    } catch (e) {
      setCommentError(e instanceof ApiError ? e.message : "评论提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !post) {
    return (
      <div className="py-16 text-center">
        <p className="mb-4 text-muted-foreground">{error ?? "文章不存在"}</p>
        <Button variant="outline" asChild>
          <Link to="/">返回首页</Link>
        </Button>
      </div>
    );
  }

  return (
    <article className="space-y-6">
      <div className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">{post.title}</h1>
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <span>{formatDate(post.created_at)}</span>
          <span className="flex items-center gap-1">
            <Eye className="h-3.5 w-3.5" />
            {post.views}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {post.reading_minutes} 分钟
          </span>
          <span className="flex gap-1.5">
            {post.tags.map((t) => (
              <Badge key={t} variant="secondary">
                {t}
              </Badge>
            ))}
          </span>
        </div>
      </div>

      <Separator />

      <div
        className="prose prose-neutral dark:prose-invert max-w-none prose-headings:tracking-tight prose-pre:bg-muted prose-code:font-mono"
        dangerouslySetInnerHTML={{ __html: post.content_html }}
      />

      <div className="flex items-center gap-3">
        <Button
          variant={liked ? "default" : "outline"}
          size="sm"
          onClick={handleLike}
          disabled={likes === null}
        >
          <Heart className={liked ? "fill-current" : ""} />
          {likes ?? "…"}
        </Button>
        {likeError && (
          <span className="text-sm text-destructive-foreground">{likeError}</span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {post.prev_slug ? (
          <Link to={`/post/${post.prev_slug}`} className="group">
            <Card className="transition-shadow hover:shadow-md">
              <CardContent className="flex items-center gap-2 p-4 text-sm">
                <ArrowLeft className="h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="text-muted-foreground">上一篇</p>
                  <p className="truncate group-hover:underline">
                    {post.prev_title}
                  </p>
                </div>
              </CardContent>
            </Card>
          </Link>
        ) : (
          <div />
        )}
        {post.next_slug && (
          <Link to={`/post/${post.next_slug}`} className="group">
            <Card className="transition-shadow hover:shadow-md">
              <CardContent className="flex items-center justify-end gap-2 p-4 text-sm">
                <div className="min-w-0 text-right">
                  <p className="text-muted-foreground">下一篇</p>
                  <p className="truncate group-hover:underline">
                    {post.next_title}
                  </p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </CardContent>
            </Card>
          </Link>
        )}
      </div>

      <Separator />

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">评论（{comments.length}）</h2>
        {commentsLoading ? (
          <div className="space-y-3">
            {[1, 2].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : comments.length > 0 ? (
          <div className="space-y-3">
            {comments.map((c) => (
              <Card key={c.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-baseline justify-between">
                    <CardTitle className="text-sm">{c.author}</CardTitle>
                    <span className="text-xs text-muted-foreground">
                      {formatDate(c.created_at)}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="text-sm whitespace-pre-wrap">
                  {c.body}
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">还没有评论，来抢沙发吧。</p>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <Input
            placeholder="你的名字"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            required
            maxLength={50}
          />
          <Textarea
            placeholder="写下你的评论…"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            required
            rows={4}
          />
          {commentError && (
            <p className="text-sm text-destructive-foreground">{commentError}</p>
          )}
          <Button type="submit" disabled={submitting}>
            {submitting ? "提交中…" : "提交评论"}
          </Button>
        </form>
      </section>
    </article>
  );
}
