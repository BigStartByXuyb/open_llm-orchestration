import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Home } from "./pages/Home";
import { History } from "./pages/History";
import { Plugins } from "./pages/Plugins";
import { Settings } from "./pages/Settings";
import { Usage } from "./pages/Usage";
import { Documents } from "./pages/Documents";
import { Login } from "./pages/Login";
import { ComingSoon } from "./components/ComingSoon";
import { useAuthStore } from "./store/authStore";

function ProtectedLayout() {
  return (
    <div className="flex h-screen bg-bg-base overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/history" element={<History />} />
          <Route path="/plugins" element={<Plugins />} />
          <Route path="/tasks" element={<ComingSoon />} />
          <Route path="/usage" element={<Usage />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/topology" element={<ComingSoon />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  const isAuthenticated = useAuthStore((s) => Boolean(s.token));

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return <ProtectedLayout />;
}
