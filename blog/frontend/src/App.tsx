import { Route, Routes } from "react-router-dom";
import { AuthProvider } from "@/lib/auth";
import Layout from "@/components/Layout";
import HomePage from "@/pages/HomePage";
import PostPage from "@/pages/PostPage";
import LoginPage from "@/pages/LoginPage";
import AdminPage from "@/pages/AdminPage";
import EditPage from "@/pages/EditPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/post/:slug" element={<PostPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/admin/new" element={<EditPage />} />
          <Route path="/admin/edit/:id" element={<EditPage />} />
          <Route
            path="*"
            element={
              <div className="container py-24 text-center text-muted-foreground">
                页面不存在
              </div>
            }
          />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
