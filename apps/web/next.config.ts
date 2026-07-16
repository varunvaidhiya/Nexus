import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker runtime image only
  // needs .next/standalone + .next/static, not node_modules.
  output: "standalone",
};

export default nextConfig;
