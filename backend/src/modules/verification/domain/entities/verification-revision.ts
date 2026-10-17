import { JsonObject } from '../../../../common/value-objects/json-value';
export class VerificationRevision {
  constructor(readonly id: string, readonly verificationId: string, readonly version: number,
    readonly recordedAt: Date, readonly snapshot: JsonObject) {}
}
