# Codex + RAG Developer Test Results

Baseline source: `docs/codex_rag_developer_test_suite.md`

Environment check:

- Project commit: `03503e2`
- Qdrant: `http://127.0.0.1:6333/healthz` returned healthy.
- RAG daemon: `http://127.0.0.1:7890/health` returned `qdrant=ok`, `embedder=ollama`, `ollama=ok`.
- Dodo repo: `/Users/nikitaf/development/projects/dodo-mobile-android/project`
- Registered RAG repo: `dodo`, collection `repo_dodo`, 31,181 vectors.

## Execution Order

1. Task 1, refactor async/suspend checkout functions.
2. Task 2, trace UI state from failing paid-order test.
3. Task 10, minimal paid-order reset-before-analytics patch plan.
4. Task 4, analytics around payment completion.
5. Task 9, paid-order response VO naming mismatch.
6. Task 3, deprecated API replacement.
7. Task 8, risky checkout payment test gaps.
8. Task 7, checkout/core architecture.
9. Task 5, profile locale dependency boundary.
10. Task 6, deferred-time code-only rename.

## Task 1: Refactor Async/Suspend Checkout Functions

Prompt:

> Find suspend/async order checkout functions related to waiting for paid orders and propose a safe refactor that extracts duplicated state-update logic.

### Plain Codex Navigation

Commands used:

- `rg -n -i "wait.*pay|pay.*order|paid.*order|setupAppStateForNewOrder" .`
- Focused follow-up `rg` for `waitForPayedOrder`, `setupAppStateForNewOrder`, and `PaidOrderResponse`.
- Source reads around checkout order processing, checkout interactor, checkout tests, checkout service, core state analyzer, main-screen wait-for-paid-order service/tests, and main-screen interactor.

Findings:

- Primary target: `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt`
- Main function: `waitForPayedOrder()` at lines 161-185.
- Result mapping: `handleOrderResponse()` at lines 193-228 maps `PaidOrderState.OK` to `OrderCreated` and `ALMOST_OK` to `OrderIsBeingCreated`.
- State reset caller: `checkoutService.setupAppStateForNewOrder()` at lines 173-179, called before `analyticsHelper.trackPaymentFinished(paymentMethodType)`.
- Existing checkout tests: `WhenWaitForPaidOrder.kt`, especially OK, ALMOST_OK, analytics, and reset assertions.
- Related duplicated success-reset path: `WaitForPaidOrderServiceImpl.getPaidOrderForState()` maps OK/ALMOST_OK to `CreatedOrder` and calls `checkoutService.setupAppStateForNewOrder()`.

Metrics:

| Task | Mode | Relevant file found? | Files read | Source tokens approx | Time to target | Final answer quality | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | Plain | Yes | 8 | ~25k | ~0.20s command time, noisy target scan | 4 | Literal grep worked, but first broad query returned translations/debug JSON/payment/profile noise before the checkout target cluster. |

### Codex + RAG Navigation

Commands used:

- `/search` with repo `dodo`, query: `Find suspend async order checkout functions related to waiting for paid orders and duplicated state update logic setupAppStateForNewOrder`
- Follow-up `/search` with exact discovered terms: `waitForPayedOrder setupAppStateForNewOrder PaidOrderResponse checkout order processing`
- Minimal source reads for the production implementation and tests.

Findings:

- Broad RAG query ranked `CheckoutService.kt`, `CheckoutDetailsInteractor.kt`, `StateAnalyzer.kt`, `WhenWaitForPaidOrder.kt`, and `CheckoutOrderProcessingService.kt` in the top five.
- Exact RAG query returned the failing/target checkout tests at ranks 2, 3, 6, and 9, the checkout processing interface at rank 7, related main-screen tests at ranks 4 and 5, and `CheckoutServiceImpl` summary at rank 10.
- RAG did surface the right semantic cluster quickly, including tests that plain grep only exposed deep inside a large result set.
- RAG chunks for some Kotlin functions were declaration-only, so a local source slice was still needed to inspect `waitForPayedOrder()` body.

