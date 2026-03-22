import {
  Alert,
  Button,
  Container,
  Group,
  MultiSelect,
  Stack,
  TextInput,
  Textarea,
  Title,
  Text,
  ActionIcon,
  Select,
} from "@mantine/core";
import { IconCheck, IconPlus, IconX } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ingestPaste } from "../api/documents";
import { useMetadataKeys, useProjects } from "../hooks/useProjects";

export function IngestPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: projects } = useProjects();
  const { data: metadataKeys } = useMetadataKeys();

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [updateExisting, setUpdateExisting] = useState(false);
  const [metaPairs, setMetaPairs] = useState<{ key: string; value: string }[]>(
    [],
  );

  const mutation = useMutation({
    mutationFn: () => {
      const metadata: Record<string, string> = {};
      for (const pair of metaPairs) {
        if (pair.key.trim() && pair.value.trim()) {
          metadata[pair.key.trim()] = pair.value.trim();
        }
      }
      return ingestPaste({
        title,
        content,
        update_existing: updateExisting,
        project_ids: projectIds,
        metadata,
      });
    },
    onSuccess: (result) => {
      if (result.success) {
        queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      }
    },
  });

  const projectOptions =
    projects?.map((p) => ({ value: p.id, label: p.name })) || [];

  const keyOptions =
    metadataKeys?.map((mk) => ({
      value: mk.key,
      label: `${mk.key} (${mk.doc_count})`,
    })) || [];

  const result = mutation.data;

  return (
    <Container size="md">
      <Title order={2} mb="md">
        Ingest Content
      </Title>

      {result?.success && (
        <Alert
          icon={<IconCheck size={16} />}
          title={result.updated ? "Updated" : "Ingested"}
          color="green"
          mb="md"
          withCloseButton
          onClose={() => mutation.reset()}
        >
          {result.updated
            ? `"${result.title}" updated and re-indexed.`
            : `"${result.title}" ingested successfully.`}
          {result.document_id && (
            <>
              {" "}
              <Text
                component="span"
                size="sm"
                c="blue"
                style={{ cursor: "pointer", textDecoration: "underline" }}
                onClick={() => navigate(`/document/${result.document_id}`)}
              >
                View document
              </Text>
            </>
          )}
        </Alert>
      )}

      {result && !result.success && result.error && (
        <Alert
          icon={<IconX size={16} />}
          title="Error"
          color="red"
          mb="md"
          withCloseButton
          onClose={() => mutation.reset()}
        >
          {result.error}
        </Alert>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <Stack gap="md">
          <TextInput
            label="Title"
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
            required
            placeholder="Document title"
          />

          {projectOptions.length > 0 && (
            <MultiSelect
              label="Projects"
              data={projectOptions}
              value={projectIds}
              onChange={setProjectIds}
              clearable
              searchable
              placeholder="Assign to projects (optional)"
            />
          )}

          <div>
            <Text size="sm" fw={500} mb="xs">
              Metadata (optional)
            </Text>
            <Stack gap="xs">
              {metaPairs.map((pair, idx) => (
                <Group key={idx} gap="xs">
                  <Select
                    placeholder="Key"
                    data={keyOptions}
                    value={pair.key}
                    onChange={(v) => {
                      const updated = [...metaPairs];
                      updated[idx] = { ...pair, key: v || "" };
                      setMetaPairs(updated);
                    }}
                    searchable
                    w={200}
                    size="sm"
                  />
                  <TextInput
                    placeholder="Value"
                    value={pair.value}
                    onChange={(e) => {
                      const updated = [...metaPairs];
                      updated[idx] = {
                        ...pair,
                        value: e.currentTarget.value,
                      };
                      setMetaPairs(updated);
                    }}
                    w={250}
                    size="sm"
                  />
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    onClick={() =>
                      setMetaPairs(metaPairs.filter((_, i) => i !== idx))
                    }
                  >
                    <IconX size={14} />
                  </ActionIcon>
                </Group>
              ))}
              <Button
                variant="light"
                size="xs"
                w={140}
                leftSection={<IconPlus size={14} />}
                onClick={() =>
                  setMetaPairs([...metaPairs, { key: "", value: "" }])
                }
              >
                Add field
              </Button>
            </Stack>
          </div>

          <Textarea
            label="Content"
            value={content}
            onChange={(e) => setContent(e.currentTarget.value)}
            minRows={10}
            autosize
            required
            placeholder="Paste your Markdown content here..."
            styles={{ input: { fontFamily: "monospace", fontSize: 13 } }}
          />

          <Group>
            <Button type="submit" loading={mutation.isPending}>
              Ingest
            </Button>
            <Button
              variant={updateExisting ? "filled" : "light"}
              color={updateExisting ? "yellow" : "gray"}
              size="sm"
              onClick={() => setUpdateExisting(!updateExisting)}
            >
              {updateExisting ? "Update existing: ON" : "Update existing: OFF"}
            </Button>
          </Group>
        </Stack>
      </form>
    </Container>
  );
}
