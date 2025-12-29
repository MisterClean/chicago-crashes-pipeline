import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: __dirname,

  // Proxy API requests in development (nginx handles this in production)
  async rewrites() {
    // In production, nginx handles routing. In dev, we proxy directly.
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    const tilesUrl = process.env.TILES_URL || "http://localhost:3000";

    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
      {
        source: "/tiles/:path*",
        destination: `${tilesUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