Metrics:

| Task | Mode | Relevant file found? | Files read | Source tokens approx | Time to target | Final answer quality | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | RAG | Yes | 5 | ~5k | 0.45s broad query; 0.14s exact follow-up | 4 | Better semantic clustering and much less irrelevant context, but line metadata was incomplete/null for the first broad query and some chunks were only signatures. |

### Safe Refactor Plan

Narrowest safe edit:

- In `CheckoutOrderProcessingServiceImpl`, extract the successful paid-order side effect from `waitForPayedOrder()`:
  - `private fun OrderResult.isSuccessfulPaidOrder() = this is OrderIsBeingCreated || this is OrderCreated`
  - `private fun handleSuccessfulPaidOrder(paymentMethodType: PaymentMethodType)` wraps `checkoutService.setupAppStateForNewOrder()` in the existing `try/catch`, then calls `analyticsHelper.trackPaymentFinished(paymentMethodType)`.
- Keep `handleOrderResponse()` unchanged. It is the state mapping and already has focused tests.
- Do not move the behavior into `CheckoutService` unless the team wants a cross-flow abstraction; `WaitForPaidOrderServiceImpl` has a similar OK/ALMOST_OK reset path but no analytics and no flow side effects, so sharing too aggressively would widen the change.

Tests to update/run:

- Existing focused tests in `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt`
- Add or strengthen an OK-state reset assertion in the checkout-processing test, because ALMOST_OK currently verifies `setupAppStateForNewOrder()` explicitly.
- If ordering matters, add an in-order verification that `checkoutService.setupAppStateForNewOrder()` happens before `analyticsHelper.trackPaymentFinished(...)`.
- Related regression tests in `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt` should remain green.

Intended Gradle target:

- `./gradlew :context:order:testDebugUnitTest --tests '*WhenWaitForPaidOrder*' --tests '*WaitForPaidOrderServiceImplTest*'`

Verification limitation:

- Gradle task discovery failed before tests could run because `/Users/nikitaf/signing/secrets.properties` is missing.

## Tasks 2-10 Summary Table

| Task | Mode | Relevant file found? | Files read | Source tokens approx | Time to target | Final answer quality | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 2 | Plain | Yes | 2 | ~1.5k | ~0.14s | 4 | Exact test-name grep found the test immediately; production path followed via `waitForPayedOrder()`. |
| 2 | RAG | Yes | 2 | ~1.2k | ~0.52s | 3 | Ranked the exact failing test first, but then included unrelated state-machine hits before the production implementation. |
| 3 | Plain | Yes | 2 | ~1.2k | ~0.15s | 4 | Literal deprecation string made plain grep ideal. |
| 3 | RAG | Yes | 2 | ~1.0k | ~0.28s | 4 | Also ranked deprecated `StateAnalyzer` and replacement `CheckoutService` at the top. |
| 4 | Plain | Yes | 3 | ~2.0k | ~0.15s | 4 | Literal `trackPaymentFinished` found helper, call site, and tests. |
| 4 | RAG | Yes | 3 | ~1.5k | ~0.27s | 3 | Found `AnalyticsHelper` first, but production flow was lower than unrelated analytics/test snippets. |
| 5 | Plain | Yes | 5 | ~1.5k | ~0.16s | 4 | Grep found the feature package, dependency interface, component, and app component owner. |
| 5 | RAG | Yes | 4 | ~1.2k | ~0.31s | 4 | Strongest RAG win after Task 1: dependency interface was ranks 1-2 and interactor/component followed. |
| 6 | Plain | Yes | 6 | ~6k | ~0.14s | 4 | Broad but exhaustive; required separating Kotlin symbols from resources/user-facing strings. |
| 6 | RAG | Partial | 4 | ~3k | ~0.18s | 3 | Found UI feature and tests, but missed several state/service/domain symbols without follow-up literal search. |
| 7 | Plain | Yes | 6 | ~5k | ~0.07s | 4 | Literal architecture anchors (`StateAnalyzer`, `CheckoutService`, `CheckoutStateProvider`) worked well. |
| 7 | RAG | Partial | 5 | ~3k | ~0.31s initial; ~0.17s targeted | 3 | Over-ranked DI provider snippets and missed `StateAnalyzer` until plain/literal follow-up. |
| 8 | Plain | Yes | 8 | ~7k | ~0.04s | 4 | Grep across production/test payment-processing functions quickly exposed covered and uncovered paths. |
| 8 | RAG | Partial | 5 | ~3k | ~0.35s | 2 | Found a few relevant functions but mixed in many unrelated test summaries; weak for coverage-gap analysis. |
| 9 | Plain | Yes | 5 | ~2k | ~0.08s | 4 | Literal `PaidOrderResponseVO`/`PaidOrderResponse` search was efficient. |
| 9 | RAG | Yes | 4 | ~1.2k | ~0.31s | 4 | Excellent semantic/literal hit: actual VO, domain model, mapper, and call site were top results. |
| 10 | Plain | Yes | 2 | ~1.4k | ~0.03s | 4 | Exact terms found the ordering-sensitive block and tests immediately. |
| 10 | RAG | Partial | 2 | ~1.0k | ~0.18s | 3 | Found helper/test snippets but missed the central production body in top results. |

