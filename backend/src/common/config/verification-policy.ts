import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { JsonObject } from '../value-objects/json-value';

export interface VerificationPolicy {
  schemaVersion: number; engineVersion: string; semanticsVersion: string;
  maxSourceCharacters: number; maxSourceLines: number; maxJsonBytes: number;
  maxAstNesting: number; maxExecutionSteps: number; maxExpressionNodes: number;
  maxGraphNodes: number; solverTimeoutMs: number;
}
export const verificationPolicy: VerificationPolicy = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../verification-policy.json'), 'utf8'),
) as VerificationPolicy;

export function analysisIsCurrent(provenance: JsonObject, scope: JsonObject): boolean {
  return provenance.engineVersion === verificationPolicy.engineVersion
    && scope.engineVersion === verificationPolicy.engineVersion
    && scope.semanticsVersion === verificationPolicy.semanticsVersion;
}

export function sourceWithinPolicy(value: unknown, allowEmpty = false): value is string {
  if (typeof value !== 'string' || (!allowEmpty && !value.trim()) || value.length > verificationPolicy.maxSourceCharacters) return false;
  const lines = value ? value.split(/\r\n|[\r\n\v\f\u001c-\u001e\u0085\u2028\u2029]/).length - Number(/[\r\n\v\f\u001c-\u001e\u0085\u2028\u2029]$/.test(value)) : 0;
  return lines <= verificationPolicy.maxSourceLines;
}
