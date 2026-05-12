/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The Python serverless functions in api/ are picked up by Vercel directly;
  // Next.js doesn't need to know about them. The api/ directory is excluded
  // from the TypeScript build via tsconfig "exclude".
  experimental: {
    // Allow large request bodies for STL uploads (default is 1 MB).
    largePageDataBytes: 128 * 1000,
  },
};

module.exports = nextConfig;
