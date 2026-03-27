/**
 * Entity auto-filing - extracts named entities from assistant responses
 * and files them to the agent's intelligence.db.
 *
 * Runs after each inference response completes. Uses regex patterns
 * for near-zero latency (~1ms). Only files NEW entities (INSERT OR IGNORE).
 *
 * Does not update existing records or extract relationships.
 */

import * as path from 'path';
import * as fs from 'fs';
import Database from 'better-sqlite3';
import { USER_DATA } from './config';
import { createLogger } from './logger';

const log = createLogger('entity-extract');

// Minimum word count before extraction runs (skip short replies).
// Agents with intelligence.db (e.g. Montgomery) use a lower threshold
// so entities are filed from virtually every substantive response.
const MIN_WORDS = 20; // low threshold - file entities from nearly every substantive response

// ---------------------------------------------------------------------------
// Patterns
// ---------------------------------------------------------------------------

// Person titles that precede a proper name
const PERSON_TITLES = [
  'President', 'Prime Minister', 'Minister', 'Secretary', 'General',
  'Admiral', 'Colonel', 'Commander', 'Ambassador', 'Chancellor',
  'Director', 'Chairman', 'Chairwoman', 'Senator', 'Governor',
  'Marshal', 'Lieutenant', 'Captain', 'Major', 'Brigadier',
  'Field Marshal', 'Chief of Staff', 'Deputy',
  'King', 'Queen', 'Prince', 'Princess', 'Emperor',
  'Pope', 'Ayatollah', 'Sheikh',
  'Dr', 'Prof', 'Professor',
];

// Organisation suffixes
const ORG_SUFFIXES = [
  'Corps', 'Ministry', 'Department', 'Institute', 'Command',
  'Forces', 'Agency', 'Authority', 'Commission', 'Committee',
  'Council', 'Bureau', 'Office', 'Division', 'Brigade',
  'Battalion', 'Regiment', 'Fleet', 'Group', 'Alliance',
  'Organisation', 'Organization', 'Foundation', 'Service',
  'Guard', 'Directorate', 'Parliament', 'Assembly',
];

// Common acronym organisations (defence/geopolitical focus)
const KNOWN_ORGS = new Set([
  'NATO', 'OSCE', 'UN', 'EU', 'IAEA', 'OPCW', 'ICC', 'ICJ',
  'RUSI', 'IISS', 'SIPRI', 'RAND', 'CSIS', 'ISW',
  'CIA', 'NSA', 'MI5', 'MI6', 'GCHQ', 'BND', 'DGSE', 'FSB', 'GRU', 'SVR',
  'AUKUS', 'QUAD', 'BRICS', 'ASEAN', 'ECOWAS', 'SADC',
  'RAF', 'USAF', 'USN', 'USMC', 'IDF', 'PLA', 'PLAN',
  'DGA', 'DSTL', 'DARPA', 'AFRL',
  'EDA', 'OCCAR', 'NSPA', 'SHAPE', 'SACEUR', 'SACLANT',
  'FCAS', 'GCAP', 'SCAF', 'TEMPEST', 'F-35', 'ITAR',
  'IMF', 'WTO', 'SWIFT',
  'RSF', 'ISIS', 'ISIL', 'AQ', 'IRGC', 'PMF', 'SDF', 'YPG', 'PKK',
  'Hamas', 'Hezbollah', 'Houthis', 'Wagner',
]);

// Countries and major geopolitical locations
const KNOWN_LOCATIONS = new Set([
  'United States', 'United Kingdom', 'Russia', 'China', 'France', 'Germany',
  'Japan', 'India', 'Brazil', 'Australia', 'Canada', 'Italy', 'Spain',
  'Turkey', 'Iran', 'Israel', 'Saudi Arabia', 'South Korea', 'North Korea',
  'Pakistan', 'Egypt', 'South Africa', 'Indonesia', 'Mexico', 'Poland',
  'Ukraine', 'Taiwan', 'Norway', 'Sweden', 'Finland', 'Denmark',
  'Netherlands', 'Belgium', 'Greece', 'Romania', 'Czech Republic',
  'Portugal', 'Hungary', 'Austria', 'Switzerland', 'Ireland',
  'Syria', 'Iraq', 'Yemen', 'Libya', 'Sudan', 'Somalia', 'Mali',
  'Niger', 'Burkina Faso', 'Ethiopia', 'Eritrea', 'Myanmar', 'Afghanistan',
  'Palestine', 'Gaza', 'West Bank', 'Lebanon', 'Kosovo', 'Georgia',
  'Moldova', 'Transnistria', 'Crimea', 'Donbas', 'Kherson', 'Zaporizhzhia',
  'Black Sea', 'Baltic Sea', 'South China Sea', 'Taiwan Strait',
  'Strait of Hormuz', 'Red Sea', 'Suez Canal', 'Arctic', 'Mediterranean',
  'Indo-Pacific', 'Sahel', 'Horn of Africa', 'Caucasus',
  'Kyiv', 'Moscow', 'Beijing', 'Washington', 'London', 'Paris', 'Berlin',
  'Brussels', 'Ankara', 'Tehran', 'Riyadh', 'Tel Aviv', 'Jerusalem',
  'Taipei', 'Seoul', 'Pyongyang', 'New Delhi', 'Islamabad', 'Kabul',
  'Damascus', 'Baghdad', 'Khartoum', 'Addis Ababa',
]);

// ---------------------------------------------------------------------------
// Extraction
// ---------------------------------------------------------------------------

interface ExtractedEntity {
  name: string;
  type: 'person' | 'organization' | 'country';
}

/**
 * Extract named entities from text using regex patterns.
 * Returns deduplicated list of {name, type} objects.
 */
