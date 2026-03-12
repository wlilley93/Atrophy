/**
 * Local embedding engine - Transformers.js on WASM/CPU.
 * Port of core/embeddings.py.
 *
 * Embeds text into 384-dim vectors using all-MiniLM-L6-v2.
 * Model loads lazily on first call. Uses WASM via @xenova/transformers
 * instead of Python's sentence-transformers.
 *
 * Vectors stored as Float32Array blobs in SQLite.
 */

import * as path from 'path';
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

async function loadPipeline(): Promise<unknown> {
  if (_pipeline) return _pipeline;
  if (_loading) return _loading;

  _loading = (async () => {
    const config = getConfig();
    const modelName = config.EMBEDDING_MODEL;
    const cacheDir = path.join(config.MODELS_DIR, modelName);

    log.info(`Loading ${modelName} via Transformers.js...`);

    // Dynamic import - @xenova/transformers is ESM
    const { pipeline, env } = await import('@xenova/transformers');
    env.cacheDir = cacheDir;
    env.allowLocalModels = true;

    _pipeline = await pipeline('feature-extraction', modelName, {
      quantized: true,
    });

    log.info(`Model loaded (${EMBEDDING_DIM}-dim, WASM)`);
    return _pipeline;
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
