import { cpSync } from "node:fs";

// Next standalone omits static assets; include them for npm start and Docker alike.
cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
