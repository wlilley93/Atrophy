/**
 * Local embedding engine - Transformers.js on WASM/CPU.
 * Port of core/embeddings.py.
 *
 * Embeds text into 384-dim vectors using all-MiniLM-L6-v2.
 * Model loads lazily on first call. Uses @huggingface/transformers (v4)
 * which avoids the onnxruntime-node 1.24+ "Tensor.location must be a
 * string" bug that broke @xenova/transformers v2 embeds.
 *
 * Vectors stored as Float32Array blobs in SQLite.
 */

import { getConfig } from './config';
import { createLogger } from './logger';

const log = createLogger('embeddings');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const EMBEDDING_DIM = 384;

// ---------------------------------------------------------------------------
// Lazy-loaded pipeline
// ---------------------------------------------------------------------------

let _pipeline: unknown = null;
let _loading: Promise<unknown> | null = null;
// Track failures to avoid log spam from a permanently broken model setup
let _failureCount = 0;
let _failureLoggedAt = 0;
const MAX_FAILURES_BEFORE_GIVE_UP = 3;
const FAILURE_LOG_INTERVAL_MS = 60 * 60 * 1000; // log once per hour after giving up
let _disabled = false;

async function loadPipeline(): Promise<unknown> {
  if (_pipeline) return _pipeline;
  if (_disabled) {
    // Throttle "still disabled" log to once per hour
    const now = Date.now();
    if (now - _failureLoggedAt > FAILURE_LOG_INTERVAL_MS) {
      log.warn(`Embeddings disabled after ${_failureCount} consecutive failures - semantic search degraded. Run 'agent-ctl health' for details.`);
      _failureLoggedAt = now;
    }
    throw new Error('embeddings disabled (consecutive failures)');
  }
  if (_loading) return _loading;

  _loading = (async () => {
    try {
      const config = getConfig();
      // Use the Xenova-prefixed model name which has ONNX weights for Transformers.js.
      // The plain `all-MiniLM-L6-v2` is the PyTorch/safetensors version which won't load.
      const modelName = config.EMBEDDING_MODEL.startsWith('Xenova/')
        ? config.EMBEDDING_MODEL
        : `Xenova/${config.EMBEDDING_MODEL}`;
      const cacheDir = config.MODELS_DIR;

      log.info(`Loading ${modelName} via @huggingface/transformers (cache: ${cacheDir})...`);

      // Dynamic import - @huggingface/transformers is ESM. Same API shape
      // as @xenova/transformers v2, so the pipeline() call is unchanged.
      const { pipeline, env } = await import('@huggingface/transformers');
      env.cacheDir = cacheDir;
      env.allowLocalModels = true;
      env.useBrowserCache = false;

      _pipeline = await pipeline('feature-extraction', modelName, {
        dtype: 'q8',
      });

      log.info(`Model loaded (${EMBEDDING_DIM}-dim, WASM)`);
      _failureCount = 0;
      return _pipeline;
    } catch (err) {
      _loading = null;
      _failureCount++;
      if (_failureCount >= MAX_FAILURES_BEFORE_GIVE_UP) {
        _disabled = true;
        _failureLoggedAt = Date.now();
        log.error(`Embedding model failed to load ${_failureCount} times - disabling. Last error:`, err);
      }
      throw err;
    }
  })();

  _pipeline = await _loading;
  _loading = null;
  return _pipeline;
}

// ---------------------------------------------------------------------------
// Embedding functions
// ---------------------------------------------------------------------------

export async function embed(text: string): Promise<Float32Array> {
  const pipe = await loadPipeline() as (text: string, opts: Record<string, unknown>) => Promise<{ data: Float32Array }>;

  const output = await pipe(text, {
    pooling: 'mean',
    normalize: true,
  });

  return new Float32Array(output.data);
}

export async function embedBatch(texts: string[]): Promise<Float32Array[]> {
  if (!texts.length) return [];

  const pipe = await loadPipeline() as (
    input: string | string[],
    opts: Record<string, unknown>,
  ) => Promise<{ data: Float32Array; dims: number[] }>;

  // Process in chunks to manage memory
  const chunkSize = 32;
  const results: Float32Array[] = [];

  for (let i = 0; i < texts.length; i += chunkSize) {
    const chunk = texts.slice(i, i + chunkSize);

    // Pass the whole chunk as an array - Transformers.js pipeline accepts
    // batched string inputs and returns a tensor with shape [n, dim].
    const output = await pipe(chunk, {
      pooling: 'mean',
      normalize: true,
    });

    // output.data is a flat Float32Array of length n * EMBEDDING_DIM.
    // Slice it into individual vectors.
    for (let j = 0; j < chunk.length; j++) {
      const start = j * EMBEDDING_DIM;
      results.push(new Float32Array(output.data.slice(start, start + EMBEDDING_DIM)));
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// Vector math
// ---------------------------------------------------------------------------

export function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  if (a.length !== b.length) return 0;

  let dot = 0;
  let normA = 0;
  let normB = 0;

  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }

  normA = Math.sqrt(normA);
  normB = Math.sqrt(normB);

  if (normA === 0 || normB === 0) return 0;
  return dot / (normA * normB);
}

// ---------------------------------------------------------------------------
// Serialization (SQLite BLOB <-> Float32Array)
// ---------------------------------------------------------------------------

export function vectorToBlob(vec: Float32Array): Buffer {
  return Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength);
}

export function blobToVector(blob: Buffer): Float32Array {
  const copy = Buffer.alloc(blob.length);
  blob.copy(copy);
  return new Float32Array(copy.buffer, copy.byteOffset, copy.length / 4);
}
