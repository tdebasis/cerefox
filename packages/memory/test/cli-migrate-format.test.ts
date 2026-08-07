/**
 * Smoke tests for `cerefox server migrate-format` (issue #164).
 *
 * `server reindex` re-embeds chunks in place but never re-chunks, so it
 * cannot advance a document's `content_format` — despite the docs (until
 * this fix) claiming it does. This command is the actual conversion path.
 *
 * Live tests probe-and-skip on Supabase reachability, matching
 * `cli-reindex.test.ts`'s convention.
 */

import { describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PKG_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = join(PKG_ROOT, "..", "..");
const BIN = join(PKG_ROOT, "dist", "bin", "cerefox.js");

function run(args: string[]): {
  stdout: string;
  stderr: string;
  status: number;
} {
  if (!existsSync(BIN)) {
    throw new Error(`Built bin not found at ${BIN}. Run \`bun run build\`.`);
  }
  const result = spawnSync("node", [BIN, ...args], {
    encoding: "utf8",
    cwd: REPO_ROOT,
    env: { ...process.env },
    timeout: 30_000,
  });
  return {
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    status: result.status ?? -1,
  };
}

// Probe via list-projects (the canonical "is the backend reachable" smoke).
const probe = run(["project", "list", "--json"]);
const LIVE_OK = probe.status === 0;

describe("cerefox server migrate-format CLI", () => {
  test("--help advertises the flags", () => {
    const { stdout, status } = run(["server", "migrate-format", "--help"]);
    expect(status).toBe(0);
    expect(stdout).toContain("content_format");
    expect(stdout).toContain("--all");
    expect(stdout).toContain("--dry-run");
    expect(stdout).toContain("--document-id");
    expect(stdout).toContain("--batch");
  });

  test("neither --all nor --document-id errors out", () => {
    const { stderr, status } = run(["server", "migrate-format"]);
    expect(status).not.toBe(0);
    expect(stderr).toContain("Pass --all");
  });

  test("invalid --batch errors out", () => {
    if (!LIVE_OK) {
      console.log("(skipped: Supabase unreachable)");
      return;
    }
    const { stderr, status } = run([
      "server", "migrate-format", "--all", "--batch", "not-a-number",
    ]);
    expect(status).not.toBe(0);
    expect(stderr).toContain("Invalid --batch");
  });

  test("--all --dry-run runs without writing (live)", () => {
    if (!LIVE_OK) {
      console.log("(skipped: Supabase unreachable)");
      return;
    }
    const { stdout, status } = run(["server", "migrate-format", "--all", "--dry-run"]);
    expect(status).toBe(0);
    // Either "Would migrate N document(s):" or "nothing to migrate"
    // depending on what the DB looks like. Both are valid outcomes.
    expect(stdout).toMatch(/Would migrate \d+ document|nothing to migrate/);
  });

  test("--document-id with a fake UUID returns not-found", () => {
    if (!LIVE_OK) {
      console.log("(skipped: Supabase unreachable)");
      return;
    }
    const { stderr, status } = run([
      "server", "migrate-format",
      "--dry-run",
      "--document-id",
      "00000000-0000-0000-0000-000000000000",
    ]);
    // Distinct from reindex's softer "nothing to reindex" on an empty
    // result set — a fake document id here is a genuine not-found.
    expect(status).toBe(3);
    expect(stderr).toContain("not found");
  });

  test(
    "--all --dry-run is idempotent across two consecutive runs",
    () => {
      if (!LIVE_OK) {
        console.log("(skipped: Supabase unreachable)");
        return;
      }
      // This doesn't prove the full migrate-then-reconverge idempotency
      // (that requires a real --all run, which this suite deliberately
      // never does against a live store), but it does prove two dry-run
      // candidate scans agree exactly — i.e. the candidate query itself
      // is stable and side-effect-free.
      const first = run(["server", "migrate-format", "--all", "--dry-run"]);
      const second = run(["server", "migrate-format", "--all", "--dry-run"]);
      expect(first.status).toBe(0);
      expect(second.status).toBe(0);
      expect(first.stdout).toBe(second.stdout);
    },
    30_000,
  );
});
