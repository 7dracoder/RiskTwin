/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Keep the build rooted in this app so a stray lockfile above the repository
  // cannot be picked up as the workspace root.
  turbopack: { root: import.meta.dirname },
  agentRules: false,
  // Everything this app talks to is the local RiskTwin API. No external image
  // hosts, fonts or analytics are configured, so the browser cannot reach a
  // hosted service (spec section 8.3).
  images: { unoptimized: true },
};

export default nextConfig;
