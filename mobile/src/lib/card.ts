// The offline membership card (ADR 0006 section 4, CHK-13). The real API issues a card seed
// `<credential id>.<secret>` once; the app derives the rotating QR `fhq.<credential>.<step>.<hmac>` from it
// offline, mirroring backend access/domain/cards.py. The demo adapter issues `FH1.<payload>.<sig>` tokens
// with an expiry instead. Either lives in SecureStore. Display data lives in AsyncStorage. The card
// screen reads only local storage, so it renders with no network and no live session.
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';

import type { ActableClient, AppCard } from '../adapters/types';
import { readJson, removeKey, writeJson } from './storage';

export type CardPayload = { kid: string; cred: string; inst: string; iat: number; exp: number };
export type CardDisplay = { clientId: string; name: string; memberNumber: string | null; label: string };
export type CardStatus = 'valid' | 'expiring' | 'expired' | 'missing';
export type StoredCards = { display: CardDisplay[]; tokens: Record<string, AppCard> };

const tokensKey = (slug: string) => `fh.cards.${slug}`;
const displayKey = (slug: string) => `fh.carddisplay.${slug}`;

function b64urlDecode(part: string): string {
  const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
  return atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
}

export function decodeCardToken(token: string): CardPayload | null {
  const parts = token.split('.');
  if (parts.length !== 3 || parts[0] !== 'FH1') return null;
  try {
    const payload = JSON.parse(b64urlDecode(parts[1]!)) as Partial<CardPayload>;
    if (typeof payload.exp !== 'number' || typeof payload.iat !== 'number' || typeof payload.cred !== 'string') return null;
    return payload as CardPayload;
  } catch {
    return null;
  }
}

const SEED = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[A-Za-z0-9_-]{16,}$/i;
const STEP_SECONDS = 30;

/** A server card seed: no expiry, revocation is checked by the server at scan. */
export const isCardSeed = (token: string) => SEED.test(token);

const bytesOf = (binary: string) => Uint8Array.from(binary, (c) => c.charCodeAt(0));
const sha256 = async (data: Uint8Array<ArrayBuffer>) => new Uint8Array(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, data));

async function hmacSha256(key: Uint8Array<ArrayBuffer>, message: Uint8Array<ArrayBuffer>): Promise<Uint8Array> {
  const block = new Uint8Array(64);
  block.set(key.length > 64 ? await sha256(key) : key);
  const pad = (byte: number) => block.map((b) => b ^ byte);
  const inner = await sha256(new Uint8Array([...pad(0x36), ...message]));
  return sha256(new Uint8Array([...pad(0x5c), ...inner]));
}

/** The QR text to show now: the derived rotating code for a seed, the token itself for a demo card. */
export async function cardCode(token: string, nowMs: number): Promise<string> {
  if (!isCardSeed(token)) return token;
  const [credentialId, secret] = token.split('.') as [string, string];
  const step = Math.floor(nowMs / 1000 / STEP_SECONDS);
  const mac = await hmacSha256(bytesOf(b64urlDecode(secret)), bytesOf(`${credentialId}.${step}`));
  const b64url = btoa(String.fromCharCode(...mac.slice(0, 16))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `fhq.${credentialId}.${step}.${b64url}`;
}

/** Refresh is due once half the lifetime has passed; past `exp` the card shows "refresh needed". */
export function cardStatus(card: AppCard | undefined, nowMs: number): CardStatus {
  if (card && isCardSeed(card.card_payload)) return 'valid';
  const payload = card ? decodeCardToken(card.card_payload) : null;
  if (!payload) return 'missing';
  const exp = payload.exp * 1000;
  if (nowMs >= exp) return 'expired';
  return nowMs >= (payload.iat * 1000 + exp) / 2 ? 'expiring' : 'valid';
}

export function displayFor(client: ActableClient): CardDisplay {
  const c = client.client;
  const name = [c.preferred_name ?? c.first_name, c.last_name].filter(Boolean).join(' ');
  const label = client.basis === 'self' ? 'You' : (client.relationship_label ?? 'Family member');
  return { clientId: c.id, name, memberNumber: c.member_number, label };
}

export async function loadCards(slug: string): Promise<StoredCards> {
  const [display, rawTokens] = await Promise.all([
    readJson<CardDisplay[]>(displayKey(slug)),
    SecureStore.getItemAsync(tokensKey(slug)),
  ]);
  return { display: display ?? [], tokens: rawTokens ? (JSON.parse(rawTokens) as Record<string, AppCard>) : {} };
}

/**
 * One card per client the identity can act for, on every guardian device (A4). The set is derived from the
 * relationship list, so a removed dependent's card disappears on the next sync and cannot reappear.
 */
export async function syncCards(
  slug: string,
  clients: ActableClient[],
  issue: (clientId: string) => Promise<AppCard>,
  nowMs = Date.now(),
): Promise<StoredCards> {
  const current = await loadCards(slug);
  const tokens: Record<string, AppCard> = {};
  for (const client of clients) {
    const id = client.client.id;
    const existing = current.tokens[id];
    tokens[id] = existing && cardStatus(existing, nowMs) === 'valid' ? existing : await issue(id);
  }
  const display = clients.map(displayFor);
  await Promise.all([
    SecureStore.setItemAsync(tokensKey(slug), JSON.stringify(tokens)),
    writeJson(displayKey(slug), display),
  ]);
  return { display, tokens };
}

export async function clearCards(slug: string) {
  await Promise.all([SecureStore.deleteItemAsync(tokensKey(slug)), removeKey(displayKey(slug))]);
}

/** Stable per-install id, the `inst` the server binds card tokens to. */
export async function installationId(): Promise<string> {
  const existing = await SecureStore.getItemAsync('fh.installation');
  if (existing) return existing;
  const id = Crypto.randomUUID();
  await SecureStore.setItemAsync('fh.installation', id);
  return id;
}
