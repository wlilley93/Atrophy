import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as child_process from 'child_process';
import * as fs from 'fs';

vi.mock('child_process');
vi.mock('fs');
vi.mock('../logger', () => ({
  createLogger: () => ({ warn: vi.fn(), info: vi.fn(), debug: vi.fn(), error: vi.fn() }),
}));

const { convertToOgg, cleanupFiles } = await import('../audio-convert');

describe('convertToOgg', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('converts mp3 to ogg by shelling out to ffmpeg', () => {
    vi.mocked(child_process.execFileSync).mockReturnValue(Buffer.from(''));
    vi.mocked(fs.existsSync).mockReturnValue(true);
    vi.mocked(fs.statSync).mockReturnValue({ size: 1024 } as fs.Stats);

    const result = convertToOgg('/tmp/test.mp3');
    expect(result).toBe('/tmp/test.ogg');
    expect(child_process.execFileSync).toHaveBeenCalledWith(
      'ffmpeg',
      ['-y', '-i', '/tmp/test.mp3', '-c:a', 'libopus', '-b:a', '64k', '-vn', '/tmp/test.ogg'],
      expect.objectContaining({ timeout: 30_000 }),
    );
  });

  it('returns null when ffmpeg fails', () => {
    vi.mocked(child_process.execFileSync).mockImplementation(() => {
      throw new Error('ffmpeg not found');
    });

    const result = convertToOgg('/tmp/test.mp3');
    expect(result).toBeNull();
  });

  it('returns null when output file is empty', () => {
    vi.mocked(child_process.execFileSync).mockReturnValue(Buffer.from(''));
    vi.mocked(fs.existsSync).mockReturnValue(true);
    vi.mocked(fs.statSync).mockReturnValue({ size: 0 } as fs.Stats);

    const result = convertToOgg('/tmp/test.mp3');
    expect(result).toBeNull();
  });
});

describe('cleanupFiles', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('removes all provided paths silently', () => {
    vi.mocked(fs.unlinkSync).mockReturnValue(undefined);

    cleanupFiles('/tmp/a.mp3', '/tmp/b.ogg', null);
    expect(fs.unlinkSync).toHaveBeenCalledTimes(2);
  });

  it('ignores errors on missing files', () => {
    vi.mocked(fs.unlinkSync).mockImplementation(() => {
      throw new Error('ENOENT');
    });

    // Should not throw
    cleanupFiles('/tmp/a.mp3');
  });
});
