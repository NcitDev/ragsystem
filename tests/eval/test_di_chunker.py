import sys
from pathlib import Path
sys.path.append(str(Path.cwd() / "src"))

from rag.core.chunker import chunk_code

source = """
@Module
class CheckoutStateModule {
    @Provides
    fun provideCheckoutOrderProcessingService(api: Api): CheckoutOrderProcessingService {
        return Impl()
    }
}
"""

chunks = chunk_code(source, "CheckoutStateModule.kt", "kotlin")
for c in chunks:
    c.enrich_metadata()
    print(c.name)
    print(c.metadata)
