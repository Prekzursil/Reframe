// lib/rpc/index.ts - barrel re-export for the typed RPC client (F4b split).
// Pure re-export (no logic): keeps `from '../lib/rpc'` working unchanged after
// the schemas/client split. Excluded from the renderer coverage gate as a barrel.
export * from './schemas';
export * from './client';
export { default } from './client';
