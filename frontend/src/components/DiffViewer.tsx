import { Group, SegmentedControl, Text } from "@mantine/core";
import { diffLines, type Change } from "diff";
import { useMemo, useState } from "react";

import styles from "./DiffViewer.module.css";

interface DiffViewerProps {
  oldContent: string;
  newContent: string;
  oldLabel?: string;
  newLabel?: string;
}

export function DiffViewer({
  oldContent,
  newContent,
  oldLabel = "Previous version",
  newLabel = "Current version",
}: DiffViewerProps) {
  const [mode, setMode] = useState<string>("unified");

  const changes = useMemo(
    () => diffLines(oldContent, newContent),
    [oldContent, newContent],
  );

  const stats = useMemo(() => {
    let added = 0;
    let removed = 0;
    for (const c of changes) {
      const lines = (c.value.match(/\n/g) || []).length;
      if (c.added) added += lines || 1;
      if (c.removed) removed += lines || 1;
    }
    return { added, removed };
  }, [changes]);

  return (
    <div>
      <Group justify="space-between" mb="xs">
        <Group gap="sm">
          <Text size="xs" c="green" fw={600}>+{stats.added} added</Text>
          <Text size="xs" c="red" fw={600}>-{stats.removed} removed</Text>
        </Group>
        <SegmentedControl
          size="xs"
          value={mode}
          onChange={setMode}
          data={[
            { label: "Unified", value: "unified" },
            { label: "Side by side", value: "split" },
          ]}
          w={200}
        />
      </Group>

      {mode === "unified" ? (
        <UnifiedDiff changes={changes} />
      ) : (
        <SplitDiff
          changes={changes}
          oldLabel={oldLabel}
          newLabel={newLabel}
        />
      )}
    </div>
  );
}

function UnifiedDiff({ changes }: { changes: Change[] }) {
  return (
    <pre className={styles.diffPre}>
      {changes.map((change, i) => {
        const cls = change.added
          ? styles.added
          : change.removed
            ? styles.removed
            : styles.context;
        return (
          <span key={i} className={cls}>
            {change.value}
          </span>
        );
      })}
    </pre>
  );
}

function SplitDiff({
  changes,
  oldLabel,
  newLabel,
}: {
  changes: Change[];
  oldLabel: string;
  newLabel: string;
}) {
  const leftLines: { text: string; type: "context" | "removed" }[] = [];
  const rightLines: { text: string; type: "context" | "added" }[] = [];

  for (const change of changes) {
    const lines = change.value.split("\n");
    // Remove trailing empty string from split
    if (lines[lines.length - 1] === "") lines.pop();

    if (change.added) {
      for (const line of lines) {
        leftLines.push({ text: "", type: "context" });
        rightLines.push({ text: line, type: "added" });
      }
    } else if (change.removed) {
      for (const line of lines) {
        leftLines.push({ text: line, type: "removed" });
        rightLines.push({ text: "", type: "context" });
      }
    } else {
      for (const line of lines) {
        leftLines.push({ text: line, type: "context" });
        rightLines.push({ text: line, type: "context" });
      }
    }
  }

  return (
    <div className={styles.splitContainer}>
      <div className={styles.splitPane}>
        <Text size="xs" fw={600} c="dimmed" mb={4}>
          {oldLabel}
        </Text>
        <pre className={styles.diffPre}>
          {leftLines.map((l, i) => (
            <span
              key={i}
              className={l.type === "removed" ? styles.removed : styles.context}
            >
              {l.text}
              {"\n"}
            </span>
          ))}
        </pre>
      </div>
      <div className={styles.splitPane}>
        <Text size="xs" fw={600} c="dimmed" mb={4}>
          {newLabel}
        </Text>
        <pre className={styles.diffPre}>
          {rightLines.map((l, i) => (
            <span
              key={i}
              className={l.type === "added" ? styles.added : styles.context}
            >
              {l.text}
              {"\n"}
            </span>
          ))}
        </pre>
      </div>
    </div>
  );
}