## Task 2: Trace UI State From Test Failure

Prompt:

> A test named `ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder` is failing. Find the production path it verifies and explain the state transition.

Answer:

- Test: `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt`, lines 163-178.
- Production path: `CheckoutDetailsPresenter.waitForPaidOrder()` calls `CheckoutDetailsInteractor.waitForPayedOrder()`, which delegates to `CheckoutOrderProcessingServiceImpl.waitForPayedOrder()`.
- In `waitForPayedOrder()`, `orderService.getPlacedOrder(...)` returns `PaidOrderResponse.getAlmostOkInstance()`.
- `handleOrderResponse()` maps `PaidOrderState.ALMOST_OK` to `OrderResult.OrderIsBeingCreated(getCurrentCheckoutState().setLoading())`.
- The flow emits initial `Polling(...)`, then the ALMOST_OK result. In `onEach`, `OrderIsBeingCreated` is treated as successful paid-order handling, so `checkoutService.setupAppStateForNewOrder()` is called before `analyticsHelper.trackPaymentFinished(...)`.

RAG note:

- RAG ranked the exact test first, which was useful.
- It did not rank `CheckoutOrderProcessingServiceImpl.waitForPayedOrder()` highly for this natural-language prompt; a follow-up literal source read was still needed.

## Task 3: Locate Deprecated API Replacement

Prompt:

> Find deprecated code that points users to `CheckoutService::setupAppStateForNewOrder` and determine what should call the new API instead.

Answer:

- Deprecated API: `StateAnalyzer.setupAppStateForNewOrder()` in `context/core/src/main/java/com/dodopizza/core/domain/state/StateAnalyzer.kt`, lines 101-102.
- Replacement target: `CheckoutService.setupAppStateForNewOrder()` in `context/order/src/main/java/com/dodopizza/order/domain/workflow/checkout/CheckoutService.kt`, lines 32-64.
- `CheckoutServiceImpl.setupAppStateForNewOrder()` delegates to the deprecated core method, then updates the customer. That means feature/order callers should depend on `CheckoutService`, not call `StateAnalyzer` directly.
- Current correct callers already include `CheckoutOrderProcessingServiceImpl`, `WaitForPaidOrderServiceImpl`, and `MainScreenInteractor.setCartFromKiosk()`.
- The direct internal `StateAnalyzerImpl.actualizeState()` self-call is inside core and should remain internal unless the core API is redesigned.

