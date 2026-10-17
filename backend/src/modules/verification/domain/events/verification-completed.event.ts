import { FormalProofStatusValue } from '../enums/formal-proof-status.enum';

export class VerificationCompletedEvent {
  readonly occurredAt = new Date();
  constructor(readonly verificationId: string, readonly status: FormalProofStatusValue) {}
}
