// /** @type {import('next').NextConfig} */
// const nextConfig = {
//   async rewrites() {
//     return [
//       // Proxy /api/* → FastAPI /api/*
//       {
//         source: '/api/:path*',
//         destination: 'http://localhost:8000/api/:path*',
//       },
//       // BackendStatus hits /api/health — but backend exposes /health (no /api prefix)
//       // So we add a dedicated rule *before* the wildcard (Next.js evaluates in order)
//       // NOTE: the wildcard above already handles /api/health → /api/health on backend,
//       // which does NOT exist. The real health endpoint is GET /health.
//       // We remap /api/health → /health on the backend.
//       {
//         source: '/health',
//         destination: 'http://localhost:8000/health',
//       },
//     ]
//   },
// }
// module.exports = nextConfig

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'https://sentinel-production-b835.up.railway.app/api/:path*',
      },
      {
        source: '/health',
        destination: 'https://sentinel-production-b835.up.railway.app/health',
      },
    ]
  },
}

module.exports = nextConfig