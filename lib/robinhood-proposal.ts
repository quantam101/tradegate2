export const SUPPORTED_ASSET_CLASSES = new Set(['equity']);
export const BLOCKED_ORDER_TYPES = new Set(['market']);
export const MAX_PROPOSAL_TTL_SECONDS = 86_400;
export const MAX_NOTIONAL_USD = 1_000;

export const RISK_REVIEW_CHECKLIST = [
  'Confirm public source is reachable and timestamped.',
  'Confirm symbol and asset class are supported.',
  'Confirm limit price, stop loss, and max loss are present.',
  'Confirm proposal is not expired.',
  'Confirm no credential or account identifier is stored.',
  'Confirm no execution is attempted without future explicit approval.',
] as const;

export type RobinhoodProposal = {
  symbol?: unknown;
  side?: unknown;
  asset_class?: unknown;
  order_type?: unknown;
  quantity?: unknown;
  limit_price?: unknown;
  stop_loss?: unknown;
  max_loss_usd?: unknown;
  expires_at?: unknown;
  thesis?: unknown;
  source_url?: unknown;
};

function finiteNumber(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function validateRobinhoodProposal(
  input: RobinhoodProposal,
  now = new Date(),
): { ok: true; proposal: Record<string, unknown> } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  const symbol = typeof input.symbol === 'string' ? input.symbol.trim().toUpperCase() : '';
  const side = typeof input.side === 'string' ? input.side.trim().toLowerCase() : '';
  const assetClass = typeof input.asset_class === 'string' ? input.asset_class.trim().toLowerCase() : '';
  const orderType = typeof input.order_type === 'string' ? input.order_type.trim().toLowerCase() : '';
  const quantity = finiteNumber(input.quantity);
  const limitPrice = finiteNumber(input.limit_price);
  const stopLoss = finiteNumber(input.stop_loss);
  const maxLoss = finiteNumber(input.max_loss_usd);
  const thesis = typeof input.thesis === 'string' ? input.thesis.trim() : '';
  const sourceUrl = typeof input.source_url === 'string' ? input.source_url.trim() : '';
  const expiresAt = typeof input.expires_at === 'string' ? new Date(input.expires_at) : null;

  if (!/^[A-Z][A-Z0-9.-]{0,14}$/.test(symbol)) errors.push('symbol must be a public-market ticker');
  if (!['buy', 'sell'].includes(side)) errors.push('side must be buy or sell');
  if (!SUPPORTED_ASSET_CLASSES.has(assetClass)) errors.push(`asset_class must be one of: ${[...SUPPORTED_ASSET_CLASSES].join(', ')}`);
  if (BLOCKED_ORDER_TYPES.has(orderType)) errors.push('market orders are blocked; use limit');
  if (orderType !== 'limit') errors.push('order_type must be limit');
  if (quantity === null || quantity <= 0) errors.push('quantity must be positive');
  if (limitPrice === null || limitPrice <= 0) errors.push('limit_price must be positive');
  if (stopLoss === null || stopLoss <= 0) errors.push('stop_loss is required and must be positive');
  if (maxLoss === null || maxLoss <= 0) errors.push('max_loss_usd is required and must be positive');
  if (quantity !== null && limitPrice !== null && quantity * limitPrice > MAX_NOTIONAL_USD) {
    errors.push(`proposal notional exceeds $${MAX_NOTIONAL_USD}`);
  }
  if (!expiresAt || Number.isNaN(expiresAt.getTime())) {
    errors.push('expires_at must be an ISO timestamp');
  } else {
    const ttl = (expiresAt.getTime() - now.getTime()) / 1000;
    if (ttl <= 0) errors.push('proposal is expired');
    if (ttl > MAX_PROPOSAL_TTL_SECONDS) errors.push(`proposal TTL exceeds ${MAX_PROPOSAL_TTL_SECONDS}s`);
  }
  if (!thesis) errors.push('thesis is required');
  if (sourceUrl && !/^https:\/\//.test(sourceUrl)) errors.push('source_url must use https');

  const serialized = JSON.stringify(input).toLowerCase();
  if (/(token|secret|password|account_number|account_id|credential)/.test(serialized)) {
    errors.push('credential and account identifiers are forbidden');
  }

  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    proposal: {
      symbol,
      side,
      asset_class: assetClass,
      order_type: orderType,
      quantity,
      limit_price: limitPrice,
      stop_loss: stopLoss,
      max_loss_usd: maxLoss,
      expires_at: expiresAt!.toISOString(),
      thesis,
      ...(sourceUrl ? { source_url: sourceUrl } : {}),
    },
  };
}
