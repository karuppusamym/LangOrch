/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@xyflow/react", "@xyflow/system"],
  allowedDevOrigins: ["http://127.0.0.1:3000", "http://localhost:3000"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
