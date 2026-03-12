/**
 * Artifact extraction logic for parsing <artifact> blocks from Claude responses.
 *
 * The agent can emit artifacts inline in its response text using:
 *   <artifact id="unique-id" type="html|svg|code" title="Title" language="html">
 *   CONTENT
 *   </artifact>
 *
 * These are extracted, stored, and the text is replaced with placeholders
 * that the renderer can turn into clickable cards.
 */

export interface Artifact {
  id: string;
  type: 'html' | 'svg' | 'code';
  title: string;
  language: string;
  content: string;
  /** Character index in the original response where this artifact appeared */
  position: number;
}

export interface ParsedResponse {
  /** The response text with artifact blocks replaced by placeholders */
  text: string;
  /** Extracted artifacts in order of appearance */
  artifacts: Artifact[];
}

const ARTIFACT_REGEX =
  /<artifact\s+id="(?<id>[^"]+)"\s+type="(?<type>[^"]+)"\s+title="(?<title>[^"]+)"\s+language="(?<language>[^"]+)"\s*>(?<content>[\s\S]*?)<\/artifact>/g;

/**
 * Parse a complete response string, extracting all artifact blocks.
 * Returns cleaned text (with placeholders) and an array of artifacts.
 */
export function parseArtifacts(response: string): ParsedResponse {
  const artifacts: Artifact[] = [];

  // Reset regex state
  ARTIFACT_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = ARTIFACT_REGEX.exec(response)) !== null) {
    const { id, type, title, language, content } = match.groups!;
    artifacts.push({
      id,
      type: type as Artifact['type'],
      title,
      language,
      content: content.trim(),
      position: match.index,
    });
  }

  // Replace artifact blocks with placeholders for rendering
  const text = response.replace(
    /<artifact\s+id="([^"]+)"[^>]*>[\s\S]*?<\/artifact>/g,
    '\n[[artifact:$1]]\n',
  );

  return { text, artifacts };
}

/**
 * Extract complete artifacts from an accumulated string.
 * Useful for streaming - call on each accumulated chunk.
 * Returns only newly completed artifacts since the last call.
 */
export function extractCompleteArtifacts(
  accumulated: string,
  alreadyExtracted: Set<string> = new Set(),
): Artifact[] {
  const newArtifacts: Artifact[] = [];

  ARTIFACT_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = ARTIFACT_REGEX.exec(accumulated)) !== null) {
    const { id, type, title, language, content } = match.groups!;
    const key = `${id}:${match.index}`;
    if (!alreadyExtracted.has(key)) {
      alreadyExtracted.add(key);
      newArtifacts.push({
        id,
        type: type as Artifact['type'],
        title,
        language,
        content: content.trim(),
        position: match.index,
      });
    }
  }

  return newArtifacts;
}

/**
 * Check if a streaming buffer might contain a partial artifact tag.
 * If true, the caller should buffer before forwarding to the renderer
 * to avoid showing raw XML.
 */
export function mightContainPartialArtifact(text: string): boolean {
  // Check for opening tag that hasn't closed yet
  const lastOpen = text.lastIndexOf('<artifact');
  if (lastOpen === -1) return false;
  const afterOpen = text.indexOf('</artifact>', lastOpen);
  return afterOpen === -1;
}

/**
 * Given multiple artifacts, deduplicate by ID (last write wins).
 * Supports iteration: re-emitting same ID replaces the previous version.
 */
export function deduplicateArtifacts(artifacts: Artifact[]): Map<string, Artifact> {
  const map = new Map<string, Artifact>();
  for (const artifact of artifacts) {
    map.set(artifact.id, artifact);
  }
  return map;
}
