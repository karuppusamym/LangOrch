const { PHASE_DEVELOPMENT_SERVER } = require("next/constants");

/** @type {import('next').NextConfig} */
module.exports = (phase) => ({
  // Keep dev and production artifacts isolated so switching between
  // `next dev` and `next build` cannot leave the server runtime pointing
  // at stale chunks from a different output layout.
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next",
  transpilePackages: ["@xyflow/react", "@xyflow/system"],
  allowedDevOrigins: ["http://127.0.0.1:3000", "http://localhost:3000"],
});
