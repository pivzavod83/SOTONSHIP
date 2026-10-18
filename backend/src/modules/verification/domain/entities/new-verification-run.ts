import { VerificationRun, VerificationRunProps } from './verification-run';
import { VerificationCompletedEvent } from '../events/verification-completed.event';
import { DiscrepancyDetectedEvent } from '../events/discrepancy-detected.event';
import { FormalProofStatusValue } from '../enums/formal-proof-status.enum';

export class NewVerificationRun extends VerificationRun {
  constructor(props: VerificationRunProps) {
    super(props);
    this.events.push(new VerificationCompletedEvent(props.id, props.formalProofStatus));
    if (props.formalProofStatus === FormalProofStatusValue.SAT_COUNTEREXAMPLE_FOUND) {
      this.events.push(new DiscrepancyDetectedEvent(props.id, props.bugCategory));
    }
  }
}