export function extractEntities(text: string): ExtractedEntity[] {
  const found = new Map<string, ExtractedEntity>();

  // --- Persons: "Title FirstName LastName" ---
  const titlePattern = PERSON_TITLES.map(t => t.replace(/\./g, '\\.')).join('|');
  const personRe = new RegExp(
    `(?:^|[\\s(])(?:${titlePattern})\\s+([A-Z][a-z]+(?:\\s+[A-Z][a-z]+){1,3})`,
    'gm',
  );
  for (const m of text.matchAll(personRe)) {
    const name = m[1].trim();
    if (name.length > 3 && !KNOWN_LOCATIONS.has(name)) {
      found.set(name, { name, type: 'person' });
    }
  }

  // --- Organisations: multi-word ending with org suffix ---
  const suffixPattern = ORG_SUFFIXES.join('|');
  const orgRe = new RegExp(
    `([A-Z][A-Za-z]+(?:\\s+(?:of|for|the|and|de|du|des|la|le))?(?:\\s+[A-Z][A-Za-z]+)*\\s+(?:${suffixPattern}))`,
    'g',
  );
  for (const m of text.matchAll(orgRe)) {
    const name = m[1].trim();
    if (name.length > 5) {
      found.set(name, { name, type: 'organization' });
    }
  }

  // --- Organisations: known acronyms ---
  for (const org of KNOWN_ORGS) {
    const re = new RegExp(`\\b${org.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);
    if (re.test(text)) {
      found.set(org, { name: org, type: 'organization' });
    }
  }

  // --- Locations: known set ---
  for (const loc of KNOWN_LOCATIONS) {
    const re = new RegExp(`\\b${loc.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);
    if (re.test(text)) {
      found.set(loc, { name: loc, type: 'country' });
    }
  }

  return Array.from(found.values());
}

// ---------------------------------------------------------------------------
// Database filing
// ---------------------------------------------------------------------------

/**
 * Map entity-extract types to ontology object types.
 * The entities table uses 'country' for locations, but the objects table
 * uses 'country' for sovereign states and 'location' for other places.
 * For auto-extraction we keep 'country' since we only extract known countries.
 */
const ENTITY_TYPE_TO_OBJECT_TYPE: Record<string, string> = {
  person: 'person',
  organization: 'organization',
  country: 'country',
};

/**
 * File extracted entities to the agent's intelligence.db.
 * Dual-writes to both the legacy `entities` table and the new `objects`
 * ontology table so new entities from conversations flow into the
 * knowledge graph.
 *
 * Uses INSERT OR IGNORE for entities (legacy) and existence checks for
 * objects (ontology) to avoid duplicates.
 * Only runs for agents that have an intelligence.db.
 */
export function fileEntities(agentName: string, text: string): number {
  const dbPath = path.join(USER_DATA, 'agents', agentName, 'data', 'intelligence.db');
  if (!fs.existsSync(dbPath)) return 0;

  const wordCount = text.split(/\s+/).length;
  if (wordCount < MIN_WORDS) return 0;

  const entities = extractEntities(text);
  if (entities.length === 0) return 0;

  let filed = 0;
  let ontologyFiled = 0;
  let db: Database.Database | null = null;
  try {
    db = new Database(dbPath);
    db.pragma('journal_mode = WAL');

    // Ensure legacy entities table exists (it should, but be safe)
    db.exec(`
      CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        aliases TEXT,
        type TEXT NOT NULL,
        subtype TEXT,
        parent_id INTEGER,
        description TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_id) REFERENCES entities(id)
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)');
    db.exec('CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)');

    const insertLegacy = db.prepare(
      `INSERT OR IGNORE INTO entities (name, type, description, created_at)
       VALUES (?, ?, 'auto-extracted', datetime('now'))`,
    );

    // Check if objects table exists (ontology schema) for dual-write
    const hasObjectsTable = db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='objects'",
    ).get();

    // Prepare ontology statements if objects table exists
    const checkObject = hasObjectsTable
      ? db.prepare('SELECT id FROM objects WHERE name = ? AND type = ?')
      : null;
    const insertObject = hasObjectsTable
      ? db.prepare(
          `INSERT INTO objects (type, name, description, first_seen, last_seen, created_at, updated_at)
           VALUES (?, ?, 'auto-extracted from conversation', datetime('now'), datetime('now'), datetime('now'), datetime('now'))`,
        )
      : null;

    // Guard against template/placeholder values leaking in as entity names
    const INVALID_NAMES = new Set(['entity name', 'string', 'name', 'example', 'null', 'undefined', 'test']);

    const insertMany = db.transaction((items: ExtractedEntity[]) => {
      for (const e of items) {
        if (INVALID_NAMES.has(e.name.toLowerCase())) continue;

        // Legacy entities table
        const result = insertLegacy.run(e.name, e.type);
        if (result.changes > 0) filed++;

        // Ontology objects table (dual-write)
        if (checkObject && insertObject) {
          const objectType = ENTITY_TYPE_TO_OBJECT_TYPE[e.type] || e.type;
          const existing = checkObject.get(e.name, objectType);
          if (!existing) {
            insertObject.run(objectType, e.name);
            ontologyFiled++;
          }
        }
      }
    });

    insertMany(entities);
  } catch (e) {
    log.error(`[${agentName}] entity filing failed: ${e}`);
  } finally {
    try { db?.close(); } catch { /* */ }
  }

  if (filed > 0 || ontologyFiled > 0) {
    log.info(
      `[${agentName}] filed ${filed} legacy + ${ontologyFiled} ontology entities (${entities.length} extracted)`,
    );
  }

  return filed + ontologyFiled;
}
