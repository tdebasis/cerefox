import {
  Anchor,
  Badge,
  Card,
  Container,
  Grid,
  Group,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconDatabase, IconFolder, IconSearch } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { fetchDashboard } from "../api/dashboard";
import { useProjects } from "../hooks/useProjects";

export function DashboardPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
  });
  const { data: projects } = useProjects();

  const projectMap = new Map(
    projects?.map((p) => [p.id, p.name]) ?? [],
  );

  return (
    <Container size="lg">
      <Title order={2} mb="md">
        Dashboard
      </Title>

      <SimpleGrid cols={{ base: 1, sm: 3 }} mb="xl">
        <Card shadow="xs" padding="lg" radius="md" withBorder>
          <Group>
            <IconDatabase size={28} color="var(--mantine-color-blue-6)" />
            <div>
              <Text size="xl" fw={700}>
                {isLoading ? <Skeleton width={40} height={28} /> : data?.doc_count ?? 0}
              </Text>
              <Text size="sm" c="dimmed">
                Documents
              </Text>
            </div>
          </Group>
        </Card>
        <Card shadow="xs" padding="lg" radius="md" withBorder>
          <Group>
            <IconFolder size={28} color="var(--mantine-color-green-6)" />
            <div>
              <Text size="xl" fw={700}>
                {isLoading ? <Skeleton width={40} height={28} /> : data?.project_count ?? 0}
              </Text>
              <Text size="sm" c="dimmed">
                Projects
              </Text>
            </div>
          </Group>
        </Card>
        <Card
          shadow="xs"
          padding="lg"
          radius="md"
          withBorder
          style={{ cursor: "pointer" }}
          onClick={() => navigate("/search")}
        >
          <Group>
            <IconSearch size={28} color="var(--mantine-color-violet-6)" />
            <Text fw={600}>Search Knowledge Base</Text>
          </Group>
        </Card>
      </SimpleGrid>

      <Title order={4} mb="sm">
        Recent Documents
      </Title>
      {isLoading ? (
        <Stack gap="xs">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={40} />
          ))}
        </Stack>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Title</Table.Th>
              <Table.Th>Chunks</Table.Th>
              <Table.Th>Size</Table.Th>
              <Table.Th>Updated</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.recent_docs.map((doc) => (
              <Table.Tr key={doc.id}>
                <Table.Td>
                  <Group gap="xs">
                    <Anchor
                      href={`/app/document/${doc.id}`}
                      onClick={(e) => {
                        e.preventDefault();
                        navigate(`/document/${doc.id}`);
                      }}
                      fw={500}
                      size="sm"
                    >
                      {doc.title || "Untitled"}
                    </Anchor>
                    {doc.project_ids.map((pid) => (
                      <Badge key={pid} variant="light" size="xs">
                        {projectMap.get(pid) || pid.slice(0, 8)}
                      </Badge>
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{doc.chunk_count}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{doc.total_chars.toLocaleString()}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {doc.updated_at
                      ? new Date(doc.updated_at).toLocaleDateString()
                      : ""}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {data && data.projects.length > 0 && (
        <>
          <Title order={4} mt="xl" mb="sm">
            Projects
          </Title>
          <Grid>
            {data.projects.map((p) => (
              <Grid.Col key={p.id} span={{ base: 12, sm: 6, md: 4 }}>
                <Card shadow="xs" padding="md" radius="md" withBorder>
                  <Text fw={600} size="sm">
                    {p.name}
                  </Text>
                  {p.description && (
                    <Text size="xs" c="dimmed" lineClamp={2}>
                      {p.description}
                    </Text>
                  )}
                  <Text size="xs" c="dimmed" mt="xs">
                    {data.project_doc_counts[p.id] ?? 0} documents
                  </Text>
                </Card>
              </Grid.Col>
            ))}
          </Grid>
        </>
      )}
    </Container>
  );
}
