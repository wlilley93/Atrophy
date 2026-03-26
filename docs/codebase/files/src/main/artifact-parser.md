# src/main/artifact-parser.ts - Inline Artifact Extraction

**Line count:** ~100 lines  
**Dependencies:** None  
**Purpose:** Parse `<artifact>` blocks from Claude responses for rich content display

## Overview

The agent can emit structured artifacts inline in its responses. These are extracted and displayed as clickable cards in the transcript that open in a full-screen viewer. Artifacts support HTML visualizations, SVG graphics, and code snippets.

## Artifact Format

```xml
<artifact id="unique-id" type="html|svg|code" title="Human-readable title" language="html">
CONTENT HERE
</artifact>
```

**Attributes:**
- `id`: Unique identifier within conversation (e.g., `solar-system-viz`)
- `type`: One of `html`, `svg`, `code`
- `title`: Human-readable title for display
- `language`: Content language (html, svg, python, typescript, etc.)

## Types

```typescript
export interface Artifact {
  id: string;
  type: 'html' | 'svg' | 'code';
  title: string;
  language: string;
  content: string;
  position: number;  // Character index in original response
}

export interface ParsedResponse {
  text: string;       // Response with artifact blocks replaced by placeholders
  artifacts: Artifact[];
}
```

## Regex Pattern

```typescript
const ARTIFACT_REGEX =
  /<artifact\s+id="(?<id>[^"]+)"\s+type="(?<type>[^"]+)"\s+title="(?<title>[^"]+)"\s+language="(?<language>[^"]+)"\s*>(?<content>[\s\S]*?)<\/artifact>/g;
```

**Captures:**
- `id`: Artifact identifier
- `type`: Content type
- `title`: Display title
- `language`: Content language
- `content`: Artifact content

## parseArtifacts

```typescript
export function parseArtifacts(response: string): ParsedResponse {
  const artifacts: Artifact[] = [];

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

  // Replace artifact blocks with placeholders
  const text = response.replace(
    /<artifact\s+id="([^"]+)"[^>]*>[\s\S]*?<\/artifact>/g,
    '\n[[artifact:$1]]\n',
  );

  return { text, artifacts };
}
```

**Returns:**
- `text`: Response with artifacts replaced by `[[artifact:id]]` placeholders
- `artifacts`: Array of extracted artifacts in order of appearance

**Placeholder format:** `[[artifact:unique-id]]`

## extractCompleteArtifacts

```typescript
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
```

**Purpose:** For streaming inference - extract only newly completed artifacts

**Deduplication key:** `${id}:${position}` - same ID at different positions = different artifacts (iteration)

## mightContainPartialArtifact

```typescript
export function mightContainPartialArtifact(text: string): boolean {
  const lastOpen = text.lastIndexOf('<artifact');
  if (lastOpen === -1) return false;
  const afterOpen = text.indexOf('</artifact>', lastOpen);
  return afterOpen === -1;
}
```

**Purpose:** Check if streaming buffer has unclosed artifact tag

**Use case:** Buffer output until artifact is complete to avoid showing raw XML

## deduplicateArtifacts

```typescript
export function deduplicateArtifacts(artifacts: Artifact[]): Map<string, Artifact> {
  const map = new Map<string, Artifact>();
  for (const artifact of artifacts) {
    map.set(artifact.id, artifact);  // Last write wins
  }
  return map;
}
```

**Purpose:** Deduplicate artifacts by ID (supports iteration - same ID replaces previous)

**Returns:** Map keyed by artifact ID

## Usage in Inference

```typescript
// In ipc/inference.ts
const { text: cleanedText, artifacts } = parseArtifacts(fullText);
if (artifacts.length > 0) {
  for (const art of artifacts) {
    ctx.mainWindow.webContents.send('inference:artifact', art);
  }
  ctx.mainWindow.webContents.send('inference:done', cleanedText);
} else {
  ctx.mainWindow.webContents.send('inference:done', fullText);
}
```

## Exported API

| Function | Purpose |
|----------|---------|
| `parseArtifacts(response)` | Parse complete response, extract all artifacts |
| `extractCompleteArtifacts(accumulated, alreadyExtracted)` | Extract new artifacts from streaming buffer |
| `mightContainPartialArtifact(text)` | Check for unclosed artifact tags |
| `deduplicateArtifacts(artifacts)` | Deduplicate by ID (last write wins) |
| `Artifact` | Interface for extracted artifacts |
| `ParsedResponse` | Interface for parse result |

## See Also

- `src/main/inference.ts` - Calls parseArtifacts on StreamDone
- `src/main/ipc/inference.ts` - Forwards artifacts to renderer
- `src/renderer/components/Artefact.svelte` - Renders artifact cards
