import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({ resolvePluginsRelativeTo: __dirname });

const config = [
  ...compat.extends("next/core-web-vitals"),
  { ignores: ["runtime/**", "scripts/**", "tests/**", "deploy/**"] },
];

export default config;