Minimal edit guidance:

- For any feature-level caller still injecting `StateAnalyzer` only to reset app state after a successful order, replace that dependency with `CheckoutService`.
- Run or inspect tests around `CheckoutServiceTests`, `WhenWaitForPaidOrder`, and `WaitForPaidOrderServiceImplTest`.

## Task 4: Add/Verify Analytics Event Around Payment Completion

Prompt:

> Add or verify analytics tracking for successful payment completion in the order checkout flow.

Answer:

- Existing analytics helper: `AnalyticsHelper.trackPaymentFinished(paymentMethodType)` in `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/AnalyticsHelper.kt`, lines 192-195.
- Production call site: `CheckoutOrderProcessingServiceImpl.waitForPayedOrder()`, lines 170-185.
- It tracks success for both `OrderIsBeingCreated` and `OrderCreated`.
- Existing tests verify tracking for OK, ALMOST_OK, and the reset test path in `WhenWaitForPaidOrder.kt`.

Patch/test gap:

- Tracking exists, so no new event is required.
- For confidence, add an ordering assertion with Mockito `inOrder(checkoutService, analyticsHelper)` in the ALMOST_OK test, and add an explicit OK-state reset assertion if the team wants parity between OK and ALMOST_OK.

## Task 5: Find Dependency Injection Boundaries

Prompt:

> For the profile locale list feature, find its dependency interface and explain what module owns the implementation.

Answer:

- Feature dependency interface: `ProfileLocaleListFeatureDependencies` in `context/profile/src/main/java/com/dodopizza/profile/feature/profilelocalelist/ProfileLocaleListFeatureDependencies.kt`.
- Dagger component: `ProfileLocaleListComponent` depends on `ProfileLocaleListFeatureDependencies`.
- Feature interactor dependencies: `AppResourceLocalesFactory`, `CurrentLocaleProvider`, and `LanguageService`.
- Owner implementation boundary: `AppComponent` implements `ProfileLocaleListFeatureDependencies` and includes `LocaleListServiceModule`.
- `LocaleListServiceModule` provides `CountryLocaleService` and `LanguageAwareCacheKeys.Factory`; the low-level locale services are app/infrastructure-owned, while profile owns the UI feature.

RAG note:

- This was a clean RAG win: top results were the dependency interface, interactor, fragment, screen, and component.

## Task 6: Rename Deferred-Time Concept Safely

Prompt:

> The team wants to rename "deferred time" to "scheduled time" in checkout UI internals without touching user-facing strings. Find code-only symbols that need review.

Code-only candidates:

- Feature package: `context/order/src/main/java/com/dodopizza/order/feature/checkout/deferredtime/**`
- Primary classes: `DeferredTimeFragment`, `DeferredTimePresenter`, `DeferredTimeInteractor`, `DeferredTimeView`, `DeferredTimeFeatureDependencies`, `DeferredTimeComponent`, `DeferredTimeModule`.
- Adapter/value objects: `DeferredIntervalItemVO`, `DeferredIntervalsVO`, `DeferredTimeVO`, `DeferredTimeIntervalBinder`, `DeferredTimeIntervalViewHolder`, `DeliveryDeferredTimeBinder`, `CarryoutDeferredTimeBinder`.
- Checkout details internals: `DeferredTimeDiffUtilCallback`, `DeferredTimeSelectionListener`, `NewDeferredTimeSelectionListener`, `CheckoutDetailsPresenter.scrollToNewDeferredTime`, `CheckoutDetailsFragment.setDeferredTimeItems`, `CheckoutDetailsView` deferred-time methods.
- State/service symbols: `DeferredTimeState`, `NewDeferredTimeState`, `CheckoutStateService.setDeferredTime`, `setNewDeferredTime`, `CheckoutStateEditService.setDeferredTime`, `CheckoutStateLogic` deferred-time mutators.
- Android test screen objects under `app/src/androidTest/java/ru/dodopizza/app/screens/checkout/defferedTime/**` and `DeferredTime` test enum.

