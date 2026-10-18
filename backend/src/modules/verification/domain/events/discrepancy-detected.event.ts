export class DiscrepancyDetectedEvent {
  readonly occurredAt = new Date();
  constructor(readonly verificationId: string, readonly bugCategory: string) {}
}
