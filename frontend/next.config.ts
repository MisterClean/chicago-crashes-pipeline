import type { NextConfig } from "next";

const ABSOLUTE_URL_PATTERN = /^https?:\/\//i;

function isAbsoluteUrl(value: string | undefined): value is string {
  return Boolean(value && ABSOLUTE_URL_PATTERN.test(value));
}

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: __dirname,

  // Proxy API requests in development (nginx handles this in production)
  async rewrites() {
    const publicApiUrl = process.env.NEXT_PUBLIC_API_URL;
    const backendUrl = isAbsoluteUrl(publicApiUrl)
      ? publicApiUrl
      : process.env.BACKEND_URL || "http://localhost:8000";
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
