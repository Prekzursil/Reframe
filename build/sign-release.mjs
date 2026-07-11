#!/usr/bin/env node
// build/sign-release.mjs — WU-U2 RELEASE-TIME signer for the auto-updater.
//
// NOT shipped in the app. Run AFTER `electron-builder` and BEFORE publishing, so the
// detached `.sig` is uploaded alongside each installer:
//
//   node build/sign-release.mjs            # sign every dist/*-win-x64.exe
//   node build/sign-release.mjs --generate-keypair   # make an offline keypair
//
// For each installer it computes sha512, builds the SAME `version‖sha512` message the
// shipping app verifies (app/main/updateVerify.ts), Ed25519-signs it with the OFFLINE
// private key from $REFRAME_UPDATE_PRIVATE_KEY, and writes `dist/<installer>.sig`
// (base64). The private key is validated-present and NEVER printed/logged/committed.
//
// ANTI-DRIFT: the three constants/functions below (UPDATE_MESSAGE_CONTEXT,
// buildSignedMessage, sha512Base64) MUST byte-match app/main/updateVerify.ts. That
// exact wire format is PINNED by app/main/updateVerify.test.ts
// ("buildSignedMessage — PINNED wire format"): if it changes there, that test fails
// and this file must be updated in lockstep. The app can't import this .ts at
// release time (no build step here), so the format is duplicated — and pinned.
import { createHash, createPrivateKey, generateKeyPairSync, sign as edSign } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// --- PINNED wire format (keep identical to app/main/updateVerify.ts) ---------------
const UPDATE_MESSAGE_CONTEXT = 'reframe:update:v1';

/** SHA-512 of `bytes`, base64-encoded. */
function sha512Base64(bytes) {
  return createHash('sha512').update(bytes).digest('base64');
}

/** The exact bytes an update signature is computed over. */
function buildSignedMessage(version, sha512Digest) {
  return `${UPDATE_MESSAGE_CONTEXT}\n${version}\n${sha512Digest}`;
}
// -----------------------------------------------------------------------------------

const PRIVATE_KEY_ENV = 'REFRAME_UPDATE_PRIVATE_KEY';
const PASSPHRASE_ENV = 'REFRAME_UPDATE_PRIVATE_KEY_PASSPHRASE';
const INSTALLER_SUFFIX = '-win-x64.exe';

const buildDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(buildDir, '..');

/** Print usage and exit. */
function usage(code) {
  process.stdout.write(
    [
      'Usage:',
      '  node build/sign-release.mjs [--dist <dir>]   Sign every <dist>/*-win-x64.exe',
      '  node build/sign-release.mjs --generate-keypair',
      '',
      `Signing reads the PEM private key from $${PRIVATE_KEY_ENV}`,
      `(optionally decrypted with $${PASSPHRASE_ENV}).`,
      '',
    ].join('\n'),
  );
  process.exit(code);
}

/** Generate an offline Ed25519 keypair; print the halves for the human to place. */
function generateKeypair() {
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const pub = publicKey.export({ type: 'spki', format: 'pem' }).toString().trim();
  const priv = privateKey.export({ type: 'pkcs8', format: 'pem' }).toString().trim();
  process.stdout.write(
    [
      '# Generated an Ed25519 update-signing keypair. RUN THIS ON AN OFFLINE MACHINE.',
      '#',
      '# 1. PUBLIC key -> embed in app/main/updateVerify.ts EMBEDDED_UPDATE_PUBLIC_KEYS:',
      pub,
      '#',
      `# 2. PRIVATE key -> store securely (e.g. a secrets manager) and export as`,
      `#    $${PRIVATE_KEY_ENV} at release time. NEVER commit it or paste it anywhere shared.`,
      priv,
      '',
    ].join('\n'),
  );
}

/** Load the offline private key from the environment; fail loud if absent/invalid. */
function loadPrivateKey() {
  const pem = process.env[PRIVATE_KEY_ENV];
  if (!pem) {
    process.stderr.write(
      `[sign-release] FAILED: $${PRIVATE_KEY_ENV} is not set. Export the offline Ed25519 ` +
        'PEM private key before signing (see --generate-keypair).\n',
    );
    process.exit(1);
  }
  const passphrase = process.env[PASSPHRASE_ENV];
  try {
    return createPrivateKey(passphrase ? { key: pem, passphrase } : pem);
  } catch (err) {
    process.stderr.write(`[sign-release] FAILED: could not load the private key: ${err.message}\n`);
    process.exit(1);
    return undefined; // unreachable — exit above
  }
}

/** Sign every installer in `distDir`, writing a sibling `.sig`. */
function signInstallers(distDir) {
  if (!existsSync(distDir)) {
    process.stderr.write(`[sign-release] FAILED: dist dir not found: ${distDir}\n`);
    process.exit(1);
  }
  const version = JSON.parse(readFileSync(join(repoRoot, 'app', 'package.json'), 'utf8')).version;
  const installers = readdirSync(distDir).filter((name) => name.endsWith(INSTALLER_SUFFIX));
  if (installers.length === 0) {
    process.stderr.write(
      `[sign-release] FAILED: no *${INSTALLER_SUFFIX} found in ${distDir} — run electron-builder first.\n`,
    );
    process.exit(1);
  }
  const privateKey = loadPrivateKey();
  for (const name of installers) {
    if (!name.includes(version)) {
      process.stderr.write(
        `[sign-release] WARNING: ${name} does not contain package version ${version}; ` +
          'the app verifies against the FEED version — make sure they match.\n',
      );
    }
    const installerPath = join(distDir, name);
    const digest = sha512Base64(readFileSync(installerPath));
    const message = buildSignedMessage(version, digest);
    const signature = edSign(null, Buffer.from(message, 'utf8'), privateKey).toString('base64');
    const sigPath = `${installerPath}.sig`;
    writeFileSync(sigPath, `${signature}\n`, 'utf8');
    process.stdout.write(`[sign-release] signed ${name} -> ${name}.sig (v${version})\n`);
  }
  process.stdout.write(
    `[sign-release] OK: signed ${installers.length} installer(s). Upload the .sig assets ` +
      'alongside the installers (gh release upload <tag> dist/*.sig).\n',
  );
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) {
    usage(0);
  }
  if (args.includes('--generate-keypair')) {
    generateKeypair();
    return;
  }
  const distFlag = args.indexOf('--dist');
  const distDir = distFlag !== -1 && args[distFlag + 1] ? args[distFlag + 1] : join(repoRoot, 'dist');
  signInstallers(distDir);
}

main();
