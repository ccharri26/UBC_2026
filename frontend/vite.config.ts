import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// `npm run dev` serves the UI on :5173 and forwards /api to uvicorn on :8000.
// `npm run build` writes dist/, which FastAPI serves at / (see api/app.py).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
