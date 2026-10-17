import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { CODE_GENERATION_PROVIDER, ICodeGenerationProvider } from '../../ports/code-generation-provider';
import { GenerationConfigurationRto } from '../../../presentation/rto/generation-configuration.rto';
import { GetGenerationConfigurationQuery } from '../get-generation-configuration.query';
@QueryHandler(GetGenerationConfigurationQuery)
export class GetGenerationConfigurationHandler implements IQueryHandler<GetGenerationConfigurationQuery> {
  constructor(@Inject(CODE_GENERATION_PROVIDER) private readonly provider: ICodeGenerationProvider) {}
  async execute(): Promise<GenerationConfigurationRto> {
    return Object.assign(new GenerationConfigurationRto(), this.provider.configuration(), { message: 'Provider-neutral placeholder. No generation adapter is enabled; configuration alone never triggers network requests.' });
  }
}
