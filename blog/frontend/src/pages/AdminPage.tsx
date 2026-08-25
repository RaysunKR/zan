import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { api, ApiError, type PostsResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export default function AdminPage() {
  const navigate = useNavigate();
  const { authenticated } = useAuth();
  const [data, setData] = useState<PostsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api<PostsResponse>("/posts?per_page=100")
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (authenticated === false) {
      navigate("/login", { replace: true });
    }
  }, [authenticated, navigate]);

  useEffect(() => {
    if (authenticated) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated]);

  const handleDelete = async (id: number) => {
    setDeleting(id);
    try {
      await api(`/posts/${id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeleting(null);
    }
  };

  if (authenticated === null || authenticated === false) {
    return <Skeleton className="h-40 w-full" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">文章管理</h1>
        <Button asChild>
          <Link to="/admin/new">
            <Plus />
            新建文章
          </Link>
        </Button>
      </div>

      {error && <p className="text-sm text-destructive-foreground">{error}</p>}

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : data && data.items.length > 0 ? (
        <div className="space-y-3">
          {data.items.map((post) => (
            <div key={post.id}>
              <div className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Link
                      to={`/post/${post.slug}`}
                      className="truncate font-medium hover:underline"
                    >
                      {post.title}
                    </Link>
                    {post.draft && <Badge variant="outline">草稿</Badge>}
                  </div>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {formatDate(post.created_at)} · {post.views} 次浏览
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button variant="outline" size="sm" asChild>
                    <Link to={`/admin/edit/${post.id}`}>
                      <Pencil />
                      编辑
                    </Link>
                  </Button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={deleting === post.id}
                      >
                        <Trash2 />
                        删除
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除「{post.title}」吗？此操作不可撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => handleDelete(post.id)}
                        >
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
              <Separator />
            </div>
          ))}
        </div>
      ) : (
        <p className="py-12 text-center text-muted-foreground">
          还没有文章，点击右上角新建。
        </p>
      )}
    </div>
  );
}
