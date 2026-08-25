import { Outlet, Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export default function Layout() {
  const { authenticated, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
        <div className="container mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
          <Link
            to="/"
            className="text-lg font-bold tracking-tight hover:opacity-80"
          >
            zan 博客
          </Link>
          <nav className="flex items-center gap-2">
            <Button variant="ghost" asChild>
              <Link to="/">首页</Link>
            </Button>
            {authenticated ? (
              <>
                <Button variant="ghost" asChild>
                  <Link to="/admin">管理</Link>
                </Button>
                <Button variant="ghost" onClick={handleLogout}>
                  退出
                </Button>
              </>
            ) : (
              <Button variant="ghost" asChild>
                <Link to="/login">登录</Link>
              </Button>
            )}
          </nav>
        </div>
      </header>
      <main className="container mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="container mx-auto max-w-4xl px-4 pb-8">
        <Separator className="mb-6" />
        <p className="text-center text-sm text-muted-foreground">
          Powered by zan · React · shadcn/ui
        </p>
      </footer>
    </div>
  );
}
