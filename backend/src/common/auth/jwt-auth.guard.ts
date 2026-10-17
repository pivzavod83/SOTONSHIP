import { CanActivate, ExecutionContext, Injectable, UnauthorizedException, ForbiddenException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { verify, createPublicKey } from 'node:crypto';
import type { Request } from 'express';
import { REQUIRED_ROLES } from './roles.decorator';

interface Claims { iss: string; aud: string | string[]; exp: number; nbf?: number; sub: string; roles: string[]; }

@Injectable()
export class JwtAuthGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<Request>();
    const token = request.headers.authorization?.match(/^Bearer ([A-Za-z0-9._~-]+)$/)?.[1];
    if (!token) throw new UnauthorizedException('A signed Bearer token is required.');
    const claims = this.validate(token);
    const required = this.reflector.getAllAndOverride<string[]>(REQUIRED_ROLES, [context.getHandler(), context.getClass()]) ?? [];
    if (!required.every((role) => claims.roles.includes(role))) throw new ForbiddenException('The token lacks a required role.');
    (request as Request & { actor?: Claims }).actor = claims;
    return true;
  }

  private validate(token: string): Claims {
    const issuer = process.env.AUTH_JWT_ISSUER;
    const audience = process.env.AUTH_JWT_AUDIENCE;
    const configuredKey = process.env.AUTH_JWT_PUBLIC_KEY;
    if (!issuer || !audience || !configuredKey) throw new UnauthorizedException('API token validation is not configured.');
    try {
      const [head, body, signature, extra] = token.split('.');
      if (!head || !body || !signature || extra !== undefined) throw new Error('Malformed JWT');
      const header = JSON.parse(Buffer.from(head, 'base64url').toString('utf8')) as { alg?: string; typ?: string };
      const claims = JSON.parse(Buffer.from(body, 'base64url').toString('utf8')) as Partial<Claims>;
      if (header.alg !== 'RS256' || (header.typ && header.typ !== 'JWT')) throw new Error('Unexpected signing algorithm');
      const key = createPublicKey(configuredKey.replace(/\\n/g, '\n'));
      const valid = verify('RSA-SHA256', Buffer.from(`${head}.${body}`), key, Buffer.from(signature, 'base64url'));
      const now = Math.floor(Date.now() / 1000);
      const audienceMatches = Array.isArray(claims.aud) ? claims.aud.includes(audience) : claims.aud === audience;
      if (!valid || claims.iss !== issuer || !audienceMatches || typeof claims.exp !== 'number' || claims.exp <= now
        || (typeof claims.nbf === 'number' && claims.nbf > now) || typeof claims.sub !== 'string' || !claims.sub.trim()
        || !Array.isArray(claims.roles) || claims.roles.some((role) => typeof role !== 'string')) throw new Error('Invalid claims or signature');
      return claims as Claims;
    } catch {
      throw new UnauthorizedException('The Bearer token is invalid or expired.');
    }
  }
}
