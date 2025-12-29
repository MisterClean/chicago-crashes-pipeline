import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",

  // Proxy API requests to FastAPI backend in development
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: process.env.BACKEND_URL
          ? `${process.env.BACKEND_URL}/:path*`
          : "http://localhost:8000/:path*",
      },
      {
        source: "/tiles/:path*",
        destination: process.env.TILES_URL
          ? `${process.env.TILES_URL}/:path*`
          : "http://localhost:3000/:path*",
      },
    ];
  },
};

export default nextConfig;