Do not mechanically rename:

- Android string resources and displayed text.
- Serialized/backend contract fields such as `deferredOrderDateTime`, `SetDeferredTimeRequestDto`, `DeferredIntervalsV1Dto`, and DTO `@SerializedName` values.
- Analytics event names unless the analytics taxonomy owner approves.

RAG note:

- RAG found the UI feature and Android test screens quickly.
- Plain grep was better for exhaustiveness and for separating production state/domain/API fields from UI-only symbols.

## Task 7: Explain Cross-Module Checkout/Core Architecture

Prompt:

> Explain how order checkout state is coordinated across `context/order` and `context/core`.

Answer:

- `context/core` owns global state analysis and mutation through `StateAnalyzer`.
- `StateAnalyzerImpl.actualizeState()` fetches/analyzes the backend state and, if it sees an order placed for the current workflow, calls its internal deprecated `setupAppStateForNewOrder()` and returns the fresh current state.
- `StateAnalyzerImpl.setupAppStateForNewOrder()` clears domain state and actualizes state again.
- `context/order` owns checkout-facing workflows and wraps core reset behavior through `CheckoutService.setupAppStateForNewOrder()`.
- `CheckoutServiceImpl.setupAppStateForNewOrder()` calls core `StateAnalyzer.setupAppStateForNewOrder()` and then `customerService.updateCustomer()`.
- Checkout UI state is built in `context/order` via `CheckoutStateProviderImpl`, which reads global `StateProvider.getCurrentState()`, runs workflow errors through `ChangeWorkflowResultHandler`, pulls checkout details from `CheckoutDetailsService`, and converts everything into `CheckoutState` with `CheckoutStateFactory`.
- User checkout mutations flow through `CheckoutStateService` -> `CheckoutStateEditService` -> `CheckoutDetailsServiceImpl` -> backend `WorkflowApi`, then map returned `ChangeWorkflowResult` back into `CheckoutState`.

RAG note:

- RAG over-ranked DI provider chunks for this architecture question and did not retrieve the important core `StateAnalyzer` body without literal terms.
- Plain navigation was more reliable here.

## Task 8: Identify Risky Test Gaps

Prompt:

> Find production functions in checkout payment processing that have state-changing behavior but weak or missing test coverage.

Prioritized gaps:

1. `CheckoutOrderProcessingServiceImpl.waitForPayedOrder()` has coverage for OK/ALMOST_OK/failure mapping and analytics, but lacks ordering verification that reset happens before `trackPaymentFinished`.
2. `chargeSbpPayment()` mirrors `chargePayment()` and `chargeSavedCardPayment()` but no focused `WhenChargeSbpPayment` test was found in the order-processing test package.
3. `createGooglePayRequest()` has success/error tests, but its state transition from `RequestInProgress(state.setLoading())` to `RequestFailed(...setPaymentFailedError())` is worth keeping because it relies on casting prior flow data.
4. `handlePaymentCanceled()` has one test for replacing a payment method error, but broader state variants are not covered.
5. `setPaymentError()` has a narrow test for setting `PaymentFailed`; it does not verify existing error cleanup or interaction with other checkout state.

Covered areas:

- `WhenChargePayment` and `WhenChargeBySavedCardPayment` cover success and failure.
- `WhenConfirm3DS` covers success and payment-failed state on error.
- `WhenWaitForPaidOrder` covers paid-order result mapping and payment analytics.

RAG note:

- RAG was weak for this task; it found some production function declarations but mixed in unrelated test summaries. Plain grep across production and test packages gave the useful coverage matrix.

## Task 9: Debug Naming Mismatch

Prompt:

> The user says "paid order response VO", but the code may use different names. Find the closest actual model/classes and call sites.

Answer:

