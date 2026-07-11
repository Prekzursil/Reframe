// keyBridge.contractParity.test.ts — proves the CURRENT hand-maintained
// keyBridge key-injection allowlist and the GENERATED needsKeyInjection set agree
// for the v1.5 POC slice. This is the concrete evidence for retiring finding #5:
// once the set is generated from the single contract, the allowlist can no longer
// silently drift from the methods that actually consume provider keys.

import { describe, expect, it } from 'vitest';

import { needsKeyInjection as keyBridgeNeedsKey } from './keyBridge';
import {
  NEEDS_KEY_INJECTION,
  needsKeyInjection as generatedNeedsKey,
} from '../renderer/src/lib/rpc/generated/needsKeyInjection.generated';

const POC_METHODS = [
  'ping',
  'library.add',
  'settings.get',
  'settings.set',
  'shortmaker.select',
  'providers.revealKey',
] as const;

describe('keyBridge <-> generated needsKeyInjection parity (POC slice)', () => {
  for (const method of POC_METHODS) {
    it(`${method}: the hand-written keyBridge and the generated set agree`, () => {
      expect(generatedNeedsKey(method)).toBe(keyBridgeNeedsKey(method));
    });
  }

  it('every generated key-injection method is also key-needing per keyBridge', () => {
    for (const method of NEEDS_KEY_INJECTION) {
      expect(keyBridgeNeedsKey(method)).toBe(true);
    }
  });
});
