import { defineConfig } from "astro/config";

// 배포 위치가 정해지면 SITE_URL / BASE_PATH 환경변수로 지정한다 (예: GitHub Pages 프로젝트 페이지).
export default defineConfig({
  site: process.env.SITE_URL,
  base: process.env.BASE_PATH ?? "/",
  trailingSlash: "always",
  build: { format: "directory" },
});
