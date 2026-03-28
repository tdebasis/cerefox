export const OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings";
export const OPENAI_MODEL = "text-embedding-3-small";
export const EMBEDDING_DIMENSIONS = 768;

const MAX_RETRIES = 3;
const INITIAL_BACKOFF_MS = 500; // 500ms, 1s, 2s exponential backoff

/**
 * Embed one or more texts via the OpenAI API.
 * Always returns an array of embeddings (one per input text).
 * Retries 5xx and network errors up to 3 times with exponential backoff.
 */
export async function embedTexts(
  input: string | string[],
  apiKey: string,
): Promise<number[][]> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(OPENAI_EMBEDDING_URL, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: OPENAI_MODEL,
          input,
          dimensions: EMBEDDING_DIMENSIONS,
        }),
      });

      if (!response.ok) {
        const err = await response.text();
        // Don't retry client errors (4xx)
        if (response.status < 500) {
          throw new Error(`OpenAI embedding error ${response.status}: ${err}`);
        }
        // Server errors (5xx) are retryable
        lastError = new Error(
          `OpenAI embedding error ${response.status}: ${err}`,
        );
        const backoff = INITIAL_BACKOFF_MS * Math.pow(2, attempt);
        console.warn(
          `Embedding API returned ${response.status} (attempt ${attempt + 1}/${MAX_RETRIES}), retrying in ${backoff}ms`,
        );
        await new Promise((r) => setTimeout(r, backoff));
        continue;
      }

      const data = await response.json();
      if (attempt > 0) {
        console.info(`Embedding API succeeded on retry ${attempt}`);
      }
      const sorted = data.data.sort(
        (a: { index: number }, b: { index: number }) => a.index - b.index,
      );
      return sorted.map((d: { embedding: number[] }) => d.embedding);
    } catch (err) {
      if (
        err instanceof Error &&
        err.message.startsWith("OpenAI embedding error")
      ) {
        // Non-retryable (4xx) errors already thrown above
        throw err;
      }
      // Network/timeout errors are retryable
      lastError = err instanceof Error ? err : new Error(String(err));
      const backoff = INITIAL_BACKOFF_MS * Math.pow(2, attempt);
      console.warn(
        `Embedding API request failed: ${lastError.message} (attempt ${attempt + 1}/${MAX_RETRIES}), retrying in ${backoff}ms`,
      );
      await new Promise((r) => setTimeout(r, backoff));
    }
  }

  throw (
    lastError ?? new Error(`Embedding API failed after ${MAX_RETRIES} attempts`)
  );
}
