/**
 * Inline artifact store - holds artifacts extracted from agent responses.
 * These are emitted via inference:artifact IPC and referenced in transcript
 * text as [[artifact:id]] placeholders.
 */

export interface InlineArtifact {
  id: string;
  type: 'html' | 'svg' | 'code';
  title: string;
  language: string;
  content: string;
}

const _artifacts = $state<Map<string, InlineArtifact>>(new Map());

export function storeArtifact(artifact: InlineArtifact): void {
  _artifacts.set(artifact.id, artifact);
}

export function getArtifact(id: string): InlineArtifact | undefined {
  return _artifacts.get(id);
}

export function clearArtifacts(): void {
  _artifacts.clear();
}

export const artifacts = _artifacts;
