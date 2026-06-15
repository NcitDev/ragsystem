import re

content = """
@Module
class CheckoutStateModule {
    @Provides
    fun provideCheckoutOrderProcessingService(api: Api): CheckoutOrderProcessingService {
        return Impl()
    }
}

class MyActivity : BaseActivity() {
    @Inject lateinit var presenter: CheckoutDetailsPresenter
}

class CheckoutService @Inject constructor(
    private val stateAnalyzer: StateAnalyzer,
    val api: CheckoutApi
)
"""

provides_kt = re.findall(r"@Provides[\s\S]*?fun\s+\w+\s*\([^)]*\)\s*:\s*([A-Z]\w+)", content)
print("Provides:", provides_kt)

injects_kt = re.findall(r"@Inject\s+(?:lateinit\s+)?var\s+\w+\s*:\s*([A-Z]\w+)", content)
injects_ctor = re.findall(r"@Inject\s+constructor\s*\((.*?)\)", content, re.DOTALL)
deps = list(injects_kt)
for ctor_args in injects_ctor:
    types = re.findall(r":\s*([A-Z]\w+)", ctor_args)
    deps.extend(types)
print("Injects:", deps)