- There is an actual `PaidOrderResponseVO` in `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/PaidOrderResponseVO.kt`.
- It is a presentation sealed class with `CreatedOrder`, `WorkflowAlreadyChanged`, and `Failure`.
- The domain response is `PaidOrderResponse` in `domain/base/src/main/java/ru/dodopizza/app/domain/order/PaidOrderResponse.kt`.
- `WaitForPaidOrderServiceImpl` maps `PaidOrderResponse` to `PaidOrderResponseVO`.
- `MainScreenInteractor.waitForPaidOrder()` returns the VO to `MainScreenPresenter.handlePaidOrder()`, which routes `CreatedOrder` to active order, `WorkflowAlreadyChanged` to profile, and ignores `Failure`.
- Checkout-details flow does not use the VO; it maps the same domain `PaidOrderResponse` into `OrderResult` inside `CheckoutOrderProcessingServiceImpl`.

RAG note:

- RAG performed very well: the VO, domain model, mapper, and likely call sites were all top results.

## Task 10: Minimal Patch Planning

Prompt:

> Make the smallest safe change so successful paid order handling always resets app state before tracking analytics.

Current state:

- `CheckoutOrderProcessingServiceImpl.waitForPayedOrder()` already calls `checkoutService.setupAppStateForNewOrder()` before `analyticsHelper.trackPaymentFinished(paymentMethodType)` for `OrderIsBeingCreated` and `OrderCreated`.
- The reset is inside a `try/catch`; analytics still fires even if reset fails.

Smallest safe patch:

- If the requirement is strictly "call reset before analytics", add a test only:
  - In `WhenWaitForPaidOrder`, use Mockito `inOrder(checkoutService, analyticsHelper)` for the ALMOST_OK path and verify `setupAppStateForNewOrder()` before `trackPaymentFinished(any())`.
  - Add equivalent OK-state ordering coverage or combine both successful states with parameterized/helper setup.
- If the requirement is "analytics must not fire unless reset succeeds", change behavior:
  - Move `analyticsHelper.trackPaymentFinished(paymentMethodType)` inside the `try` after `checkoutService.setupAppStateForNewOrder()`.
  - Add a test where `checkoutService.setupAppStateForNewOrder()` throws and verify `trackPaymentFinished` is not called.

Recommended interpretation:

- Use the test-only patch first, because existing production code already has reset-before-analytics order. Changing failure behavior would be product/analytics-sensitive.

Intended Gradle target:

- `./gradlew :context:order:testDebugUnitTest --tests '*WhenWaitForPaidOrder*'`

Verification limitation:

- Gradle still cannot run because `/Users/nikitaf/signing/secrets.properties` is missing.

## Overall Result

RAG helped most on semantic discovery where the query named a feature but not exact files: Tasks 1, 5, and 9. It was competitive on Tasks 3 and 4.

Plain Codex navigation won where literal anchors were obvious or exhaustiveness mattered: Tasks 2, 3, 6, 7, 8, and 10.

Main RAG limitations observed:

- Some Kotlin chunks are signature-only, so relevant files still require local source reads.
- Architecture prompts can over-rank DI provider snippets.
- Coverage-gap prompts need test/production pairing, which current retrieval does not reliably synthesize.
- Exact known symbol queries work well; broader natural-language queries sometimes miss the central function body.

## 2026-06-06 IDE-Index Rerun

After adding SQLite lexical context packs plus the `ast-index` adapter, I reran the
10-task navigation benchmark with:

```bash
python3 tests/eval/compare_navigation.py
```

Scope:

- This measures navigation, not final code-patch correctness.
- Vanilla is `rg -l` with task-specific literal patterns.
- `ast_index` is direct `ast-index symbol` lookup over expected symbols.
- `rag` is the daemon JSON `/context-pack` endpoint with AST + lexical retrieval
  and semantic vector fallback disabled, so source-token usage reflects exact
  context packing rather than embedding recall.

