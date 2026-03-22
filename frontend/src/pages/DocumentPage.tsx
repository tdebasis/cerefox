import {
  Accordion,
  Anchor,
  Badge,
  Button,
  Code,
  Container,
  Divider,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import {
  IconDownload,
  IconEdit,
  IconTrash,
} from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useState } from "react";

import { fetchDocument, fetchChunks, deleteDocument, getDownloadUrl } from "../api/documents";
import { useProjects } from "../hooks/useProjects";

export function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ["document", id],
    queryFn: () => fetchDocument(id!),
    enabled: !!id,
  });

  const { data: chunks, isLoading: chunksLoading } = useQuery({
    queryKey: ["document-chunks", id],
    queryFn: () => fetchChunks(id!),
    enabled: !!id,
  });

  const { data: projects } = useProjects();
  const projectMap = new Map(projects?.map((p) => [p.id, p.name]) ?? []);

  const deleteMutation = useMutation({
    mutationFn: () => deleteDocument(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      navigate("/");
    },
  });

  if (isLoading) {
    return (
      <Container size="lg">
        <Group justify="center" mt="xl">
          <Loader />
        </Group>
      </Container>
    );
  }

  if (error || !doc) {
    return (
      <Container size="lg">
        <Text c="red" mt="xl">
          {error ? String(error) : "Document not found."}
        </Text>
      </Container>
    );
  }

  const metaEntries = Object.entries(doc.doc_metadata || {});

  return (
    <Container size="lg">
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Title order={2}>{doc.doc_title || "Untitled"}</Title>
          <Group gap="xs" mt="xs">
            {doc.project_ids.map((pid) => (
              <Badge key={pid} variant="light" size="sm">
                {projectMap.get(pid) || pid.slice(0, 8)}
              </Badge>
            ))}
            <Text size="sm" c="dimmed">
              {doc.chunk_count} chunks | {doc.total_chars.toLocaleString()} chars
            </Text>
            {doc.created_at && (
              <Text size="xs" c="dimmed">
                Created {new Date(doc.created_at).toLocaleDateString()}
              </Text>
            )}
            {doc.updated_at && (
              <Text size="xs" c="dimmed">
                Updated {new Date(doc.updated_at).toLocaleDateString()}
              </Text>
            )}
          </Group>
        </div>
        <Group gap="xs">
          <Button
            variant="light"
            size="xs"
            leftSection={<IconEdit size={14} />}
            onClick={() => navigate(`/document/${id}/edit`)}
          >
            Edit
          </Button>
          <Button
            variant="light"
            size="xs"
            leftSection={<IconDownload size={14} />}
            component="a"
            href={getDownloadUrl(id!)}
          >
            Download
          </Button>
          {!confirmDelete ? (
            <Button
              variant="light"
              color="red"
              size="xs"
              leftSection={<IconTrash size={14} />}
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </Button>
          ) : (
            <Group gap={4}>
              <Button
                color="red"
                size="xs"
                onClick={() => deleteMutation.mutate()}
                loading={deleteMutation.isPending}
              >
                Confirm delete
              </Button>
              <Button
                variant="subtle"
                size="xs"
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </Button>
            </Group>
          )}
        </Group>
      </Group>

      {metaEntries.length > 0 && (
        <>
          <Divider my="sm" />
          <Accordion variant="contained" mb="md">
            <Accordion.Item value="metadata">
              <Accordion.Control>
                <Text size="sm" fw={500}>
                  Metadata ({metaEntries.length} fields)
                </Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Table>
                  <Table.Tbody>
                    {metaEntries.map(([k, v]) => (
                      <Table.Tr key={k}>
                        <Table.Td fw={500} w={200}>
                          {k}
                        </Table.Td>
                        <Table.Td>{String(v)}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        </>
      )}

      {doc.versions.length > 0 && (
        <>
          <Text size="sm" fw={500} mb="xs">
            Version History
          </Text>
          <Group gap="xs" mb="md">
            {doc.versions.map((v) => (
              <Anchor
                key={v.version_id}
                href={getDownloadUrl(id!, v.version_id)}
                size="xs"
              >
                <Badge variant="outline" size="sm">
                  v{v.version_number} | {v.total_chars.toLocaleString()} chars |{" "}
                  {new Date(v.created_at).toLocaleDateString()}
                </Badge>
              </Anchor>
            ))}
          </Group>
        </>
      )}

      <Divider my="sm" />

      <Accordion variant="separated" multiple defaultValue={["content"]}>
        <Accordion.Item value="content">
          <Accordion.Control>
            <Text size="sm" fw={500}>
              Full Content ({doc.total_chars.toLocaleString()} chars)
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            <Code
              block
              style={{ whiteSpace: "pre-wrap", maxHeight: 600, overflow: "auto" }}
            >
              {doc.full_content || "(empty)"}
            </Code>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="chunks">
          <Accordion.Control>
            <Text size="sm" fw={500}>
              Chunks ({doc.chunk_count})
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            {chunksLoading ? (
              <Loader size="sm" />
            ) : (
              <Stack gap="sm">
                {chunks?.map((c) => (
                  <div
                    key={c.chunk_id}
                    style={{
                      border: "1px solid var(--mantine-color-gray-3)",
                      borderRadius: 8,
                      padding: 8,
                    }}
                  >
                    <Text size="xs" c="dimmed" mb={4} style={{ fontFamily: "monospace" }}>
                      {c.heading_path.length > 0
                        ? c.heading_path.join(" > ")
                        : "(preamble)"}
                    </Text>
                    <Code
                      block
                      style={{ whiteSpace: "pre-wrap", fontSize: 12 }}
                    >
                      {c.content}
                    </Code>
                  </div>
                ))}
              </Stack>
            )}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Container>
  );
}
