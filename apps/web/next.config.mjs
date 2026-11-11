/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ponytail: the API is a separate local process; no rewrites/proxy layer needed
  async headers() {
    return [{ source: "/(.*)", headers: [{ key: "X-Content-Type-Options", value: "nosniff" }] }];
  },
};
export default nextConfig;