Summary:

| Mode | Expected-file hit rate | First expected rank = 1 | Typical result count | Latency shape | Source-token shape |
| --- | ---: | ---: | ---: | --- | --- |
| Vanilla `rg` | 10/10 | 3/10 | 5-75 files | ~58-158 ms | No packing; Codex still has to decide file slices |
| Direct `ast-index` | 10/10 | 10/10 | 2-19 files | ~15-55 ms | Metadata only until the caller reads slices |
| RAG context-pack | 10/10 | 10/10 | 4-8 slices | ~286-767 ms | 203-2394 source tokens |

Measured table:

| Task | Vanilla first rank / results | ast-index first rank / results | RAG first rank / slices | RAG source tokens | RAG first paths |
| --- | ---: | ---: | ---: | ---: | --- |
| 01 refactor paid-order reset | 3 / 11 | 1 / 5 | 1 / 4 | 203 | `CheckoutOrderProcessingService.kt`, `CheckoutDetailsInteractor.kt`, `CheckoutService.kt` |
| 02 trace failing paid-order test | 1 / 5 | 1 / 3 | 1 / 4 | 819 | `WhenWaitForPaidOrder.kt`, `CheckoutOrderProcessingService.kt`, `CheckoutDetailsInteractor.kt` |
| 03 deprecated state reset API | 1 / 7 | 1 / 2 | 1 / 6 | 1434 | `CheckoutService.kt`, `StateAnalyzer.kt`, `BlockStoreService.kt` |
| 04 payment completion analytics | 3 / 8 | 1 / 3 | 1 / 5 | 244 | `AnalyticsHelper.kt`, `PaymentAnalytics.kt`, `CheckoutOrderProcessingService.kt` |
| 05 profile locale DI boundary | 1 / 5 | 1 / 3 | 1 / 7 | 2143 | `ProfileLocaleListFeatureDependencies.kt`, `ProfileLocaleListComponent.kt`, `LocaleListServiceModule.kt` |
| 06 deferred-time rename | 6 / 33 | 1 / 11 | 1 / 8 | 1557 | `DeferredTimeFragment.kt`, `DeferredTimePresenter.kt`, `CheckoutState.kt` |
| 07 checkout/core architecture | 9 / 75 | 1 / 5 | 1 / 8 | 2394 | `StateAnalyzer.kt`, `CheckoutService.kt`, `CheckoutStateProvider.kt` |
| 08 payment test gaps | 5 / 17 | 1 / 7 | 1 / 6 | 747 | `CheckoutOrderProcessingService.kt`, `CardChargeServiceAsyncImpl.kt`, `PaymentServiceFacade.kt` |
| 09 paid-order response VO naming | 24 / 42 | 1 / 19 | 1 / 8 | 1766 | `PaidOrderResponseVO.kt`, `PaidOrderResponse.kt`, `MainScreenPresenter.kt` |
| 10 reset before analytics | 7 / 16 | 1 / 5 | 1 / 4 | 203 | `CheckoutOrderProcessingService.kt`, `CheckoutDetailsInteractor.kt`, `CheckoutService.kt` |

Interpretation:

- The raw AST index is now the precision ceiling: exact symbols, definitions,
  usages, and call tree are consistently better than grep for first relevant
  file rank.
- The evolved RAG no longer behaves like embedding search for developer tasks.
  It now acts as an IDE-style context packer: exact symbol lookup first,
  lexical fallback second, semantic fallback optional.
- RAG is slower than direct `rg`/`ast-index`, but it spends that time to return
  bounded source slices. For these tasks the model would receive hundreds or low
  thousands of tokens, not whole 1000-3000 line files.
- Remaining weakness is not recall; it is slice quality. Some Kotlin expression
  bodies are still clipped too tightly, and coverage-gap tasks need explicit
  production-to-test pairing rather than just a ranked list of relevant slices.
