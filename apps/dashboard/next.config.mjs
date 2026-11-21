/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Keep the build rooted in this app so a stray lockfile above the repository
  // cannot be picked up as the workspace root.
  turbopack: { root: import.meta.dirname },
  // The controller and worker pages are intentionally opened from the DGX's
  // private LAN address during a live demo. Next dev otherwise blocks its own
  // client chunks when the Host header is not localhost.
  allowedDevOrigins: ["127.0.0.1", "localhost", "10.0.0.199"],
  agentRules: false,
  // Everything this app talks to is the local RiskTwin API. No external image
  // hosts, fonts or analytics are configured, so the browser cannot reach a
  // hosted service (spec section 8.3).
  images: { unoptimized: true },
};

export default nextConfig;
