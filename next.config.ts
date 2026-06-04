import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  outputFileTracingIncludes: {
    "/api/registry": [
      "./agents/registry.yaml",
      "./connectors/registry.yaml",
      "./eaos.config.yaml",
      "./data/logs/audit.jsonl",
      "./data/approvals.json",
    ],
  },
};

export default nextConfig;
