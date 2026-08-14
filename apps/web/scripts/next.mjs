import path from "node:path";
import { fileURLToPath } from "node:url";

// Some managed Windows environments reject the native SWC addon. The official
// WASM package keeps local builds reproducible; set ATLAS_USE_NATIVE_SWC=1 to
// opt back into the faster native compiler.
if (process.platform === "win32" && process.env.ATLAS_USE_NATIVE_SWC !== "1") {
  const here = path.dirname(fileURLToPath(import.meta.url));
  process.env.NEXT_TEST_WASM = "1";
  process.env.NEXT_TEST_WASM_DIR = path.resolve(here, "../node_modules/@next/swc-wasm-nodejs");
}

await import("next/dist/bin/next");
