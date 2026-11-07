import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";
import { installRbacDeniedGuard } from "@/lib/rbacDeniedGuard";
import { installCvHeader } from "@/lib/entitas";

installRbacDeniedGuard();
// Tahap 8: header X-CV (pilihan CV Portal Keuangan) — hanya terkirim selama Portal Keuangan terbuka.
installCvHeader();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
