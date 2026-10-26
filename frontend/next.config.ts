import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: __dirname,

  async redirects() {
    return [
      {
        source: "/dashboard",
        destination: "/dashboard/location-report",
        permanent: true,
      },
    ];
  },

  // Next.js proxies browser requests to the Rust API in both environments.
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8003";

    return [
      {
        source: "/admin/:path*",
        destination: `${backendUrl}/admin/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
